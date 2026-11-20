#!/usr/bin/env python3
"""The runner as a hosted task: Papex Labs runs it on Render Workflows, and Papex's server starts it when a
run is sent. A scheduled run of runner.py stays as the fallback.

  build:  pip install -r runner/requirements.txt
  start:  python runner/render_task.py          (from the repository root)

One task, decide. It takes no input and runs what the scheduled run runs, `runner.py --post`, with --api
from PAPEX_API (default https://api.papex.org) and the token from PAPEX_SHARED_WORK_RUNNER_TOKEN, read by
runner.py as always (and, for open tasks, PAPEX_SHARED_WORK_PUBLISHER_TOKEN when it is set: the step after an
accepted run). It returns what the runner printed, and the counts:

  {"lines": ["b-7f3a21: ACCEPTED "], "accepted": 1, "rejected": 0, "skipped": 0, "alert": false, "exitCode": 0}

When the runner stops (the queue cannot be read, there is no token, --api is not https) the task fails with
the runner's message, and the token is never in it. A verdict Papex refuses, or one sent run the runner cannot
decide, does not stop it: an ALERT line names that batch ("alert": true) and the others are decided. The rules
are runner.py's; this file adds none.

Only this file needs the Render SDK (runner/requirements.txt), and only where the worker is built
(build_app). decide_queue() needs nothing but Python, so the kit's tests run it without the SDK.
"""

import contextlib
import importlib.util
import io
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
API_ENV = "PAPEX_API"
DEFAULT_API = "https://api.papex.org"
DECIDED = re.compile(r"^\S+: (ACCEPTED|REJECTED)( |$)")
SKIPPED = re.compile(r"^\S+ \S+: not a list of this kit$")


def _load_runner():
    # By path: the folder runner/ would otherwise compete with runner.py for the name "runner".
    spec = importlib.util.spec_from_file_location("papex_rerun_runner", os.path.join(HERE, "runner.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


runner = _load_runner()


class RunnerFailed(RuntimeError):
    """The runner stopped. The task fails with this message."""


class _Kept(io.TextIOBase):
    """What the runner prints still goes to the task's log, and is kept for the summary."""

    def __init__(self, log):
        super().__init__()
        self.log, self.kept = log, io.StringIO()

    def write(self, text):
        self.kept.write(text)
        self.log.write(text)
        self.log.flush()
        return len(text)


def summarize(lines, exit_code):
    outcomes = [m.group(1) for m in map(DECIDED.match, lines) if m]
    return {"lines": lines, "accepted": outcomes.count("ACCEPTED"), "rejected": outcomes.count("REJECTED"),
            "skipped": sum(1 for line in lines if SKIPPED.match(line)),
            "alert": any(line.startswith("ALERT ") for line in lines), "exitCode": exit_code}


def _failure(reason, printed):
    text = reason if not printed else f"{reason} (printed before it stopped: {' | '.join(printed)})"
    for name in (runner.TOKEN_ENV, runner.PUBLISHER_TOKEN_ENV):
        token = os.environ.get(name, "").strip()
        if token:
            text = text.replace(token, "[token]")
    return "The runner stopped: " + text[:1500]


def decide_queue():
    """Run the runner once, as the scheduled run does, and return what it printed and the counts.

    runner.main stops with SystemExit, which is not an Exception; the Render SDK reports only an Exception
    as a failed run, so every stop becomes RunnerFailed here (with the message, without the token).
    """
    api = os.environ.get(API_ENV, "").strip() or DEFAULT_API
    out = _Kept(sys.stdout)
    try:
        with contextlib.redirect_stdout(out):
            code = runner.main(["--post", "--api", api])
    except SystemExit as stop:
        code = stop.code
        if isinstance(code, str):
            raise RunnerFailed(_failure(code, _lines(out))) from None
    except Exception as error:
        raise RunnerFailed(_failure(f"{type(error).__name__}: {error}", _lines(out))) from None
    code = code or 0
    if code != 0:
        raise RunnerFailed(_failure(f"it exited {code}", _lines(out)))
    return summarize(_lines(out), code)


def _lines(out):
    return [line for line in out.kept.getvalue().splitlines() if line.strip()]


def build_app():
    """The worker, with its one task. Imports the Render SDK."""
    from render.workflows import Retry, TaskContext, Workflows

    app = Workflows(default_plan="flex")

    # No automatic retries (Render's default is three). A failure here is an answer from Papex or a missing
    # token, which a retry seconds later would meet again; the next sent run or the scheduled run decides what
    # is left. Each decision is posted with expectedState SUBMITTED, so no run is decided twice.
    # A queue of a few runs takes seconds; each call to Papex may wait 60 s.
    @app.task(name="decide", timeout_seconds=600, plan="flex", retry=Retry(max_retries=0, wait_duration_ms=1000))
    def decide(ctx: TaskContext) -> dict:
        return decide_queue()

    return app


if __name__ == "__main__":
    build_app().start()
