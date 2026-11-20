#!/usr/bin/env python3
"""The gates a task folder must pass before it is published. Deterministic; nothing is sent.

  python3 tools/task_lint.py TASK_FOLDER... [--python OTHER_PYTHON]...
  python3 tools/task_lint.py --family FAMILY_FOLDER... [--python OTHER_PYTHON]...

One line per check, "ok" or "FAIL", and exit 0 only when every check of every folder passes:

  files           task.json, checker.py, best_known.json, manifest.ndjson, card.md, probe.md, probe/cases.json;
                  nothing else but probe files
  task.json       complete and within the contract's limits (tasks/README.md), the words Papex never uses absent
  howTo size      the list's howTo as tools/publish_task.py sends it, in its longest round: at most 7,500 bytes
                  (the server stores at most 8,192)
  card.md         none of the words Papex never uses (outside quotation marks)
  checker rules   read from its source: imports only from a short standard-library list, no open() but the one
                  object file read-only, no exec/eval/compile/__import__/getattr, no double-underscore names or
                  attributes but __name__ (type(e).__name__ names an error), os
                  only as os.path.getsize/isfile/exists, sys only for argv, exit, stdout and the like, no writes
  checkerSha256   task.json's value, the SHA-256 of checker.py and the manifest's inputSha256 agree
  manifest        manifest.ndjson is exactly the line the kit writes for task.json, and names the slug
  best known      record task: best_known.json, as the result file would carry it, holds exactly objectKeys, is
                  within maxObjectBytes and passes the checker with exactly bestKnown.value (the file as it is
                  gives the same line);
                  counterexample task: best_known.json (labelled variants only) does not pass the checker
  unknown keys    record task: best_known.json with one more key is rejected by the checker
  probe           every file in probe/ is a case of probe/cases.json and behaves as the case says (probe.md);
                  at least one rejected file holds a key the format does not name;
                  record task: at least three broken files rejected; counterexample task: at least three near
                  misses rejected, and at least one known-false variant accepted through its probe script ("via")
  same output     every run of the checker above gives byte-identical output when run again
  time            every run stays within checkerSeconds
  other Python    with --python: the same output lines under each interpreter named

With --family, each folder is a family (families/<family>/: checker.py, README.md, probe/cases.json):

  files           checker.py, README.md and probe/cases.json; probe files only besides
  README.md       there, and none of the words Papex never uses (outside quotation marks)
  checker rules   as above, with the two files a family's checker reads: argv[1] (the object) and argv[2]
                  (the params), each opened once, for reading
  probe           every case (object, params, label, line) gives exactly its expected line; at least one case
                  passes and at least three are rejected; a passing case gives the same line on the canonical
                  bytes Papex carries
  unknown keys    every passing case with one more key in the object, and with one more key in the params, is
                  rejected
  same output, time, other Python   as above (time: the cases' checkerSeconds, 60 by default)

The checker runs as task.py runs it (python3 -I -S -B, an empty folder, a minimal environment, time and memory
limits). The rules are read from the source; they are a gate for what Papex Labs publishes, not a sandbox.
"""

import ast
import fractions
import json
import os
import re
import sys

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.dont_write_bytecode = True
sys.path.insert(0, KIT)
import task as kit  # noqa: E402

REQUIRED = ("task.json", "checker.py", "best_known.json", "manifest.ndjson", "card.md", "probe.md")
ALLOWED_IMPORTS = {"json", "sys", "os", "os.path", "math", "fractions", "decimal", "itertools", "functools",
                   "collections", "heapq", "bisect", "re"}
FORBIDDEN_NAMES = {"exec", "eval", "compile", "__import__", "globals", "locals", "vars", "getattr", "setattr",
                   "delattr", "breakpoint", "input", "help", "exit", "quit", "memoryview", "__builtins__"}
SYS_ATTRIBUTES = {"argv", "exit", "setrecursionlimit", "getrecursionlimit", "stdout", "stderr", "version_info",
                  "maxsize", "float_info", "set_int_max_str_digits", "get_int_max_str_digits"}
