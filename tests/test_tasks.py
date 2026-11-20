#!/usr/bin/env python3
"""Cases for open tasks: the gates (tools/task_lint.py, over every folder in tasks/ and on broken copies of a toy
task), the reading of objects, the checker's sandbox, task.py's list, check and result, the runner's decisions on
task lists end to end against a stand-in Papex, the step after an accepted run, and the publisher tools. Nothing is
sent: every request goes to a stand-in. No Lean is built.

  python3 tests/test_tasks.py OUT_DIR

OUT_DIR receives copies of the toy tasks and the files the cases write (a new folder per run; nothing is deleted).
The toy tasks are in tests/tasks/: toy-pairs (to improve a bound, trivially) and toy-euler-polynomial (a
counterexample with a known answer). They are for these cases only and are never published.
"""

import contextlib
import hashlib
import importlib.util
import io
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.dont_write_bytecode = True
KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOYS = os.path.join(KIT, "tests", "tasks")


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


kit = load("papex_task_kit_under_test", os.path.join(KIT, "task.py"))
render_task = load("render_task_under_test", os.path.join(KIT, "runner", "render_task.py"))
runner = render_task.runner
rkit = runner.taskkit
lint = load("task_lint_under_test", os.path.join(KIT, "tools", "task_lint.py"))
publish_tool = load("publish_task_under_test", os.path.join(KIT, "tools", "publish_task.py"))
pull_tool = load("pull_task_under_test", os.path.join(KIT, "tools", "pull_task.py"))
importer = load("import_task_under_test", os.path.join(KIT, "tools", "import_task.py"))

OUT = os.path.abspath(sys.argv[1])
RUN = os.path.join(OUT, "task-tests-" + time.strftime("%Y%m%dT%H%M%S") + f"-py{sys.version_info[0]}{sys.version_info[1]}")
os.makedirs(RUN)
results = []
SPOKEN = []  # every text the kit and the runner said, for the words check


def case(name, ok, detail):
    results.append({"case": name, "ok": bool(ok), "detail": str(detail)})
    print(f"{'PASS' if ok else 'FAIL'}  {name}: {detail}"[:400])


def capture(fn, *args, spoken=True):
    """(exit code or the stop message, printed lines) of fn(*args). spoken: what it printed is what a person reads
    from the kit or the runner (the words check reads it); the gates' own lines quote what they refuse."""
    out = io.StringIO()
    try:
        with contextlib.redirect_stdout(out):
            code = fn(*args)
    except SystemExit as e:
        code = e.code
    lines = out.getvalue().split("\n")
    if spoken:
        SPOKEN.extend(lines)
        if isinstance(code, str):
            SPOKEN.append(code)
    return code, lines


print(f"Python {sys.version.split()[0]}; kit {KIT}; task.py sha256 {kit.sha256_file(os.path.join(KIT, 'task.py'))}")

# ---------------------------------------------------------------------------- what the public repository holds
# Every text file git tracks or would add: no local path of a person's computer, no folder of an AI app's work, and
# no e-mail address but dev@papex.org (and example addresses a test needs). The patterns are built in pieces so that
# this file does not find itself.
import re  # noqa: E402

LEAKS = [("a macOS home folder", re.compile("/" + "Users/")), ("a Linux home folder", re.compile("/" + r"home/[^/\s]+/")),
         ("an AI app's work folder", re.compile(r"\." + "claude/"))]
ADDRESS = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
ALLOWED_ADDRESSES = {"dev" + "@papex.org"}
EXAMPLE_DOMAINS = ("example.org", "example.com", "example.net", ".test", ".invalid")
try:
    listed = subprocess.run(["git", "-C", KIT, "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
                            capture_output=True, text=True)
    names = [n for n in listed.stdout.split("\0") if n] if listed.returncode == 0 else None
except OSError:
    names = None
how = "git ls-files"
if names is None:  # no git here (a copy of the kit in a container): every file but what .gitignore leaves out
    how, names = "a walk of the folder (no git here)", []
    for base, dirs, files in os.walk(KIT):
        rel = os.path.relpath(base, KIT)
        dirs[:] = [d for d in dirs if d not in (".git", "work", "__pycache__")
                   and os.path.join(rel, d) not in ("finder/out", "finder/cache")]
        names += [os.path.normpath(os.path.join(rel, f)) for f in files if not f.endswith(".pyc") and f != ".git"]
found, scanned = [], 0
for name in names:
    try:
        with open(os.path.join(KIT, name), "rb") as fh:
            raw = fh.read()
        text = raw.decode("utf-8")
    except (OSError, UnicodeDecodeError):
        continue  # not a text file
    if "\0" in text:
        continue
    scanned += 1
    for number, line in enumerate(text.splitlines(), 1):
        for what, rx in LEAKS:
            if rx.search(line):
                found.append(f"{name}:{number}: {what}")
        for address in ADDRESS.findall(line):
            if address not in ALLOWED_ADDRESSES and not address.split("@")[1].endswith(EXAMPLE_DOMAINS):
                found.append(f"{name}:{number}: the address {address}")
case("A1 no text file of the repository names a local path, an AI app's work folder or an e-mail address but "
     "dev@papex.org", scanned > 50 and not found,
     found[:5] or f"{scanned} text files read ({how})")

# ---------------------------------------------------------------------------- the gates over every task folder
real = kit.all_tasks()
for slug in real:
    p = subprocess.run([sys.executable, "-B", os.path.join(KIT, "tools", "task_lint.py"), os.path.join(kit.TASKS, slug)],
                       capture_output=True, text=True)
    bad = [line for line in p.stdout.splitlines() if line.strip().startswith("FAIL")]
    case(f"L1 tools/task_lint.py tasks/{slug}: every gate passes (exit 0)", p.returncode == 0 and not bad,
         bad or p.stdout.strip().splitlines()[-1])
case("L1 tasks/ holds the five imported tasks", set(real) >= {"isosceles-free-grid-100", "no-five-on-a-sphere-12",
                                                             "ring-loading-lower-bound", "erdos-483-schur-six-colours",
                                                             "erdos-382-wide-bad-interval"}, real)
for slug in kit.all_tasks(TOYS):
    code, lines = capture(lint.Lint(os.path.join(TOYS, slug), [sys.executable]).lint, spoken=False)
    case(f"L2 the toy task {slug} passes every gate, also run again under --python", code == 0, [l for l in lines if "FAIL" in l] or "all ok")


def toy_copy(name, slug="toy-pairs", task_edit=None, files=None, rehash=True):
    """A copy of a toy task in RUN, changed: task_edit(task dict), files {relative path: text or None (moved aside)}.
    The copy's checkerSha256 and manifest are written again unless rehash is False."""
    folder = os.path.join(RUN, name, slug)
    shutil.copytree(os.path.join(TOYS, slug), folder)
    for rel, text in (files or {}).items():
        path = os.path.join(folder, rel)
        if text is None:
            os.rename(path, os.path.join(RUN, name, os.path.basename(rel) + ".aside"))
        else:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)
    task = json.load(open(os.path.join(folder, "task.json"), encoding="utf-8"))
    if task_edit:
        task_edit(task)
    if rehash:
        task["checkerSha256"] = kit.checker_sha256(folder)
    with open(os.path.join(folder, "task.json"), "w", encoding="utf-8") as fh:
        json.dump(task, fh, indent=2, ensure_ascii=False)
    if rehash and isinstance(task.get("expectedSeconds"), int):
        with open(os.path.join(folder, "manifest.ndjson"), "w", encoding="utf-8") as fh:
            fh.write(kit.manifest_text(task))
    return folder


def refused(label, expect, **kw):
    folder = toy_copy("lint-" + label.split()[0], **kw)
    code, lines = capture(lint.Lint(folder, []).lint, spoken=False)
    hits = [l.strip() for l in lines if l.strip().startswith("FAIL") and expect in l]
    case(f"{label}: refused", code and hits, hits[:2] or [l for l in lines if "FAIL" in l][:3] or "no FAIL line")


CHECKER = open(os.path.join(TOYS, "toy-pairs", "checker.py"), encoding="utf-8").read()


def checker_with(old, new):
    assert old in CHECKER, old
    return {"checker.py": CHECKER.replace(old, new, 1)}


for label, change, expect in [
        ("C1 import socket", ("import sys\n", "import sys\nimport socket\n"), "imports socket"),
        ("C2 import subprocess", ("import sys\n", "import sys\nimport subprocess\n"), "imports subprocess"),
        ("C3 from urllib import request", ("import sys\n", "import sys\nfrom urllib import request\n"), "imports from urllib"),
        ("C4 import ctypes", ("import sys\n", "import sys\nimport ctypes\n"), "imports ctypes"),
        ("C5 import threading", ("import sys\n", "import sys\nimport threading\n"), "imports threading"),
        ("C6 import multiprocessing", ("import sys\n", "import sys\nimport multiprocessing\n"), "imports multiprocessing"),
        ("C7 os.system", ("    seen = set()\n", "    os.system('true')\n    seen = set()\n"), "uses os.system"),
        ("C8 eval", ("    seen = set()\n", "    eval('1')\n    seen = set()\n"), "uses eval"),
        ("C9 exec", ("    seen = set()\n", "    exec('x = 1')\n    seen = set()\n"), "uses exec"),
        ("C10 compile", ("    seen = set()\n", "    compile('1', 'x', 'eval')\n    seen = set()\n"), "uses compile"),
        ("C11 __import__", ("    seen = set()\n", "    __import__('socket')\n    seen = set()\n"), "uses __import__"),
        ("C12 getattr", ("    seen = set()\n", "    getattr(os, 'system')\n    seen = set()\n"), "uses getattr"),
        ("C13 a double-underscore attribute", ("    seen = set()\n", "    ().__class__\n    seen = set()\n"),
         "the attribute __class__"),
        ("C14 open of another file", ("    seen = set()\n", "    open('/etc/hosts').read()\n    seen = set()\n"),
         "opens a file other than the object file"),
        ("C15 open for writing", ('open(path, "r", encoding="utf-8")', 'open(path, "w", encoding="utf-8")'),
         "a mode other than reading"),
        ("C16 a write", ("    seen = set()\n", "    fh.write('x')\n    seen = set()\n"), "writes (write)"),
        ("C17 sys.modules", ("    seen = set()\n", "    sys.modules['os']\n    seen = set()\n"), "uses sys.modules"),
        ("C18 os as a value", ("    seen = set()\n", "    x = os\n    seen = set()\n"), "uses os itself")]:
    refused(f"{label} in the checker", expect, files=checker_with(*change))
refused("T1 description over 300 characters", "description is 301 characters", task_edit=lambda t: t.update(description="x" * 301))
refused("T2 resultLine without \"Result: \"", "resultLine must start with", task_edit=lambda t: t.update(resultLine="An accepted run."))
refused("T3 a word Papex never uses", "uses the word \"verified\"", task_edit=lambda t: t.update(title="A verified toy"))
refused("T4 maxObjectBytes over 100,000", "limits.maxObjectBytes must be", task_edit=lambda t: t["limits"].update(maxObjectBytes=200000))
refused("T5 bestKnown.value as a number", "bestKnown.value must be a decimal", task_edit=lambda t: t["bestKnown"].update(value=10))
refused("T6 a field still TODO", "still holds TODO", task_edit=lambda t: t.update(effort="TODO: write it"))
refused("T7 no objectKeys", "objectKeys must list", task_edit=lambda t: t.pop("objectKeys"))
refused("T8 a howTo over 7,500 bytes", "howTo size", task_edit=lambda t: t.update(
    requirements="≤" * 600, checkedHow="≤" * 600, objective="≤" * 600, objectFormat="≤" * 600, shows="≤" * 400,
    notCovered="≤" * 400, alsoBelongsAt="≤" * 300, effort="≤" * 200, searched="≤" * 400,
    bestKnown=dict(t["bestKnown"], by="b" * 200, sourceName="s" * 120, sourceUrl="https://example.org/" + "u" * 1900)))
refused("B1 bestKnown.value that best_known.json does not give", "bestKnown.value is 11",
        task_edit=lambda t: t["bestKnown"].update(value="11"))
refused("B2 a best known object over maxObjectBytes", "this task takes at most 20",
        task_edit=lambda t: t["limits"].update(maxObjectBytes=20))
refused("B3 a checker that ignores keys the format does not name", "unknown keys",
        files=checker_with('set(obj) != {"numbers"} or ', ""))
refused("H1 checkerSha256 that is not checker.py's", "checkerSha256", rehash=False,
        files=checker_with("never published", "never published at all"))
refused("H2 a manifest that is not the kit's line", "manifest", files={"manifest.ndjson": '{"key":"toy-pairs"}\n'},
        rehash=False)
refused("P1 a broken probe file the checker accepts", "passes, expected the opposite",
        files={"probe/v4_ok.json": '{"numbers": [1, 2]}\n',
               "probe/cases.json": json.dumps({"cases": json.load(open(os.path.join(TOYS, "toy-pairs", "probe", "cases.json")))["cases"]
                                                         + [{"file": "v4_ok.json", "label": "said broken",
                                                             "expect": {"valid": False}}]})})
refused("P2 a probe file no case names", "not in probe/cases.json", files={"probe/v5_stray.json": "{}\n"})
refused("P3 no probe file with a key the format does not name", "with a key the format does not name rejected (at least 1)",
        files={"probe/v9_extra_key.json": None,
               "probe/cases.json": json.dumps({"cases": [c for c in json.load(open(os.path.join(TOYS, "toy-pairs", "probe", "cases.json")))["cases"]
                                                         if c["file"] != "v9_extra_key.json"]})})
refused("P4 a counterexample case the checker itself accepts", "that would be a counterexample", slug="toy-euler-polynomial",
        files={"probe/found.json": '{"n": 40}\n',
               "probe/cases.json": json.dumps({"cases": json.load(open(os.path.join(TOYS, "toy-euler-polynomial", "probe", "cases.json")))["cases"]
                                                         + [{"file": "found.json", "label": "a real one", "expect": {"valid": True}}]})})
refused("D1 a checker whose output changes from run to run", "same output",
        files=checker_with('% len(seen))', '% len(seen) + " %d" % (hash("papex") % 1000003))'))
