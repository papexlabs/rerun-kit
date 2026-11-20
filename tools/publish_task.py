#!/usr/bin/env python3
"""Publish a round of an open task on Papex, from its folder in tasks/.

  PAPEX_SHARED_WORK_PUBLISHER_TOKEN=… python3 tools/publish_task.py TASK_FOLDER
      [--round N --replaces SLUG-r<N-1> [--best-value V]] [--api URL] [--dry-run]

It runs the gates of tools/task_lint.py first and publishes nothing when one fails. Without --round it
publishes round 1 (the problem page is created from task.json's problem.create when Papex has none).
--round N --replaces SLUG-r<N-1> publishes a later round and closes the open round before it as replaced
by it; its best known value is task.json's, or with --best-value V the value of the run accepted on the
replaced list (Papex as the source, that list's page as its address, today as the date), as the runner
does. --round N without --replaces publishes a card again after it was pulled (Papex takes it only when
round N-1 is closed). Papex numbers rounds without gaps: N is the highest round there + 1.

--dry-run prints the request and sends nothing (no token needed). The token is read from the environment,
sent only as the Authorization header, and never printed. --api defaults to https://api.papex.org.
"""

import importlib.util
import json
import os
import sys

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.dont_write_bytecode = True


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


publisher = load("papex_task_publisher", os.path.join(KIT, "runner", "publisher.py"))
lint = load("papex_task_lint", os.path.join(KIT, "tools", "task_lint.py"))
kit = publisher.kit


def take(argv, name):
    if name in argv:
        i = argv.index(name)
        if i + 1 >= len(argv):
            sys.exit(f"{name} needs a value.")
        value = argv[i + 1]
        del argv[i:i + 2]
        return value
    return None


def build(folder, round_text=None, replaces=None, best_value=None):
    """The request body for the folder and round; SystemExit with a reason when the arguments do not fit."""
    folder = os.path.abspath(folder)
    root, slug = os.path.dirname(folder), os.path.basename(folder)
    try:
        task = kit.load_task(slug, root)
    except kit.TaskError as e:
        sys.exit(str(e))
    try:
        round_ = int(round_text) if round_text is not None else 1
    except ValueError:
        sys.exit("--round takes a whole number.")
    if replaces is not None and replaces != f"{slug}-r{round_ - 1}":
        sys.exit(f"Round {round_} can replace only the round before it, {slug}-r{round_ - 1}.")
    if best_value is not None and (replaces is None or not kit.is_decimal(best_value)):
        sys.exit("--best-value takes the decimal score of the run accepted on the list named by --replaces.")
    best = publisher.accepted_best(best_value, task["problem"]["slug"], replaces) if best_value is not None else None
    if task["kind"] == "counterexample" and best is not None:
        sys.exit("A counterexample task has no best known value.")
    try:
        return publisher.publish_body(task, round_, best, replaces, root=root)
    except ValueError as e:
        sys.exit(str(e))


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    dry = "--dry-run" in argv
    argv = [a for a in argv if a != "--dry-run"]
    round_text, replaces, best_value = take(argv, "--round"), take(argv, "--replaces"), take(argv, "--best-value")
    api = take(argv, "--api") or kit.DEFAULT_API
    if len(argv) != 1 or argv[0].startswith("-"):
        sys.exit(__doc__.strip())
    api = kit.api_address(api)
    folder = argv[0]
    if lint.Lint(folder, []).lint():
        sys.exit("\nNothing was published: the task does not pass every gate.")
    print()
    body = build(folder, round_text, replaces, best_value)
    if dry:
        print(f"POST {api}/api/shared-work/publisher/tasks (dry run: nothing sent)")
        print(json.dumps(body, indent=1, ensure_ascii=False))
        return 0
    token = os.environ.get(publisher.TOKEN_ENV, "").strip()
    if not token:
        sys.exit(f"Set {publisher.TOKEN_ENV} (or use --dry-run).")
    try:
        answer = publisher.Publisher(api, token).publish(body)
    except publisher.PublisherError as e:
        sys.exit(f"Not published: {e}")
    answer = answer if isinstance(answer, dict) else {}
    where = (kit.SITE + answer["path"]) if isinstance(answer.get("path"), str) else body["list"]["key"]
    print(("Already published: " if answer.get("already") else "Published: ") + f"{body['problem']['slug']}/"
          f"{body['list']['key']}" + (" (the problem page was created)" if answer.get("problemCreated") else ""))
    print(f"  {where}")
    if replaces:
        print(f"  {replaces} is closed, replaced by it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
