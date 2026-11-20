#!/usr/bin/env python3
"""Close one open task's list on Papex (pull its card).

  PAPEX_SHARED_WORK_PUBLISHER_TOKEN=… python3 tools/pull_task.py LIST_KEY --reason "…" [--problem SLUG]
      [--api URL] [--dry-run]

LIST_KEY is <task slug>-r<round>. The problem is task.json's (tasks/<slug>/), or --problem. The reason (1 to
300 characters) is kept in Papex's audit. Closing is idempotent: a list already closed answers as it is.
--dry-run prints the request and sends nothing. The token is read from the environment, sent only as the
Authorization header, and never printed. --api defaults to https://api.papex.org.
"""

import importlib.util
import json
import os
import sys

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.dont_write_bytecode = True
_spec = importlib.util.spec_from_file_location("papex_task_publisher", os.path.join(KIT, "runner", "publisher.py"))
publisher = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(publisher)
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


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    dry = "--dry-run" in argv
    argv = [a for a in argv if a != "--dry-run"]
    reason, problem, api = take(argv, "--reason"), take(argv, "--problem"), take(argv, "--api") or kit.DEFAULT_API
    if len(argv) != 1 or argv[0].startswith("-"):
        sys.exit(__doc__.strip())
    api = kit.api_address(api)
    key = argv[0]
    m = kit.LIST_KEY_RE.match(key)
    if not m:
        sys.exit("LIST_KEY is a task's list, such as isosceles-free-grid-100-r1.")
    if problem is None:
        try:
            problem = kit.load_task(m.group("slug"))["problem"]["slug"]
        except kit.TaskError as e:
            sys.exit(f"{e} Or name the problem with --problem.")
    if not kit.SLUG_RE.match(problem):
        sys.exit("--problem takes a problem's slug.")
    if not reason or not reason.strip() or len(reason.strip()) > 300:
        sys.exit("--reason takes why the card is pulled, 1 to 300 characters.")
    path = f"/api/shared-work/publisher/tasks/{problem}/{key}/close"
    if dry:
        print(f"POST {api}{path} (dry run: nothing sent)")
        print(json.dumps({"reason": reason.strip()}, ensure_ascii=False))
        return 0
    token = os.environ.get(publisher.TOKEN_ENV, "").strip()
    if not token:
        sys.exit(f"Set {publisher.TOKEN_ENV} (or use --dry-run).")
    try:
        answer = publisher.Publisher(api, token).close(problem, key, reason.strip())
    except publisher.PublisherError as e:
        sys.exit(f"Not closed: {e}")
    state = answer.get("state") if isinstance(answer, dict) else None
    print(f"{problem}/{key}: {state or 'closed'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