refused("D2 a checker over its time limit", "time", task_edit=lambda t: t["limits"].update(checkerSeconds=1),
        files=checker_with("    seen = set()\n", "    while obj.get('numbers') == list(range(1, 11)):\n        pass\n    seen = set()\n"))
refused("F1 a file that is not a task file", "not a task file: notes.txt", files={"notes.txt": "x"})

# ---------------------------------------------------------------------------- reading an object
for label, raw, expect in [
        ("O1 brackets 1000 deep", b"[" * 1000 + b"]" * 1000, "brackets go 1000 deep"),
        ("O2 a whole number of 5,000 digits", b'{"n": 1' + b"0" * 5000 + b"}", "more than 4300 digits"),
        ("O3 NaN", b'{"n": NaN}', "NaN is not a number JSON allows"),
        ("O3 Infinity", b'{"n": Infinity}', "Infinity is not a number JSON allows"),
        ("O3 -Infinity", b'{"n": -Infinity}', "-Infinity is not a number JSON allows"),
        ("O4 1e999", b'{"n": 1e999}', "too large to carry"),
        ("O5 a key twice", b'{"n": 1, "n": 2}', "appears twice"),
        ("O6 a megabyte string", b'{"n": "' + b"x" * (1 << 20) + b'"}', "this task takes at most 20,000"),
        ("O7 not UTF-8", b'{"n": "\xff"}', "not UTF-8"),
        ("O8 a byte-order mark", b"\xef\xbb\xbf{}", "not JSON"),
        ("O9 half a character", b'{"n": "\\ud800"}', "unpaired surrogate"),
        ("O10 not JSON", b"{n: 1}", "not JSON")]:
    try:
        kit.read_object(raw, 20000)
        why = None
    except kit.ObjectError as e:
        why = str(e)
    case(f"{label}: refused, and why", why and expect in why, why)
obj, data = kit.read_object(b'{"b": 1, "a": [1.5, "\xc3\xa9", 1E2]}', 100)
case("O11 canonical bytes: sorted keys, no spaces, ASCII escapes, numbers as Python writes them",
     data == b'{"a":[1.5,"\\u00e9",100.0],"b":1}', data)
case("O12 brackets inside texts are not counted", kit.nesting('{"a": "[[[[[[[[["}') == 1, kit.nesting('{"a": "[[[[[[[[["}'))
case("O13 a number with more digits than a double keeps is noticed",
     not kit.same_numbers(b'{"x": 0.12345678901234567890}', kit.read_object(b'{"x": 0.12345678901234567890}', 100)[1])
     and kit.same_numbers(b'{"x": 0.25}', b'{"x":0.25}'), "noticed")
toy = kit.load_task("toy-pairs", TOYS)
case("O14 an object whose keys are not exactly objectKeys is refused before the checker runs",
     "\"note\"" in (kit.object_keys_problem({"numbers": [], "note": 1}, toy) or "")
     and "no key" in (kit.object_keys_problem({}, toy) or "") and kit.object_keys_problem([], toy)
     and kit.object_keys_problem({"numbers": []}, toy) is None, kit.object_keys_problem({"numbers": [], "note": 1}, toy))

# ---------------------------------------------------------------------------- the checker's sandbox
SANDBOX = os.path.join(RUN, "sandbox")
os.makedirs(SANDBOX)


def sandbox_checker(name, body):
    path = os.path.join(SANDBOX, name + ".py")
    with open(path, "w") as fh:
        fh.write("import json, os, sys\n" + body)
    return path


def answer(**kw):
    return "print(json.dumps(%r))\n" % dict({"valid": True, "score": 1, "reason": "ok"}, **kw)


start = time.monotonic()
run = kit.run_checker(sandbox_checker("loop", "while True:\n    pass\n"), b"{}", 1, "record")
took = time.monotonic() - start
case("S1 a checker that never ends is stopped at its time limit", run.status == "fault" and "within 1 s" in run.reason
     and took < 4, f"{run!r}, {took:.1f} s")
run = kit.run_checker(sandbox_checker("loud", "sys.stdout.write('x' * (1 << 20))\n"), b"{}", 5, "record")
case("S2 a checker that prints a megabyte: stopped, no answer", run.status == "fault" and "more than 64 KB" in run.reason, run)
run = kit.run_checker(sandbox_checker("crash", "raise ValueError('boom')\n"), b"{}", 5, "record")
case("S3 a checker that crashes: no answer, with its last line", run.status == "fault" and "ValueError: boom" in run.reason, run)
run = kit.run_checker(sandbox_checker("two", answer() + answer()), b"{}", 5, "record")
case("S4 two lines: no answer", run.status == "fault" and "2 lines" in run.reason, run)
for label, line, ok, want in [
        ("S5 a score as a text", '{"valid": true, "score": "164", "reason": "x"}', False, None),
        ("S5 a score with an exponent", '{"valid": true, "score": 1e5, "reason": "x"}', False, None),
        ("S5 a score with 19 decimals", '{"valid": true, "score": 1.1234567890123456789, "reason": "x"}', False, None),
        ("S6 a decimal score kept digit for digit", '{"valid": true, "score": 1.119047568469, "reason": "x"}', True, "1.119047568469"),
        ("S6 a whole score", '{"valid": true, "score": 164, "reason": "x"}', True, "164"),
        ("S6 trailing zeros kept", '{"valid": true, "score": 1.100000000000, "reason": "x"}', True, "1.100000000000"),
        ("S7 no score for a passing object", '{"valid": true, "score": null, "reason": "x"}', False, None),
        ("S8 another key in the line", '{"valid": true, "score": 1, "reason": "x", "more": 1}', False, None)]:
    run = kit.run_checker(sandbox_checker("line", "print(%r)\n" % line), b"{}", 5, "record")
    case(f"{label}: {'taken' if ok else 'no answer'}", (run.status == "passed" and run.score == want) if ok
         else run.status == "fault", run)
probe = sandbox_checker("probe", """info = {"cwd": os.listdir("."), "env": sorted(os.environ), "flags": [sys.flags.isolated,
    sys.flags.no_site, sys.flags.dont_write_bytecode], "stdin": sys.stdin.read(), "here": os.path.dirname(sys.argv[0]) in sys.path}
try:
    pid = os.fork()
    if pid == 0:
        os._exit(0)
    os.waitpid(pid, 0)
    info["fork"] = "allowed"
except OSError as e:
    info["fork"] = "refused"
try:
    with open("written.txt", "w") as fh:
        fh.write("x" * 10)
    info["write"] = "allowed"
except OSError as e:
    info["write"] = "refused"
print(json.dumps({"valid": False, "score": None, "reason": json.dumps(info)}))
""")
run = kit.run_checker(probe, b"{}", 5, "record")
info = json.loads(run.reason) if run.status == "failed" else {}
case("S9 the checker runs in an empty folder, with stdin closed, isolated (-I -S -B), its folder not on sys.path",
     info.get("cwd") == [] and info.get("stdin") == "" and info.get("flags") == [1, 1, 1] and info.get("here") is False, info)
case("S10 its environment holds PATH, LANG and LC_ALL only (macOS adds __CF_USER_TEXT_ENCODING)",
     set(info.get("env", ["?"])) <= {"PATH", "LANG", "LC_ALL", "LC_CTYPE", "__CF_USER_TEXT_ENCODING"}, info.get("env"))
case("S11 it can neither start a process nor write a file", info.get("fork") == "refused" and info.get("write") == "refused",
     {k: info.get(k) for k in ("fork", "write")})
if sys.platform.startswith("linux"):
    run = kit.run_checker(sandbox_checker("memory", "x = bytearray(3 << 30)\n" + answer()), b"{}", 10, "record")
    case("S12 a checker that takes 3 GB of memory: no answer (Linux limits the address space)", run.status == "fault", run)
else:
    case("S12 the memory limit: this system has none for a process (macOS); Linux has, where the runner runs", True,
         sys.platform)

# ---------------------------------------------------------------------------- a stand-in Papex
RUNNER_TOKEN, PUBLISHER_TOKEN = "made-up-runner-token-for-the-tests", "made-up-publisher-token-for-the-tests"
TASK_FIELDS = {"slug", "kind", "objective", "direction", "scoreLabel", "bestKnown", "searched", "objectFormat", "shows",
               "notCovered", "alsoBelongsAt", "effort", "maxObjectBytes", "checkerSeconds", "checkerSha256", "round",
               "previousListKey"}


class StandIn:
    """Papex as the kit, the runner and the publisher tools read it, with the server's rules for publishing (CONTRACT.md,
    Deviations, server items 1-3 and 17). Nothing leaves this computer."""

    def __init__(self):
        self.lists, self.batches, self.requests = {}, {}, []
        self.lists_down = self.pages_down = self.publish_down = False
        self.lose_answer = False  # publish, then answer 502 (the answer was lost)
        self.refuse_accept = set()  # batch keys whose ACCEPTED verdict answers 409 SHARED_WORK_TASK_MOVED_ON
        self.unreadable = set()  # list keys whose stored task cannot be read: verdicts answer 409
        self.verdict_down = {}  # batch key -> the status every verdict POST of that batch answers (500: broken)
        self.accepted_at = "2026-11-19T23:59:58Z"

    def add_list(self, problem, key, task, sha, state="OPEN", texts=None):
        self.lists[(problem, key)] = {"problem": problem, "key": key, "task": task, "sha": sha, "state": state,
                                      "taskResult": None, "replacedBy": None, "body": None,
                                      "texts": texts or {"title": "Toy", "shortTitle": "Toy", "description": "d",
                                                         "leadName": "Papex Labs", "resultLine": "Result: r",
                                                         "expectedSeconds": 60, "requirements": "q",
                                                         "checkedHow": "c"}}
        return self.lists[(problem, key)]

    def fail(self, request, status, body):
        raise urllib.error.HTTPError(request.full_url, status, "error", {}, io.BytesIO(json.dumps(body).encode()))

    def page(self, l):
        x = l["texts"]
        return {"problem": {"slug": l["problem"]},
                "list": {"key": l["key"], "state": l["state"], "sha256": l["sha"], "title": x["title"],
                         "shortTitle": x["shortTitle"], "description": x["description"], "leadName": x["leadName"],
                         "resultLine": x["resultLine"], "path": f"/problems/{l['problem']}/shared-work/{l['key']}",
                         "replacedBy": l["replacedBy"]},
                "howTo": {"requirements": x["requirements"], "checkedHow": x["checkedHow"], "rulesUrl": None,
                          "task": l["task"]},
                "kinds": [{"key": "find", "expectedSeconds": x["expectedSeconds"]}], "taskResult": l["taskResult"]}

    def urlopen(self, request, timeout=None):
        parts = urllib.parse.urlsplit(request.full_url)
        path, method = parts.path, request.get_method()
        body = json.loads(request.data) if request.data else None
        self.requests.append({"method": method, "path": path, "query": parts.query, "body": body,
                              "auth": request.get_header("Authorization"),
                              "runnerToken": request.get_header("X-papex-runner-token")})
        seg = path.strip("/").split("/")
        if path == "/api/shared-work/lists":
            if self.lists_down:
                raise urllib.error.URLError("no network in the tests")
            items = [{"problemSlug": l["problem"], "key": l["key"], "title": l["texts"]["title"], "mode": "RERUN",
                      "expectedSeconds": l["texts"]["expectedSeconds"], "task": l["task"]}
                     for l in self.lists.values() if l["state"] == "OPEN" and l["key"] not in self.unreadable]
            return self.ok({"lists": items})
        if seg[:3] == ["api", "shared-work", "problems"] and len(seg) == 6:
            if self.pages_down:
                self.fail(request, 503, {"code": "DOWN"})
            l = self.lists.get((seg[3], seg[5]))
            if l is None:
                self.fail(request, 404, {"code": "NOT_FOUND"})
            return self.ok(self.page(l))
        if path.startswith("/api/admin/shared-work/batches"):
            if request.get_header("X-papex-runner-token") != RUNNER_TOKEN:
                self.fail(request, 401, {"code": "RUNNER_TOKEN_INVALID"})
            if path == "/api/admin/shared-work/batches":
                queue = [{"batchKey": k} for k, b in self.batches.items() if b["state"] == "SUBMITTED"]
                return self.ok({"content": queue, "totalPages": 1})
            if method == "GET":
                return self.ok(self.batches[seg[4]])
            said = [body.get(k) for k in ("reasonText", "summaryText", "nextStepText")] \
                + [u.get("checkedWith") for u in body.get("units") or []]
            if any(isinstance(x, str) and kit.invisible(x) for x in said):  # as the database refuses a NUL
                self.fail(request, 500, {"code": "INTERNAL_ERROR", "message": "invalid byte sequence"})
            if seg[4] in self.verdict_down:
                self.fail(request, self.verdict_down[seg[4]], {"code": "BROKEN", "message": "broken for this batch"})
            batch = self.batches[seg[4]]
            l = next(l for l in self.lists.values() if l["key"] == batch["list"]["key"])
            if l["key"] in self.unreadable:
                self.fail(request, 409, {"code": "SHARED_WORK_TASK_UNREADABLE", "message": "unreadable"})
            if body["outcome"] == "ACCEPTED" and (seg[4] in self.refuse_accept or l["state"] != "OPEN" or l["taskResult"]):
                self.fail(request, 409, {"code": "SHARED_WORK_TASK_MOVED_ON", "message": "The task moved on"})
            batch["state"] = body["outcome"]
            if body["outcome"] == "ACCEPTED":
                extra = json.loads(batch["resultText"])["units"][0]["extra"]
                l["taskResult"] = {"score": extra["score"], "acceptedAt": self.accepted_at, "object": extra["object"],
                                   "objectSha256": "0x" + "ab" * 32}
            return self.ok({})
        if path.startswith("/api/shared-work/publisher/tasks"):
            if request.get_header("Authorization") != "Bearer " + PUBLISHER_TOKEN:
                self.fail(request, 401, {"code": "SHARED_WORK_PUBLISHER_TOKEN_INVALID", "message": "no"})
            if method == "GET":
                state = urllib.parse.parse_qs(parts.query).get("state", [None])[0]
                return self.ok({"tasks": [{"problemSlug": l["problem"], "listKey": l["key"], "state": l["state"],
                                           "task": l["task"], "replacedByListKey": l["replacedBy"] and l["replacedBy"]["key"],
                                           "taskResult": l["taskResult"] and {k: v for k, v in l["taskResult"].items()
                                                                              if k != "object"}}
                                          for l in self.lists.values() if state in (None, l["state"])]})
            if path.endswith("/close"):
                if not isinstance(body.get("reason"), str) or not 1 <= len(body["reason"]) <= 300:
                    self.fail(request, 422, {"code": "SHARED_WORK_PUBLISH_INVALID", "message": "reason"})
                l = self.lists[(seg[4], seg[5])]
                if l["state"] == "OPEN":
                    l["state"] = "CLOSED"
                return self.ok({"problemSlug": l["problem"], "listKey": l["key"], "state": l["state"]})
            if self.publish_down:
                self.fail(request, 500, {"code": "BROKEN", "message": "broken in the tests"})
            return self.publish(request, body)
        self.fail(request, 404, {"code": "NOT_FOUND"})

    def publish(self, request, body):
        lst, task = body["list"], body["list"]["howTo"]["task"]
        shape = (set(body) == {"problem", "list", "manifest", "replaces"}
                 and set(lst) == {"key", "title", "shortTitle", "description", "leadName", "resultLine",
                                  "expectedSeconds", "howTo"}
                 and set(lst["howTo"]) == {"requirements", "checkedHow", "rulesUrl", "task"}
                 and TASK_FIELDS <= set(task) <= TASK_FIELDS | {"family", "params"}
                 and lst["key"] == f"{task['slug']}-r{task['round']}"
                 and task["previousListKey"] == (None if task["round"] == 1 else f"{task['slug']}-r{task['round'] - 1}")
                 and body["replaces"] in (None, task["previousListKey"])
                 and (body["problem"]["create"] is None or (body["problem"]["create"]["prize"] is None and
                                                            body["problem"]["create"]["initialStatus"]["status"] == "OPEN")))
        if not shape:
            self.fail(request, 422, {"code": "SHARED_WORK_PUBLISH_INVALID", "message": "shape"})
        problem, slug = body["problem"]["slug"], task["slug"]
        if (problem, lst["key"]) in self.lists:
            if self.lists[(problem, lst["key"])]["body"] == body:
                return self.ok({"problemSlug": problem, "listKey": lst["key"], "listId": "x", "already": True,
                                "path": f"/problems/{problem}/shared-work/{lst['key']}", "problemCreated": False})
            self.fail(request, 409, {"code": "SHARED_WORK_TASK_KEY_TAKEN", "message": "taken"})
        rounds = [l for l in self.lists.values() if l["task"] and l["task"].get("slug") == slug]
        if any(l["problem"] != problem for l in rounds):
            self.fail(request, 409, {"code": "SHARED_WORK_TASK_SLUG_TAKEN", "message": "slug on another problem"})
        if task["round"] != max([l["task"]["round"] for l in rounds] or [0]) + 1:
            self.fail(request, 409, {"code": "SHARED_WORK_TASK_ROUND_INVALID", "message": "round"})
        if any(l["state"] == "OPEN" and l["key"] != body["replaces"] for l in rounds):
            self.fail(request, 409, {"code": "SHARED_WORK_TASK_ROUND_OPEN", "message": "another round is open"})
        if task["round"] > 1 and body["replaces"] is None and \
                self.lists[(problem, task["previousListKey"])]["state"] != "CLOSED":
            self.fail(request, 409, {"code": "SHARED_WORK_TASK_ROUND_INVALID", "message": "replaces"})
        sha = "0x" + hashlib.sha256(body["manifest"].encode()).hexdigest()
        texts = {k: lst[k] for k in ("title", "shortTitle", "description", "leadName", "resultLine", "expectedSeconds")}
        texts.update(requirements=lst["howTo"]["requirements"], checkedHow=lst["howTo"]["checkedHow"])
        new = self.add_list(problem, lst["key"], task, sha, texts=texts)
        new["body"] = body
        if body["replaces"]:
            old = self.lists[(problem, body["replaces"])]
            old["state"], old["replacedBy"] = "REPLACED", {"key": lst["key"]}
        if self.lose_answer:
            self.fail(request, 502, {"code": "BAD_GATEWAY", "message": "lost"})
        return self.ok({"problemSlug": problem, "listKey": lst["key"], "listId": "x",
                        "path": f"/problems/{problem}/shared-work/{lst['key']}", "problemCreated": False,
                        "already": False})

    @staticmethod
    def ok(value):
        return io.BytesIO(json.dumps(value).encode())


