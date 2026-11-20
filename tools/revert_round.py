#!/usr/bin/env python3
"""After an accepted run is withdrawn: publish the task's next round with the best known value that held before it.

  PAPEX_SHARED_WORK_PUBLISHER_TOKEN=… python3 tools/revert_round.py PROBLEM LIST_KEY [--api URL] [--dry-run]

LIST_KEY is the round whose accepted run was withdrawn. The round after it was published with that run's score as
its best known value. This reads Papex's publisher listing (GET /api/shared-work/publisher/tasks), takes the best
known value LIST_KEY itself had (the value before the withdrawn run), and publishes a new round that replaces the
task's open round with that value. A task folder of this kit gives the texts; a family's task takes them from the
open round's page on Papex. --dry-run reads the listing, prints the request and sends nothing. The token is read
from the environment, sent only as the Authorization header, and never printed.
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


def revert_body(items, problem, key, read_page, root=None):
    """The publish request that undoes the withdrawn run of list `key` (SystemExit saying why it cannot)."""
    withdrawn = next((i for i in items if i.get("problemSlug") == problem and i.get("listKey") == key), None)
    if withdrawn is None or not isinstance(withdrawn.get("task"), dict):
        sys.exit(f"Papex lists no task list {problem}/{key}.")
    task = withdrawn["task"]
    if task.get("kind") != "record":
        sys.exit("A counterexample's list closes after its accepted run; there is no best known value to restore.")
    before = task.get("bestKnown")
    rounds = [i for i in items if i.get("problemSlug") == problem and isinstance(i.get("task"), dict)
              and i["task"].get("slug") == task.get("slug") and i.get("state") == "OPEN"]
    if not rounds:
        sys.exit(f"Task {task.get('slug')} has no open round on Papex to replace.")
    current = max(rounds, key=lambda i: i["task"].get("round") or 0)
    if (current["task"].get("round") or 0) <= (task.get("round") or 0):
        sys.exit(f"The open round {current['listKey']} is not after {key}: nothing to undo.")
    replaces = current["listKey"]
    local = os.path.join(root or kit.TASKS, task["slug"], "task.json")
    if os.path.isfile(local):
        mine = kit.load_task(task["slug"], root)
        return publisher.publish_body(mine, current["task"]["round"] + 1, before, replaces, problem, root)
    page, why = read_page(problem, replaces)
    if not page:
        sys.exit(f"The page of {replaces} could not be read ({why}).")
    return publisher.family_round_body(page, problem, current["task"], before, replaces)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    dry = "--dry-run" in argv
    argv = [a for a in argv if a != "--dry-run"]
    api = kit.api_address(take(argv, "--api") or kit.DEFAULT_API)
    if len(argv) != 2 or any(a.startswith("-") for a in argv) or not kit.LIST_KEY_RE.match(argv[1]):
        sys.exit(__doc__.strip())
    problem, key = argv
    token = os.environ.get(publisher.TOKEN_ENV, "").strip()
    if not token:
        sys.exit(f"Set {publisher.TOKEN_ENV}: the publisher listing needs it, also for --dry-run.")
    pub = publisher.Publisher(api, token)
    try:
        items = pub.tasks()
    except publisher.PublisherError as e:
        sys.exit(f"The publisher listing could not be read: {e}")
    body = revert_body(items, problem, key,
                       lambda p, k: kit.read_json_url(f"{api}/api/shared-work/problems/{p}/lists/{k}", 30))
    best = body["list"]["howTo"]["task"]["bestKnown"]
    print(f"{problem}/{body['list']['key']} replaces {body['replaces']}: best known {best['value']} "
          f"({best['sourceName']}, as of {best['asOf']}), the value before the withdrawn run of {key}")
    if dry:
        print(f"POST {api}/api/shared-work/publisher/tasks (dry run: nothing sent)")
        print(json.dumps(body, indent=1, ensure_ascii=False))
        return 0
    try:
        answer = pub.publish(body)
    except publisher.PublisherError as e:
        sys.exit(f"Not published: {e}")
    print("Already published." if isinstance(answer, dict) and answer.get("already") else "Published.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
