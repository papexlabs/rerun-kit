#!/usr/bin/env python3
"""Cases for what the kit refuses before it builds anything, and for the batch file the kit writes itself
(--batch). Nothing here builds or runs Lean, and nothing is sent: where a case runs the kit to its end,
the fetch and the build are stand-ins and Papex is a stand-in too.

  python3 tests/test_release.py OUT_DIR [--corpus DIR] [--py39 PYTHON] [--real]

OUT_DIR    receives the small test projects (a new folder per run; nothing is deleted).
--corpus   compares the kit's TOML reader with Python's tomllib (Python 3.11 or later) on every file in DIR;
           with --py39 PYTHON the kit's reader is also run under that older Python on the same files.
--real     reads the files of this kit's own lists through `gh api` (read-only, text only) into OUT_DIR,
           checks every file against the list's SHA-256 and runs the kit's search on them. Needs `gh`.
"""

import base64
import contextlib
import hashlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import time

sys.dont_write_bytecode = True
KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec_ = importlib.util.spec_from_file_location("rerun", os.path.join(KIT, "rerun.py"))
rerun = importlib.util.module_from_spec(spec_)
spec_.loader.exec_module(rerun)

args = sys.argv[1:]
OUT = os.path.abspath(args[0])
CORPUS = args[args.index("--corpus") + 1] if "--corpus" in args else None
PY39 = args[args.index("--py39") + 1] if "--py39" in args else None
REAL = "--real" in args
RUN = os.path.join(OUT, "release-tests-" + time.strftime("%Y%m%dT%H%M%S") + f"-py{sys.version_info[0]}{sys.version_info[1]}")
os.makedirs(RUN)
results = []


def case(name, ok, detail):
    results.append({"case": name, "ok": bool(ok), "detail": detail})
    print(f"{'PASS' if ok else 'FAIL'}  {name}: {detail}"[:400])


print(f"Python {sys.version.split()[0]}; kit {KIT}; rerun.py sha256 {rerun.sha256_file(os.path.join(KIT, 'rerun.py'))}")

# ---------------------------------------------------------------------------- the TOML reader
try:
    import tomllib
except ImportError:
    tomllib = None


def mine(text):
    try:
        return rerun._Toml(text).read()
    except rerun.TomlError as e:
        return {"<refused>": str(e)}


SAME = [  # files both readers must read the same way
    ("strings with # and escapes", 'name = "a # not a comment"\nx = "q\\"uote \\\\ \\u00e9 \\t"\ny = \'lit # \\n\'\n'),
    ("dotted keys and sub-tables of array tables",
     'name = "x"\n[leanOptions]\npp.unicode.fun = true\npp.proofs = false\nautoImplicit = false\n'
     '[[lean_lib]]\nname = "A"\n[lean_lib.leanOptions]\nwarningAsError = true\n[[lean_lib]]\nname = "B"\n'),
    ("inline tables and multi-line arrays with comments",
     'leanOptions = { pp.unicode.fun = true, autoImplicit = false }\n'
     'defaultTargets = [\n  "A", # first\n  "B",\n]\n# end\n'),
    ("quoted keys, integers, header after its sub-table",
     '"name" = "x"\nmaxHeartbeats = 400000\n[a.b]\nc = -1\n[a]\nd = +0\n'),
    ("CRLF line ends", 'name = "x"\r\n[[require]]\r\nname = "mathlib"\r\n'),
]
REFUSED = [  # files the kit's reader refuses (Python's may refuse them too, or read them)
    ("multi-line string", 'name = """x"""\n'),
    ("a number with a point", "x = 1.5\n"),
    ("a date", "x = 2026-11-19\n"),
    ("a key defined twice", 'name = "a"\nname = "b"\n'),
    ("a table defined twice", "[a]\n[a]\n"),
    ("a table header over a dotted key", "a.b = 1\n[a]\n"),
    ("a trailing comma in an inline table", "x = { a = 1, }\n"),
    ("an inline table over two lines", "x = { a = 1,\n b = 2 }\n"),
    ("an escape TOML 1.0 does not have", 'x = "\\e"\n'),
    ("a string that does not end", 'x = "abc\n'),
    ("text after a value", 'x = "a" y = 1\n'),
    ("a hexadecimal number", "x = 0x10\n"),
]
for label, text in SAME:
    got = mine(text)
    want = tomllib.loads(text) if tomllib else None
    case(f"T same reading: {label}", "<refused>" not in got and (want is None or got == want),
         f"kit={got}" + ("" if want is None else f" tomllib={want}"))
for label, text in REFUSED:
    got = mine(text)
    case(f"T refused: {label}", "<refused>" in got, got.get("<refused>", got))

