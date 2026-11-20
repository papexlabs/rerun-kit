#!/usr/bin/env python3
"""Bring a family's folder into families/, then run the family gates.

  python3 tools/import_family.py SOURCE_FOLDER [--update]

A family is one checker that takes parameters (families/<family>/: checker.py, README.md, probe/). The folder's name
is the family's name. This copies checker.py and README.md as they are, and the probe cases into the kit's layout:

  probe/cases.json   {"checkerSeconds": 60, "cases": [{"object": "a.json", "params": "p.json", "label": "…",
                                                        "line": "<the checker's exact output line>"}, …]}

with the object and params files next to it. The source's probe cases may be laid out in any of these ways (the
importer says which one it read):

  A  probe/cases.json (or cases.ndjson) in the kit's layout, or with other names for the same fields: objectFile,
     paramsFile, name/what for the label, expected/expectedLine/output for the line; object and params may also be
     written inline (a JSON object instead of a file name), and an expected output may be a JSON object instead of
     a line (then the kit compares valid, score and reason);
  B  one folder per case, probe/<case>/ with object.json, params.json and expected (.json, .txt or no suffix);
  C  flat files probe/<case>.object.json, probe/<case>.params.json and probe/<case>.expected(.json|.txt).

A probe file is named by its plain name in its folder: a name with a folder part ("../x", "/etc/x", "a/b.json"), a
name starting with a dot, or a link is refused, so nothing outside the source's probe folder is read and nothing
outside families/<family>/probe/ is written. It never writes in the source folder, and writes nothing over a family
already in families/ unless --update is given (then it replaces the files the source has; it deletes nothing). Then
it runs
python3 tools/task_lint.py --family families/<family>.
"""

import importlib.util
import json
import os
import shutil
import sys

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.dont_write_bytecode = True
sys.path.insert(0, KIT)
import task as kit  # noqa: E402

FIELD = {"object": ("object", "objectFile", "object_file"), "params": ("params", "paramsFile", "params_file"),
         "label": ("label", "name", "what", "description"),
         "line": ("line", "expected", "expectedLine", "expected_line", "output", "expect")}


def plain_file(folder, name):
    """(the path of the probe file `name` in folder, None), or (None, why it is refused)."""
    if not isinstance(name, str) or not name or name != os.path.basename(name) or "\\" in name or "/" in name \
            or name.startswith(".") or os.path.isabs(name) or kit.invisible(name):
        return None, f"{json.dumps(name)[:80]} is not a plain file name in the probe folder"
    path = os.path.join(folder, name)
    if os.path.islink(path) or not os.path.isfile(path):
        return None, f"{json.dumps(name)[:80]} is " + ("a link" if os.path.islink(path) else "not a file") \
            + " in the probe folder"
    if os.path.dirname(os.path.realpath(path)) != os.path.realpath(folder):
        return None, f"{json.dumps(name)[:80]} is not in the probe folder"
    return path, None


def pick(case, field):
    for name in FIELD[field]:
        if name in case:
            return case[name]
    return None


def read_cases_file(probe):
    """Layout A: the cases of probe/cases.json or probe/cases.ndjson, or None."""
    for name in ("cases.json", "cases.ndjson"):
        path = os.path.join(probe, name)
        if not os.path.isfile(path):
            continue
        text = open(path, encoding="utf-8").read()
        if name.endswith(".ndjson"):
            return {"cases": [json.loads(line) for line in text.splitlines() if line.strip()]}, f"A ({name})"
        spec = json.loads(text)
        return (spec if isinstance(spec, dict) else {"cases": spec}), f"A ({name})"
    return None, None


def expected_in(folder, stem):
    for suffix in (".json", ".txt", ".line", ""):
        path = os.path.join(folder, stem + suffix)
        if os.path.isfile(path):
            return open(path, encoding="utf-8").read().strip()
    return None