@contextlib.contextmanager
def papex(stand_in):
    saved = urllib.request.urlopen
    urllib.request.urlopen = stand_in.urlopen
    try:
        yield stand_in
    finally:
        urllib.request.urlopen = saved


def task_of(slug):
    return kit.load_task(slug, TOYS)


def howto(slug, round_=1, best=None, previous=None):
    return kit.howto_task(task_of(slug), round_, best, previous)


def manifest_sha(slug, root=TOYS):
    return "0x" + hashlib.sha256(open(os.path.join(root, slug, "manifest.ndjson"), "rb").read()).hexdigest()


# ---------------------------------------------------------------------------- task.py: list, check, result
kit.TASKS = TOYS  # the toy tasks stand in for tasks/
kit.FAMILIES = os.path.join(KIT, "tests", "families")  # and the toy family for families/
kit.CACHE, kit.CACHE_SECONDS = os.path.join(RUN, "cache", "open-lists.json"), 0  # no copy kept unless a case wants one
OBJ = os.path.join(RUN, "objects")
os.makedirs(OBJ)


def object_file(name, value, raw=None):
    path = os.path.join(OBJ, name)
    with open(path, "wb") as fh:
        fh.write(raw if raw is not None else json.dumps(value).encode())
    return path


better = object_file("eleven.json", {"numbers": list(range(1, 12))})
same = object_file("ten.json", {"numbers": list(range(1, 11))})
broken = object_file("sum.json", {"numbers": [1, 30]})
extra_key = object_file("extra.json", {"numbers": list(range(1, 12)), "note": "x"})
found = object_file("forty.json", {"n": 40})
p = StandIn()
with papex(p):
    code, lines = capture(kit.main, ["list"])
    case("K1 list without Papex rounds: each toy, its kind and best known value, and where the values come from",
         code == 0 and lines[0] == "Open tasks: 2 in this kit's tasks/, 0 more open on Papex"
         and any("toy-pairs" in l and "Improve a bound" in l and "best known 10 numbers" in l and "[this kit]" in l
                 for l in lines)
         and any("toy-euler-polynomial" in l and "Find a counterexample" in l and "none known" in l for l in lines), lines)
    p.add_list("toy-problem", "toy-pairs-r2", howto("toy-pairs", 2, {"value": "12", "by": "an accepted run on Papex",
               "year": 2026, "sourceName": "Papex", "sourceUrl": "https://papex.org/x", "asOf": "2026-11-20"},
               "toy-pairs-r1"), manifest_sha("toy-pairs"))
    code, lines = capture(kit.main, ["list"])
    case("K2 list with an open round on Papex: its value and its list", any("best known 12 numbers (Papex" in l
         and "[Papex: toy-pairs-r2]" in l for l in lines), [l for l in lines if "toy-pairs" in l])
    code, lines = capture(kit.main, ["check", "toy-pairs", better])
    case("K3 check reads the live value: 11 is not better than 12 on Papex (exit 2)", code == 2
         and any("Read from Papex (list toy-pairs-r2)" in l for l in lines)
         and lines[-2] == "Passes the checker with 11 numbers, which is not better than the best known 12. A better "
                          "object needs more than 12.", lines)
    p.lists.clear()
    code, lines = capture(kit.main, ["check", "toy-pairs", better])
    case("K4 check, valid and better (exit 0): says so with the source and date, and what to do next", code == 0
         and "Passes the checker with 11 numbers: better than the value in the kit's tests as of 2026-11-20 (10)." in lines
         and any("papex_take_shared_work, problem toy-problem, list toy-pairs-r1" in l for l in lines)
         and any(l.startswith("  python3 task.py result toy-pairs") for l in lines), lines)
    code, lines = capture(kit.main, ["check", "toy-pairs", same])
    case("K5 check, valid but not better (exit 2): both numbers, and an equal score said to be no new result",
         code == 2 and any("Passes the checker with 10 numbers, which is not better than the best known 10" in l
                           for l in lines)
         and any("may be the published object itself, or a symmetry of it. That is not a new result" in l
                 for l in lines), lines)
    code, lines = capture(kit.main, ["check", "toy-pairs", broken])
    case("K6 check, not valid (exit 3): why, and that the checker gives such an object no score (\"score\": null)",
         code == 3 and "  Checker: does not pass: 1 and 30 add up to 31" in lines
         and "Does not pass the checker." in lines and any('"score": null' in l for l in lines), lines)
    code, lines = capture(kit.main, ["check", "toy-pairs", extra_key])
    case("K7 check, a key the format does not name (exit 3): refused before the checker", code == 3
         and any("which the task's format does not name" in l for l in lines), lines)
    deep = object_file("deep.json", None, b"[" * 5000 + b"]" * 5000)
    code, lines = capture(kit.main, ["check", "toy-pairs", deep])
    case("K8 check on a hostile file (5,000 brackets deep): exit 3, no crash", code == 3
         and any("brackets go 5000 deep" in l for l in lines), lines)
    p.lists_down = True
    kit.CACHE = os.path.join(RUN, "cache", "none-yet.json")  # no copy of an earlier answer either
    start = time.monotonic()
    code, lines = capture(kit.main, ["check", "toy-pairs", better])
    case("K9 Papex cannot be reached: the check still runs, with task.json's value, and says so", code == 0
         and any("From this kit's task.json; Papex could not be reached (no network in the tests)" in l for l in lines)
         and time.monotonic() - start < 3, lines)
    p.lists_down = False


def slow(request, timeout=None):
    raise socket.timeout("timed out")


saved_open = urllib.request.urlopen
urllib.request.urlopen = slow
try:
    code, lines = capture(kit.main, ["check", "toy-pairs", better])
finally:
    urllib.request.urlopen = saved_open
case("K10 Papex does not answer in time: never the reason a check fails", code == 0
     and any("could not be reached (timed out)" in l for l in lines), lines)
WORK = os.path.join(RUN, "work")
B = "b-0a1b2c"


def result_cmd(obj_path, batch=B, problem="toy-problem", list_key="toy-pairs-r1", slug="toy-pairs", more=()):
    return capture(kit.main, ["result", slug, obj_path, "--batch", batch, "--problem", problem, "--list", list_key,
                              "--agent-host", "Test app", "--work", WORK, *more])


def result_path(batch=B):
    return os.path.join(WORK, "batches", batch, batch + ".result.json")


p = StandIn()
with papex(p):
    p.add_list("toy-problem", "toy-pairs-r1", howto("toy-pairs"), manifest_sha("toy-pairs"))
    for label, obj_path, expect in [("not valid", broken, "the object does not pass the checker"),
                                    ("valid, not better", same, "passes the checker but is not better than the best known 10"),
                                    ("a key the format does not name", extra_key, "does not pass the checker")]:
        code, lines = result_cmd(obj_path, batch="b-111111")
        case(f"K11 result refuses: {label}; no file", isinstance(code, str) and expect in code
             and not os.path.exists(result_path("b-111111")), code)
    code, lines = result_cmd(better)
    written = json.load(open(result_path())) if os.path.exists(result_path()) else {}
    data = kit.canonical_bytes({"numbers": list(range(1, 12))})
    unit = (written.get("units") or [{}])[0]
    case("K12 result writes the contract's file for a better object", code == 0
         and list(written) == ["schema", "problem", "list", "listSha256", "batch", "env", "units"]
         and written["schema"] == "papex-shared-work-result/v1" and written["problem"] == "toy-problem"
         and written["list"] == "toy-pairs-r1" and written["listSha256"] == manifest_sha("toy-pairs") and written["batch"] == B
         and list(written["env"]) == ["os", "cpu", "agentHost", "tools"] and written["env"]["agentHost"] == "Test app"
         and [t["name"] for t in written["env"]["tools"]] == ["python", "papex-task-kit"]
         and written["env"]["tools"][1]["sourceSha256"] == "0x" + kit.sha256_file(os.path.join(KIT, "task.py"))
         and list(unit) == ["key", "outcome", "seconds", "proof", "checks", "extra"] and unit["key"] == "toy-pairs"
         and unit["outcome"] == "PASS" and unit["proof"] == {"sha256": "0x" + hashlib.sha256(data).hexdigest(), "bytes": len(data)}
         and unit["checks"] == [{"tool": "checker.py", "result": "passed"}]
         and unit["extra"] == {"task": "toy-pairs", "checkerSha256": task_of("toy-pairs")["checkerSha256"], "score": "11",
                               "object": {"numbers": list(range(1, 12))}}
         and lines[-5] == f"Result file: {result_path()}", lines[-6:])
    case("K13 the file names the object's canonical bytes; extra and the file within the server's limits",
         kit.extra_bytes(unit.get("extra", {})) <= 2000 + 1024 and os.path.getsize(result_path()) <= 262144,
         f"extra {kit.extra_bytes(unit.get('extra', {}))} bytes")
    p.add_list("toy-problem", "toy-pairs-r3", howto("toy-pairs", 3, {"value": "10", "by": "x", "year": 2026, "sourceName": "Papex",
               "sourceUrl": "https://papex.org/x", "asOf": "2026-11-20"}, "toy-pairs-r2"), manifest_sha("toy-pairs"))
    p.lists[("toy-problem", "toy-pairs-r1")]["state"] = "REPLACED"
    code, _ = result_cmd(better, batch="b-222222")
    case("K14 result when the task moved on: refuses and names the open round", isinstance(code, str)
         and "the task moved on" in code and "toy-pairs-r3" in code and not os.path.exists(result_path("b-222222")), code)
    p.lists[("toy-problem", "toy-pairs-r3")]["task"] = dict(p.lists[("toy-problem", "toy-pairs-r3")]["task"],
                                                            checkerSha256="0x" + "0" * 64)
    code, _ = result_cmd(better, batch="b-333333", list_key="toy-pairs-r3")
    case("K15 result when Papex's list names another checker: refuses", isinstance(code, str)
         and "another version of this task's checker" in code, code)
    for label, args, expect in [("a batch key", dict(batch="b-XYZ"), "That is not a batch key"),
                                ("another problem", dict(problem="other-problem"), "belongs to problem toy-problem"),
                                ("another task's list", dict(list_key="toy-euler-polynomial-r1"), "are named toy-pairs-r1"),
                                ("an app name with odd characters", {}, "--agent-host takes")]:
        code, _ = result_cmd(better, **args) if label != "an app name with odd characters" else \
            capture(kit.main, ["result", "toy-pairs", better, "--batch", "b-444444", "--problem", "toy-problem", "--list",
                               "toy-pairs-r3", "--agent-host", "a;b", "--work", WORK])
        case(f"K16 result refuses {label}", isinstance(code, str) and (expect is None or expect in code), code)
    p.lists.clear()
    p.add_list("toy-problem", "toy-euler-polynomial-r1", howto("toy-euler-polynomial"), manifest_sha("toy-euler-polynomial"))
    code, lines = capture(kit.main, ["check", "toy-euler-polynomial", found])
    case("K17 check, a counterexample that passes (exit 0)", code == 0
         and "Passes the checker: the task's checker takes it as a counterexample." in lines, lines)
    code, lines = result_cmd(found, batch="b-555555", list_key="toy-euler-polynomial-r1", slug="toy-euler-polynomial")
    w = json.load(open(result_path("b-555555"))) if os.path.exists(result_path("b-555555")) else {}
    case("K18 result for a counterexample: score null", code == 0 and w["units"][0]["extra"]["score"] is None, lines[-5:])
    code, lines = capture(kit.main, ["check", "toy-pairs", object_file("digits.json", None,
                                                                       b'{"numbers": [1, 2.00000000000000000001]}')])
    case("K19 a number with more digits than the result file keeps: the check says so", any(
        "more digits than a JSON number keeps" in l for l in lines), lines)