OS_CHAINS = {("path", "getsize"), ("path", "isfile"), ("path", "exists")}
READ_MODES = {"r", "rb", "rt"}
WRITE_CALLS = {"write", "writelines", "dump"}
HOWTO_LIMIT = 8192  # the server's limit on a list's stored howTo
HOWTO_MAX = 7500  # what the lint lets through, measured as tools/publish_task.py sends it
EXTRA_KEY = "papexLintExtraKey"


def checker_findings(source, name="checker.py", family=False):
    """What the checker's source does that the rules forbid (empty: nothing). family: the checker of a family, which
    reads two files, the object (sys.argv[1]) and the params (sys.argv[2])."""
    indexes = (1, 2) if family else (1,)
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        return [f"{name}:{e.lineno}: Python cannot read it ({e.msg})"]
    parent = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parent[child] = node
    found = []

    def at(node, what):
        found.append(f"{name}:{getattr(node, 'lineno', 0)}: {what}")

    def chain(node):
        """The attribute names after a Name: os.path.getsize -> ['path', 'getsize']."""
        names, cur = [], node
        while isinstance(parent.get(cur), ast.Attribute) and parent[cur].value is cur:
            cur = parent[cur]
            names.append(cur.attr)
        return names, cur

    argv_names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            v = node.value
            if isinstance(v, ast.Subscript) and isinstance(v.value, ast.Attribute) and v.value.attr == "argv" \
                    and isinstance(v.value.value, ast.Name) and v.value.value.id == "sys" \
                    and isinstance(v.slice, ast.Constant) and v.slice.value in indexes:
                argv_names.add(node.targets[0].id)
    opens, opened = 0, []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name not in ALLOWED_IMPORTS:
                    at(node, f"imports {alias.name}")
                elif alias.asname and alias.name.split(".")[0] in ("os", "sys"):
                    at(node, f"imports {alias.name} under another name")
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                at(node, "a relative import")
            elif node.module in ("os", "os.path", "sys"):
                at(node, f"from {node.module} import … (write {node.module}.name instead)")
            elif node.module not in ALLOWED_IMPORTS:
                at(node, f"imports from {node.module}")
            if any(a.name == "*" for a in node.names):
                at(node, "import *")
        elif isinstance(node, ast.Name):
            if node.id in FORBIDDEN_NAMES:
                at(node, f"uses {node.id}")
            elif node.id.startswith("__") and node.id != "__name__":
                at(node, f"uses {node.id}")
            elif node.id == "open":
                call = parent.get(node)
                if not (isinstance(call, ast.Call) and call.func is node):
                    at(node, "uses open other than to call it")
            elif node.id in ("os", "sys") and isinstance(node.ctx, ast.Load):
                names, _ = chain(node)
                if node.id == "os" and tuple(names[:2]) not in OS_CHAINS:
                    at(node, "uses os." + ".".join(names[:2]) if names else "uses os itself")
                elif node.id == "sys" and (not names or names[0] not in SYS_ATTRIBUTES):
                    at(node, "uses sys." + names[0] if names else "uses sys itself")
            elif node.id in ("os", "sys"):
                at(node, f"assigns to {node.id}")
        elif isinstance(node, ast.Attribute):
            if node.attr.startswith("__") and node.attr.endswith("__") and node.attr != "__name__":
                at(node, f"uses the attribute {node.attr}")
            if node.attr in WRITE_CALLS and isinstance(parent.get(node), ast.Call) and parent[node].func is node:
                base = node.value
                to_stdout = isinstance(base, ast.Attribute) and base.attr in ("stdout", "stderr") \
                    and isinstance(base.value, ast.Name) and base.value.id == "sys"
                if not to_stdout:
                    at(node, f"writes ({node.attr})")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "open":
            opens += 1
            first = node.args[0] if node.args else None
            if not (isinstance(first, ast.Name) and first.id in argv_names):
                at(node, "opens a file other than the object file (sys.argv[1], given a name)" if not family else
                   "opens a file other than the object and params files (sys.argv[1] and sys.argv[2], given names)")
            elif first.id in opened:
                at(node, f"opens {first.id} twice")
            else:
                opened.append(first.id)
            mode = node.args[1] if len(node.args) > 1 else next((k.value for k in node.keywords if k.arg == "mode"),
                                                                 None)
            if mode is not None and not (isinstance(mode, ast.Constant) and mode.value in READ_MODES):
                at(node, "opens a file in a mode other than reading")
            if len(node.args) > 2 or any(k.arg not in ("mode", "encoding", "errors", "newline") for k in node.keywords):
                at(node, "opens a file with arguments other than mode and encoding")
    if opens > len(indexes):
        found.append(f"{name}: opens files {opens} times; " + ("the object and the params files are opened once each"
                                                               if family else "the one object file is opened once"))
    return found