if CORPUS and tomllib:
    names = sorted(os.listdir(CORPUS))
    texts = {n: open(os.path.join(CORPUS, n), encoding="utf-8").read() for n in names}
    older = {}
    if PY39:
        code = ("import json,sys,importlib.util;s=importlib.util.spec_from_file_location('r',sys.argv[1]);"
                "r=importlib.util.module_from_spec(s);s.loader.exec_module(r);d=json.load(open(sys.argv[2]));"
                "out={}\nfor n,t in d.items():\n  try: out[n]=r._Toml(t).read()\n  except r.TomlError as e: out[n]={'<refused>':str(e)}\n"
                "print(json.dumps({'python':sys.version.split()[0],'tomllib':__import__('importlib').util.find_spec('tomllib') is not None,'out':out}))")
        blob = os.path.join(RUN, "corpus.json")
        with open(blob, "w") as fh:
            json.dump(texts, fh)
        p = subprocess.run([PY39, "-I", "-B", "-c", code, os.path.join(KIT, "rerun.py"), blob], capture_output=True, text=True)
        older = json.loads(p.stdout) if p.returncode == 0 else {"error": p.stderr[-500:]}
    agree, refused = 0, []
    for n in names:
        want = tomllib.loads(texts[n])
        got = mine(texts[n])
        if got == want and (not older or older.get("out", {}).get(n) == want):
            agree += 1
        else:
            refused.append(n)
    case(f"T corpus: the kit's reader and tomllib on {len(names)} real lakefile.toml files"
         + (f", and the kit's reader under Python {older.get('python')} (tomllib there: {older.get('tomllib')})" if older else ""),
         agree == len(names), f"{agree} of {len(names)} read the same; differing: {refused}")

# ---------------------------------------------------------------------------- small projects
TOOLCHAIN = "leanprover/lean4:v4.33.0"
LAKEFILE = '''name = "Demo"
version = "0.1.0"
defaultTargets = ["Demo", "Solution"]

[leanOptions]
autoImplicit = false

[[require]]
name = "mathlib"
git = "https://github.com/leanprover-community/mathlib4.git"
rev = "v4.33.0"

[[lean_lib]]
name = "Demo"

[[lean_lib]]
name = "Solution"
roots = ["Solution"]
'''
H = "0123456789abcdef0123456789abcdef01234567"


def manifest(**change):
    m = {"version": "1.2.0", "packagesDir": ".lake/packages", "name": "Demo", "lakeDir": ".lake", "fixedToolchain": False,
         "packages": [
             {"name": "mathlib", "type": "git", "url": "https://github.com/leanprover-community/mathlib4.git", "rev": H,
              "scope": "", "inherited": False, "inputRev": "v4.33.0", "configFile": "lakefile.lean",
              "manifestFile": "lake-manifest.json"},
             {"name": "batteries", "type": "git", "url": "https://github.com/leanprover-community/batteries", "rev": H,
              "scope": "leanprover-community", "inherited": True, "inputRev": "main", "configFile": "lakefile.toml",
              "manifestFile": "lake-manifest.json"},
             {"name": "Cli", "type": "git", "url": "https://github.com/leanprover/lean4-cli", "rev": H,
              "scope": "leanprover", "inherited": True, "inputRev": "v4.33.0", "configFile": "lakefile.toml",
              "manifestFile": "lake-manifest.json"}]}
    for key, value in change.items():
        if key.startswith("pkg_"):
            m["packages"][0][key[4:]] = value
        else:
            m[key] = value
    return json.dumps(m, indent=1)


FILES = {
    "Demo.lean": "import Demo.A\n",
    "Demo/A.lean": "import Mathlib.Tactic\n\ntheorem Demo.a : 1 + 1 = 2 := by norm_num\n",
    "Solution.lean": "/-! The proof. -/\nimport Demo\n\ntheorem main : 2 = 1 + 1 := Demo.a.symm\n",
}