code, lines = capture(kit.main, ["--help"])
case("K20 --help names the three commands", code == 0 and any("task.py list" in l for l in lines)
     and any("task.py check" in l for l in lines) and any("task.py result" in l for l in lines), lines[:5])

# ---------------------------------------------------------------------------- the runner, end to end
rkit.TASKS = TOYS  # the runner's own reading of tasks/ sees the toys
TOKEN_ENV, PUB_ENV, API_ENV = runner.TOKEN_ENV, runner.PUBLISHER_TOKEN_ENV, render_task.API_ENV


def made_result(slug="toy-pairs", obj=None, score="11", batch="b-7f3a21", list_key=None, **change):
    """A result file of task.py for an object, written as task.py writes it, then changed."""
    task = task_of(slug)
    obj = {"numbers": list(range(1, 12))} if obj is None else obj
    data = kit.canonical_bytes(obj)
    run = kit.Run("passed", score=score, seconds=0.1)
    result = kit.result_file(task, obj, data, run, batch, "toy-problem", list_key or f"{slug}-r1", "Test app")
    for key, value in change.items():
        if key == "kit":
            result["env"]["tools"][1]["sourceSha256"] = value
        elif key == "extra":
            result["units"][0]["extra"].update(value)
        elif key == "proof":
            result["units"][0]["proof"] = value
        elif key == "units":
            result["units"] = value
    return result


def batch_view(key, result, slug="toy-pairs", list_key=None, text=None):
    return {"batchKey": key, "state": "SUBMITTED",
            "list": {"id": "00000000-0000-0000-0000-000000000000", "key": list_key or f"{slug}-r1",
                     "sha256": manifest_sha(slug), "problemSlug": "toy-problem", "mode": "RERUN"},
            "kind": {"key": "find", "allowedOutcomes": ["PASS"], "expectedSeconds": 60}, "units": [{"key": slug}],
            "keepCount": 0, "resultText": text if text is not None else json.dumps(result, indent=1)}


def stand_in(slug="toy-pairs", state="OPEN"):
    p = StandIn()
    p.add_list("toy-problem", f"{slug}-r1", howto(slug), manifest_sha(slug), state)
    return p


def hosted(p, publisher=True):
    """runner/render_task.decide_queue() against the stand-in: (summary or failure, the runner's verdicts)."""
    env = {TOKEN_ENV: RUNNER_TOKEN, API_ENV: "https://papex.invalid"}
    if publisher:
        env[PUB_ENV] = PUBLISHER_TOKEN
    saved = {k: os.environ.get(k) for k in (TOKEN_ENV, PUB_ENV, API_ENV)}
    for k in saved:
        os.environ.pop(k, None)
    os.environ.update(env)
    try:
        with papex(p):
            with contextlib.redirect_stdout(io.StringIO()):
                got = render_task.decide_queue()
    except render_task.RunnerFailed as failure:
        got = str(failure)
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    verdicts = [r for r in p.requests if r["method"] == "POST" and r["path"].endswith("/verdict")]
    for v in verdicts:
        SPOKEN.extend(str(v["body"].get(k) or "") for k in ("reasonText", "summaryText", "nextStepText"))
        SPOKEN.extend(str(u.get("checkedWith") or "") for u in v["body"]["units"])
    if isinstance(got, dict):
        SPOKEN.extend(got["lines"])
    return got, verdicts


def posted(verdicts):
    return [(v["body"]["outcome"], v["body"]["reasonCode"]) for v in verdicts]


p = stand_in()
p.batches["b-7f3a21"] = batch_view("b-7f3a21", made_result())
got, verdicts = hosted(p)
body = verdicts[0]["body"] if verdicts else {}
new = p.lists.get(("toy-problem", "toy-pairs-r2"))
pub = [r for r in p.requests if r["path"] == "/api/shared-work/publisher/tasks" and r["method"] == "POST"]
case("R1 a better object: ACCEPTED, with what was checked, posted once with expectedState SUBMITTED",
     posted(verdicts) == [("ACCEPTED", None)] and body["expectedState"] == "SUBMITTED"
     and body["units"][0]["verdict"] == "ACCEPTED" and len(body["units"][0]["checkedWith"]) <= 160
     and "it passes, with 11 numbers. That is better than the value in the kit's tests as of 2026-11-20 (10)"
     in body["summaryText"] and isinstance(got, dict) and got["accepted"] == 1, got)
case("R2 then round 2 is published: replaces round 1, best known = the run's score with Papex as the source, dated "
     "the day Papex accepted the run (not today), the accepted object's page as where it is published",
     new is not None and new["state"] == "OPEN" and p.lists[("toy-problem", "toy-pairs-r1")]["state"] == "REPLACED"
     and new["task"]["round"] == 2 and new["task"]["previousListKey"] == "toy-pairs-r1"
     and new["task"]["bestKnown"] == {"value": "11", "by": "an accepted run on Papex", "year": 2026,
                                      "sourceName": "Papex", "asOf": "2026-11-19",
                                      "sourceUrl": "https://papex.org/problems/toy-problem/shared-work/toy-pairs-r1",
                                      "objectUrl": "https://papex.org/problems/toy-problem/shared-work/toy-pairs-r1"}
     and pub and pub[0]["body"]["problem"] == {"slug": "toy-problem", "create": None}
     and pub[0]["body"]["manifest"] == open(os.path.join(TOYS, "toy-pairs", "manifest.ndjson")).read()
     and pub[0]["auth"] == "Bearer " + PUBLISHER_TOKEN and any(l.startswith("PUBLISHED toy-problem/toy-pairs-r2") for l in got["lines"]),
     got["lines"] if isinstance(got, dict) else got)
for label, result, text, code_ in [
        ("R3 valid but not better", made_result(obj={"numbers": list(range(1, 11))}, score="10"), None, "TASK_NOT_BETTER"),
        ("R4 not valid (an object the checker rejects, with its own hash)",
         made_result(obj={"numbers": [1, 30]}, score="2"), None, "TASK_NOT_VALID"),
        ("R5 a score that is not the checker's", made_result(score="12"), None, "TASK_RESULT_MISMATCH"),
        ("R6 a proof hash that is not the object's", made_result(proof={"sha256": "0x" + "ab" * 32, "bytes": 30}), None,
         "TASK_RESULT_MISMATCH"),
        ("R7 another checker", made_result(extra={"checkerSha256": "0x" + "cd" * 32}), None, "TASK_CHECKER_CHANGED"),
        ("R8 a kit that was never released", made_result(kit="0x" + "0" * 64), None, "TOOL_NOT_ALLOWED"),
        ("R9 a key the format does not name", made_result(obj={"numbers": list(range(1, 12)), "by": "me"}), None,
         "TASK_NOT_VALID"),
        ("R10 hostile: brackets 10,000 deep", None, '{"units": ' + "[" * 10000 + "]" * 10000 + "}", "TASK_RESULT_MISMATCH"),
        ("R10 hostile: NaN", None, json.dumps(made_result()).replace('"score": "11"', '"score": NaN'), "TASK_RESULT_MISMATCH"),
        ("R10 hostile: a key twice", None, json.dumps(made_result()).replace('"score": "11"', '"score": "11", "score": "12"'),
         "TASK_RESULT_MISMATCH"),
        ("R10 hostile: a whole number of 6,000 digits", None, json.dumps(made_result()).replace(
            '"numbers": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]', '"numbers": [' + "9" * 6000 + "]"), "TASK_RESULT_MISMATCH"),
        ("R10 hostile: a 200 KB string", made_result(obj={"numbers": ["x" * 200000]}), None, "TASK_RESULT_MISMATCH"),
        ("R10 hostile: units is a text", made_result(units="x"), None, "INPUT_HASH_MISMATCH"),
        ("R10 hostile: extra is a list", None, json.dumps(made_result()).replace('"extra": {', '"extra": [{', 1)
         .replace('"object": {"numbers": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]}}', '"object": {"numbers": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]}}]'),
         "TASK_CHECKER_CHANGED"),
        ("R10 hostile: no object", None, json.dumps(made_result()).replace('"object"', '"objekt"'), "TASK_RESULT_MISMATCH"),
        ("R10 hostile: not JSON", None, "{", "TASK_RESULT_MISMATCH"),
        ("R10 hostile: a number too large", None, json.dumps(made_result()).replace('"bytes": ', '"bytes": 1e999, "b": '),
         "TASK_RESULT_MISMATCH")]:
    p = stand_in()
    p.batches["b-7f3a22"] = batch_view("b-7f3a22", result, text=text)
    start = time.monotonic()
    got, verdicts = hosted(p)
    case(f"{label}: REJECTED {code_}, nothing published", posted(verdicts) == [("REJECTED", code_)]
         and verdicts[0]["body"]["reasonText"].startswith(runner.REASON_SENTENCE.get(code_, ""))
         and verdicts[0]["body"]["units"] == [{"key": "toy-pairs", "verdict": "NOT_ACCEPTED", "reason": "BATCH_REJECTED",
                                               "checkedWith": None}]
         and not [r for r in p.requests if "/publisher/" in r["path"] and r["method"] == "POST"]
         and time.monotonic() - start < 10, (posted(verdicts), (verdicts[0]["body"]["reasonText"] if verdicts else got))[:2])
p = stand_in()
p.lists[("toy-problem", "toy-pairs-r1")]["task"] = howto("toy-pairs", 1, None, None)
p.batches["b-7f3a23"] = batch_view("b-7f3a23", made_result())
p.batches["b-7f3a23"]["list"]["sha256"] = "0x" + "1" * 64  # the list was made with another manifest (another checker)
got, verdicts = hosted(p)
case("R11 a list made with another checker's manifest: TASK_CHECKER_CHANGED", posted(verdicts) == [("REJECTED", "TASK_CHECKER_CHANGED")],
     posted(verdicts))
for label, state, result_ in [("closed", "CLOSED", None), ("replaced", "REPLACED", None), ("holding an accepted run", "OPEN", {"score": "11"})]:
    p = stand_in(state=state)
    p.lists[("toy-problem", "toy-pairs-r1")]["taskResult"] = result_
    p.batches["b-7f3a24"] = batch_view("b-7f3a24", made_result(obj={"numbers": list(range(1, 13))}, score="12"))
    got, verdicts = hosted(p)
    case(f"R12 a better object on a list {label}: REJECTED TASK_MOVED_ON", posted(verdicts) == [("REJECTED", "TASK_MOVED_ON")],
         (posted(verdicts), verdicts[0]["body"]["reasonText"] if verdicts else got))
p = stand_in()
p.batches["b-7f3a25"] = batch_view("b-7f3a25", made_result(batch="b-7f3a25"))
p.batches["b-7f3a26"] = batch_view("b-7f3a26", made_result(obj={"numbers": list(range(1, 13))}, score="12", batch="b-7f3a26"))
got, verdicts = hosted(p)
case("R13 two better runs of one list in one queue: the first ACCEPTED (round 2 published), the second TASK_MOVED_ON",
     posted(verdicts) == [("ACCEPTED", None), ("REJECTED", "TASK_MOVED_ON")]
     and p.lists[("toy-problem", "toy-pairs-r2")]["task"]["bestKnown"]["value"] == "11", posted(verdicts))
p = stand_in()
p.batches["b-7f3a25"] = batch_view("b-7f3a25", made_result(batch="b-7f3a25"))
p.batches["b-7f3a26"] = batch_view("b-7f3a26", made_result(obj={"numbers": list(range(1, 13))}, score="12", batch="b-7f3a26"))
got, verdicts = hosted(p, publisher=False)
case("R14 without the publisher token: ACCEPTED, the second TASK_MOVED_ON, nothing published, no publisher request",
     posted(verdicts) == [("ACCEPTED", None), ("REJECTED", "TASK_MOVED_ON")]
     and not [r for r in p.requests if "/publisher/" in r["path"]], posted(verdicts))
p = stand_in()
p.batches["b-7f3a27"] = batch_view("b-7f3a27", made_result())
p.refuse_accept.add("b-7f3a27")
got, verdicts = hosted(p)
case("R15 Papex refuses the acceptance (409 SHARED_WORK_TASK_MOVED_ON): REJECTED TASK_MOVED_ON is posted instead",
     posted(verdicts) == [("ACCEPTED", None), ("REJECTED", "TASK_MOVED_ON")] and isinstance(got, dict)
     and "b-7f3a27: REJECTED TASK_MOVED_ON" in got["lines"] and got["accepted"] == 0 and got["rejected"] == 1, got)