MONTH = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?"
DATE_IN_TEXT = re.compile(r"\b\d{4}-\d{2}(?:-\d{2})?\b|\b\d{1,2} " + MONTH + r" \d{4}\b|\b" + MONTH
                          + r" (?:\d{1,2},? )?\d{4}\b")
NUMBER_IN_TEXT = re.compile(r"(?<![\w.,/])-?\d+(?:\.\d+)?(?:/\d+)?(?![\w/]|[.,]\d)")


def stale_texts(task):
    """Where a text that goes into the list names the task's own best known value (written as a decimal or a
    fraction) or a date. Every round copies these texts, and a later round has another best known value and another
    date: they live in bestKnown only."""
    best = (task.get("bestKnown") or {}).get("value") if task["kind"] == "record" else None
    try:
        value = fractions.Fraction(best) if isinstance(best, str) else None
    except (ValueError, ZeroDivisionError):
        value = None
    found = []
    for key in kit.PUBLIC_TEXTS:
        text = task.get(key)
        if not isinstance(text, str):
            continue
        for m in DATE_IN_TEXT.finditer(text):
            found.append(f"{key} names the date \"{m.group()}\"")
        for m in NUMBER_IN_TEXT.finditer(text):
            try:
                same = value is not None and fractions.Fraction(m.group()) == value
            except (ValueError, ZeroDivisionError):
                same = False
            if same:
                found.append(f"{key} names the best known value (\"{m.group()}\")")
    return found


def card_words(text):
    found = []
    for number, line in enumerate(text.splitlines(), 1):
        bare = re.sub(r"\"[^\"]*\"|“[^”]*”", "", line)
        for m in kit.NEVER_WORDS.finditer(bare):
            found.append(f"card.md:{number}: the word \"{m.group()}\"")
    return found


def howto_bytes(task):
    """The largest the list's howTo gets, in bytes, serialised as tools/publish_task.py and the runner send it
    (json.dumps, UTF-8): round 1, and a late round whose best known value is an accepted run on Papex."""
    late = {"value": "-" + "9" * 18 + "." + "9" * 18, "by": "an accepted run on Papex", "year": 9999,
            "sourceName": "Papex", "asOf": "2026-11-20",
            "sourceUrl": f"{kit.SITE}/problems/{task['problem']['slug']}/shared-work/{task['slug']}-r9998"}
    sizes = []
    for round_, best, previous in ((1, None, None), (9999, late if task["kind"] == "record" else None,
                                                     f"{task['slug']}-r9998")):
        howto = {"requirements": task["requirements"].strip(), "checkedHow": task["checkedHow"].strip(),
                 "rulesUrl": None, "task": kit.howto_task(task, round_, best, previous)}
        sizes.append(len(json.dumps(howto, ensure_ascii=False).encode("utf-8")))
    return max(sizes)