def gather(source):
    """(cases as dicts {object, params, label, line|expect, objectData?, paramsData?}, checkerSeconds, layout)."""
    probe = os.path.join(source, "probe")
    spec, layout = read_cases_file(probe)
    found = []
    if spec is not None:
        for i, case in enumerate(spec.get("cases") or []):
            found.append({"object": pick(case, "object"), "params": pick(case, "params"),
                          "label": pick(case, "label") or f"case {i + 1}", "line": pick(case, "line"), "dir": probe})
        return found, spec.get("checkerSeconds", 60), layout
    names = sorted(os.listdir(probe)) if os.path.isdir(probe) else []
    dirs = [n for n in names if os.path.isdir(os.path.join(probe, n))]
    if dirs:
        for d in dirs:
            folder = os.path.join(probe, d)
            found.append({"object": "object.json", "params": "params.json", "label": d,
                          "line": expected_in(folder, "expected"), "dir": folder})
        return found, 60, "B (one folder per case)"
    stems = sorted({n[:-len(".object.json")] for n in names if n.endswith(".object.json")})
    for stem in stems:
        found.append({"object": stem + ".object.json", "params": stem + ".params.json", "label": stem,
                      "line": expected_in(probe, stem + ".expected"), "dir": probe})
    return found, 60, "C (flat files)" if stems else "none"


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    update = "--update" in argv
    argv = [a for a in argv if a != "--update"]
    if len(argv) != 1:
        sys.exit(__doc__.strip())
    source = os.path.abspath(argv[0])
    name = os.path.basename(os.path.normpath(source))
    if not kit.SLUG_RE.match(name) or len(name) > 40:
        sys.exit(f"{name} is not a family's name (lowercase letters, digits and hyphens, at most 40).")
    if not os.path.isfile(os.path.join(source, "checker.py")):
        sys.exit(f"{source} has no checker.py.")
    dest = os.path.join(kit.FAMILIES, name)
    if os.path.exists(dest) and not update:
        sys.exit(f"families/{name} exists. Add --update to replace the files the source has (nothing is deleted).")
    cases, seconds, layout = gather(source)
    os.makedirs(os.path.join(dest, "probe"), exist_ok=True)
    shutil.copyfile(os.path.join(source, "checker.py"), os.path.join(dest, "checker.py"))
    if os.path.isfile(os.path.join(source, "README.md")):
        shutil.copyfile(os.path.join(source, "README.md"), os.path.join(dest, "README.md"))
    written, problems = [], []
    for i, case in enumerate(cases, 1):
        entry = {}
        for field in ("object", "params"):
            value = case[field]
            if isinstance(value, (dict, list)):  # written inline: a file of the kit's own
                fname = f"case{i:02d}.{field}.json"
                with open(os.path.join(dest, "probe", fname), "w", encoding="utf-8") as fh:
                    fh.write(json.dumps(value) + "\n")
            elif isinstance(value, str):
                path, why = plain_file(case["dir"], value)
                if path is None:
                    problems.append(f"case {i} ({case['label']}): {field} refused: {why}")
                    fname = None
                else:
                    fname = value if case["dir"] == os.path.join(source, "probe") else f"case{i:02d}.{field}.json"
                    shutil.copyfile(path, os.path.join(dest, "probe", fname))
            else:
                problems.append(f"case {i} ({case['label']}): no {field} file")
                fname = None
            entry[field] = fname
        entry["label"] = str(case["label"])
        line = case["line"]
        if isinstance(line, dict):
            entry["expect"] = line
        elif isinstance(line, str) and line.strip():
            entry["line"] = line.strip()
        else:
            problems.append(f"case {i} ({case['label']}): no expected output")
        written.append(entry)
    with open(os.path.join(dest, "probe", "cases.json"), "w", encoding="utf-8") as fh:
        fh.write(json.dumps({"checkerSeconds": seconds, "cases": written}, indent=2, ensure_ascii=False) + "\n")
    print(f"families/{name}: copied from {source}")
    print(f"  checker.py {kit.checker_sha256(dest)}; README.md "
          + ("copied" if os.path.isfile(os.path.join(source, "README.md")) else "MISSING in the source"))
    print(f"  probe cases: {len(written)}, read as layout {layout}")
    for p in problems:
        print(f"  {p}")
    print(f"Next: python3 tools/task_lint.py --family families/{name}")
    spec = importlib.util.spec_from_file_location("papex_task_lint", os.path.join(KIT, "tools", "task_lint.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    print()
    return 1 if module.FamilyLint(dest, []).lint() else 0


if __name__ == "__main__":
    sys.exit(main())