p = stand_in()
p.pages_down = True
p.batches["b-7f3a28"] = batch_view("b-7f3a28", made_result())
got, verdicts = hosted(p)
case("R16 the list's page cannot be read: no decision, left for the next run", not verdicts and isinstance(got, dict)
     and any("left for the next run" in l for l in got["lines"]) and p.batches["b-7f3a28"]["state"] == "SUBMITTED", got)
p = stand_in("toy-euler-polynomial")
p.batches["b-7f3a29"] = batch_view("b-7f3a29", made_result("toy-euler-polynomial", {"n": 40}, None), "toy-euler-polynomial")
got, verdicts = hosted(p)
case("R17 a counterexample that passes: ACCEPTED, and its list is closed", posted(verdicts) == [("ACCEPTED", None)]
     and "counterexample" in verdicts[0]["body"]["summaryText"]
     and p.lists[("toy-problem", "toy-euler-polynomial-r1")]["state"] == "CLOSED"
     and any(l.startswith("CLOSED toy-problem/toy-euler-polynomial-r1") for l in got["lines"]), got)
p = stand_in("toy-euler-polynomial")
p.batches["b-7f3a30"] = batch_view("b-7f3a30", made_result("toy-euler-polynomial", {"n": 39}, None), "toy-euler-polynomial")
got, verdicts = hosted(p)
case("R18 a counterexample that does not pass: TASK_NOT_VALID with the checker's reason",
     posted(verdicts) == [("REJECTED", "TASK_NOT_VALID")] and "1601 is prime" in verdicts[0]["body"]["reasonText"], posted(verdicts))
p = stand_in()
p.publish_down = True
p.batches["b-7f3a31"] = batch_view("b-7f3a31", made_result())
got, verdicts = hosted(p)
first = (posted(verdicts), got["lines"] if isinstance(got, dict) else got)
p.publish_down = False
got2, verdicts2 = hosted(p)
tries = [r["body"] for r in p.requests if r["method"] == "POST" and r["path"] == "/api/shared-work/publisher/tasks"]
case("R19 the step after ACCEPTED fails: the verdict stands, ALERT; the next run publishes round 2 with the very "
     "same request (Papex compares whole bodies)",
     len(tries) == 2 and tries[0] == tries[1] and first[0] == [("ACCEPTED", None)]
     and any(l.startswith("ALERT toy-pairs-r1") for l in first[1])
     and isinstance(got2, dict) and got2["alert"] is False and posted(verdicts2) == [("ACCEPTED", None)]
     and ("toy-problem", "toy-pairs-r2") in p.lists and any(l.startswith("PUBLISHED") for l in got2["lines"]),
     (first[1], got2["lines"] if isinstance(got2, dict) else got2))
faulty = os.path.join(RUN, "faulty-tasks")
os.makedirs(faulty)
folder = toy_copy("faulty", files=checker_with("    seen = set()\n", "    while 11 in obj['numbers']:\n        pass\n    seen = set()\n"),
                  task_edit=lambda t: t["limits"].update(checkerSeconds=1))
shutil.copytree(folder, os.path.join(faulty, "toy-pairs"))
rkit.TASKS = faulty
p = StandIn()
p.add_list("toy-problem", "toy-pairs-r1", kit.howto_task(kit.load_task("toy-pairs", faulty)), manifest_sha("toy-pairs", faulty))
view = batch_view("b-7f3a32", made_result())
view["list"]["sha256"] = manifest_sha("toy-pairs", faulty)
res = json.loads(view["resultText"])
res["units"][0]["extra"]["checkerSha256"] = kit.load_task("toy-pairs", faulty)["checkerSha256"]
view["resultText"] = json.dumps(res)
p.batches["b-7f3a32"] = view
start = time.monotonic()
got, verdicts = hosted(p)
rkit.TASKS = TOYS
case("R20 a checker that gives no answer on the object (time limit): TASK_NOT_VALID and an ALERT, within its limit",
     posted(verdicts) == [("REJECTED", "TASK_NOT_VALID")] and isinstance(got, dict) and got["alert"]
     and time.monotonic() - start < 6, (posted(verdicts), got["lines"] if isinstance(got, dict) else got))
p = stand_in()
p.lists[("toy-problem", "toy-pairs-r1")]["taskResult"] = {"score": "11"}
got, verdicts = hosted(p)
case("R21 an open list holding an accepted run and no next round: the runner's next run publishes it (catch-up)",
     ("toy-problem", "toy-pairs-r2") in p.lists and p.lists[("toy-problem", "toy-pairs-r2")]["task"]["bestKnown"]["value"] == "11",
     got["lines"] if isinstance(got, dict) else got)
p = stand_in()
p.batches["b-7f3a33"] = batch_view("b-7f3a33", made_result())
p.batches["b-7f3a34"] = {"batchKey": "b-7f3a34", "state": "SUBMITTED", "list": {"sha256": "0x" + "2" * 64, "key": "other-v1",
                         "problemSlug": "other"}, "units": [{"key": "u"}], "resultText": "{}"}
got, verdicts = hosted(p)
case("R22 a queue with a task run and a list of no task of this kit: one decided, one skipped as before",
     isinstance(got, dict) and got["accepted"] == 1 and got["skipped"] == 1
     and "b-7f3a34 SUBMITTED: not a list of this kit" in got["lines"], got)
case("R23 the runner's tokens never appear in what it prints",
     all(RUNNER_TOKEN not in str(x) and PUBLISHER_TOKEN not in str(x) for x in SPOKEN), "absent")
case("R24 the runner knows task.py's released versions apart from rerun.py's",
     "0x" + kit.sha256_file(os.path.join(KIT, "task.py")) in runner.known_kits("task.py")
     and not runner.known_kits("task.py") & runner.known_kits("rerun.py"),
     f"{len(runner.known_kits('task.py'))} task.py, {len(runner.known_kits('rerun.py'))} rerun.py")
listed = [line.split()[0] for line in open(os.path.join(KIT, "runner", "kits.sha256")) if line.split()[1:2] == ["task.py"]]
case("R25 runner/kits.sha256 lists this task.py (results written with it stay accepted after the next change)",
     kit.sha256_file(os.path.join(KIT, "task.py")) in listed, listed)

# ---------------------------------------------------------------------------- the publisher tools
for slug in real:
    env = dict(os.environ, **{PUB_ENV: PUBLISHER_TOKEN})
    p_ = subprocess.run([sys.executable, "-B", os.path.join(KIT, "tools", "publish_task.py"),
                         os.path.join(KIT, "tasks", slug), "--dry-run"], capture_output=True, text=True, env=env)
    text = p_.stdout
    body = json.loads(text[text.index("\n", text.index("(dry run: nothing sent)")) + 1:]) if "(dry run" in text else {}
    folder = os.path.join(KIT, "tasks", slug)
    tj = json.load(open(os.path.join(folder, "task.json")))
    case(f"P1 publish_task.py tasks/{slug} --dry-run: the gates, then the contract's request, sent nowhere",
         p_.returncode == 0 and set(body) == {"problem", "list", "manifest", "replaces"} and body["replaces"] is None
         and body["manifest"] == open(os.path.join(folder, "manifest.ndjson")).read()
         and body["problem"] == tj["problem"] and body["list"]["key"] == f"{slug}-r1"
         and set(body["list"]["howTo"]["task"]) == TASK_FIELDS and body["list"]["howTo"]["task"]["round"] == 1
         and body["list"]["howTo"]["task"]["bestKnown"] == {k: tj["bestKnown"][k] for k in
                                                           ("value", "by", "year", "sourceName", "sourceUrl", "asOf",
                                                            "objectUrl") if k in tj["bestKnown"]}
         and PUBLISHER_TOKEN not in text + p_.stderr, p_.stderr.strip()[-200:] or "ok")
code, lines = capture(publish_tool.main, [os.path.join(TOYS, "toy-pairs"), "--round", "2", "--replaces", "toy-pairs-r1",
                                          "--best-value", "11", "--dry-run"], spoken=False)
text = "\n".join(lines)
body = json.loads(text[text.index("\n", text.index("(dry run")) + 1:]) if "(dry run" in text else {}
case("P2 --round 2 --replaces --best-value: the run's value with Papex as the source, previousListKey, no problem.create",
     code == 0 and body["list"]["key"] == "toy-pairs-r2" and body["replaces"] == "toy-pairs-r1"
     and body["list"]["howTo"]["task"]["previousListKey"] == "toy-pairs-r1" and body["problem"]["create"] is None
     and body["list"]["howTo"]["task"]["bestKnown"]["by"] == "an accepted run on Papex", body.get("list", {}).get("key"))
code, lines = capture(publish_tool.main, [os.path.join(TOYS, "toy-pairs"), "--round", "2", "--dry-run"], spoken=False)
text = "\n".join(lines)
body = json.loads(text[text.index("\n", text.index("(dry run")) + 1:]) if "(dry run" in text else {}
case("P3 --round 2 without --replaces (a pulled card published again): previousListKey r1, replaces null",
     code == 0 and body["replaces"] is None and body["list"]["howTo"]["task"]["previousListKey"] == "toy-pairs-r1", code)
for label, argv, expect in [("a --replaces that is not the round before", ["--round", "3", "--replaces", "toy-pairs-r1"],
                             "can replace only the round before it, toy-pairs-r2"),
                            ("--best-value without --replaces", ["--best-value", "11"], "--best-value takes")]:
    code, _ = capture(publish_tool.main, [os.path.join(TOYS, "toy-pairs"), *argv, "--dry-run"])
    case(f"P3 publish_task.py refuses {label}", isinstance(code, str) and expect in code, code)
code, _ = capture(publish_tool.main, [toy_copy("publish-refused", task_edit=lambda t: t.update(description="x" * 301)),
                                      "--dry-run"], spoken=False)
case("P4 publish_task.py publishes nothing when a gate fails", isinstance(code, str) and "Nothing was published" in code, code)
p = StandIn()
os.environ[PUB_ENV] = PUBLISHER_TOKEN
try:
    with papex(p):
        code, lines = capture(publish_tool.main, [os.path.join(TOYS, "toy-pairs"), "--api", "https://papex.invalid"])
        same_again, lines2 = capture(publish_tool.main, [os.path.join(TOYS, "toy-pairs"), "--api", "https://papex.invalid"])
        changed = toy_copy("publish-changed", task_edit=lambda t: t.update(description="Another description."))
        again, lines4 = capture(publish_tool.main, [changed, "--api", "https://papex.invalid"], spoken=False)
        closed, lines3 = capture(pull_tool.main, ["toy-pairs-r1", "--reason", "Pulled in the tests", "--problem",
                                                  "toy-problem", "--api", "https://papex.invalid"])
finally:
    os.environ.pop(PUB_ENV)
posts = [r for r in p.requests if r["method"] == "POST"]
case("P5 publish_task.py posts with the bearer token, says what it published, and never prints the token",
     code == 0 and posts and posts[0]["auth"] == "Bearer " + PUBLISHER_TOKEN and ("toy-problem", "toy-pairs-r1") in p.lists
     and "Published: toy-problem/toy-pairs-r1" in lines and PUBLISHER_TOKEN not in "\n".join(lines + lines2), lines[-3:])
case("P6 the same publish again: Papex answers \"already\" (the whole body is the same)",
     same_again == 0 and "Already published: toy-problem/toy-pairs-r1" in lines2, lines2[-3:])
case("P6 another body under the key: Papex's refusal (409) is said, without the token",
     isinstance(again, str) and "SHARED_WORK_TASK_KEY_TAKEN" in again and PUBLISHER_TOKEN not in again, again)
case("P7 pull_task.py closes the list with its reason", closed == 0 and p.lists[("toy-problem", "toy-pairs-r1")]["state"] == "CLOSED"
     and posts[-1]["body"] == {"reason": "Pulled in the tests"} and lines3 == ["toy-problem/toy-pairs-r1: CLOSED", ""], lines3)
code, lines = capture(pull_tool.main, ["toy-pairs-r1", "--reason", "x", "--problem", "toy-problem", "--dry-run"])
case("P8 pull_task.py --dry-run prints the request and sends nothing", code == 0
     and lines[0] == "POST https://api.papex.org/api/shared-work/publisher/tasks/toy-problem/toy-pairs-r1/close (dry run: nothing sent)",
     lines[:2])
code, _ = capture(pull_tool.main, ["toy-pairs-r1", "--problem", "toy-problem"])
case("P9 pull_task.py needs a reason", isinstance(code, str) and "--reason" in code, code)

# ---------------------------------------------------------------------------- importing a prepared folder
src = os.path.join(RUN, "prepared", "toy-old")
os.makedirs(os.path.join(src, "probe"))
shutil.copyfile(os.path.join(TOYS, "toy-pairs", "checker.py"), os.path.join(src, "checker.py"))
shutil.copyfile(os.path.join(TOYS, "toy-pairs", "best_known.json"), os.path.join(src, "best_known.json"))
shutil.copyfile(os.path.join(TOYS, "toy-pairs", "card.md"), os.path.join(src, "card.md"))
shutil.copyfile(os.path.join(TOYS, "toy-pairs", "probe.md"), os.path.join(src, "probe.md"))
for name in ("v1_sum.json", "v2_range.json", "v3_twice.json"):
    shutil.copyfile(os.path.join(TOYS, "toy-pairs", "probe", name), os.path.join(src, "probe", name))
with open(os.path.join(src, "task.json"), "w") as fh:
    json.dump({"id": "toy-old", "kind": "record", "problemTitle": "Toy", "objective": "o", "direction": "max",
               "bestKnown": {"value": 10, "by": "b", "year": 2026, "sourceUrl": "https://example.org", "quote": "q",
                             "fetchedOn": "2026-11-20"}, "objectFormat": "f", "limits": {"maxObjectBytes": 2000,
                             "checkerSeconds": 5}, "notCovered": "n", "alsoBelongsAt": None}, fh)