class Lint:
    def __init__(self, folder, pythons):
        self.folder, self.pythons, self.failed = os.path.abspath(folder), pythons, 0
        self.runs = []  # (what, run) of every checker run, for the "same output" and "time" checks

    def line(self, ok, gate, detail):
        print(kit.printable(f"  {'ok  ' if ok else 'FAIL'}  {gate}: {detail}"))  # details quote checkers' output
        self.failed += not ok

    def run(self, what, data, kind, via=None, python=None):
        checker = os.path.join(self.folder, "checker.py")
        script, args = (os.path.join(self.folder, "probe", via), (checker,)) if via else (checker, ())
        seconds = self.task["limits"]["checkerSeconds"] if self.task_ok else 10
        result = kit.run_checker(script, data, seconds, kind, args=args, python=python)
        if python is None:
            again = kit.run_checker(script, data, seconds, kind, args=args)
            self.runs.append((what, result, again, data, kind, via))
        return result

    def lint(self):
        folder = self.folder
        slug = os.path.basename(folder)
        print(f"tasks/{slug}" if os.path.dirname(folder) == os.path.abspath(kit.TASKS) else folder)
        missing = [n for n in REQUIRED if not os.path.isfile(os.path.join(folder, n))]
        if not os.path.isfile(os.path.join(folder, "probe", "cases.json")):
            missing.append("probe/cases.json")
        extra = []
        for name in sorted(os.listdir(folder)):
            path = os.path.join(folder, name)
            if name == "probe" and os.path.isdir(path):
                for inner in sorted(os.listdir(path)):
                    if not (inner.endswith((".json", ".py")) and os.path.isfile(os.path.join(path, inner))):
                        extra.append("probe/" + inner)
            elif not (name in REQUIRED and os.path.isfile(path)):
                extra.append(name + ("/" if os.path.isdir(path) else ""))
        self.line(not missing and not extra, "files",
                  "all there" if not missing and not extra else
                  "; ".join(filter(None, [missing and "missing " + ", ".join(missing),
                                          extra and "not a task file: " + ", ".join(sorted(extra))])))
        if missing:
            return self.failed
        try:
            self.task = kit.read_task_file(folder)
        except kit.TaskError as e:
            self.task, problems = None, [str(e)]
        else:
            problems = kit.task_problems(self.task, folder)
        self.task_ok = not problems
        if problems:
            for p in problems:
                self.line(False, "task.json", p)
            return self.failed
        task = self.task
        self.line(True, "task.json", f"complete; {kit.KIND_LABELS[task['kind']]}, maxObjectBytes {task['limits']['maxObjectBytes']:,},"
                                     f" checkerSeconds {task['limits']['checkerSeconds']}")
        stale = stale_texts(task)
        self.line(not stale, "list texts", "; ".join(stale) + " (every round copies the texts: the value and its date "
                  "live in bestKnown only)" if stale else "no list text names the best known value or a date")
        size = howto_bytes(task)
        self.line(size <= HOWTO_MAX, "howTo size",
                  f"{size:,} bytes as published, in its longest round (at most {HOWTO_MAX:,}; the server takes "
                  f"{HOWTO_LIMIT:,})")
        words = card_words(open(os.path.join(folder, "card.md"), encoding="utf-8").read())
        self.line(not words, "card.md", "; ".join(words) if words else "none of the words Papex never uses")
        source = open(os.path.join(folder, "checker.py"), encoding="utf-8").read()
        findings = checker_findings(source)
        for f in findings:
            self.line(False, "checker rules", f)
        if not findings:
            self.line(True, "checker rules", "standard-library imports from the list only; reads only the object "
                                             "file; no exec, eval, subprocess, network or writes")
        sha = kit.checker_sha256(folder)
        manifest_raw = open(os.path.join(folder, "manifest.ndjson"), "rb").read()
        try:
            line = json.loads(manifest_raw.decode("utf-8"))
        except ValueError:
            line = {}
        agree = task["checkerSha256"] == sha == line.get("inputSha256")
        self.line(agree, "checkerSha256", f"task.json, checker.py and the manifest: {sha}" if agree else
                  f"task.json {task['checkerSha256']}, checker.py {sha}, manifest {line.get('inputSha256')}"
                  " (python3 tools/import_task.py on the folder writes them)")
        want = kit.manifest_text(task).encode("utf-8")
        self.line(manifest_raw == want and len(want) <= 16384 and line.get("key") == task["slug"], "manifest",
                  want.decode().strip() if manifest_raw == want else
                  f"not the line the kit writes for task.json: {want.decode().strip()}")
        self.best_known()
        self.probe()
        same = [r[0] for r in self.runs if r[1].output != r[2].output or r[1].status != r[2].status]
        self.line(not same, "same output", f"{len(self.runs)} checker runs, each run twice: identical" if not same
                  else "differs on " + ", ".join(same))
        limit = task["limits"]["checkerSeconds"]
        worst = max(self.runs, key=lambda r: max(r[1].seconds, r[2].seconds)) if self.runs else None
        slowest = max(worst[1].seconds, worst[2].seconds) if worst else 0.0
        slow = [r[0] for r in self.runs if "did not finish" in r[1].reason or "did not finish" in r[2].reason]
        self.line(not slow and slowest <= limit, "time",
                  f"slowest run {slowest:.2f} s ({worst[0] if worst else '-'}); limit {limit} s" if not slow
                  else "over the limit: " + ", ".join(slow))
        for python in self.pythons:
            self.other_python(python)
        return self.failed

    def best_known(self):
        task, folder = self.task, self.folder
        raw = open(os.path.join(folder, "best_known.json"), "rb").read()
        kind = task["kind"]
        try:
            obj, data = kit.read_object(raw, task["limits"]["maxObjectBytes"])
        except kit.ObjectError as e:
            if kind == "record":
                self.line(False, "best known", f"best_known.json: {e}")
                return
            obj, data = None, None
        if kind == "record":
            why = kit.object_keys_problem(obj, task)
            if why:
                self.line(False, "best known", f"best_known.json: {why}")
                return
            want = task["bestKnown"]["value"]
            carried = self.run("best_known.json as carried", data, kind)
            as_is = self.run("best_known.json as it is", raw, kind)
            ok = carried.passed and carried.score == want and as_is.output == carried.output
            self.line(ok, "best known",
                      f"best_known.json ({len(data):,} bytes as carried) passes with {carried.score}, exactly "
                      f"bestKnown.value" if ok else
                      f"best_known.json gives {carried.status} {carried.score!r} ({carried.reason[:160]}); "
                      f"bestKnown.value is {want}" + ("" if as_is.output == carried.output else
                                                       "; the file as it is gives another line"))
            more = dict(obj, **{EXTRA_KEY: 1})
            extra = self.run("best_known.json with an extra key", kit.canonical_bytes(more), kind)
            self.line(extra.status == "failed", "unknown keys",
                      f"best_known.json with a key the format does not name is rejected: {extra.reason[:120]}"
                      if extra.status == "failed" else
                      f"best_known.json with an extra key \"{EXTRA_KEY}\" gives {extra.status}: the checker must "
                      "reject every key the format does not name (an accepted object is shown publicly)")
        else:
            result = self.run("best_known.json", data if data is not None else raw, kind)
            self.line(result.status == "failed", "best known",
                      "best_known.json (labelled variants only) does not pass the checker" if result.status == "failed"
                      else f"best_known.json gives {result.status}: it must hold only labelled variants")

    def probe(self):
        task, folder = self.task, self.folder
        try:
            cases = json.load(open(os.path.join(folder, "probe", "cases.json"), encoding="utf-8"),
                              parse_float=str, parse_int=str)["cases"]
            assert isinstance(cases, list)
        except (OSError, ValueError, KeyError, TypeError, AssertionError) as e:
            self.line(False, "probe", f"probe/cases.json could not be read ({e})")
            return
        files = sorted(n for n in os.listdir(os.path.join(folder, "probe")) if n.endswith(".json") and n != "cases.json")
        named = [c.get("file") for c in cases if isinstance(c, dict)]
        unlisted = [f for f in files if f not in named]
        if unlisted:
            self.line(False, "probe", "not in probe/cases.json: " + ", ".join(unlisted))
        rejected = variants = extra_keys = 0
        for case in cases:
            ok, detail = self.case(case)
            self.line(ok, "probe", detail)
            if ok and case["expect"]["valid"] is False and not case.get("via"):
                rejected += 1
                if self.has_unknown_key(case["file"]):
                    extra_keys += 1
            if ok and case["expect"]["valid"] is True and case.get("via"):
                variants += 1
        self.line(extra_keys >= 1, "probe", f"{extra_keys} probe files with a key the format does not name rejected "
                                            "(at least 1)")
        if task["kind"] == "record":
            self.line(rejected >= 3, "probe", f"{rejected} broken files rejected (at least 3)")
        else:
            self.line(rejected >= 3 and variants >= 1, "probe",
                      f"{rejected} near misses rejected (at least 3); {variants} known-false variants accepted "
                      "through their probe script (at least 1)")

    def has_unknown_key(self, name):
        try:
            obj = json.load(open(os.path.join(self.folder, "probe", name), encoding="utf-8"))
        except (OSError, ValueError):
            return False
        return isinstance(obj, dict) and bool(set(obj) - set(self.task["objectKeys"]))

    def case(self, case):
        task, folder = self.task, self.folder
        if not isinstance(case, dict) or not isinstance(case.get("file"), str) or not isinstance(case.get("label"), str) \
                or not isinstance(case.get("expect"), dict) or not isinstance(case["expect"].get("valid"), bool):
            return False, f"a case of probe/cases.json is not {{file, label, expect: {{valid, …}}}}: {str(case)[:120]}"
        name, expect, via = case["file"], case["expect"], case.get("via")
        if "TODO" in json.dumps(case):
            return False, f"{name}: the case still holds TODO"
        path = os.path.join(folder, "probe", name)
        if os.path.basename(name) != name or not os.path.isfile(path):
            return False, f"{name}: no such file in probe/"
        if via is not None and (not isinstance(via, str) or os.path.basename(via) != via or not via.endswith(".py")
                                or not os.path.isfile(os.path.join(folder, "probe", via))):
            return False, f"{name}: via names no script in probe/"
        if task["kind"] == "counterexample" and expect["valid"] and not via:
            return False, f"{name}: the task's checker is expected to accept it: that would be a counterexample"
        result = self.run(f"probe/{name}", open(path, "rb").read(), "variant" if via else task["kind"], via=via)
        got = {"passed": True, "failed": False}.get(result.status)
        problems = []
        if got is None:
            problems.append(f"no answer ({result.reason[:120]})")
        elif got != expect["valid"]:
            problems.append(f"{'passes' if got else 'is rejected'}, expected the opposite ({result.reason[:120]})")
        if got is not None and "score" in expect and not via and expect["score"] != result.score:
            problems.append(f"score {result.score}, expected {expect['score']}")
        if got is not None and "reason" in expect and expect["reason"] != result.said:
            problems.append(f"reason \"{result.reason[:100]}\", expected \"{str(expect['reason'])[:100]}\"")
        label = case["label"] if len(case["label"]) <= 70 else case["label"][:69] + "…"
        what = ("accepted" if expect["valid"] else "rejected") + (f" through {via}" if via else "")
        return not problems, f"{name} ({label}): " + ("; ".join(problems) if problems else f"{what}, as probe.md says")

    def other_python(self, python):
        differ = []
        for what, mine, _, data, kind, via in self.runs:
            theirs = self.run(what, data, kind, via=via, python=python)
            if theirs.output != mine.output:
                differ.append(what)
        self.line(not differ, "other Python", f"{python}: the same lines for all {len(self.runs)} runs" if not differ
                  else f"{python}: other lines for " + ", ".join(differ))