def project(name, files=None, lakefile=LAKEFILE, man=None, toolchain=TOOLCHAIN + "\n", drop=()):
    src = os.path.join(RUN, name)
    tree = dict(FILES if files is None else files)
    for path, text in (("lakefile.toml", lakefile), ("lake-manifest.json", man or manifest()), ("lean-toolchain", toolchain)):
        if path not in drop:
            tree.setdefault(path, text)
    digests = {}
    for path, text in tree.items():
        full = os.path.join(src, path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as fh:
            fh.write(text)
        digests[path] = hashlib.sha256(text.encode()).hexdigest()
    return src, {"projectDir": "", "toolchain": TOOLCHAIN, "files": digests}


def check(name, expect, **kw):
    """expect: None (nothing found) or a piece of text one finding must contain."""
    src, spec = project(name, **kw)
    found = rerun.scan_source(src, spec)
    ok = (found == []) if expect is None else any(expect in f for f in found)
    case(name, ok, found if found else "nothing found")


def lib_with(line):
    return LAKEFILE.replace('[[lean_lib]]\nname = "Demo"\n', '[[lean_lib]]\nname = "Demo"\n' + line + "\n")


check("A1 a clean project", None)
check("A2 known Lean options (pp.unicode.fun, relaxedAutoImplicit, weak.linter.*, maxSynthPendingDepth)", None,
      lakefile=LAKEFILE.replace("autoImplicit = false\n", "pp.unicode.fun = true\nrelaxedAutoImplicit = false\n"
                                "weak.linter.mathlibStandardSet = true\nmaxSynthPendingDepth = 3\n"))
check("A3 a library's own leanOptions (warningAsError)", None,
      lakefile=LAKEFILE + '\n[lean_lib.leanOptions]\nwarningAsError = true\n')
check("A4 Mathlib named by scope only (no git address)", None,
      lakefile=LAKEFILE.replace('git = "https://github.com/leanprover-community/mathlib4.git"\n', 'scope = "leanprover-community"\n'))
check("A5 globs and a lean_exe", None,
      lakefile=lib_with('globs = ["Demo.+"]') + '\n[[lean_exe]]\nname = "x"\nroot = "Demo"\n')
check("O1 as before: #eval", "#eval", files=dict(FILES, **{"Demo/A.lean": FILES["Demo/A.lean"] + "#eval 1\n"}))
check("O2 as before: lakefile.lean", "a build file written as a program", files=dict(FILES, **{"lakefile.lean": "import Lake\n"}))
check("O3 as before: an import of a library other than Mathlib", "imports Batteries",
      files=dict(FILES, **{"Demo/A.lean": "import Batteries.Data.List\n"}))
for key, line in [("moreLeanArgs", 'moreLeanArgs = ["--load-dynlib=x.so"]'), ("weakLeanArgs", 'weakLeanArgs = ["--plugin=x.so"]'),
                  ("moreLinkArgs", 'moreLinkArgs = ["-lx"]'), ("precompileModules", "precompileModules = true"),
                  ("plugins", 'plugins = ["x"]'), ("dynlibs", 'dynlibs = ["x"]'), ("extraDepTargets", 'extraDepTargets = ["x"]')]:
    check(f"R1 lean_lib sets {key}", f"{key} is not a key the kit knows", lakefile=lib_with(line))
check("R2 package sets moreLeanArgs", "moreLeanArgs is not a key", lakefile='moreLeanArgs = ["--plugin=x.so"]\n' + LAKEFILE)
check("R3 the option debug.skipKernelTC (package)", "debug.skipKernelTC",
      lakefile=LAKEFILE.replace("autoImplicit = false\n", "debug.skipKernelTC = true\n"))
check("R3 the option debug.skipKernelTC (library, inline table)", "debug.skipKernelTC",
      lakefile=lib_with("leanOptions = { debug.skipKernelTC = true }"))
check("R3 an option set through weak. (weak.debug.skipKernelTC)", "weak.debug.skipKernelTC",
      lakefile=LAKEFILE.replace("autoImplicit = false\n", "weak.debug.skipKernelTC = true\n"))
check("R4 buildDir moved", "buildDir is not a key", lakefile='buildDir = "out"\n' + LAKEFILE)
check("R4 packagesDir moved in lakefile.toml", "packagesDir is not a key", lakefile='packagesDir = "pk"\n' + LAKEFILE)
check("R4 packagesDir moved in lake-manifest.json", "moves Lake's folders", man=manifest(packagesDir="pk"))
check("R4 lakeDir moved in lake-manifest.json", "moves Lake's folders", man=manifest(lakeDir="lk"))
check("R5 an unknown key", "unknownThing is not a key", lakefile="unknownThing = 1\n" + LAKEFILE)
check("R5 a srcDir outside the project", "srcDir leaves the project", lakefile=lib_with('srcDir = "../elsewhere"'))
check("R6 a second requirement (Comparator)", "the only requirement allowed is Mathlib",
      lakefile=LAKEFILE + '\n[[require]]\nname = "Comparator"\ngit = "https://github.com/leanprover/comparator.git"\nrev = "v4.33.0"\n')
check("R6 a requirement from a folder of the repository", "the only requirement allowed is Mathlib",
      lakefile=LAKEFILE + '\n[[require]]\nname = "vend"\npath = "vendor/vend"\n')
check("R6 Mathlib from a fork (lakefile.toml)", "Mathlib must come from leanprover-community",
      lakefile=LAKEFILE.replace("leanprover-community/mathlib4", "someone/mathlib4"))
check("R6 Mathlib from another scope", "Mathlib must come from leanprover-community",
      lakefile=LAKEFILE.replace('git = "https://github.com/leanprover-community/mathlib4.git"\n', 'scope = "someone"\n'))
check("R6 Mathlib requirement with a path", "path is not a key", lakefile=LAKEFILE.replace('rev = "v4.33.0"\n', 'rev = "v4.33.0"\npath = "m"\n'))
check("R7 Mathlib from a fork (lake-manifest.json)", "not from leanprover-community or leanprover",
      man=manifest(pkg_url="https://github.com/someone/mathlib4.git"))
check("R7 a dependency from elsewhere (lake-manifest.json)", "not from leanprover-community or leanprover",
      man=manifest(pkg_url="https://gitlab.com/leanprover-community/mathlib4.git"))
check("R7 a path package (lake-manifest.json)", "not a git repository", man=manifest(pkg_type="path", pkg_dir="./vendor"))
check("R7 a package not fixed at a commit", "not fixed at a commit", man=manifest(pkg_rev="main"))
check("R7 an unknown key in lake-manifest.json", "is not a key the kit knows", man=manifest(scripts="x"))
check("R7 no lake-manifest.json", "the project has none", drop=("lake-manifest.json",))
check("R8 a tracked file in .lake", "Lake's own folder .lake", files=dict(FILES, **{".lake/build/lib/lean/Demo.olean": "x"}))
check("R9 lean-toolchain names another version", "names another Lean version", toolchain="leanprover/lean4:v4.34.0\n")
check("R9 no lean-toolchain", "lean-toolchain: the project has none", drop=("lean-toolchain",))
check("R10 no lakefile.toml", "the project has no lakefile.toml", drop=("lakefile.toml",))
check("R10 a lakefile.toml the kit cannot read", "the kit cannot read it", lakefile='name = """Demo"""\n')
check("R11 an import written with « »", "an import the kit cannot read",
      files=dict(FILES, **{"Solution.lean": "import Demo.«A»\n"}))
check("R11 two imports on one line", "an import the kit cannot read",
      files=dict(FILES, **{"Solution.lean": "import Demo import Batteries\n"}))
check("R11 an import over two lines", "an import the kit cannot read",
      files=dict(FILES, **{"Solution.lean": "import\n  Batteries.Data.List\n"}))
check("R11 an import with a trailing dot", "an import the kit cannot read",
      files=dict(FILES, **{"Solution.lean": "import Mathlib.\n"}))

check("R12 '--' inside a string does not hide the rest of the line", "#eval",
      files=dict(FILES, **{"Demo/A.lean": FILES["Demo/A.lean"] + 'def s := "--" ++ toString (1 : Nat) #eval 1\n'}))
check("R12 '--' inside a raw string does not hide the rest of the line", "#eval",
      files=dict(FILES, **{"Demo/A.lean": FILES["Demo/A.lean"] + 'def s := r#"a"b -- "# #eval 1\n'}))
check("R12 '/-' inside a string does not hide the lines after it", "run_cmd",
      files=dict(FILES, **{"Demo/A.lean": FILES["Demo/A.lean"] + 'def s := "/-"\nrun_cmd pure ()\ndef t := "-/"\n'}))
check("A6 a character literal and primes make no false finding", None,
      files=dict(FILES, **{"Demo/A.lean": FILES["Demo/A.lean"] + "def c : Char := '\"' -- a quote\ntheorem h' : 1 = 1 := rfl\n"}))

# make_spec.py: it writes nothing for a unit the kit would stop, and the same bytes as before otherwise.
# Its git calls are replaced by a stand-in that copies a local test project; nothing is fetched.
def make_spec_with(project_src, seed, out, tool):
    s = importlib.util.spec_from_file_location("make_spec_under_test", tool)
    tool_mod = importlib.util.module_from_spec(s)
    s.loader.exec_module(tool_mod)

    def fake_git(folder, *a):
        if a[0] == "checkout":
            import shutil
            for base, _, names in os.walk(project_src):
                for n in names:
                    rel = os.path.relpath(os.path.join(base, n), project_src)
                    os.makedirs(os.path.dirname(os.path.join(folder, rel)), exist_ok=True)
                    shutil.copyfile(os.path.join(base, n), os.path.join(folder, rel))
        if a[0] == "rev-parse":
            return seed["commit"] + "\n"
        if a[0] == "ls-files":
            names = []
            for base, _, ns in os.walk(project_src):
                names += [os.path.relpath(os.path.join(base, n), project_src).replace(os.sep, "/") for n in ns]
            return "\n".join(sorted(names)) + "\n"
        return ""

    tool_mod.git = fake_git
    seed_path = out + ".seed.json"
    with open(seed_path, "w") as fh:
        json.dump(seed, fh)
    argv, sys.argv = sys.argv, ["make_spec.py", seed_path, out]
    try:
        tool_mod.main()
        return None
    except SystemExit as e:
        return str(e)
    finally:
        sys.argv = argv


SEED = {"schema": "papex-rerun-spec/v1", "system": "lean4", "title": "test", "repo": "https://github.com/x/y.git",
        "commit": "0" * 40, "projectDir": "", "toolchain": TOOLCHAIN,
        "theorems": [{"name": "main", "module": "Solution"}], "permittedAxioms": ["propext"],
        "outputs": [".lake/build/lib/lean/Solution.olean"], "diskGb": 12, "expectedSeconds": 300}
src, _ = project("M-clean")
out = os.path.join(RUN, "M-clean.spec.json")
why = make_spec_with(src, SEED, out, os.path.join(KIT, "tools", "make_spec.py"))
case("M1 make_spec.py writes a clean unit's file", why is None and os.path.exists(out), why or "written")
src, _ = project("M-refused", lakefile=lib_with('moreLeanArgs = ["--plugin=x.so"]'))
out = os.path.join(RUN, "M-refused.spec.json")
why = make_spec_with(src, SEED, out, os.path.join(KIT, "tools", "make_spec.py"))
case("M2 make_spec.py writes nothing for a unit the kit would stop", why and not os.path.exists(out), why)
OLD_TOOL = os.environ.get("PAPEX_OLD_MAKE_SPEC")  # the make_spec.py of the previous kit, to compare bytes
if OLD_TOOL:
    src, _ = project("M-compare")
    a, b = os.path.join(RUN, "M-new.spec.json"), os.path.join(RUN, "M-old.spec.json")
    make_spec_with(src, SEED, a, os.path.join(KIT, "tools", "make_spec.py"))
    make_spec_with(src, SEED, b, OLD_TOOL)
    case("M3 make_spec.py writes the same bytes as the previous kit's", open(a, "rb").read() == open(b, "rb").read(),
         hashlib.sha256(open(a, "rb").read()).hexdigest()[:16])

# ---------------------------------------------------------------------------- --batch: the batch file the kit writes
# A run an AI app took through the Papex connection comes with a batch key, the problem and the list, and no
# batch file. The kit writes that file itself from its own list files, for a list of one unit.
ERDOS, ERDOS_LIST = "erdos-problem-824", "lean-rerun-v1"
ERDOS_LIST_SHA256 = "0x1f837a1b5edcd6bd99a26e74cde4bf9b2d2c0aac8a61070a094a7b2cae8e28f2"  # the value Papex froze
BATCH_KEY = "b-0a1b2c"
# The keys of a batch file downloaded from a run's page, in their order.
DOWNLOADED_KEYS = ["schema", "problem", "list", "listSha256", "batch", "kind", "resultSchema", "units",
                   "reservedUntil", "closesAt"]


def stops(work, *args):
    """What the kit says when it stops (None: it did not stop)."""
    try:
        work(*args)
    except SystemExit as e:
        return str(e.code)
    return None


def batch_files(work_root):
    found = []
    for base, _, names in os.walk(os.path.join(work_root, "batches")):
        found += [os.path.join(base, n) for n in names]
    return found


w = os.path.join(RUN, "batch-erdos")
written = rerun.write_batch(w, BATCH_KEY, ERDOS, ERDOS_LIST)
raw = open(written, "rb").read().decode()
want = ('{"schema":"papex-shared-work-batch/v1","problem":"erdos-problem-824","list":"lean-rerun-v1",'
        f'"listSha256":"{ERDOS_LIST_SHA256}","batch":"{BATCH_KEY}","kind":"run",'
        '"resultSchema":"papex-shared-work-result/v1","units":[{"key":"erdos-824-lean","keepProof":false}]}')
case("B1 --batch writes the batch file of erdos-problem-824/lean-rerun-v1 where --key keeps Papex's",
     written == os.path.join(w, "batches", BATCH_KEY, BATCH_KEY + ".json") and raw == want,
     f"{os.path.relpath(written, RUN)}: {raw}")
for problem in sorted(os.listdir(rerun.LISTS)):
    for mname in sorted(n for n in os.listdir(os.path.join(rerun.LISTS, problem)) if n.endswith(".manifest.ndjson")):
        list_key = mname[:-len(".manifest.ndjson")]
        mpath = os.path.join(rerun.LISTS, problem, mname)
        lines = [json.loads(line) for line in open(mpath) if line.strip()]
        w = os.path.join(RUN, f"batch-{problem}-{list_key}")
        why = stops(rerun.write_batch, w, BATCH_KEY, problem, list_key)
        got = json.load(open(batch_files(w)[0])) if not why and batch_files(w) else {}
        why = why or stops(rerun.find_spec, got, lines[0]["key"])  # the kit's own reading of a batch file
        case(f"B2 {problem}/{list_key}: written from the list's file, and the kit's reading of a batch file takes it",
             not why and len(lines) == 1 and got.get("listSha256") == "0x" + hashlib.sha256(open(mpath, "rb").read()).hexdigest()
             and got.get("kind") == lines[0]["kind"] and got.get("units") == [{"key": lines[0]["key"], "keepProof": False}],
             why or f"listSha256 {got.get('listSha256')}, unit {got.get('units')}")
read = [k for k in DOWNLOADED_KEYS[-2:] for f in ("rerun.py", "show.py", os.path.join("runner", "runner.py"))
        if k in open(os.path.join(KIT, f), encoding="utf-8").read()]
case("B3 the written file has a downloaded one's keys but reservedUntil and closesAt, which the kit and the runner never read",
     list(json.loads(want)) == DOWNLOADED_KEYS[:-2] and not read, f"keys {list(json.loads(want))}; read: {read or 'nowhere'}")

made = os.path.join(RUN, "made-up-lists")  # small lists made up for the cases that stop
UNIT_LINE = '{"key":"%s","kind":"run","expectedSeconds":300,"inputSha256":"0x%s"}\n'
for list_key, text in [("shared-v1", UNIT_LINE % ("u-1", "0" * 64) + UNIT_LINE % ("u-2", "1" * 64)), ("empty-v1", "\n"),
                       ("broken-v1", '{"key":"u-1",\n'), ("no-kind-v1", '{"key":"u-1","expectedSeconds":300}\n')]:
    os.makedirs(os.path.join(made, "demo-problem"), exist_ok=True)
    with open(os.path.join(made, "demo-problem", list_key + ".manifest.ndjson"), "w") as fh:
        fh.write(text)
real_lists, rerun.LISTS = rerun.LISTS, made
try:
    for label, args, expect in [
            ("B4 a list of more than one unit", (BATCH_KEY, "demo-problem", "shared-v1"),
             "Use the command with the key from the batch's page on papex.org, or the batch file from that page."),
            ("B4 a list of no unit", (BATCH_KEY, "demo-problem", "empty-v1"), "has 0 units"),
            ("B5 a list this kit does not have", (BATCH_KEY, "demo-problem", "lean-rerun-v9"),
             "This kit has no list demo-problem/lean-rerun-v9. Get the newest kit (git pull)"),
            ("B6 a list file the kit cannot read", (BATCH_KEY, "demo-problem", "broken-v1"), "could not be read"),
            ("B6 a unit without a kind", (BATCH_KEY, "demo-problem", "no-kind-v1"), "names a unit this kit cannot read"),
            ("B7 not a batch key", ("b-XYZ123", "demo-problem", "shared-v1"), "That is not a batch key"),
            ("B7 a batch key too long", ("b-0123456789a", "demo-problem", "shared-v1"), "That is not a batch key"),
            ("B7 not a problem's slug", (BATCH_KEY, "Demo_Problem", "shared-v1"), "--problem and --list take"),
            ("B7 a list key that leaves lists/", (BATCH_KEY, "demo-problem", "../shared-v1"), "--problem and --list take")]:
        w = os.path.join(RUN, "batch-refused")
        why = stops(rerun.write_batch, w, *args)
        case(f"{label}: stops and writes nothing", why and expect in why and not batch_files(w), why)
finally:
    rerun.LISTS = real_lists

w = os.path.join(RUN, "batch-usage")
USAGE = "--batch goes with --problem and --list, and without --key or a BATCH_FILE"
for label, argv in [("U1 --batch with --key", ["--batch", BATCH_KEY, "--problem", ERDOS, "--list", ERDOS_LIST, "--key", "swk_" + "A" * 43]),
                    ("U1 --batch with a BATCH_FILE", ["--batch", BATCH_KEY, "--problem", ERDOS, "--list", ERDOS_LIST, written]),
                    ("U2 --batch without --list", ["--batch", BATCH_KEY, "--problem", ERDOS]),
                    ("U2 --batch without --problem", ["--batch", BATCH_KEY, "--list", ERDOS_LIST]),
                    ("U3 --problem and --list without --batch", ["--problem", ERDOS, "--list", ERDOS_LIST])]:
    why = stops(rerun.main, argv + ["--plain", "--work", w])
    case(f"{label}: one usage line, nothing written", why and why.startswith(USAGE) and "\n" not in why and not batch_files(w), why)
why = stops(rerun.main, ["--docker", "--plain", "--work", w])
case("U4 no --key, no BATCH_FILE, no --batch: the usage line names the three", why and "--key KIT_KEY" in why
     and "BATCH_FILE" in why and "--batch BATCH_KEY --problem SLUG --list LIST_KEY" in why and "\n" not in why, why)


# The kit run to its end with stand-ins for the fetch and the build (nothing is built). Papex cannot be reached:
# the kit's only ways out are urlopen (downloads) and Kit (the kit routes), and both are replaced.
def run_kit(argv, kit_class=None):
    calls = []
    saved = {name: getattr(rerun, name) for name in ("fetch", "build", "free_gb", "Kit")}
    saved_open = rerun.urllib.request.urlopen

    def no_network(*a, **k):
        calls.append("urlopen")
        raise OSError("no network in the tests")

    class NoKit:
        def __init__(self, *a):
            calls.append("Kit")
            raise SystemExit("the kit tried to reach Papex")

    rerun.fetch = lambda spec, work: 1.0
    rerun.build = lambda spec, work: {"lean": "Lean (version 4.0.0, a stand-in)", "buildExit": 0, "buildSeconds": 2.0,
                                      "checkSeconds": 1.0, "axioms": {"main": ["propext"]}, "problems": [],
                                      "outputSha256": "0x" + "ab" * 32, "outputBytes": 10, "outcome": "PASS"}
    rerun.free_gb = lambda path: 999.0
    rerun.Kit = kit_class or NoKit
    rerun.urllib.request.urlopen = no_network
    out = io.StringIO()
    try:
        with contextlib.redirect_stdout(out):
            code = rerun.main(argv)
    except SystemExit as e:
        code = e.code
    finally:
        for name, value in saved.items():
            setattr(rerun, name, value)
        rerun.urllib.request.urlopen = saved_open
    return code, out.getvalue().split("\n"), calls


def closing(work_root, *advice):
    result = os.path.join(work_root, "batches", BATCH_KEY, BATCH_KEY + ".result.json")
    return ["", f"Result file: {result}", *advice,
            f"The work folder holds Lean and Mathlib ({work_root}). Delete it with: python3 rerun.py --clean", ""]


w1 = os.path.join(RUN, "run-batch")
code1, lines1, calls1 = run_kit(["--batch", BATCH_KEY, "--problem", ERDOS, "--list", ERDOS_LIST, "--plain", "--work", w1,
                                 "--agent-host", "Test app"])
end1 = closing(w1, "  The AI app that took the run gives the result file, exactly as it is, to the Papex connection",
               f"  (papex_prepare_shared_work_batch, batch {BATCH_KEY}), or you upload it on your run's page.",
               "  Only you send it: on that page on papex.org, choose how you are shown, and press Send.")
try:
    result1 = json.load(open(os.path.join(w1, "batches", BATCH_KEY, BATCH_KEY + ".result.json")))
except (OSError, ValueError):
    result1 = {}
case("E1 --batch runs to its end, sends nothing, and its last lines say what to do next on this path",
     code1 == 0 and lines1[-len(end1):] == end1 and not calls1 and result1.get("batch") == BATCH_KEY
     and result1.get("listSha256") == ERDOS_LIST_SHA256 and result1.get("env", {}).get("agentHost") == "Test app",
     f"exit {code1}; calls to Papex: {calls1 or 'none'}; last lines: {lines1[-len(end1):-1]}")

w2 = os.path.join(RUN, "run-batch-file")
code2, lines2, calls2 = run_kit([os.path.join(w1, "batches", BATCH_KEY, BATCH_KEY + ".json"), "--plain", "--work", w2])
end2 = closing(w2, "  Upload it on your run's page on papex.org, choose how you are shown, and send it.")
case("E2 BATCH_FILE (the file --batch wrote): the same run, and its last lines as in the published kit",
     code2 == 0 and lines2[-len(end2):] == end2 and not calls2 and lines1[:-len(end1)] == lines2[:-len(end2)],
     f"exit {code2}; calls to Papex: {calls2 or 'none'}; last lines: {lines2[-len(end2):-1]}")


class StandInPapex(rerun.Kit):
    """Papex as the kit routes answer; nothing leaves this computer."""

    def request(self, method, route, body=None, timeout=30.0):
        if route == "/batch":
            return want.encode()
        if route == "/result":
            return b'{"pagePath":"/runs/b-0a1b2c"}'
        return b"{}"


w3 = os.path.join(RUN, "run-key")
code3, lines3, calls3 = run_kit(["--key", "swk_" + "A" * 43, "--plain", "--work", w3], StandInPapex)
end3 = closing(w3, "  Sent to Papex. Go back to your run's page, choose how you are shown, and press Send.",
               "  https://papex.org/runs/b-0a1b2c")
case("E3 --key (Papex a stand-in): its first and last lines as in the published kit",
     code3 == 0 and lines3[-len(end3):] == end3 and not calls3 and lines3[:3] == [
         "With the key the kit asks Papex what to run, says when it is done, and sends the result",
         "file at the end. Nothing else leaves this computer.", ""],
     f"exit {code3}; last lines: {lines3[-len(end3):-1]}")

show_spec = importlib.util.spec_from_file_location("show", os.path.join(KIT, "show.py"))
show = importlib.util.module_from_spec(show_spec)
show_spec.loader.exec_module(show)
background = os.environ.get("PAPEX_KIT_BACKGROUND")
os.environ["PAPEX_KIT_BACKGROUND"] = "dark"  # otherwise the show asks the terminal
try:
    stage = show.Stage(stream=io.StringIO())
    stage.hear(end2[2], "advice", {})
    one = stage.after == show.clauses(end2[2].strip(), min(60, stage.width() - 10))
    stage = show.Stage(stream=io.StringIO())
    for line in end1[2:5]:
        stage.hear(line, "advice", {})
    three = " ".join(stage.after) == " ".join(line.strip() for line in end1[2:5]) and max(map(len, stage.after)) <= 60
finally:
    if background is None:
        os.environ.pop("PAPEX_KIT_BACKGROUND")
    else:
        os.environ["PAPEX_KIT_BACKGROUND"] = background
case("S1 the show's Next box: one advice line as before, the three of --batch as one text", one and three, stage.after)

# ---------------------------------------------------------------------------- the kit's own lists
if REAL:
    def gh(path):
        p = subprocess.run(["gh", "api", path], capture_output=True, text=True)
        if p.returncode != 0:
            raise SystemExit(f"gh api {path}: {p.stderr[:200]}")
        return json.loads(p.stdout)

    cache = os.path.join(OUT, "release-tests-blobs")
    os.makedirs(cache, exist_ok=True)
    for problem in sorted(os.listdir(os.path.join(KIT, "lists"))):
        folder = os.path.join(KIT, "lists", problem)
        for mname in sorted(n for n in os.listdir(folder) if n.endswith(".manifest.ndjson")):
            list_key = mname[:-len(".manifest.ndjson")]
            for line in open(os.path.join(folder, mname)):
                if not line.strip():
                    continue
                entry = json.loads(line)
                spec_path = os.path.join(folder, list_key, entry["key"] + ".spec.json")
                raw = open(spec_path, "rb").read()
                spec = json.loads(raw)
                same_line = "0x" + hashlib.sha256(raw).hexdigest() == entry["inputSha256"]
                repo = spec["repo"][len("https://github.com/"):-len(".git")]
                tree = gh(f"repos/{repo}/git/trees/{spec['commit']}?recursive=1")
                pre = (spec["projectDir"] + "/") if spec["projectDir"] else ""
                blobs = {e["path"]: e["sha"] for e in tree["tree"] if e["type"] == "blob" and e["path"].startswith(pre)}
                same_files = not tree.get("truncated") and set(blobs) == set(spec["files"])
                src = os.path.join(RUN, "real-" + entry["key"])
                mismatched = []
                for path, digest in spec["files"].items():
                    cached = os.path.join(cache, blobs.get(path, "missing"))
                    if not os.path.exists(cached):
                        data = base64.b64decode(gh(f"repos/{repo}/git/blobs/{blobs[path]}")["content"])
                        with open(cached, "wb") as fh:
                            fh.write(data)
                    data = open(cached, "rb").read()
                    if hashlib.sha256(data).hexdigest() != digest:
                        mismatched.append(path)
                    os.makedirs(os.path.dirname(os.path.join(src, path)), exist_ok=True)
                    with open(os.path.join(src, path), "wb") as fh:
                        fh.write(data)
                found = rerun.scan_source(src, spec)
                case(f"L {problem}/{list_key}/{entry['key']}: {repo} at {spec['commit'][:12]}",
                     same_line and same_files and not mismatched and found == [],
                     f"list file matches its manifest line: {same_line}; the commit's files are the list's files: "
                     f"{same_files} ({len(spec['files'])}); SHA-256 mismatches: {mismatched}; kit's search: "
                     f"{found if found else 'nothing found'}")

passed = sum(r["ok"] for r in results)
print(f"\n{passed} of {len(results)} cases as expected (Python {sys.version.split()[0]}). Projects in {RUN}")
with open(os.path.join(RUN, "results.json"), "w") as fh:
    json.dump(results, fh, indent=1, ensure_ascii=False)
sys.exit(0 if passed == len(results) else 1)