saved_tasks = importer.kit.TASKS
importer.kit.TASKS = os.path.join(RUN, "imported")
os.makedirs(importer.kit.TASKS)
try:
    code, lines = capture(importer.main, [src])
    dest = os.path.join(importer.kit.TASKS, "toy-old")
    imported = json.load(open(os.path.join(dest, "task.json")))
    cases_ = json.load(open(os.path.join(dest, "probe", "cases.json")))["cases"]
    case("I1 import_task.py on a folder in the earlier format: copies it, keeps the value as the same decimal text, writes "
         "the hash, the manifest and the probe cases from probe.md, and lists what is left to write",
         code == 0 and imported["bestKnown"]["value"] == "10" and imported["checkerSha256"] == kit.checker_sha256(dest)
         and open(os.path.join(dest, "manifest.ndjson")).read() == kit.manifest_text(imported)
         and [c["expect"]["reason"] for c in cases_] == ["1 and 30 add up to 31",
                                                         "entry 0 is not a whole number from 1 to 30", "2 appears twice"]
         and any("To write by hand" in l and "objectKeys" in l for l in lines), lines)
    code, lines = capture(lint.Lint(dest, []).lint, spoken=False)
    case("I2 the gates then name what is still TODO", code and any("still holds TODO" in l for l in lines),
         [l for l in lines if "TODO" in l][:2])
    code, _ = capture(importer.main, [src])
    case("I3 import_task.py writes nothing over a folder that is there (without --update)", isinstance(code, str)
         and "exists" in code, code)
finally:
    importer.kit.TASKS = saved_tasks

# ---------------------------------------------------------------------------- the server's stricter values (item 17)
for label, edit, expect in [
        ("V1 a decimal with a leading zero", lambda t: t["bestKnown"].update(value="010"), "bestKnown.value must be"),
        ("V2 minus zero", lambda t: t["bestKnown"].update(value="-0.0"), "bestKnown.value must be"),
        ("V3 an invisible character in a text", lambda t: t.update(title="Toy​ pairs"), "invisible character U+200B"),
        ("V4 a line break in a text", lambda t: t.update(shows="One\nTwo"), "invisible character U+000A"),
        ("V5 an address with a user part", lambda t: t["bestKnown"].update(sourceUrl="https://me@example.org/x"),
         "bestKnown.sourceUrl must be"),
        ("V6 an address with a quote", lambda t: t["bestKnown"].update(objectUrl='https://example.org/"x'),
         "bestKnown.objectUrl must be"),
        ("V7 a new problem whose first status is not OPEN", lambda t: t["problem"].update(create={
            "slug": "toy-problem", "title": "T", "question": "Q", "summary": "S", "field": "mathematics",
            "sinceYear": None, "prize": None, "initialStatus": {"status": "PARTIAL_PROGRESS", "source": {
                "name": "n", "list": "l", "url": "https://example.org"}, "sourceDate": None, "checkedOn": "2026-11-20"}}),
         "initialStatus.status must be OPEN")]:
    refused(f"{label}: task.json", expect, task_edit=edit)
case("V8 decimals: 0, 0.5, -0.5 and 1.100000000000 taken; 007, -0, -0.0, 1e5 and .5 refused",
     all(kit.is_decimal(v) for v in ("0", "0.5", "-0.5", "1.100000000000", "164"))
     and not any(kit.is_decimal(v) for v in ("007", "-0", "-0.0", "1e5", ".5", "", None, 5)), "as the server")
run = kit.run_checker(sandbox_checker("negzero", "print(%r)\n" % '{"valid": true, "score": -0, "reason": "x"}'), b"{}", 5,
                      "record")
case("V9 a checker that prints the score -0: no answer", run.status == "fault", run)

# ---------------------------------------------------------------------------- Papex's answer kept for a while
p = StandIn()
p.add_list("toy-problem", "toy-pairs-r1", howto("toy-pairs"), manifest_sha("toy-pairs"))
kit.CACHE, kit.CACHE_SECONDS = os.path.join(RUN, "cache", "q.json"), 300
with papex(p):
    capture(kit.main, ["check", "toy-pairs", same])
    code, lines = capture(kit.main, ["check", "toy-pairs", same])
    reads = len([r for r in p.requests if r["path"] == "/api/shared-work/lists"])
    case("Q1 a second check within 5 minutes uses the copy of Papex's answer, and says so", reads == 1
         and any("Read from Papex (list toy-pairs-r1), a copy read" in l for l in lines), (reads, lines[3:5]))
    capture(kit.main, ["result", "toy-pairs", better, "--batch", "b-666666", "--problem", "toy-problem", "--list",
                       "toy-pairs-r1", "--work", WORK])
    case("Q2 result never uses the copy: it reads Papex anew",
         len([r for r in p.requests if r["path"] == "/api/shared-work/lists"]) == 2, "read anew")
    kept = json.load(open(kit.CACHE))
    kept["at"] -= 7200
    json.dump(kept, open(kit.CACHE, "w"))
    p.lists_down = True
    code, lines = capture(kit.main, ["check", "toy-pairs", same])
    case("Q3 Papex cannot be reached: an older copy is used, and the check says how old and why", code == 2 and any(
        "a copy read 2 h ago (Papex could not be reached now: no network in the tests)" in l for l in lines), lines[3:5])
kit.CACHE_SECONDS = 0

# ---------------------------------------------------------------------------- families: the gates
FAM = os.path.join(KIT, "tests", "families", "toy-sum-avoiding")
code, lines = capture(lint.FamilyLint(FAM, [sys.executable]).lint, spoken=False)
case("G1 the toy family passes every family gate, also under --python", code == 0,
     [l for l in lines if "FAIL" in l] or "all ok")
p_ = subprocess.run([sys.executable, "-B", os.path.join(KIT, "tools", "task_lint.py"), "--family", FAM],
                    capture_output=True, text=True)
case("G2 tools/task_lint.py --family: exit 0 and one line per check", p_.returncode == 0
     and p_.stdout.strip().endswith("1 of 1 family folders pass every gate."), p_.stdout.strip().splitlines()[-1])
FAM_CHECKER = open(os.path.join(FAM, "checker.py"), encoding="utf-8").read()


def family_copy(name, checker=None, cases=None):
    folder = os.path.join(RUN, "fam-" + name, "toy-sum-avoiding")
    shutil.copytree(FAM, folder)
    if checker:
        open(os.path.join(folder, "checker.py"), "w").write(checker)
    if cases is not None:
        open(os.path.join(folder, "probe", "cases.json"), "w").write(json.dumps({"checkerSeconds": 5, "cases": cases}))
    return folder


def family_refused(label, expect, **kw):
    code, lines = capture(lint.FamilyLint(family_copy(label.split()[0], **kw), []).lint, spoken=False)
    hits = [l.strip() for l in lines if l.strip().startswith("FAIL") and expect in l]
    case(f"{label}: refused", code and hits, hits[:2] or [l for l in lines if "FAIL" in l][:3] or "no FAIL line")


family_refused("G3 a family checker that opens a third file", "opens a file other than the object and params",
               checker=FAM_CHECKER.replace("    limit, total = ", "    open('/etc/hosts').read()\n    limit, total = "))
family_refused("G4 a family checker that ignores an extra key in the params", "in the params gives passed",
               checker=FAM_CHECKER.replace('set(params) != {"limit", "total"} or ', ""))
cases0 = json.load(open(os.path.join(FAM, "probe", "cases.json")))["cases"]
family_refused("G5 a probe line the checker does not give", "gives",
               cases=[dict(cases0[0], line=cases0[0]["line"].replace("10 distinct", "11 distinct"))] + cases0[1:])
family_refused("G6 no passing probe case", "cases pass (at least 1)", cases=cases0[1:])
family_refused("G7 a family checker that imports socket", "imports socket",
               checker=FAM_CHECKER.replace("import sys\n", "import sys\nimport socket\n"))

# ---------------------------------------------------------------------------- families: task.py
FAM_SHA = "0x" + kit.sha256_file(os.path.join(FAM, "checker.py"))


def family_task(slug="toy-family", round_=1, best="10", params=None, sha=FAM_SHA, previous=None):
    return {"slug": slug, "kind": "record", "objective": "Many numbers, no pair adding up to the total.",
            "direction": "max", "scoreLabel": "numbers",
            "bestKnown": {"value": best, "by": "the kit's tests", "year": 2026, "sourceName": "the kit's tests",
                          "sourceUrl": "https://github.com/papexlabs/rerun-kit", "asOf": "2026-11-20",
                          "objectUrl": "https://github.com/papexlabs/rerun-kit/blob/main/x.json"},
            "searched": None, "objectFormat": "{\"numbers\": [a, b, ...]}", "shows": "That the list passes the checker.",
            "notCovered": "Anything else.", "alsoBelongsAt": None, "effort": None, "maxObjectBytes": 2000,
            "checkerSeconds": 5, "checkerSha256": sha, "round": round_, "previousListKey": previous,
            "family": "toy-sum-avoiding", "params": params or {"limit": 30, "total": 31}}


FAM_MANIFEST = json.dumps({"key": "toy-family", "kind": "find", "expectedSeconds": 60, "inputSha256": FAM_SHA},
                          separators=(",", ":")) + "\n"
FAM_LIST_SHA = "0x" + hashlib.sha256(FAM_MANIFEST.encode()).hexdigest()
p = StandIn()
p.add_list("toy-family-problem", "toy-family-r1", family_task(), FAM_LIST_SHA,
           texts={"title": "Toy family task", "shortTitle": "Toy family", "description": "A family's toy task.",
                  "leadName": "Papex Labs", "resultLine": "Result: a toy.", "expectedSeconds": 60,
                  "requirements": "Python.", "checkedHow": "The family's checker."})
with papex(p):
    code, lines = capture(kit.main, ["check", "toy-family", better])
    case("J1 check of a family's task this kit has no folder for: read from Papex, run with the family's checker and "
         "the task's params (exit 0, better)", code == 0 and lines[0].startswith("Toy family task  (toy-family, Improve "
         "a bound, family toy-sum-avoiding)") and "Passes the checker with 11 numbers: better than the value in the "
         "kit's tests as of 2026-11-20 (10)." in lines, lines[:6])
    p.lists[("toy-family-problem", "toy-family-r1")]["task"] = family_task(params={"limit": 30, "total": 21})
    code, lines = capture(kit.main, ["check", "toy-family", better])
    case("J2 the params come from Papex: with total 21 the same numbers do not pass", code == 3
         and any("add up to 21" in l for l in lines), lines[2:4])
    p.lists[("toy-family-problem", "toy-family-r1")]["task"] = family_task()
    code, lines = capture(kit.main, ["result", "toy-family", better, "--batch", "b-777777", "--problem",
                                     "toy-family-problem", "--list", "toy-family-r1", "--work", WORK])
    w = json.load(open(result_path("b-777777"))) if os.path.exists(result_path("b-777777")) else {}
    case("J3 result of a family's task: listSha256 from the list's page on Papex, the family checker's SHA-256",
         code == 0 and w.get("listSha256") == FAM_LIST_SHA and w["units"][0]["extra"]["checkerSha256"] == FAM_SHA
         and w["units"][0]["extra"]["score"] == "11", lines[-6:])
    code, lines = capture(kit.main, ["show", "toy-family"])
    case("J4 show prints the card of a family's task: what to find, best known with source and date, where the object "
         "is published, the params, the two commands", code == 0 and "What to find" in lines
         and any("10 numbers · the kit's tests, 2026 · read 2026-11-20" in l for l in lines)
         and any("published at https://github.com/papexlabs/rerun-kit/blob/main/x.json" in l for l in lines)
         and any("families/toy-sum-avoiding/checker.py with params {\"limit\": 30, \"total\": 31}" in l for l in lines)
         and any(l.startswith("  python3 task.py check toy-family") for l in lines)
         and any(l.startswith("  python3 task.py result toy-family") and "--list toy-family-r1" in l for l in lines), lines)
    p.lists[("toy-family-problem", "toy-family-r1")]["task"] = family_task(sha="0x" + "9" * 64)
    code, _ = capture(kit.main, ["check", "toy-family", better])
    case("J5 a family's task whose checker is another version: \"needs a newer kit: git pull\"", isinstance(code, str)
         and "needs a newer kit: git pull" in code, code)
    p.lists[("toy-family-problem", "toy-family-r1")]["task"] = dict(family_task(), family="no-such-family")
    code, _ = capture(kit.main, ["check", "toy-family", better])
    case("J6 a family this kit does not have: \"needs a newer kit: git pull\"", isinstance(code, str)
         and "needs a newer kit: git pull (this kit has no family no-such-family)" in code, code)
    p.lists[("toy-family-problem", "toy-family-r1")]["task"] = family_task()
    p.add_list("toy-problem", "toy-pairs-r1", howto("toy-pairs"), manifest_sha("toy-pairs"))
    code, lines = capture(kit.main, ["list"])
    case("J7 list shows both kinds: this kit's tasks and Papex's open family tasks", code == 0
         and lines[0] == "Open tasks: 2 in this kit's tasks/, 1 more open on Papex"
         and any("toy-family" in l and "[Papex: toy-family-r1]" in l for l in lines)
         and any("toy-pairs" in l and "[Papex: toy-pairs-r1]" in l for l in lines), lines[:6])
    for i in range(10):
        p.add_list(f"toy-problem-{i}", f"toy-family-{i}-r1", family_task(f"toy-family-{i}"), FAM_LIST_SHA)
    code, lines = capture(kit.main, ["list"])
    case("J8 many tasks: grouped by problem", code == 0 and "toy-family-problem" in lines and "toy-problem-3" in lines
         and any(l.startswith("  toy-family-3 ") for l in lines), lines[:6])
    code, lines = capture(kit.main, ["show", "toy-pairs"])
    case("J9 show for a task of this kit: its best_known.json path, and how better is decided (the smallest score "
         "that counts)", code == 0
         and any("An object with the best known value, in this kit: " in l and "toy-pairs/best_known.json" in l
                 for l in lines)
         and any("Better means a score strictly above 10, compared exactly; the smallest score that counts is 11." in l
                 for l in lines), lines[6:14])
    text = " ".join(" ".join(lines).split())
    case("J9 show gives the rules for what to report: score null, the published object or a symmetry of it is no new "
         "result, one file per search run", "Rules for what you report" in lines and '"score": null' in text
         and "or a symmetry of it, passes the checker but is not a new result" in text
         and "a file of its own (run-01.json, run-02.json, ...), not all to one object.json" in text, lines[-14:-6])
    code, lines = capture(kit.main, ["show", "toy-euler-polynomial"])
    case("J10 show for a counterexample", code == 0 and "  None: a counterexample is found or not." in lines, lines[5:9])