class FamilyLint(Lint):
    """The gates of a family's folder (--family)."""

    def lint(self):
        folder = self.folder
        name = os.path.basename(folder)
        print(f"families/{name}" if os.path.dirname(folder) == os.path.abspath(kit.FAMILIES) else folder)
        missing = [n for n in ("checker.py", "README.md", os.path.join("probe", "cases.json"))
                   if not os.path.isfile(os.path.join(folder, n))]
        extra = []
        for entry in sorted(os.listdir(folder)):
            path = os.path.join(folder, entry)
            if entry == "probe" and os.path.isdir(path):
                for inner in sorted(os.listdir(path)):
                    if not (inner.endswith((".json", ".py", ".txt")) and os.path.isfile(os.path.join(path, inner))):
                        extra.append("probe/" + inner)
            elif entry not in ("checker.py", "README.md") or not os.path.isfile(path):
                extra.append(entry + ("/" if os.path.isdir(path) else ""))
        named = kit.SLUG_RE.match(name) and len(name) <= 40
        self.line(not missing and not extra and named, "files",
                  "all there" if not missing and not extra and named else
                  "; ".join(filter(None, [missing and "missing " + ", ".join(missing),
                                          extra and "not a family file: " + ", ".join(extra),
                                          not named and "the folder's name is not a family's name"])))
        if missing:
            return self.failed
        readme = open(os.path.join(folder, "README.md"), encoding="utf-8").read()
        words = card_words(readme)
        self.line(readme.strip() and not words, "README.md",
                  "; ".join(words) if words else "there, and none of the words Papex never uses" if readme.strip()
                  else "empty")
        findings = checker_findings(open(os.path.join(folder, "checker.py"), encoding="utf-8").read(), family=True)
        for f in findings:
            self.line(False, "checker rules", f)
        if not findings:
            self.line(True, "checker rules", "standard-library imports from the list only; reads only the object and "
                                             "params files; no exec, eval, subprocess, network or writes")
        try:
            spec = json.load(open(os.path.join(folder, "probe", "cases.json"), encoding="utf-8"))
            cases, self.seconds = spec["cases"], spec.get("checkerSeconds", 60)
            assert isinstance(cases, list) and isinstance(self.seconds, int) and 1 <= self.seconds <= 120
        except (OSError, ValueError, KeyError, TypeError, AssertionError) as e:
            self.line(False, "probe", f"probe/cases.json could not be read ({e})")
            return self.failed
        self.task_ok, self.task = True, {"limits": {"checkerSeconds": self.seconds}}
        listed = {c.get(k) for c in cases if isinstance(c, dict) for k in ("object", "params")}
        unlisted = [n for n in sorted(os.listdir(os.path.join(folder, "probe")))
                    if n.endswith(".json") and n != "cases.json" and n not in listed]
        if unlisted:
            self.line(False, "probe", "not in probe/cases.json: " + ", ".join(unlisted))
        passed, rejected = [], 0
        for case in cases:
            ok, detail, got = self.family_case(case)
            self.line(ok, "probe", detail)
            if ok and got is True:
                passed.append(case)
            elif ok and got is False:
                rejected += 1
        self.line(len(passed) >= 1 and rejected >= 3, "probe",
                  f"{len(passed)} cases pass (at least 1), {rejected} are rejected (at least 3)")
        for case in passed:
            obj = json.load(open(os.path.join(folder, "probe", case["object"]), encoding="utf-8"))
            params = json.load(open(os.path.join(folder, "probe", case["params"]), encoding="utf-8"))
            for what, o, p in (("object", dict(obj, **{EXTRA_KEY: 1}) if isinstance(obj, dict) else None, params),
                               ("params", obj, dict(params, **{EXTRA_KEY: 1}) if isinstance(params, dict) else None)):
                if o is None or p is None:
                    self.line(False, "unknown keys", f"{case['object']}: the {what} is not a JSON object")
                    continue
                run = self.run(f"{case['object']} with an extra key in the {what}", kit.canonical_bytes(o), "any",
                               params=kit.canonical_bytes(p))
                self.line(run.status == "failed", "unknown keys",
                          f"{case['object']} with a key the format does not name in the {what}: rejected "
                          f"({run.reason[:80]})" if run.status == "failed" else
                          f"{case['object']} with an extra key \"{EXTRA_KEY}\" in the {what} gives {run.status}: the "
                          "checker must reject every key the format does not name (an accepted object is shown publicly)")
        same = [r[0] for r in self.runs if r[1].output != r[2].output or r[1].status != r[2].status]
        self.line(not same, "same output", f"{len(self.runs)} checker runs, each run twice: identical" if not same
                  else "differs on " + ", ".join(same))
        worst = max(self.runs, key=lambda r: max(r[1].seconds, r[2].seconds)) if self.runs else None
        slowest = max(worst[1].seconds, worst[2].seconds) if worst else 0.0
        slow = [r[0] for r in self.runs if "did not finish" in r[1].reason or "did not finish" in r[2].reason]
        self.line(not slow and slowest <= self.seconds, "time",
                  f"slowest run {slowest:.2f} s ({worst[0] if worst else '-'}); limit {self.seconds} s" if not slow
                  else "over the limit: " + ", ".join(slow))
        for python in self.pythons:
            self.other_python(python)
        return self.failed

    def run(self, what, data, kind, via=None, python=None, params=None):
        checker = os.path.join(self.folder, "checker.py")
        result = kit.run_checker(checker, data, self.seconds, kind, python=python, params=params)
        if python is None:
            again = kit.run_checker(checker, data, self.seconds, kind, params=params)
            self.runs.append((what, result, again, data, kind, params))
        return result

    def other_python(self, python):
        differ = []
        for what, mine, _, data, kind, params in self.runs:
            if kit.run_checker(os.path.join(self.folder, "checker.py"), data, self.seconds, kind, python=python,
                               params=params).output != mine.output:
                differ.append(what)
        self.line(not differ, "other Python", f"{python}: the same lines for all {len(self.runs)} runs" if not differ
                  else f"{python}: other lines for " + ", ".join(differ))

    def family_case(self, case):
        """(ok, the line to print, True/False for a case that passes or is rejected as expected)."""
        if not isinstance(case, dict) or not all(isinstance(case.get(k), str) for k in ("object", "params", "label")) \
                or not (isinstance(case.get("line"), str) or isinstance(case.get("expect"), dict)):
            return False, f"a case of probe/cases.json is not {{object, params, label, line}}: {str(case)[:120]}", None
        paths = [os.path.join(self.folder, "probe", case[k]) for k in ("object", "params")]
        if any(os.path.basename(p) != os.path.basename(os.path.normpath(p)) or not os.path.isfile(p) for p in paths) \
                or any(os.path.basename(case[k]) != case[k] for k in ("object", "params")):
            return False, f"{case['object']}: no such file in probe/ ({case['object']}, {case['params']})", None
        raw, params = (open(p, "rb").read() for p in paths)
        run = self.run(f"probe/{case['object']} + {case['params']}", raw, "any", params=params)
        line = run.output.decode("utf-8", "replace").strip()
        if isinstance(case.get("line"), str):
            want = case["line"].strip()
            ok = line == want
            valid = json.loads(want).get("valid") if want.startswith("{") else None
            detail = "the expected line" if ok else f"gives {line[:120]!r}, expected {want[:120]!r}"
        else:
            want = case["expect"]
            got = {"passed": True, "failed": False}.get(run.status)
            valid = want.get("valid")
            ok = got is not None and got == valid and ("score" not in want or str(want["score"]) == str(run.score)) \
                and ("reason" not in want or want["reason"] == run.said)
            detail = "as expected" if ok else f"gives {run.status} {run.score!r} ({run.reason[:100]})"
        if ok and valid is True:
            obj, data = kit.read_object(raw, 1 << 30)
            carried = self.run(f"probe/{case['object']} as carried", data, "any",
                               params=kit.canonical_bytes(json.loads(params.decode("utf-8"))))
            if carried.output != run.output:
                ok, detail = False, "the canonical bytes Papex carries give another line than the file"
        label = case["label"] if len(case["label"]) <= 60 else case["label"][:59] + "…"
        return ok, f"{case['object']} + {case['params']} ({label}): {detail}", valid if ok else None


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    pythons = []
    while "--python" in argv:
        i = argv.index("--python")
        if i + 1 >= len(argv):
            sys.exit("--python needs a path.")
        pythons.append(argv[i + 1])
        del argv[i:i + 2]
    family = "--family" in argv
    argv = [a for a in argv if a != "--family"]
    if not argv or any(a.startswith("-") for a in argv):
        sys.exit(__doc__.strip())
    folders = [a for a in argv if os.path.isdir(a)]
    for name in argv:
        if name not in folders:  # tasks/* also names tasks/README.md
            print(f"{name}: skipped, not a folder" + ("" if os.path.exists(name) else " (there is no such path)"))
    if len(folders) < len(argv):
        print()
    if not folders:
        print(f"No {'family' if family else 'task'} folder was named.")
        return 1
    failed_folders = 0
    for folder in folders:
        failed_folders += (FamilyLint if family else Lint)(folder, pythons).lint() > 0
        print()
    passed = len(folders) - failed_folders
    print(f"{passed} of {len(folders)} {'family' if family else 'task'} folders pass every gate.")
    return 0 if failed_folders == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
