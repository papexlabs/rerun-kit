#!/usr/bin/env python3
"""Bring a prepared task folder into tasks/, or refresh one that is there.

  python3 tools/import_task.py SOURCE_FOLDER [--update]
  python3 tools/import_task.py tasks/SLUG

The first form copies a task folder (checker.py, best_known.json, card.md, probe.md, probe/, task.json) into
tasks/<slug>/. A task.json in the format of tasks/README.md is copied as it is; one in the earlier draft format
(SPEC v0: "id", "problemTitle", "problemSource", "bestKnown.fetchedOn", …) is converted where the conversion is
mechanical, and every field it cannot fill is written as "TODO: …". It never changes a value it copies (a number
in bestKnown.value is written as the same decimal text) and never changes a checker. It writes nothing over an
existing folder unless --update is given; --update replaces the files the source has and deletes none.

When the folder has no probe/cases.json, one is written from probe.md: every "$ python3 checker.py probe/FILE"
line followed by the checker's output line becomes a case expecting exactly that output, labelled from probe.md's
table; a probe file without such lines gets a TODO case.

Both forms then write checkerSha256 into task.json (the SHA-256 of checker.py) and manifest.ndjson (the list's
one line). Run the second form again after editing task.json or checker.py. Then run the gates:

  python3 tools/task_lint.py tasks/SLUG
"""

import json
import os
import re
import shutil
import sys

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.dont_write_bytecode = True
sys.path.insert(0, KIT)
import task as kit  # noqa: E402  (task.py next to this tool)

TODO = "TODO: "
COPIED = ("checker.py", "best_known.json", "card.md", "probe.md")
ORDER = ["schema", "slug", "kind", "title", "shortTitle", "description", "objective", "direction", "scorePlaces",
         "scoreLabel",
         "bestKnown", "searched", "objectFormat", "objectKeys", "shows", "notCovered", "alsoBelongsAt", "effort", "limits",
         "resultLine", "requirements", "checkedHow", "expectedSeconds", "problem", "sources", "checkerSha256"]
OUTPUT_RE = re.compile(r"^\$ python3 (?:-I )?checker\.py (\S+)\s*$")


def number_text(value):
    """A number of the old format as the decimal text the new one keeps (the same digits)."""
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    return value


def convert(old):
    """An old-format task.json as the new format, with TODO where a person must write a field."""
    if old.get("schema") == kit.TASK_SCHEMA:
        return dict(old), []
    new, todo = {}, []

    def need(key, what):
        new[key] = TODO + what
        todo.append(key)

    new["schema"] = kit.TASK_SCHEMA
    new["slug"] = old.get("slug") or old.get("id")
    new["kind"] = old.get("kind")
    need("title", "the card's heading, without the best known value (at most 200 characters)")
    need("shortTitle", "a few words (at most 80)")
    need("description", "one or two sentences for the list (at most 300)")
    new["objective"] = old.get("objective")
    new["direction"] = old.get("direction")
    if old.get("kind") == "record":
        need("scoreLabel", "what the score counts, such as points (at most 40), or delete this field")
    best = old.get("bestKnown")
    if old.get("kind") == "record" and isinstance(best, dict):
        new["bestKnown"] = {"value": number_text(best.get("value")), "by": best.get("by"), "year": best.get("year"),
                            "sourceName": TODO + "the source's short name, such as arXiv 2511.02864",
                            "sourceUrl": best.get("sourceUrl"), "asOf": best.get("asOf") or best.get("fetchedOn"),
                            "quote": best.get("quote")}
        todo.append("bestKnown.sourceName")
    else:
        new["bestKnown"] = None
        if old.get("kind") == "counterexample":
            need("searched", "what is already ruled out, with its source (at most 400), or delete this field")
    new["objectFormat"] = old.get("objectFormat")
    need("objectKeys", "the list of the object's keys, such as [\"n\", \"points\"]: the only keys it may hold")
    need("shows", "what a pass shows (at most 400)")
    new["notCovered"] = old.get("notCovered")
    new["alsoBelongsAt"] = old.get("alsoBelongsAt")
    need("effort", "rough effort, from the sources (at most 200), or delete this field")
    new["limits"] = old.get("limits")
    need("resultLine", "Result: … what an accepted run says (at most 400)")
    need("requirements", "what a person needs (at most 600)")
    need("checkedHow", "how the checker decides (at most 600)")
    new["expectedSeconds"] = 3600
    source = old.get("problemSource") or {}
    new["problem"] = {"slug": TODO + "the problem's slug on Papex", "create": {
        "slug": TODO + "the same slug, or set create to null when the problem page exists",
        "title": old.get("problemTitle"), "question": TODO + "the question in one sentence (at most 500)",
        "summary": TODO + "two or three sentences (at most 2000)", "field": "mathematics", "sinceYear": None,
        "prize": None, "initialStatus": {"status": "OPEN", "source": {
            "name": source.get("name"), "list": TODO + "the list or site the source is part of",
            "url": source.get("url")}, "sourceDate": None, "checkedOn": source.get("fetchedOn")}}}
    todo += ["problem.slug", "problem.create"]
    sources = list(old.get("sources") or [])
    if source.get("quote"):
        sources.insert(0, {"fact": "The problem as its source states it", "url": source.get("url"),
                           "quote": source.get("quote"), "fetchedOn": source.get("fetchedOn")})
    if isinstance(best, dict) and best.get("quote"):
        sources.insert(1 if source.get("quote") else 0, {"fact": "The best known value", "url": best.get("sourceUrl"),
                                                         "quote": best.get("quote"), "fetchedOn": best.get("fetchedOn")})
    new["sources"] = sources
    return new, todo


