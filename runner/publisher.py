#!/usr/bin/env python3
"""Papex's publisher routes for open tasks, and the requests built from a task's folder.

Used by runner/runner.py (after an accepted run: the next round, or closing a counterexample's list) and by
tools/publish_task.py and tools/pull_task.py. Python's standard library only.

  POST /api/shared-work/publisher/tasks                              publish a round of a task
  POST /api/shared-work/publisher/tasks/{problemSlug}/{listKey}/close  close a task's list
  GET  /api/shared-work/publisher/tasks                              every task list, any state

The token (env PAPEX_SHARED_WORK_PUBLISHER_TOKEN, read by the callers) goes only into the Authorization header,
which is never passed on: no redirect is followed at all (a 3xx answer is an error), and the API's address must be
https (http only on this computer). The token is never printed or written.
"""

import datetime
import importlib.util
import json
import os
import sys
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.dirname(HERE)
TOKEN_ENV = "PAPEX_SHARED_WORK_PUBLISHER_TOKEN"
LEAD_NAME = "Papex Labs"
ACCEPTED_BY = "an accepted run on Papex"
CLOSE_REASON = "A run that passes the task's checker was accepted."
USER_AGENT = "papex-task-publisher"


def load_kit():
    """task.py next to this folder, by path (the folder runner/ would compete with runner.py for its name)."""
    before = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec = importlib.util.spec_from_file_location("papex_task_kit", os.path.join(KIT, "task.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = before
    return module


kit = load_kit()


class PublisherError(Exception):
    """An answer of Papex that is not a success (status, code), or no answer (status None)."""

    def __init__(self, status, code, text):
        super().__init__(text)
        self.status, self.code = status, code


class Publisher:
    def __init__(self, api, token, timeout=60):
        why = kit.api_problem(api)
        if why:
            raise SystemExit(f"Papex's API must be an https address such as https://api.papex.org: {why}.")
        self.api, self.token, self.timeout = api.rstrip("/"), token, timeout

    def call(self, method, path, body=None):
        data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(self.api + path, data=data, method=method)
        request.add_unredirected_header("Authorization", "Bearer " + self.token)
        request.add_header("Accept", "application/json")
        request.add_header("User-Agent", USER_AGENT)
        if data is not None:
            request.add_header("Content-Type", "application/json")
        try:
            with kit.open_url(request, self.timeout) as response:
                text = response.read(8 << 20).decode("utf-8", "replace")
        except urllib.error.HTTPError as error:
            try:
                answer = json.loads(error.read(65536).decode("utf-8", "replace"))
                code, text = answer.get("code"), answer.get("message") or answer.get("error")
            except (ValueError, AttributeError, OSError):
                code, text = None, None
            raise PublisherError(error.code, code, self._clean(f"{method} {path} answered {error.code}"
                                                              + (f" {code}" if code else "")
                                                              + (f": {text}" if text else ""))) from None
        except Exception as error:  # noqa: BLE001 - no answer at all
            raise PublisherError(None, None, self._clean(f"{method} {path}: no answer "
                                                         f"({getattr(error, 'reason', None) or error})")) from None
        try:
            return json.loads(text) if text.strip() else None
        except ValueError:
            raise PublisherError(None, None, f"{method} {path}: the answer was not JSON") from None

    def _clean(self, text):
        return kit.clean(text.replace(self.token, "[token]") if self.token else text, 600)

    def publish(self, body):
        return self.call("POST", "/api/shared-work/publisher/tasks", body)

    def close(self, problem_slug, list_key, reason):
        return self.call("POST", f"/api/shared-work/publisher/tasks/{problem_slug}/{list_key}/close", {"reason": reason})

    def tasks(self, state=None):
        """Every task list, or those in one state (OPEN, CLOSED, REPLACED or DRAFT)."""
        answer = self.call("GET", "/api/shared-work/publisher/tasks" + (f"?state={state}" if state else ""))
        items = answer.get("tasks") if isinstance(answer, dict) else None
        if not isinstance(items, list):
            raise PublisherError(None, None, "GET /api/shared-work/publisher/tasks: the answer has no tasks list")
        return [item for item in items if isinstance(item, dict)]


def list_page_url(problem_slug, list_key, site=None):
    return f"{site or kit.SITE}/problems/{problem_slug}/shared-work/{list_key}"


def manifest_of(task, root=None):
    """The exact text of tasks/<slug>/manifest.ndjson; ValueError when it is not the line the kit writes."""
    with open(os.path.join(root or kit.TASKS, task["slug"], "manifest.ndjson"), "rb") as fh:
        text = fh.read().decode("utf-8")
    if text != kit.manifest_text(task):
        raise ValueError(f"tasks/{task['slug']}/manifest.ndjson is not the line the kit writes for task.json "
                         f"(python3 tools/import_task.py tasks/{task['slug']} writes it)")
    return text


def accepted_best(score, problem_slug, list_key, on=None):
    """The best known value of the round after an accepted run: the run's score, with Papex as the source. The
    accepted object is shown on that list's page, so it is also where the best known object is published. on: the
    date the run was accepted (UTC), so that a retry sends the very same request; today (UTC) when not given."""
    on = on if isinstance(on, str) and kit._date(on) else kit.today()
    page = list_page_url(problem_slug, list_key)
    return {"value": score, "by": ACCEPTED_BY, "year": int(on[:4]), "sourceName": "Papex", "sourceUrl": page,
            "asOf": on, "objectUrl": page}


def publish_body(task, round_=1, best=None, replaces=None, problem_slug=None, root=None):
    """The body of POST /api/shared-work/publisher/tasks for one round of a task (the contract's shape).
    best: that round's bestKnown (default task.json's). Papex's rules (server item 17): previousListKey is null in
    round 1 and the round before otherwise; replaces names that open round, or is null when that round is CLOSED
    (a pulled card published again); round is the highest round on Papex + 1."""
    previous = None if round_ == 1 else f"{task['slug']}-r{round_ - 1}"
    if round_ < 1 or (replaces is not None and replaces != previous):
        raise ValueError(f"round {round_} of {task['slug']} can replace only {previous or 'no list'}, not {replaces}")
    slug = problem_slug or task["problem"]["slug"]
    return {
        "problem": {"slug": slug, "create": task["problem"]["create"] if round_ == 1 else None},
        "list": {"key": f"{task['slug']}-r{round_}", "title": task["title"].strip(),
                 "shortTitle": task["shortTitle"].strip(), "description": task["description"].strip(),
                 "leadName": LEAD_NAME, "resultLine": task["resultLine"].strip(),
                 "expectedSeconds": task["expectedSeconds"],
                 "howTo": {"requirements": task["requirements"].strip(), "checkedHow": task["checkedHow"].strip(),
                           "rulesUrl": None, "task": kit.howto_task(task, round_, best, previous)}},
        "manifest": manifest_of(task, root),
        "replaces": replaces}


def next_round_body(task, list_task, score, problem_slug, list_key, on=None, root=None):
    """The round after list_key, which accepted a run with this score on the date `on` (list_task: that list's
    howTo.task)."""
    round_ = int(list_task.get("round") or 0) + 1
    return publish_body(task, round_, accepted_best(score, problem_slug, list_key, on), list_key, problem_slug, root)


TASK_FIELDS = ("slug", "kind", "objective", "direction", "scoreLabel", "bestKnown", "searched", "objectFormat", "shows",
               "notCovered", "alsoBelongsAt", "effort", "maxObjectBytes", "checkerSeconds", "checkerSha256", "round",
               "previousListKey", "family", "params")


def family_round_body(page, problem_slug, list_task, best, replaces):
    """The next round of a family's task, which has no folder in this kit: the texts from the replaced list's page
    on Papex, the task as that list holds it with round + 1, previousListKey = replaces, and best as its best known
    value. The manifest is the kit's line for the task (key, kind find, expected seconds, the checker)."""
    lst, howto = page["list"], page["howTo"]
    old = {k: list_task[k] for k in TASK_FIELDS if k in list_task}
    task = dict(old, round=int(old["round"]) + 1, bestKnown=best)
    task["previousListKey"] = f"{task['slug']}-r{task['round'] - 1}"
    if replaces is not None and replaces != task["previousListKey"]:
        raise ValueError(f"round {task['round']} of {task['slug']} can replace only {task['previousListKey']}")
    kinds = [k for k in page.get("kinds") or [] if isinstance(k, dict)]
    expected = kinds[0].get("expectedSeconds") if kinds else None
    if not isinstance(expected, int):
        raise ValueError("the list's page gives no expected seconds")
    manifest = json.dumps({"key": task["slug"], "kind": kit.FIND_KIND, "expectedSeconds": expected,
                           "inputSha256": task["checkerSha256"]}, separators=(",", ":")) + "\n"
    return {"problem": {"slug": problem_slug, "create": None},
            "list": {"key": f"{task['slug']}-r{task['round']}", "title": lst["title"], "shortTitle": lst["shortTitle"],
                     "description": lst["description"], "leadName": lst.get("leadName") or LEAD_NAME,
                     "resultLine": lst["resultLine"], "expectedSeconds": expected,
                     "howTo": {"requirements": howto.get("requirements"), "checkedHow": howto.get("checkedHow"),
                               "rulesUrl": howto.get("rulesUrl"), "task": task}},
            "manifest": manifest, "replaces": replaces}


def today():
    return datetime.date.today().isoformat()