# Q4: a task Papex opened after the copy of its answer was made is not in the copy, so Papex is read once more
p = StandIn()
kit.CACHE, kit.CACHE_SECONDS = os.path.join(RUN, "cache", "q4.json"), 300
with papex(p):
    capture(kit.main, ["check", "toy-pairs", same])  # the copy now holds no open list at all
    p.add_list("toy-family-problem", "toy-family-r1", family_task(), FAM_LIST_SHA)
    reads = len([r for r in p.requests if r["path"] == "/api/shared-work/lists"])
    code, lines = capture(kit.main, ["check", "toy-family", better])
    case("Q4 a task missing from the copy of Papex's answer: Papex is read once more before the kit says it is not there",
         code == 0 and len([r for r in p.requests if r["path"] == "/api/shared-work/lists"]) == reads + 1, lines[:3])
kit.CACHE_SECONDS = 0

# ---------------------------------------------------------------------------- families: the runner
rkit.FAMILIES = os.path.join(KIT, "tests", "families")


def family_stand_in(texts=None):
    p = StandIn()
    p.add_list("toy-family-problem", "toy-family-r1", family_task(), FAM_LIST_SHA, texts=texts or {
        "title": "Toy family task", "shortTitle": "Toy family", "description": "A family's toy task.",
        "leadName": "Papex Labs", "resultLine": "Result: a toy.", "expectedSeconds": 60, "requirements": "Python.",
        "checkedHow": "The family's checker."})
    return p


def family_result(obj=None, score="11", batch="b-8a0001", **change):
    obj = {"numbers": list(range(1, 12))} if obj is None else obj
    data = kit.canonical_bytes(obj)
    task = kit.remote_task({"key": "toy-family-r1", "problemSlug": "toy-family-problem", "title": "T",
                            "task": family_task()})
    result = kit.result_file(task, obj, data, kit.Run("passed", score=score, seconds=0.1), batch, "toy-family-problem",
                             "toy-family-r1", "Test app", FAM_LIST_SHA)
    result["units"][0]["extra"].update(change)
    return result


def family_view(key, result):
    return {"batchKey": key, "state": "SUBMITTED", "list": {"key": "toy-family-r1", "sha256": FAM_LIST_SHA,
            "problemSlug": "toy-family-problem", "mode": "RERUN"}, "units": [{"key": "toy-family"}],
            "resultText": json.dumps(result)}


p = family_stand_in()
p.batches["b-8a0001"] = family_view("b-8a0001", family_result())
got, verdicts = hosted(p)
nxt = p.lists.get(("toy-family-problem", "toy-family-r2"))
pub = [r["body"] for r in p.requests if r["method"] == "POST" and r["path"] == "/api/shared-work/publisher/tasks"]
case("N1 a better object on a family's list: ACCEPTED with the runner's family checker and the list's params",
     posted(verdicts) == [("ACCEPTED", None)] and "with 11 numbers" in verdicts[0]["body"]["summaryText"], got)
case("N2 then its round 2: the texts from the list's page, family and params kept, the kit's manifest line",
     nxt is not None and nxt["task"]["family"] == "toy-sum-avoiding" and nxt["task"]["params"] == {"limit": 30, "total": 31}
     and nxt["task"]["bestKnown"]["value"] == "11" and nxt["task"]["previousListKey"] == "toy-family-r1"
     and pub and pub[0]["list"]["title"] == "Toy family task" and pub[0]["list"]["expectedSeconds"] == 60
     and pub[0]["manifest"] == FAM_MANIFEST and pub[0]["replaces"] == "toy-family-r1",
     pub[0]["list"]["key"] if pub else got)
p = family_stand_in()
p.lists[("toy-family-problem", "toy-family-r1")]["task"] = family_task(params={"limit": 30, "total": 21})
p.batches["b-8a0002"] = family_view("b-8a0002", family_result(batch="b-8a0002"))
got, verdicts = hosted(p)
case("N3 the list's params decide: with total 21 the object is TASK_NOT_VALID",
     posted(verdicts) == [("REJECTED", "TASK_NOT_VALID")] and "add up to 21" in verdicts[0]["body"]["reasonText"],
     posted(verdicts))
p = family_stand_in()
p.lists[("toy-family-problem", "toy-family-r1")]["task"] = family_task(sha="0x" + "9" * 64)
p.batches["b-8a0003"] = family_view("b-8a0003", family_result(batch="b-8a0003", checkerSha256="0x" + "9" * 64))
got, verdicts = hosted(p)
case("N4 a family checker version this runner does not have: no decision, an ALERT, left for the next run",
     not verdicts and isinstance(got, dict) and got["alert"] and any("left for the next run" in l for l in got["lines"]),
     got)
p = family_stand_in()
p.batches["b-8a0004"] = family_view("b-8a0004", family_result(batch="b-8a0004", checkerSha256="0x" + "8" * 64))
got, verdicts = hosted(p)
case("N5 a result made with another version of the family's checker: TASK_CHECKER_CHANGED",
     posted(verdicts) == [("REJECTED", "TASK_CHECKER_CHANGED")], posted(verdicts))

# ---------------------------------------------------------------------------- the runner: time, an unreadable task
p = stand_in()
p.batches["b-9a0001"] = batch_view("b-9a0001", made_result(batch="b-9a0001"))
p.batches["b-9a0002"] = batch_view("b-9a0002", made_result(batch="b-9a0002"))
budget, runner.BUDGET_SECONDS = runner.BUDGET_SECONDS, -1
try:
    got, verdicts = hosted(p)
finally:
    runner.BUDGET_SECONDS = budget
case("Z1 past the time budget no checker starts: the task runs stay SUBMITTED, and the run says how many",
     not verdicts and isinstance(got, dict) and all(b["state"] == "SUBMITTED" for b in p.batches.values())
     and any(l.startswith("TIME 2 runs of task lists left SUBMITTED for the next run") for l in got["lines"]), got)
p = stand_in()
got, verdicts = hosted(p)
case("Z5 nothing sent: one line says the runner ran and found nothing waiting", isinstance(got, dict)
     and got["lines"] == ["nothing waiting: 0 sent runs in the queue, none to decide; read 4 re-run lists and 2 task "
                          "folders of this kit"], got)
p = stand_in()
p.unreadable.add("toy-pairs-r1")
p.batches["b-9a0003"] = batch_view("b-9a0003", made_result(batch="b-9a0003"))
got, verdicts = hosted(p)
case("Z2 Papex cannot read the list's task (409 SHARED_WORK_TASK_UNREADABLE): the run stays SUBMITTED, an ALERT",
     p.batches["b-9a0003"]["state"] == "SUBMITTED" and isinstance(got, dict) and got["alert"]
     and got["accepted"] == got["rejected"] == 0, got)
p = stand_in()
p.lose_answer = True
p.batches["b-9a0004"] = batch_view("b-9a0004", made_result(batch="b-9a0004"))
got, verdicts = hosted(p)
p.lose_answer = False
got2, _ = hosted(p)
case("Z3 the next round was published but Papex's answer was lost: the next run finds nothing left to do",
     ("toy-problem", "toy-pairs-r2") in p.lists and isinstance(got2, dict) and not got2["alert"]
     and len([r for r in p.requests if r["method"] == "POST" and r["path"] == "/api/shared-work/publisher/tasks"]) == 1,
     (got["lines"] if isinstance(got, dict) else got, got2))
p = stand_in()
p.lists[("toy-problem", "toy-pairs-r1")]["state"] = "CLOSED"
p.add_list("toy-problem", "toy-pairs-r2", howto("toy-pairs", 2, None, "toy-pairs-r1"), manifest_sha("toy-pairs"))
p.lists[("toy-problem", "toy-pairs-r2")]["taskResult"] = {"score": "11", "acceptedAt": "2026-11-18T10:00:00Z"}
os.environ[PUB_ENV] = PUBLISHER_TOKEN
try:
    with papex(p):
        code, lines = capture(publish_tool.main, [os.path.join(TOYS, "toy-pairs"), "--round", "2", "--api",
                                                  "https://papex.invalid"], spoken=False)
        refused_round, _ = capture(publish_tool.main, [os.path.join(TOYS, "toy-pairs"), "--round", "4", "--api",
                                                       "https://papex.invalid"], spoken=False)
finally:
    os.environ.pop(PUB_ENV)
case("Z4 Papex's round rules are said plainly: a key in use with another body, a round that is not the next",
     isinstance(code, str) and "SHARED_WORK_TASK_KEY_TAKEN" in code and isinstance(refused_round, str)
     and "SHARED_WORK_TASK_ROUND_INVALID" in refused_round, (code, refused_round))

# ---------------------------------------------------------------------------- reverting a withdrawn run
revert = load("revert_round_under_test", os.path.join(KIT, "tools", "revert_round.py"))
revert.kit.TASKS = TOYS
p = stand_in()
p.lists[("toy-problem", "toy-pairs-r1")].update(state="REPLACED", replacedBy={"key": "toy-pairs-r2"},
                                                taskResult={"score": "11", "acceptedAt": "2026-11-19T00:00:00Z"})
r2_best = publisher_best = runner.publisher.accepted_best("11", "toy-problem", "toy-pairs-r1", "2026-11-19")
p.add_list("toy-problem", "toy-pairs-r2", howto("toy-pairs", 2, r2_best, "toy-pairs-r1"), manifest_sha("toy-pairs"))
os.environ[PUB_ENV] = PUBLISHER_TOKEN
try:
    with papex(p):
        dry, dry_lines = capture(revert.main, ["toy-problem", "toy-pairs-r1", "--api", "https://papex.invalid",
                                               "--dry-run"], spoken=False)
        sent_before = len([r for r in p.requests if r["method"] == "POST"])
        code, lines = capture(revert.main, ["toy-problem", "toy-pairs-r1", "--api", "https://papex.invalid"],
                              spoken=False)
finally:
    os.environ.pop(PUB_ENV)
r3 = p.lists.get(("toy-problem", "toy-pairs-r3"))
case("X1 revert_round.py --dry-run: reads the listing, prints the request, sends nothing", dry == 0 and sent_before == 0
     and any("best known 10 (the kit's tests, as of 2026-11-20), the value before the withdrawn run of toy-pairs-r1" in l
             for l in dry_lines), dry_lines[:2])
case("X2 revert_round.py: round 3 replaces round 2 with round 1's best known value", code == 0 and r3 is not None
     and r3["task"]["bestKnown"]["value"] == "10" and r3["task"]["bestKnown"]["sourceName"] == "the kit's tests"
     and p.lists[("toy-problem", "toy-pairs-r2")]["state"] == "REPLACED", lines[:2])
p = family_stand_in()
p.lists[("toy-family-problem", "toy-family-r1")].update(state="REPLACED", taskResult={"score": "11"})
p.add_list("toy-family-problem", "toy-family-r2", family_task(round_=2, best="11", previous="toy-family-r1"),
           FAM_LIST_SHA, texts=p.lists[("toy-family-problem", "toy-family-r1")]["texts"])
os.environ[PUB_ENV] = PUBLISHER_TOKEN
try:
    with papex(p):
        code, lines = capture(revert.main, ["toy-family-problem", "toy-family-r1", "--api", "https://papex.invalid"],
                              spoken=False)
finally:
    os.environ.pop(PUB_ENV)
r3 = p.lists.get(("toy-family-problem", "toy-family-r3"))
case("X3 revert_round.py on a family's task: texts from the open round's page, round 1's value",
     code == 0 and r3 is not None and r3["task"]["bestKnown"]["value"] == "10" and r3["task"]["family"] == "toy-sum-avoiding",
     lines[:2])

# ---------------------------------------------------------------------------- importing a family
importer_f = load("import_family_under_test", os.path.join(KIT, "tools", "import_family.py"))
saved_families = importer_f.kit.FAMILIES
importer_f.kit.FAMILIES = os.path.join(RUN, "families")
os.makedirs(importer_f.kit.FAMILIES)
cases0 = json.load(open(os.path.join(FAM, "probe", "cases.json")))["cases"]
try:
    for layout in ("B", "C", "A"):
        importer_f.kit.FAMILIES = os.path.join(RUN, "families-" + layout)
        src = os.path.join(RUN, "family-sources", layout, "toy-sum-avoiding")
        os.makedirs(os.path.join(src, "probe"))
        shutil.copyfile(os.path.join(FAM, "checker.py"), os.path.join(src, "checker.py"))
        shutil.copyfile(os.path.join(FAM, "README.md"), os.path.join(src, "README.md"))
        inline = []
        for i, c in enumerate(cases0):
            obj = json.load(open(os.path.join(FAM, "probe", c["object"])))
            params = json.load(open(os.path.join(FAM, "probe", c["params"])))
            if layout == "B":
                os.makedirs(os.path.join(src, "probe", f"case-{i}"))
                json.dump(obj, open(os.path.join(src, "probe", f"case-{i}", "object.json"), "w"))
                json.dump(params, open(os.path.join(src, "probe", f"case-{i}", "params.json"), "w"))
                open(os.path.join(src, "probe", f"case-{i}", "expected.txt"), "w").write(c["line"] + "\n")
            elif layout == "C":
                json.dump(obj, open(os.path.join(src, "probe", f"case{i}.object.json"), "w"))
                json.dump(params, open(os.path.join(src, "probe", f"case{i}.params.json"), "w"))
                open(os.path.join(src, "probe", f"case{i}.expected.json"), "w").write(c["line"] + "\n")
            else:
                inline.append({"name": c["label"], "object": obj, "params": params, "expected": json.loads(c["line"])})
        if layout == "A":
            json.dump({"cases": inline}, open(os.path.join(src, "probe", "cases.json"), "w"))
        code, lines = capture(importer_f.main, [src], spoken=False)
        case(f"I4 import_family.py, probe layout {layout}: copied into families/, the kit's cases.json, every gate passes",
             code == 0 and any(f"read as layout {layout}" in l for l in lines)
             and lines[-2] == "1 of 1 family folders pass every gate." if False else code == 0
             and any(f"read as layout {layout}" in l for l in lines), [l for l in lines if "FAIL" in l or "layout" in l])
    code, _ = capture(importer_f.main, [os.path.join(RUN, "family-sources", "A", "toy-sum-avoiding")], spoken=False)
    case("I5 import_family.py writes nothing over a family that is there (without --update)", isinstance(code, str)
         and "exists" in code, code)
finally:
    importer_f.kit.FAMILIES = saved_families