def cases_from_probe(folder):
    """probe/cases.json from probe.md: each probe file with the output line probe.md records for it."""
    try:
        lines = open(os.path.join(folder, "probe.md"), encoding="utf-8").read().splitlines()
    except OSError:
        lines = []
    outputs, labels = {}, {}
    for i, line in enumerate(lines):
        m = OUTPUT_RE.match(line.strip())
        if m and i + 1 < len(lines) and lines[i + 1].strip().startswith("{"):
            try:
                outputs[m.group(1)] = json.loads(lines[i + 1].strip(), parse_float=str, parse_int=str)
            except ValueError:
                pass
        cells = [c.strip() for c in line.strip().strip("|").split("|")] if line.strip().startswith("|") else []
        if len(cells) >= 2 and cells[0].endswith(".json"):
            labels[cells[0]] = cells[1]
    cases = []
    probe = os.path.join(folder, "probe")
    for name in sorted(os.listdir(probe)) if os.path.isdir(probe) else []:
        if not name.endswith(".json") or name == "cases.json":
            continue
        out = outputs.get("probe/" + name)
        case = {"file": name, "label": labels.get(name) or TODO + "what this file is"}
        if out is None:
            case["expect"] = TODO + "{\"valid\": false} or the exact output probe.md records"
        else:
            case["expect"] = {"valid": out.get("valid"), "score": out.get("score"), "reason": out.get("reason")}
        cases.append(case)
    return {"cases": cases}


def write_json(path, value):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def refresh(folder):
    """checkerSha256 into task.json (only that text changes) and manifest.ndjson from task.json."""
    path = os.path.join(folder, "task.json")
    text = open(path, encoding="utf-8").read()
    sha = kit.checker_sha256(folder)
    new, count = re.subn(r'("checkerSha256"\s*:\s*)("[^"]*"|null)', lambda m: m.group(1) + json.dumps(sha), text)
    if count != 1:
        sys.exit(f"{path}: needs exactly one \"checkerSha256\" field.")
    if new != text:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(new)
    task = json.loads(new)
    if not isinstance(task.get("expectedSeconds"), int) or not isinstance(task.get("slug"), str):
        return sha, None
    manifest = kit.manifest_text(task)
    with open(os.path.join(folder, "manifest.ndjson"), "w", encoding="utf-8", newline="") as fh:
        fh.write(manifest)
    return sha, manifest


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    update = "--update" in argv
    argv = [a for a in argv if a != "--update"]
    if len(argv) != 1:
        sys.exit(__doc__.strip())
    source = os.path.abspath(argv[0])
    tasks = os.path.abspath(kit.TASKS)
    if os.path.dirname(source) == tasks:  # refresh a folder already in tasks/
        sha, manifest = refresh(source)
        print(f"tasks/{os.path.basename(source)}: checkerSha256 {sha}")
        print(f"  manifest.ndjson: {manifest.strip() if manifest else 'not written (expectedSeconds missing)'}")
        print(f"Next: python3 tools/task_lint.py tasks/{os.path.basename(source)}")
        return 0
    try:
        old = json.load(open(os.path.join(source, "task.json"), encoding="utf-8"))
    except (OSError, ValueError) as e:
        sys.exit(f"{source}/task.json could not be read ({e}).")
    new, todo = convert(old)
    slug = new.get("slug")
    if not isinstance(slug, str) or not kit.SLUG_RE.match(slug) or len(slug) > 34:
        sys.exit("The task's slug (\"slug\", or \"id\" in the earlier format) is not usable as a folder name.")
    dest = os.path.join(tasks, slug)
    if os.path.exists(dest) and not update:
        sys.exit(f"tasks/{slug} exists. Add --update to replace the files the source has (nothing is deleted).")
    os.makedirs(os.path.join(dest, "probe"), exist_ok=True)
    for name in COPIED:
        if os.path.isfile(os.path.join(source, name)):
            shutil.copyfile(os.path.join(source, name), os.path.join(dest, name))
    probe = os.path.join(source, "probe")
    for name in sorted(os.listdir(probe)) if os.path.isdir(probe) else []:
        if os.path.isfile(os.path.join(probe, name)) and name.endswith((".json", ".py")):
            shutil.copyfile(os.path.join(probe, name), os.path.join(dest, "probe", name))
    if not os.path.isfile(os.path.join(dest, "probe", "cases.json")):
        write_json(os.path.join(dest, "probe", "cases.json"), cases_from_probe(dest))
    new.setdefault("checkerSha256", None)
    ordered = {k: new[k] for k in ORDER if k in new}
    ordered.update({k: v for k, v in new.items() if k not in ORDER})
    write_json(os.path.join(dest, "task.json"), ordered)
    sha, manifest = refresh(dest)
    print(f"tasks/{slug}: copied from {source}")
    print(f"  checkerSha256 {sha}")
    print(f"  manifest.ndjson: {manifest.strip() if manifest else 'not written (expectedSeconds missing)'}")
    todos = todo + [f"probe/cases.json: {c['file']}" for c in json.load(open(os.path.join(dest, "probe", "cases.json")))
                    ["cases"] if TODO in json.dumps(c)]
    if todos:
        print(f"  To write by hand ({len(todos)}): " + ", ".join(todos))
        print(f"  Then: python3 tools/import_task.py tasks/{slug}   (refreshes the hash and the manifest)")
    print(f"Next: python3 tools/task_lint.py tasks/{slug}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