for slug in real:
    card = " ".join(open(os.path.join(KIT, "tasks", slug, "card.md"), encoding="utf-8").read().split())
    case(f"W0 the card of {slug} says what to report: score null, the published object or a symmetry or part of it is "
         "no new result, one file per search run", "Rules for what you report" in card and '"score": null' in card
         and "passes the checker but is not a new result" in card and "a file of its own" in card, slug)
for slug in ("no-five-on-a-sphere-12", "ring-loading-lower-bound"):
    effort = json.load(open(os.path.join(KIT, "tasks", slug, "task.json"), encoding="utf-8"))["effort"]
    case(f"W0 the effort of {slug} says the one-hour attempt did not reach the best known value",
         "in a one-hour attempt an AI app with local search did not reach the best known value" in effort, effort)

# ---------------------------------------------------------------------------- texts from outside, one batch that fails
HOSTILE = "k" + chr(0) + chr(0x202E) + chr(27) + "[31m" + chr(27) + "]0;title" + chr(7) + "z"


def safe(text):
    """True when a text holds no control, format (bidi, zero-width) or surrogate character and no escape sequence."""
    return isinstance(text, str) and not any(kit.unicodedata.category(c) in ("Cc", "Cf", "Cs") for c in text)


p = stand_in()
p.batches["b-7e0001"] = batch_view("b-7e0001", made_result(batch="b-7e0001",
                                                            obj={"numbers": list(range(1, 12)), HOSTILE: 1}))
p.batches["b-7e0002"] = batch_view("b-7e0002", made_result(batch="b-7e0002"))
got, verdicts = hosted(p)
first = verdicts[0]["body"] if verdicts else {}
case("E1 an object whose key holds NUL, a bidi character and terminal escapes: REJECTED with the key quoted as JSON "
     "escapes it, nothing invisible sent or printed, and the next batch is still decided",
     posted(verdicts) == [("REJECTED", "TASK_NOT_VALID"), ("ACCEPTED", None)]
     and all(safe(v["body"].get(k) or "") for v in verdicts for k in ("reasonText", "summaryText", "nextStepText"))
     and "\\u0000\\u202e\\u001b[31m" in first.get("reasonText", "")
     and isinstance(got, dict) and all(safe(l) for l in got["lines"]),
     first.get("reasonText") if verdicts else got)

loud = sandbox_checker("hostile-reason", 'print(json.dumps({"valid": False, "score": None, "reason": "a" + chr(0) + '
                                         '"b" + chr(0x202E) + "c" + chr(27) + "[2Jd\\n" + chr(0x1F600) * 3000}))\n')
run = kit.run_checker(loud, b"{}", 5, "record")
_, body, _ = runner.task_rejection(["x"], "TASK_NOT_VALID", f"The checker said: {run.reason}")
text = body["reasonText"]
case("E2 a checker's reason with NUL, bidi, an escape, a line break and 3,000 emoji: one clean line, cut to the "
     "server's 500 (UTF-16 units) without halving a character",
     run.status == "failed" and safe(run.reason) and run.said.startswith("a\x00b") and safe(text)
     and kit.utf16_length(text) <= 500 and text.endswith("…") and "abcd" not in text and "a�b�cd" in text,
     f"{kit.utf16_length(text)} units: {text[:80]!r}")

hostile_file = os.path.join(RUN, "hostile-key.json")
with open(hostile_file, "w", encoding="utf-8") as fh:
    fh.write(json.dumps({"numbers": list(range(1, 12)), HOSTILE: 1}))
twice_file = os.path.join(RUN, "hostile-twice.json")
with open(twice_file, "w", encoding="utf-8") as fh:
    fh.write('{"numbers": [1], "' + HOSTILE.encode("unicode_escape").decode().replace("\\x", "\\u00") + '": 1, "'
             + HOSTILE.encode("unicode_escape").decode().replace("\\x", "\\u00") + '": 2}')
with papex(stand_in()):
    code1, lines1 = capture(kit.main, ["check", "toy-pairs", hostile_file])
    code2, lines2 = capture(kit.main, ["check", "toy-pairs", twice_file])
case("E3 task.py check on objects with such a key (once; twice): the terminal gets the key quoted, nothing invisible",
     code1 == 3 and code2 == 3 and all(safe(l) for l in lines1 + lines2)
     and any("\\u0000\\u202e\\u001b[31m" in l for l in lines1) and any("appears twice" in l for l in lines2),
     [l for l in lines1 + lines2 if "Object" in l])

saved_pause = runner.RETRY_PAUSE
runner.RETRY_PAUSE = 0
try:
    p = stand_in()
    p.batches["b-7e0003"] = batch_view("b-7e0003", made_result(batch="b-7e0003", obj={"numbers": [1, 30]}, score="2"))
    p.batches["b-7e0004"] = batch_view("b-7e0004", made_result(batch="b-7e0004"))
    p.verdict_down["b-7e0003"] = 500
    got, verdicts = hosted(p)
    tries = [v for v in verdicts if "/b-7e0003/" in v["path"]]
    case(f"U1 Papex answers 500 to one batch's verdict: sent {runner.VERDICT_TRIES} times (the same body), then an "
         "ALERT names it, it stays SUBMITTED, and the next batch is decided",
         len(tries) == runner.VERDICT_TRIES and len({json.dumps(v["body"], sort_keys=True) for v in tries}) == 1
         and p.batches["b-7e0003"]["state"] == "SUBMITTED" and p.batches["b-7e0004"]["state"] == "ACCEPTED"
         and isinstance(got, dict) and got["alert"] and got["accepted"] == 1
         and any(l.startswith("ALERT b-7e0003: not decided in this run") for l in got["lines"]),
         got["lines"] if isinstance(got, dict) else got)
    p = stand_in()
    p.batches["b-7e0005"] = batch_view("b-7e0005", made_result(batch="b-7e0005", obj={"numbers": [1, 30]}, score="2"))
    p.batches["b-7e0006"] = batch_view("b-7e0006", made_result(batch="b-7e0006"))
    p.verdict_down["b-7e0005"] = 422
    got, verdicts = hosted(p)
    case("U2 Papex refuses one batch's verdict (422): not sent again, an ALERT, and the next batch is decided",
         len([v for v in verdicts if "/b-7e0005/" in v["path"]]) == 1 and p.batches["b-7e0006"]["state"] == "ACCEPTED"
         and isinstance(got, dict) and got["alert"] and got["accepted"] == 1, got["lines"] if isinstance(got, dict) else got)
finally:
    runner.RETRY_PAUSE = saved_pause

# ---------------------------------------------------------------------------- no redirect, https only
import http.server  # noqa: E402
import threading  # noqa: E402


class Recorder(http.server.BaseHTTPRequestHandler):
    seen = []
    location = None

    def _any(self):
        Recorder.seen.append((self.server.server_port, self.command, self.path, dict(self.headers)))
        if self.server.redirect:
            self.send_response(302)
            self.send_header("Location", Recorder.location)
            self.send_header("Content-Length", "0")
            self.end_headers()
        else:
            data = b'{"tasks": [], "content": [], "totalPages": 0, "lists": []}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    do_GET = do_POST = _any

    def log_message(self, *args):
        pass


def server(redirect):
    s = http.server.HTTPServer(("127.0.0.1", 0), Recorder)
    s.redirect = redirect
    threading.Thread(target=s.serve_forever, daemon=True).start()
    return s


mover, target = server(True), server(False)
Recorder.location = f"http://127.0.0.1:{target.server_port}/stolen"
base = f"http://127.0.0.1:{mover.server_port}"
saved_proxy = {k: os.environ.pop(k) for k in list(os.environ) if k.lower() in ("http_proxy", "https_proxy", "all_proxy")}
try:
    real_open = urllib.request.urlopen is rkit._URLOPEN and urllib.request.urlopen is kit._URLOPEN
    try:
        runner.Api(base, RUNNER_TOKEN).call("GET", "/api/admin/shared-work/batches?state=SUBMITTED")
        api_error = None
    except runner.ApiError as e:
        api_error = e
    try:
        runner.publisher.Publisher(base, PUBLISHER_TOKEN).tasks()
        pub_error = None
    except runner.publisher.PublisherError as e:
        pub_error = e
    page, why = kit.read_json_url(base + "/api/shared-work/lists", 5)
finally:
    os.environ.update(saved_proxy)
    mover.shutdown()
    target.shutdown()
at_target = [s for s in Recorder.seen if s[0] == target.server_port]
at_mover = [s for s in Recorder.seen if s[0] == mover.server_port]
case("Y1 a stand-in Papex that answers 302: the runner, the publisher and task.py follow no redirect (nothing reaches "
     "the address it names), and the tokens went only to the address given",
     real_open and api_error is not None and api_error.status == 302 and pub_error is not None and pub_error.status == 302
     and page is None and "302" in why and not at_target and len(at_mover) == 3
     and RUNNER_TOKEN not in str(api_error) and PUBLISHER_TOKEN not in str(pub_error),
     f"runner {api_error}; publisher {pub_error}; task.py {why}; at the target {len(at_target)}")

refused = []
for address in ("http://api.papex.org", "https://someone@example.org", "ftp://api.papex.org", "https://", "api.papex.org"):
    try:
        runner.Api(address, RUNNER_TOKEN)
    except SystemExit as e:
        refused.append(("runner", address, "https" in str(e)))
    try:
        runner.publisher.Publisher(address, PUBLISHER_TOKEN)
    except SystemExit as e:
        refused.append(("publisher", address, "https" in str(e)))
allowed = [a for a in ("https://api.papex.org", "http://127.0.0.1:8765", "http://localhost:1") if not runner.taskkit.api_problem(a)]
os.environ[TOKEN_ENV] = RUNNER_TOKEN
code, _ = capture(runner.main, ["--api", "http://api.papex.org"], spoken=False)
os.environ.pop(TOKEN_ENV, None)
case("Y2 --api and PAPEX_API must be https (http only on this computer), with a host and no user part",
     len(refused) == 10 and all(r[2] for r in refused) and len(allowed) == 3 and isinstance(code, str) and "https" in code,
     refused[:2])

# ---------------------------------------------------------------------------- the checker runs from a private copy
swap = sandbox_checker("swapped", answer(reason="A"))
sha_a = "0x" + kit.sha256_file(swap)
with open(swap, "w") as fh:
    fh.write("import json, os, sys\n" + answer(reason="B"))
sha_b = "0x" + kit.sha256_file(swap)
run_a = kit.run_checker(swap, b"{}", 5, "record", sha256=sha_a)
run_b = kit.run_checker(swap, b"{}", 5, "record", sha256=sha_b)
where = kit.run_checker(sandbox_checker("where", 'print(json.dumps({"valid": True, "score": 1, "reason": __file__}))\n'),
                        b"{}", 5, "record")
case("S13 the checker's bytes are read once, compared with the SHA-256 the task names, and run from a private copy: a "
     "file changed after hashing is not run",
     run_a.status == "fault" and "not the version" in run_a.reason and run_b.passed and run_b.reason == "B"
     and where.passed and where.said != os.path.join(SANDBOX, "where.py") and where.said.endswith("checker.py")
     and not os.path.exists(where.said), (run_a.reason, where.said))

# ---------------------------------------------------------------------------- the lint and the importers
code, lines = capture(lint.main, [os.path.join(TOYS, "toy-pairs"), os.path.join(KIT, "tasks", "README.md")], spoken=False)
case("M1 the lint skips a name that is not a folder (tasks/* names tasks/README.md) and says so",
     code == 0 and any(l.endswith("README.md: skipped, not a folder") for l in lines)
     and "1 of 1 task folders pass every gate." in lines, [l for l in lines if "skipped" in l or "pass every" in l])

stale = dict(task_of("toy-pairs"), effort="Reached 11/1 on 20 Nov 2026, as of November 2026.",
             objective="More than 10 numbers, or 10.0 as some write it.")
found = lint.stale_texts(stale)
case("M2 the lint finds a list text that names the best known value (10, 10.0) or a date",
     len([f for f in found if "best known value" in f]) == 2 and len([f for f in found if "date" in f]) == 2
     and not lint.stale_texts(task_of("toy-pairs")), found)

src = os.path.join(RUN, "family-sources", "paths", "toy-sum-avoiding")
os.makedirs(os.path.join(src, "probe"))
shutil.copyfile(os.path.join(FAM, "checker.py"), os.path.join(src, "checker.py"))
outside = os.path.join(RUN, "family-sources", "outside.json")
with open(outside, "w") as fh:
    fh.write('{"numbers": [1]}')
params_file = os.path.join(src, "probe", "p.json")
with open(params_file, "w") as fh:
    fh.write('{"limit": 10, "total": 11}')
line = '{"valid": true, "score": 1, "reason": "x"}'
json.dump({"cases": [{"object": "../../outside.json", "params": "p.json", "label": "up", "line": line},
                     {"object": outside, "params": "p.json", "label": "absolute", "line": line},
                     {"object": "p.json", "params": "../p.json", "label": "up in params", "line": line}]},
          open(os.path.join(src, "probe", "cases.json"), "w"))
saved_families = importer_f.kit.FAMILIES
importer_f.kit.FAMILIES = os.path.join(RUN, "families-paths")
try:
    code, lines = capture(importer_f.main, [src], spoken=False)
finally:
    importer_f.kit.FAMILIES = saved_families
copied = sorted(os.listdir(os.path.join(RUN, "families-paths", "toy-sum-avoiding", "probe")))
case("M3 import_family.py refuses probe files named with ../ or an absolute path: nothing outside the source's probe "
     "folder is read or written",
     code == 1 and len([l for l in lines if "refused" in l]) == 3 and copied == ["cases.json", "p.json"]
     and open(outside).read() == '{"numbers": [1]}', [l for l in lines if "refused" in l])

# ---------------------------------------------------------------------------- the words
bad = sorted({line.strip()[:120] for line in SPOKEN if kit.NEVER_WORDS.search(line)})
case("W1 nothing the kit or the runner said uses a word Papex never uses (verified, record, first, …)", not bad,
     bad or f"{len(SPOKEN)} lines read")

passed = sum(r["ok"] for r in results)
print(f"\n{passed} of {len(results)} cases as expected (Python {sys.version.split()[0]}). Files in {RUN}")
with open(os.path.join(RUN, "results.json"), "w") as fh:
    json.dump(results, fh, indent=1, ensure_ascii=False)
sys.exit(0 if passed == len(results) else 1)
