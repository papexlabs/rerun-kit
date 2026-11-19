#!/usr/bin/env python3
"""Run a published, machine-checkable result on your own computer and tell Papex what happened.

  python3 rerun.py --key KIT_KEY [--api URL] [--docker] [--work DIR] [--agent-host NAME]
  python3 rerun.py BATCH_FILE    [--docker] [--work DIR] [--agent-host NAME]
  python3 rerun.py --check [--work DIR]
  python3 rerun.py --clean [--work DIR]

Your run's page on papex.org shows the first command with a key for your run, to copy. With the key
the kit asks Papex what to run, says when it is done, and sends the result file at the end. Nothing
else leaves this computer, and the key is never written to a file or printed. BATCH_FILE is the file
you can download from the page instead; then the kit sends nothing, and you upload the result file
on the page yourself.

What a run does, for a Lean proof:

  1. reads the list's file in lists/: which repository, which commit, the SHA-256 of every file to
     be built, the Lean version, the theorem and the axioms it may rest on;
  2. downloads Lean's installer (elan, a fixed version, checked by SHA-256), the repository at that
     commit, and Mathlib's ready-made build, all into the work folder next to this file;
  3. refuses to go on unless every file to be built has the SHA-256 the list names, unless the files
     Lake reads (lakefile.toml, lake-manifest.json, lean-toolchain) hold nothing the kit does not
     know, and unless a text search of the Lean files finds nothing that runs programs while building;
  4. builds the proof with Lean and asks Lean which axioms the theorem rests on;
  5. writes work/BATCH/BATCH.result.json: passed or failed, the axioms, the versions, the seconds.

Nothing is installed outside the work folder (about 11 GB for a Lean proof that uses Mathlib);
--clean deletes it. --docker does steps 2 to 4 inside a container and cuts the container's network
before the build (needs Docker). --check only tests that this computer can do a run.

A passing run shows that Lean accepts a proof of the sentence in the list's statement file, on your
computer. It is not peer review, and it does not say that the sentence is the problem.

Needs Python 3.9 or later, git and curl, on macOS or Linux (on Windows: WSL). See README.md.
"""

import hashlib
import http.client
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
LISTS = os.path.join(HERE, "lists")
KIT_NAME = "papex-rerun-kit"
KIT_VERSION = "1"
BATCH_SCHEMA = "papex-shared-work-batch/v1"
RESULT_SCHEMA = "papex-shared-work-result/v1"
SPEC_SCHEMA = "papex-rerun-spec/v1"
RESULT_MAX_BYTES = 262144
EXTRA_MAX_BYTES = 2048
DEFAULT_API = "https://api.papex.org"
KEY_RE = re.compile(r"^swk_[A-Za-z0-9_-]{43}$")
BATCH_RE = re.compile(r"^b-[0-9a-f]{6,10}$")
SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
UNIT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,119}$")
AGENT_HOST_RE = re.compile(r"^[\w ._+()/:-]{1,80}$")
KEY_HASHES = "kit-keys.sha256"  # in a batch's folder: the SHA-256 of each key used, never a key
DOCKER_IMAGE = "ubuntu:24.04"

# Lean's installer, one fixed release. The kit downloads the archive for this computer from
# https://github.com/leanprover/elan/releases/download/<version>/ and checks its SHA-256.
ELAN_VERSION = "v4.4.0"
ELAN_SHA256 = {
    "elan-aarch64-apple-darwin.tar.gz": "27af24edeace839730e8c9119783f12d5f694327d4771605021ca09db1ab0a87",
    "elan-x86_64-apple-darwin.tar.gz": "a5123096d662216ceaf69d68d6bbabb118c024d20d270bf0d639a830dd4ff97e",
    "elan-x86_64-unknown-linux-gnu.tar.gz": "0e8250aa2be86c7af929ade68db617af9edc8b9ccf6eaf5ece228250d0d032e2",
    "elan-aarch64-unknown-linux-gnu.tar.gz": "45cde3006f82f98804c94cf2ca4949d117060a5f3cc8afa62f523759947ee21f",
}

# What the text search looks for in the Lean files to be built, comments left out. Any of these can
# make a build run a program; a proof has no need of them. One hit stops the run.
FORBIDDEN = [
    (r"#eval\b", "#eval"), (r"#exit\b", "#exit"), (r"\brun_cmd\b", "run_cmd"),
    (r"\brun_elab\b", "run_elab"), (r"\brun_meta\b", "run_meta"),
    (r"\b(builtin_)?initialize\b", "initialize"), (r"\bunsafe\b", "unsafe"),
    (r"@\[\s*extern\b", "@[extern]"), (r"\bimplemented_by\b", "implemented_by"),
    (r"\bnative_decide\b", "native_decide"), (r"\bofReduceBool\b", "ofReduceBool"),
    (r"\bIO\b", "IO"), (r"\bLean\.", "Lean."), (r"\bopen\s+Lean\b", "open Lean"),
    (r"\belab(_rules)?\b", "elab"), (r"\bmacro(_rules)?\b", "macro"), (r"\bsyntax\b", "syntax"),
    (r"\bdeclare_syntax_cat\b", "declare_syntax_cat"), (r"\bevalExpr\b", "evalExpr"),
]
IMPORT_RE = re.compile(r"^\s*(?:public\s+|private\s+|meta\s+)*import\s+(?:all\s+)?([A-Za-z0-9_.']+)\s*$")
AXIOMS_RE = re.compile(r"^'([^']+)' depends on axioms: \[(.*)\]\s*$")
NO_AXIOMS_RE = re.compile(r"^'([^']+)' does not depend on any axioms\s*$")


def stop(message):
    raise SystemExit(message)


def say(line=""):
    print(line, flush=True)


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def minutes(seconds):
    seconds = int(seconds)
    return f"{seconds // 60} min {seconds % 60:02d} s" if seconds >= 60 else f"{seconds} s"


# ---------------------------------------------------------------------------- the list's files

def load_json(path, what):
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
        return raw, json.loads(raw)
    except (OSError, ValueError) as e:
        stop(f"{what} could not be read ({e}).")


def find_spec(batch, unit_key):
    """The file that says what this unit runs, found through the list's manifest and checked
    against it. Returns (path, spec, 0x-sha256 of the spec file)."""
    problem, list_key = str(batch.get("problem")), str(batch.get("list"))
    if not SLUG_RE.match(problem) or not SLUG_RE.match(list_key) or not UNIT_RE.match(unit_key):
        stop("The batch names a problem, list or unit this kit cannot read.")
    manifest = os.path.join(LISTS, problem, list_key + ".manifest.ndjson")
    if not os.path.exists(manifest):
        stop(f"This kit has no list {problem}/{list_key}. Get the newest kit (git pull) and run the "
             "same command again.")
    if "0x" + sha256_file(manifest) != batch.get("listSha256"):
        stop(f"The list file {os.path.relpath(manifest)} is not the one Papex froze. Get the newest "
             "kit (git pull) and run the same command again.")
    wanted = None
    with open(manifest, encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                entry = json.loads(line)
                if entry.get("key") == unit_key:
                    wanted = entry
    if not wanted:
        stop(f"Unit {unit_key} is not in the list file.")
    path = os.path.join(LISTS, problem, list_key, unit_key + ".spec.json")
    raw, spec = load_json(path, f"The unit's file {os.path.relpath(path)}")
    digest = "0x" + sha256_bytes(raw)
    if digest != wanted.get("inputSha256"):
        stop(f"The unit's file {os.path.relpath(path)} is not the one the list names.")
    check_spec(spec, path)
    return path, spec, digest


def check_spec(spec, path):
    def bad(why):
        stop(f"{os.path.relpath(path)}: {why}")

    if spec.get("schema") != SPEC_SCHEMA:
        bad("not a papex-rerun-spec/v1 file")
    if spec.get("system") != "lean4":
        bad("this kit runs Lean 4 proofs only")
    if not re.match(r"^https://github\.com/[\w.-]+/[\w.-]+\.git$", str(spec.get("repo"))):
        bad("repo must be an https GitHub address ending in .git")
    if not re.match(r"^[0-9a-f]{40}$", str(spec.get("commit"))):
        bad("commit must be a full 40-character hash")
    project = spec.get("projectDir")
    if not isinstance(project, str) or project.startswith("/") or ".." in project.split("/"):
        bad("projectDir must be a path inside the repository")
    files = spec.get("files")
    if not isinstance(files, dict) or not files:
        bad("files must name every file to be built with its SHA-256")
    for name, digest in files.items():
        if name.startswith("/") or ".." in name.split("/") or not re.match(r"^[0-9a-f]{64}$", str(digest)):
            bad(f"files: {name}")
    if not re.match(r"^leanprover/lean4:v[0-9][\w.-]*$", str(spec.get("toolchain"))):
        bad("toolchain must be a released Lean 4 version")
    theorems = spec.get("theorems")
    if not isinstance(theorems, list) or not theorems:
        bad("theorems must name at least one theorem")
    for t in theorems:
        if not (isinstance(t, dict) and re.match(r"^[\w.']+$", str(t.get("name")))
                and re.match(r"^[\w.']+$", str(t.get("module")))):
            bad("theorems: each needs a name and the module to import")
    if not isinstance(spec.get("permittedAxioms"), list):
        bad("permittedAxioms must be a list")
    if not isinstance(spec.get("outputs"), list) or not spec["outputs"]:
        bad("outputs must name the built files to fingerprint")


# ---------------------------------------------------------------------------- running tools

def tool_env(work):
    """The environment every tool of a run gets: its home is the work folder, and nothing of this
    computer's own environment (tokens, keys) is passed on except what a download needs."""
    home = os.path.join(work, "home")
    env = {
        "HOME": home,
        "ELAN_HOME": os.path.join(home, ".elan"),
        "PATH": os.pathsep.join([os.path.join(home, ".elan", "bin"), "/usr/local/bin", "/opt/homebrew/bin",
                                 "/usr/bin", "/bin", "/usr/sbin", "/sbin"]),
        "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
        "GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
        "TMPDIR": os.path.join(work, "tmp"),
    }
    for name in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "NO_PROXY", "no_proxy",
                 "SSL_CERT_FILE", "SSL_CERT_DIR"):
        if os.environ.get(name):
            env[name] = os.environ[name]
    return env


def run(cmd, cwd, env, log, label):
    """Run a tool to its end, its output into the log file; one line every 20 s says it is alive.
    Returns (exit code, seconds)."""
    start = time.monotonic()
    with open(log, "ab") as out:
        out.write(("\n$ " + " ".join(cmd) + "\n").encode())
        out.flush()
        try:
            p = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=out, stderr=subprocess.STDOUT,
                                 stdin=subprocess.DEVNULL)
        except OSError as e:
            stop(f"{cmd[0]} could not be started ({e}).")
        last = start
        while True:
            try:
                code = p.wait(timeout=1.0)
                break
            except subprocess.TimeoutExpired:
                if time.monotonic() - last >= 20:
                    last = time.monotonic()
                    say(f"    … {label}, {minutes(last - start)}")
            except KeyboardInterrupt:
                p.terminate()
                raise
    return code, time.monotonic() - start


def output_of(cmd, cwd, env):
    try:
        p = subprocess.run(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           stdin=subprocess.DEVNULL, text=True, errors="replace")
    except OSError as e:
        return 127, str(e)
    return p.returncode, p.stdout


def tail(log, lines=12):
    try:
        with open(log, "rb") as fh:
            fh.seek(max(0, os.path.getsize(log) - 6000))
            text = fh.read().decode("utf-8", "replace").replace("\r", "\n")
    except OSError:
        return ""
    kept = [line for line in text.split("\n") if line.strip()][-lines:]
    return "\n".join("    " + line[:200] for line in kept)


# ---------------------------------------------------------------------------- phase 1: fetch

def elan_archive():
    system, machine = platform.system(), platform.machine().lower()
    arch = {"arm64": "aarch64", "aarch64": "aarch64", "x86_64": "x86_64", "amd64": "x86_64"}.get(machine)
    target = {"Darwin": "apple-darwin", "Linux": "unknown-linux-gnu"}.get(system)
    if not arch or not target:
        stop(f"This kit runs on macOS and Linux (on Windows: WSL). This computer is {system} {machine}.")
    return f"elan-{arch}-{target}.tar.gz"


def download(url, path):
    req = urllib.request.Request(url, headers={"User-Agent": f"{KIT_NAME}/{KIT_VERSION}"})
    try:
        with urllib.request.urlopen(req, timeout=120) as answer, open(path, "wb") as fh:
            shutil.copyfileobj(answer, fh)
    except (urllib.error.URLError, OSError, http.client.HTTPException) as e:
        stop(f"Could not download {url} ({getattr(e, 'reason', e)}). Check the connection and run the "
             "same command again.")


def install_elan(work, env, log):
    elan = os.path.join(env["ELAN_HOME"], "bin", "elan")
    if os.path.exists(elan):
        return
    name = elan_archive()
    archive = os.path.join(work, "tmp", name)
    say(f"  Lean's installer (elan {ELAN_VERSION})")
    download(f"https://github.com/leanprover/elan/releases/download/{ELAN_VERSION}/{name}", archive)
    if sha256_file(archive) != ELAN_SHA256[name]:
        os.remove(archive)
        stop("The installer that came down is not the one this kit expects (SHA-256 differs). Nothing "
             "was run.")
    folder = os.path.join(work, "tmp", "elan-init")
    shutil.rmtree(folder, ignore_errors=True)
    os.makedirs(folder)
    with tarfile.open(archive) as tar:
        member = tar.getmember("elan-init")
        if not member.isfile():
            stop("The installer archive is not what this kit expects.")
        with tar.extractfile(member) as src, open(os.path.join(folder, "elan-init"), "wb") as dst:
            shutil.copyfileobj(src, dst)
    init = os.path.join(folder, "elan-init")
    os.chmod(init, 0o755)
    code, _ = run([init, "-y", "--no-modify-path", "--default-toolchain", "none"], work, env, log,
                  "installing elan")
    if code != 0 or not os.path.exists(elan):
        stop("Lean's installer did not finish:\n" + tail(log))


def strip_comments(text):
    """Lean source without block comments (they nest) and line comments."""
    out, depth, i = [], 0, 0
    while i < len(text):
        two = text[i:i + 2]
        if two == "/-":
            depth += 1
            i += 2
        elif two == "-/" and depth:
            depth -= 1
            i += 2
        elif depth:
            if text[i] == "\n":
                out.append("\n")
            i += 1
        elif two == "--":
            while i < len(text) and text[i] != "\n":
                i += 1
        else:
            out.append(text[i])
            i += 1
    return "".join(out)


RAW_STRING_RE = re.compile(r'r(#*)"')
CHAR_LITERAL_RE = re.compile(r"'(\\.|[^\\'])'")


def strip_comments_knowing_strings(text):
    """Lean source without comments, where "--" or "/-" inside a string, a raw string r#"..."# or a
    character literal does not start a comment. The search reads the file both ways (this one and
    strip_comments), so a comment sign inside a string cannot hide code from it; a mistake here can only
    add findings, never remove one."""
    out, i, n = [], 0, len(text)
    while i < n:
        c, two = text[i], text[i:i + 2]
        if two == "--":
            while i < n and text[i] != "\n":
                i += 1
        elif two == "/-":
            depth, i = 1, i + 2
            while i < n and depth:
                if text[i:i + 2] == "/-":
                    depth, i = depth + 1, i + 2
                elif text[i:i + 2] == "-/":
                    depth, i = depth - 1, i + 2
                else:
                    if text[i] == "\n":
                        out.append("\n")
                    i += 1
        elif c == "r" and (i == 0 or not (text[i - 1].isalnum() or text[i - 1] in "_'!?.")) and \
                RAW_STRING_RE.match(text, i):
            hashes = len(RAW_STRING_RE.match(text, i).group(1))
            end = text.find('"' + "#" * hashes, i + 2 + hashes)
            end = n if end < 0 else end + 1 + hashes
            out.append(text[i:end])
            i = end
        elif c == '"':
            j = i + 1
            while j < n and text[j] != '"':
                j += 2 if text[j] == "\\" else 1
            out.append(text[i:j + 1])
            i = j + 1
        elif c == "'" and (i == 0 or not (text[i - 1].isalnum() or text[i - 1] in "_'!?")) and \
                CHAR_LITERAL_RE.match(text, i):
            m = CHAR_LITERAL_RE.match(text, i)
            out.append(m.group())
            i += len(m.group())
        else:
            out.append(c)
            i += 1
    return "".join(out)


def is_module_file(path):
    """True when a Lean file opens with the keyword `module` (Lean's module system)."""
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in strip_comments(fh.read()).split("\n"):
                if line.strip():
                    return line.strip() == "module"
    except OSError:
        pass
    return False


# ---------------------------------------------------------------------------- the files Lake reads
#
# Before anything is built, Lake reads three files of the project: lakefile.toml, lake-manifest.json and
# lean-toolchain. The kit reads them first and stops at anything it does not know: a key or an option it
# has no list for, a requirement other than Mathlib, a package that is not a git commit of
# leanprover-community or leanprover, a Lean version other than the list's.

class TomlError(Exception):
    pass


TOML_BARE_KEY = re.compile(r"[A-Za-z0-9_-]+")
TOML_SCALAR = re.compile(r"(true|false|[+-]?(?:0|[1-9][0-9]*))(?=[ \t\n,\]}#]|$)")
TOML_ESCAPES = {'"': '"', "\\": "\\", "n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f"}


class _Toml:
    """A strict reader of the part of TOML that Lake's build files use: comments, [table] and [[array]]
    headers, keys (bare, quoted, dotted), one-line strings, true and false, whole numbers, arrays and
    one-line inline tables. Anything else (multi-line strings, numbers with a point or a date, a key
    defined twice, a table extended in a way TOML forbids or that is unclear) raises TomlError. Written
    by hand so that the kit runs on Python 3.9; on Python 3.11 and later the kit also reads the file with
    Python's own tomllib and stops if the two readings differ."""

    def __init__(self, text):
        if "\x00" in text or "\r" in text.replace("\r\n", ""):
            raise TomlError("a character the kit does not read (NUL or a lone carriage return)")
        self.s, self.i = text.replace("\r\n", "\n"), 0
        self.root = {}
        self.kind = {}  # id(table) -> "header", "implicit", "dotted", "inline", "array-item"

    def fail(self, why):
        raise TomlError(f"line {self.s.count(chr(10), 0, self.i) + 1}: {why}")

    def peek(self):
        return self.s[self.i] if self.i < len(self.s) else ""

    def ws(self):
        while self.peek() in (" ", "\t") and self.peek():
            self.i += 1

    def comment(self):
        if self.peek() == "#":
            while self.i < len(self.s) and self.s[self.i] != "\n":
                if (ord(self.s[self.i]) < 32 and self.s[self.i] != "\t") or self.s[self.i] == "\x7f":
                    self.fail("a control character in a comment")
                self.i += 1

    def end_of_line(self):
        self.ws()
        self.comment()
        if self.i < len(self.s):
            if self.s[self.i] != "\n":
                self.fail("more text after a value")
            self.i += 1

    def blank(self):  # spaces, line ends and comments, as allowed inside an array
        while True:
            self.ws()
            if self.peek() == "#":
                self.comment()
            elif self.peek() == "\n":
                self.i += 1
            else:
                return

    def string(self):
        quote = self.peek()
        if self.s.startswith(quote * 3, self.i):
            self.fail("a multi-line string")
        self.i += 1
        out = []
        while True:
            c = self.peek()
            if not c or c == "\n":
                self.fail("a string that does not end on its line")
            if c == quote:
                self.i += 1
                return "".join(out)
            if quote == '"' and c == "\\":
                e = self.s[self.i + 1:self.i + 2]
                if e in TOML_ESCAPES:
                    out.append(TOML_ESCAPES[e])
                    self.i += 2
                    continue
                n = {"u": 4, "U": 8}.get(e)
                digits = self.s[self.i + 2:self.i + 2 + n] if n else ""
                if not n or not re.fullmatch(r"[0-9A-Fa-f]{%d}" % n, digits):
                    self.fail("an escape in a string the kit does not read")
                code = int(digits, 16)
                if code > 0x10FFFF or 0xD800 <= code <= 0xDFFF:
                    self.fail("an escape in a string the kit does not read")
                out.append(chr(code))
                self.i += 2 + n
                continue
            if (ord(c) < 32 and c != "\t") or c == "\x7f":
                self.fail("a control character in a string")
            out.append(c)
            self.i += 1

    def key(self):
        parts = []
        while True:
            self.ws()
            if self.peek() in ('"', "'"):
                parts.append(self.string())
            else:
                m = TOML_BARE_KEY.match(self.s, self.i)
                if not m:
                    self.fail("a key the kit does not read")
                parts.append(m.group())
                self.i = m.end()
            self.ws()
            if self.peek() != ".":
                return parts
            self.i += 1

    def value(self, depth=0):
        if depth > 8:
            self.fail("values nested too deep")
        c = self.peek()
        if c in ('"', "'"):
            return self.string()
        if c == "[":
            self.i += 1
            items = []
            while True:
                self.blank()
                if self.peek() == "]":
                    self.i += 1
                    return items
                items.append(self.value(depth + 1))
                self.blank()
                if self.peek() == ",":
                    self.i += 1
                elif self.peek() == "]":
                    self.i += 1
                    return items
                else:
                    self.fail("an array the kit does not read")
        if c == "{":
            self.i += 1
            table = {}
            self.kind[id(table)] = "inline"
            self.ws()
            if self.peek() == "}":
                self.i += 1
                return table
            while True:
                path = self.key()
                if self.peek() != "=":
                    self.fail("an inline table the kit does not read")
                self.i += 1
                self.ws()
                self.assign(table, path, self.value(depth + 1), inline=True)
                self.ws()
                if self.peek() == ",":
                    self.i += 1
                    self.ws()
                elif self.peek() == "}":
                    self.i += 1
                    return table
                else:
                    self.fail("an inline table the kit does not read (it must be on one line)")
        m = TOML_SCALAR.match(self.s, self.i)
        if not m:
            self.fail("a value the kit does not read (only strings, true, false, whole numbers, arrays and "
                      "inline tables)")
        self.i = m.end()
        word = m.group(1)
        return True if word == "true" else False if word == "false" else int(word)

    def assign(self, table, path, value, inline=False):
        for part in path[:-1]:
            if part not in table:
                table[part] = {}
                self.kind[id(table[part])] = "inline-dotted" if inline else "dotted"
            elif not (isinstance(table[part], dict) and self.kind.get(id(table[part])) in ("dotted", "inline-dotted")):
                self.fail(f"the key {'.'.join(path)} extends a table defined elsewhere")
            table = table[part]
        if path[-1] in table:
            self.fail(f"the key {'.'.join(path)} is defined twice")
        table[path[-1]] = value

    def header(self, path, array):
        table = self.root
        for part in path[:-1]:
            if part not in table:
                table[part] = {}
                self.kind[id(table[part])] = "implicit"
            node = table[part]
            if isinstance(node, list) and node and self.kind.get(id(node)) == "array":
                node = node[-1]
            if not isinstance(node, dict) or self.kind.get(id(node)) in ("inline", "inline-dotted"):
                self.fail(f"the table [{'.'.join(path)}] goes through a value")
            table = node
        last = path[-1]
        if array:
            if last not in table:
                table[last] = []
                self.kind[id(table[last])] = "array"
            if not (isinstance(table[last], list) and self.kind.get(id(table[last])) == "array"):
                self.fail(f"[[{'.'.join(path)}]] names something that is not an array of tables")
            item = {}
            self.kind[id(item)] = "header"
            table[last].append(item)
            return item
        if last in table:
            node = table[last]
            if not (isinstance(node, dict) and self.kind.get(id(node)) == "implicit"):
                self.fail(f"the table [{'.'.join(path)}] is defined twice")
            self.kind[id(node)] = "header"
            return node
        table[last] = {}
        self.kind[id(table[last])] = "header"
        return table[last]

    def read(self):
        table = self.root
        while True:
            self.blank()
            if self.i >= len(self.s):
                return self.root
            if self.peek() == "[":
                array = self.s.startswith("[[", self.i)
                self.i += 2 if array else 1
                path = self.key()
                if not self.s.startswith("]]" if array else "]", self.i):
                    self.fail("a table header the kit does not read")
                self.i += 2 if array else 1
                table = self.header(path, array)
            else:
                path = self.key()
                if self.peek() != "=":
                    self.fail("a line the kit does not read")
                self.i += 1
                self.ws()
                self.assign(table, path, self.value())
            self.end_of_line()


def read_toml(text):
    """The build file as a dictionary, or TomlError. Two readers where Python has tomllib (3.11 and later):
    the kit's own and Python's; they must agree."""
    mine = _Toml(text).read()
    try:
        import tomllib
    except ImportError:
        return mine
    try:
        theirs = tomllib.loads(text)
    except ValueError as e:
        raise TomlError(f"Python's TOML reader refuses it ({e})")
    if theirs != mine:
        raise TomlError("the kit's TOML reader and Python's read it differently")
    return mine


MODULE_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_']*(\.[A-Za-z_][A-Za-z0-9_']*)*$")
GLOB_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_']*(\.[A-Za-z_][A-Za-z0-9_']*)*(\.[*+])?$")
# The keys of lakefile.toml the kit knows, with the type each must have. Any other key stops the run:
# moreLeanArgs, weakLeanArgs, moreLinkArgs, precompileModules, plugins, dynlibs, extraDepTargets,
# buildDir, packagesDir and the like can make Lake load or run a program or put files elsewhere.
STR, BOOL, STRS = "a text", "true or false", "a list of texts"
PACKAGE_KEYS = {"name": STR, "version": STR, "versionTags": STR, "description": STR, "keywords": STRS,
                "homepage": STR, "license": STR, "licenseFiles": STRS, "readmeFile": STR, "reservoir": BOOL,
                "defaultTargets": STRS, "testDriver": STR, "testDriverArgs": STRS, "lintDriver": STR,
                "lintDriverArgs": STRS, "srcDir": STR, "fixedToolchain": BOOL}
LIB_KEYS = {"name": STR, "srcDir": STR, "roots": STRS, "globs": STRS, "libName": STR}
EXE_KEYS = {"name": STR, "root": STR, "srcDir": STR, "exeName": STR}
REQUIRE_KEYS = {"name": STR, "git": STR, "rev": STR, "scope": STR, "version": STR}
# The Lean options a build file may set. Others stop the run: debug.skipKernelTC, for one, turns off
# Lean's kernel check.
OPTION_NAMES = {"autoImplicit", "relaxedAutoImplicit", "maxHeartbeats", "maxRecDepth", "maxSynthPendingDepth",
                "synthInstance.maxHeartbeats", "synthInstance.maxSize", "warningAsError"}
OPTION_PREFIXES = ("pp.", "linter.", "weak.linter.")
MATHLIB_URL_RE = re.compile(r"^https://github\.com/leanprover-community/mathlib4(\.git)?$")
PACKAGE_URL_RE = re.compile(r"^https://github\.com/(leanprover-community|leanprover)/[A-Za-z0-9_.-]+$")
MANIFEST_KEYS = {"version", "packagesDir", "packages", "name", "lakeDir", "fixedToolchain"}
MANIFEST_PACKAGE_KEYS = {"name", "type", "url", "rev", "scope", "inherited", "inputRev", "configFile",
                         "manifestFile", "subDir"}
IMPORT_WORD_RE = re.compile(r"^\s*(?:(?:public|private|meta)\s+)*import\b")


def has_type(value, kind):
    if kind == STR:
        return isinstance(value, str)
    if kind == BOOL:
        return isinstance(value, bool)
    return isinstance(value, list) and all(isinstance(v, str) for v in value)


def inside_project(path):
    return isinstance(path, str) and not path.startswith("/") and ".." not in path.replace("\\", "/").split("/")


def build_file_findings(src, spec):
    """What stops the run in the files Lake reads (empty: nothing). Read before anything is built."""
    project, files = spec["projectDir"], spec["files"]
    pre = (project + "/") if project else ""
    found = []
    for name in sorted(files):
        if ".lake" in name[len(pre):].split("/"):
            found.append(f"{name}: a file of Lake's own folder .lake is part of the repository")

    def keys(where, table, known):
        for key, value in table.items():
            if key not in known:
                found.append(f"{pre}lakefile.toml: {where}{key} is not a key the kit knows")
            elif not has_type(value, known[key]):
                found.append(f"{pre}lakefile.toml: {where}{key} must be {known[key]}")
            elif key == "srcDir" and not inside_project(value):
                found.append(f"{pre}lakefile.toml: {where}srcDir leaves the project")

    def options(where, table, prefix=""):
        if not isinstance(table, dict):
            found.append(f"{pre}lakefile.toml: {where}leanOptions must be a table")
            return
        for key, value in table.items():
            full = prefix + key
            if isinstance(value, dict):  # pp.unicode.fun = true reads as {pp: {unicode: {fun: true}}}
                options(where, value, full + ".")
            elif not (full in OPTION_NAMES or full.startswith(OPTION_PREFIXES)) or \
                    not isinstance(value, (bool, int, str)):
                found.append(f"{pre}lakefile.toml: {where}sets the Lean option {full}, which the kit does not know")

    def tables(conf, key):
        value = conf.get(key, [])
        if not isinstance(value, list) or not all(isinstance(v, dict) for v in value):
            found.append(f"{pre}lakefile.toml: {key} must be written as [[{key}]] tables")
            return []
        return value

    if pre + "lakefile.toml" not in files:
        found.append(f"{pre}lakefile.toml: the project has no lakefile.toml")
    else:
        try:
            with open(os.path.join(src, pre + "lakefile.toml"), encoding="utf-8") as fh:
                conf = read_toml(fh.read())
        except (OSError, UnicodeDecodeError, TomlError) as e:
            found.append(f"{pre}lakefile.toml: the kit cannot read it ({e})")
            conf = None
        if conf is not None:
            keys("", {k: v for k, v in conf.items() if k not in ("leanOptions", "require", "lean_lib", "lean_exe")},
                 PACKAGE_KEYS)
            if "leanOptions" in conf:
                options("", conf["leanOptions"])
            for req in tables(conf, "require"):
                keys("require ", req, REQUIRE_KEYS)
                git, scope = req.get("git"), req.get("scope")
                if str(req.get("name")).lower() != "mathlib":
                    found.append(f"{pre}lakefile.toml: requires {req.get('name')}; the only requirement allowed is Mathlib")
                elif (git is None and scope != "leanprover-community") or \
                        (git is not None and not MATHLIB_URL_RE.match(str(git))) or \
                        (scope is not None and scope != "leanprover-community"):
                    found.append(f"{pre}lakefile.toml: Mathlib must come from leanprover-community")
            for lib in tables(conf, "lean_lib"):
                where = f"lean_lib {lib.get('name')}: "
                keys(where, {k: v for k, v in lib.items() if k != "leanOptions"}, LIB_KEYS)
                if "leanOptions" in lib:
                    options(where, lib["leanOptions"])
                for r in (lib.get("roots") if has_type(lib.get("roots"), STRS) else []):
                    if not MODULE_NAME_RE.match(r):
                        found.append(f"{pre}lakefile.toml: {where}the root {r} is not a module name the kit reads")
                for g in (lib.get("globs") if has_type(lib.get("globs"), STRS) else []):
                    if not GLOB_RE.match(g):
                        found.append(f"{pre}lakefile.toml: {where}the glob {g} is not one the kit reads")
            for exe in tables(conf, "lean_exe"):
                keys(f"lean_exe {exe.get('name')}: ", exe, EXE_KEYS)

    if pre + "lake-manifest.json" not in files:
        found.append(f"{pre}lake-manifest.json: the project has none, so its packages are not fixed")
    else:
        try:
            with open(os.path.join(src, pre + "lake-manifest.json"), encoding="utf-8") as fh:
                manifest = json.load(fh)
            if not isinstance(manifest, dict) or not isinstance(manifest.get("packages"), list):
                raise ValueError("not a manifest")
        except (OSError, UnicodeDecodeError, ValueError) as e:
            found.append(f"{pre}lake-manifest.json: the kit cannot read it ({e})")
            manifest = {"packages": []}
        for key in set(manifest) - MANIFEST_KEYS:
            found.append(f"{pre}lake-manifest.json: {key} is not a key the kit knows")
        if manifest.get("packagesDir", ".lake/packages") != ".lake/packages" or manifest.get("lakeDir", ".lake") != ".lake":
            found.append(f"{pre}lake-manifest.json: moves Lake's folders (packagesDir or lakeDir)")
        for p in manifest["packages"]:
            if not isinstance(p, dict):
                found.append(f"{pre}lake-manifest.json: a package the kit cannot read")
                continue
            name = p.get("name")
            for key in set(p) - MANIFEST_PACKAGE_KEYS:
                found.append(f"{pre}lake-manifest.json: package {name}: {key} is not a key the kit knows")
            if p.get("type") != "git" or p.get("subDir") is not None:
                found.append(f"{pre}lake-manifest.json: package {name} is not a git repository (a folder, for instance)")
            elif not PACKAGE_URL_RE.match(str(p.get("url"))) or \
                    (str(name).lower() == "mathlib" and not MATHLIB_URL_RE.match(str(p.get("url")))):
                found.append(f"{pre}lake-manifest.json: package {name} comes from {str(p.get('url'))[:80]}, not from "
                             "leanprover-community or leanprover on GitHub")
            elif not re.match(r"^[0-9a-f]{40}$", str(p.get("rev"))):
                found.append(f"{pre}lake-manifest.json: package {name} is not fixed at a commit")

    if pre + "lean-toolchain" not in files:
        found.append(f"{pre}lean-toolchain: the project has none")
    else:
        try:
            with open(os.path.join(src, pre + "lean-toolchain"), encoding="utf-8") as fh:
                if fh.read().strip() != spec["toolchain"]:
                    found.append(f"{pre}lean-toolchain: names another Lean version than the list's file")
        except (OSError, UnicodeDecodeError) as e:
            found.append(f"{pre}lean-toolchain: the kit cannot read it ({e})")
    return found


def scan_source(src, spec):
    """The text search of step 3, after the check of the files Lake reads. Returns the list of
    findings (empty: nothing found)."""
    project = spec["projectDir"]
    lean_files = [name for name in spec["files"] if name.endswith(".lean")]
    own = set()
    for name in lean_files:
        inside = os.path.relpath(name, project) if project else name
        own.add(inside[:-len(".lean")].replace(os.sep, ".").replace("/", "."))
    found = build_file_findings(src, spec)
    for name in sorted(spec["files"]):
        base = os.path.basename(name)
        if base == "lakefile.lean":
            found.append(f"{name}: a build file written as a program")
        if not name.endswith(".lean"):
            continue
        with open(os.path.join(src, name), encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        code = strip_comments(text)
        other = strip_comments_knowing_strings(text).split("\n")
        for number, line in enumerate(code.split("\n"), 1):
            also = other[number - 1] if number <= len(other) else ""
            m = IMPORT_RE.match(line)
            if m and not MODULE_NAME_RE.match(m.group(1)):  # a trailing dot, a part starting with a digit...
                found.append(f"{name}:{number}: an import the kit cannot read")
                continue
            if m:
                module = m.group(1)
                if not (module == "Mathlib" or module.startswith("Mathlib.") or module in own):
                    found.append(f"{name}:{number}: imports {module}")
                continue
            if IMPORT_WORD_RE.match(line):  # «names», two imports on a line, an import over two lines...
                found.append(f"{name}:{number}: an import the kit cannot read")
                continue
            for pattern, word in FORBIDDEN:
                if re.search(pattern, line) or re.search(pattern, also):
                    found.append(f"{name}:{number}: {word}")
        for number in range(len(code.split("\n")) + 1, len(other) + 1):  # lines only the second reading has
            for pattern, word in FORBIDDEN:
                if re.search(pattern, other[number - 1]):
                    found.append(f"{name}:{number}: {word}")
    return found


def fetch(spec, work):
    """Phase 1 (needs the network): installer, the repository at its commit, checks, Lean and
    Mathlib's ready-made build. Returns the seconds it took. Nothing of the proof is built here."""
    start = time.monotonic()
    env = tool_env(work)
    for folder in ("home", "tmp"):
        os.makedirs(os.path.join(work, folder), exist_ok=True)
    log = os.path.join(work, "fetch.log")
    marker = os.path.join(work, "fetched.json")
    src = os.path.join(work, "src")
    project = os.path.join(src, spec["projectDir"])
    git = shutil.which("git", path=env["PATH"])
    if not git:
        stop("git was not found. Install git and run the same command again.")
    if not shutil.which("curl", path=env["PATH"]):  # Mathlib's own download tool calls it
        stop("curl was not found. Install curl and run the same command again.")

    install_elan(work, env, log)

    code, head = output_of([git, "-C", src, "rev-parse", "HEAD"], work, env) if os.path.isdir(src) else (1, "")
    if code != 0 or head.strip() != spec["commit"]:
        say(f"  The repository at commit {spec['commit'][:12]}")
        shutil.rmtree(src, ignore_errors=True)
        os.makedirs(src)
        for cmd in ([git, "init", "-q", "."], [git, "remote", "add", "origin", spec["repo"]],
                    [git, "fetch", "-q", "--depth", "1", "origin", spec["commit"]],
                    [git, "checkout", "-q", "--detach", "FETCH_HEAD"]):
            code, _ = run(cmd, src, env, log, "getting the repository")
            if code != 0:
                stop("The repository could not be fetched:\n" + tail(log))
        code, head = output_of([git, "-C", src, "rev-parse", "HEAD"], work, env)
        if code != 0 or head.strip() != spec["commit"]:
            stop("The repository that came down is not at the commit the list names. Nothing was built.")

    code, listed = output_of([git, "-C", src, "ls-files", "--", spec["projectDir"] or "."], work, env)
    tracked = set(listed.split("\n")) - {""}
    if code != 0 or tracked != set(spec["files"]):
        stop("The repository's files are not the ones the list names. Nothing was built.")
    for name, digest in spec["files"].items():
        path = os.path.join(src, name)
        if os.path.islink(path) or not os.path.isfile(path) or sha256_file(path) != digest:
            stop(f"{name} is not the file the list names (SHA-256 differs). Nothing was built.")
    say(f"  {len(spec['files'])} files match the list's SHA-256 values")

    found = scan_source(src, spec)
    if found:
        stop("The text search found something that could run a program while building. Nothing was "
             "built.\n" + "\n".join("    " + line for line in found[:20]))
    say("  Text search: nothing that runs programs while building")

    try:
        with open(marker) as fh:
            done = json.load(fh).get("commit") == spec["commit"]
    except (OSError, ValueError):
        done = False
    if not done:
        say(f"  Lean {spec['toolchain'].split(':v')[-1]} and Mathlib's ready-made build (the long step)")
        code, _ = run(["lake", "exe", "cache", "get"], project, env, log, "downloading")
        if code != 0:
            stop("Lean or Mathlib's ready-made build could not be fetched:\n" + tail(log))
    code, version = output_of(["lean", "--version"], project, env)
    wanted = spec.get("leanCommit")
    if code != 0 or (wanted and wanted not in version):
        stop("The Lean that was installed is not the version the list names:\n    " + version.strip()[:200])
    with open(marker, "w") as fh:
        json.dump({"commit": spec["commit"], "lean": version.strip()}, fh)
    return time.monotonic() - start


# ---------------------------------------------------------------------------- phase 2: build

def build(spec, work):
    """Phase 2 (needs no network): build, ask for the axioms, fingerprint what was built.
    Returns the record of the run."""
    env = tool_env(work)
    src = os.path.join(work, "src")
    project = os.path.join(src, spec["projectDir"])
    log = os.path.join(work, "build.log")
    if os.path.exists(log):
        os.remove(log)
    _, version = output_of(["lean", "--version"], project, env)

    say("  Building the proof")
    code, build_seconds = run(["lake", "build"], project, env, log, "building")
    record = {"lean": version.strip()[:60], "buildExit": code, "buildSeconds": round(build_seconds, 1),
              "checkSeconds": 0.0, "axioms": {}, "problems": []}
    if code != 0:
        record["problems"].append("the build failed")

    if code == 0:
        check = os.path.join(work, "check.lean")
        modules = sorted({t["module"] for t in spec["theorems"]})
        # A file of Lean's module system is imported from a module: a plain file would load the
        # private part of every library file too, which takes minutes and gigabytes.
        as_module = any(is_module_file(os.path.join(project, *m.split(".")) + ".lean") for m in modules)
        with open(check, "w") as fh:
            fh.write("module\n\n" if as_module else "")
            fh.write("".join(f"{'public ' if as_module else ''}import {m}\n" for m in modules))
            fh.write("\n" + "".join(f"#print axioms {t['name']}\n" for t in spec["theorems"]))
        say("  Asking Lean which axioms the theorem rests on")
        start = time.monotonic()
        check_code, text = output_of(["lake", "env", "lean", check], project, env)
        record["checkSeconds"] = round(time.monotonic() - start, 1)
        record["checkSha256"] = "0x" + sha256_bytes(text.encode())
        with open(log, "ab") as fh:
            fh.write(("\n$ lake env lean check.lean\n" + text).encode())
        # Lean wraps a long axioms line ("... depends on axioms: [propext,\n Classical.choice,\n ...]");
        # join the continuation lines of an open bracket before reading them.
        lines = []
        for line in text.split("\n"):
            if lines and line[:1].isspace() and lines[-1].count("[") > lines[-1].count("]"):
                lines[-1] += " " + line.strip()
            else:
                lines.append(line)
        for line in lines:
            m = AXIOMS_RE.match(line)
            if m:
                record["axioms"][m.group(1)] = [a.strip() for a in m.group(2).split(",") if a.strip()]
            m = NO_AXIOMS_RE.match(line)
            if m:
                record["axioms"][m.group(1)] = []
        if check_code != 0:
            record["problems"].append("Lean could not print the axioms")
        permitted = set(spec["permittedAxioms"])
        for t in spec["theorems"]:
            axioms = record["axioms"].get(t["name"])
            if axioms is None:
                record["problems"].append(f"no axioms line for {t['name']}")
            elif not set(axioms) <= permitted:
                record["problems"].append(
                    f"{t['name']} rests on {', '.join(sorted(set(axioms) - permitted))}")

    passed = not record["problems"]
    h, size = hashlib.sha256(), 0
    names = spec["outputs"] if passed else []
    for name in names:
        path = os.path.join(src, name)
        if not os.path.isfile(path):
            record["problems"].append(f"{name} was not built")
            passed = False
            break
        h.update((name + "\n" + sha256_file(path) + "\n").encode())
        size += os.path.getsize(path)
    if passed:
        record["outputSha256"], record["outputBytes"] = "0x" + h.hexdigest(), size
    else:  # a failed run is fingerprinted by its log, so a failure can still be reported
        record["outputSha256"], record["outputBytes"] = "0x" + sha256_file(log), max(1, os.path.getsize(log))
    record["outcome"] = "PASS" if passed else "FAIL"
    return record


# ---------------------------------------------------------------------------- --docker

def docker_run(spec_path, spec, work, name):
    """Steps 2 to 4 inside a container. The network is cut before anything of the proof is built.
    The container and its volume are named after the list; --clean removes them."""
    docker = shutil.which("docker")
    if not docker:
        stop("--docker needs Docker, which was not found on this computer.")

    def d(*args, capture=False):
        p = subprocess.run([docker, *args], stdout=subprocess.PIPE if capture else None,
                           stderr=subprocess.STDOUT if capture else None, text=True)
        return p.returncode, (p.stdout or "")

    if d("info", capture=True)[0] != 0:
        stop("Docker is installed but not running. Start it and run the same command again.")
    d("rm", "-f", name, capture=True)
    code, out = d("run", "-d", "--name", name, "-v", f"{name}:/work", DOCKER_IMAGE, "sleep", "infinity",
                  capture=True)
    if code != 0:
        stop("The container could not be started:\n    " + out.strip()[-400:])
    try:
        say("  Preparing the container")
        setup = ("export DEBIAN_FRONTEND=noninteractive; apt-get update -qq >/dev/null && "
                 "apt-get install -y -qq --no-install-recommends python3 git curl ca-certificates >/dev/null && "
                 "(id runner >/dev/null 2>&1 || useradd -m runner) && mkdir -p /kit /work && "
                 "chown -R runner:runner /work /kit")
        code, out = d("exec", name, "bash", "-c", setup, capture=True)
        if code != 0:
            stop("The container could not be prepared:\n    " + out.strip()[-400:])
        d("cp", os.path.abspath(__file__), f"{name}:/kit/rerun.py", capture=True)
        d("cp", spec_path, f"{name}:/kit/spec.json", capture=True)
        inside = ["exec", "-u", "runner", name, "python3", "/kit/rerun.py", "--spec", "/kit/spec.json",
                  "--work", "/work"]
        if d(*inside, "--phase", "fetch")[0] != 0:
            stop("The run stopped in the container before the build (see the lines above).")
        if d("network", "disconnect", "bridge", name, capture=True)[0] != 0:
            stop("The container's network could not be cut, so nothing was built.")
        say("  The container's network is cut")
        if d(*inside, "--phase", "build")[0] != 0:
            stop("The build could not be run in the container (see the lines above).")
        os.makedirs(work, exist_ok=True)
        for item in ("record.json", "build.log"):
            d("cp", f"{name}:/work/{item}", os.path.join(work, item), capture=True)
    finally:
        d("rm", "-f", name, capture=True)
    _, record = load_json(os.path.join(work, "record.json"), "The container's record")
    return record


# ---------------------------------------------------------------------------- the result file

def cpu_name():
    try:
        if platform.system() == "Darwin":
            return subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True,
                                  text=True).stdout.strip() or platform.machine()
        with open("/proc/cpuinfo") as fh:
            for line in fh:
                if line.lower().startswith("model name"):
                    return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.machine() or "unknown"


def result_file(batch, records, agent_host):
    units = []
    lean = ""
    for unit in batch["units"]:
        r = records.get(unit["key"])
        if not r:
            continue
        lean = r["lean"]
        extra = {"spec": r["spec"], "commit": r["commit"], "mode": r["mode"], "axioms": r["axioms"],
                 "buildSeconds": r["buildSeconds"], "checkSeconds": r["checkSeconds"],
                 "fetchSeconds": r["fetchSeconds"], "checkSha256": r.get("checkSha256"),
                 "problems": r["problems"][:5]}
        while len(json.dumps(extra, separators=(",", ":")).encode()) > EXTRA_MAX_BYTES and extra["problems"]:
            extra["problems"].pop()
        units.append({
            "key": unit["key"], "outcome": r["outcome"],
            "seconds": round(r["buildSeconds"] + r["checkSeconds"], 1),
            "proof": {"sha256": r["outputSha256"], "bytes": r["outputBytes"]},
            "checks": [{"tool": "lake build", "result": "passed" if r["buildExit"] == 0 else "failed"},
                       {"tool": "#print axioms", "result": "permitted" if r["outcome"] == "PASS" else "not shown"}],
            "extra": extra,
        })
    env = {
        "os": platform.platform()[:120],
        "cpu": cpu_name()[:120],
        "tools": [
            {"name": "lean", "version": (lean or "unknown")[:60]},
            {"name": "elan", "version": ELAN_VERSION},
            {"name": KIT_NAME, "version": KIT_VERSION, "sourceSha256": "0x" + sha256_file(os.path.abspath(__file__))},
        ],
    }
    if agent_host:
        env["agentHost"] = agent_host
    return {"schema": RESULT_SCHEMA, "problem": batch["problem"], "list": batch["list"],
            "listSha256": batch["listSha256"], "batch": batch["batch"], "env": env, "units": units}


# ---------------------------------------------------------------------------- talking to Papex

class KitError(Exception):
    """An answer of Papex that is not a success (status), or no answer at all (status None)."""

    def __init__(self, status, text):
        super().__init__(text)
        self.status = status

    def why(self):
        return str(self).rstrip(".")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """A redirect is taken as an error, so the key never goes to another address."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Kit:
    """The kit routes of Papex for one batch. The key goes only into the Authorization header."""

    def __init__(self, api, key):
        self.api, self.key = api, key
        self.opener = urllib.request.build_opener(NoRedirect)

    def request(self, method, route, body=None, timeout=30.0):
        req = urllib.request.Request(self.api + "/api/shared-work/kit" + route, data=body, method=method)
        req.add_unredirected_header("Authorization", "Bearer " + self.key)
        req.add_header("User-Agent", f"{KIT_NAME}/{KIT_VERSION}")
        req.add_header("Accept", "application/json")
        if body is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with self.opener.open(req, timeout=timeout) as answer:
                return answer.read()
        except urllib.error.HTTPError as e:
            try:  # Papex answers an error with {"code": ..., "error": "what happened", ...}
                answer = json.loads(e.read().decode("utf-8", "replace"))
                text = answer.get("error") or answer.get("message")
            except (ValueError, AttributeError, OSError):
                text = None
            raise KitError(e.code, " ".join(str(text).split())[:300] if text else f"HTTP {e.code}") from None
        except (urllib.error.URLError, OSError, http.client.HTTPException, ValueError) as e:
            reason = str(getattr(e, "reason", None) or e) or type(e).__name__
            raise KitError(None, f"no answer: {reason}") from None

    def progress(self, done, quiet):
        """Tell Papex how many units are done. A report that fails never stops the run."""
        def send():
            try:
                self.request("POST", "/progress", json.dumps({"done": done}).encode(), 5.0)
            except KitError as e:
                if not quiet["said"]:
                    quiet["said"] = True
                    say(f"  Could not tell Papex how far the run is ({e.why()}). The run goes on.")
        thread = threading.Thread(target=send, daemon=True)
        thread.start()
        thread.join(6.0)


def api_address(url):
    parts = urllib.parse.urlsplit(url)
    if parts.scheme == "https" or (parts.scheme == "http" and parts.hostname in ("127.0.0.1", "localhost", "::1")):
        return url.rstrip("/")
    stop("--api takes an https address, for example https://api.papex.org (http only on this computer).")


def key_hash(key):
    return hashlib.sha256(key.encode()).hexdigest()


def batches_dir(work_root):
    return os.path.join(work_root, "batches")


def fetch_batch(kit, work_root):
    """GET the batch and keep it as the batch file in its folder; return that file's path."""
    try:
        body = kit.request("GET", "/batch")
    except KitError as e:
        if e.status == 401:
            stop(f"The key was not accepted ({e.why()}). Copy the command again from your run's page on "
                 "papex.org and run it.")
        if e.status == 409:
            stop(f"This run no longer takes a result ({e.why()}). Nothing was run.")
        if e.status is None:
            stop(f"Papex could not be reached ({e.why()}). Check the connection and run the same "
                 "command again.")
        stop(f"Papex did not say what to run ({e.why()}). Run the same command again later.")
    try:
        name = json.loads(body).get("batch")
    except (ValueError, AttributeError):
        name = None
    if not BATCH_RE.match(str(name)):
        stop("Papex did not send a batch file. Run the same command again later.")
    folder = os.path.join(batches_dir(work_root), name)
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"{name}.json")
    with open(path, "wb") as fh:
        fh.write(body)
    hashes = os.path.join(folder, KEY_HASHES)
    if not os.path.exists(hashes) or key_hash(kit.key) not in open(hashes).read().split():
        with open(hashes, "a") as fh:
            fh.write(key_hash(kit.key) + "\n")
    return path


def send_result(kit, path):
    with open(path, "rb") as fh:
        body = fh.read()
    try:
        answer = kit.request("PUT", "/result", body, 60.0)
    except (KitError, KeyboardInterrupt) as e:
        why = e.why() if isinstance(e, KitError) else "stopped"
        say(f"  It was not sent ({why}).")
        if getattr(e, "status", None) == 409:
            say("  This run no longer takes a result, on its page either.")
        else:
            say("  Upload it on your run's page on papex.org, choose how you are shown, and send it.")
        return False
    say("  Sent to Papex. Go back to your run's page, choose how you are shown, and press Send.")
    try:
        page = json.loads(answer).get("pagePath")
    except (ValueError, AttributeError):
        page = None
    if isinstance(page, str) and re.match(r"^/[\w/.-]{1,200}$", page):
        say(f"  {'https://papex.org' + page if kit.api == DEFAULT_API else page}")
    return True


# ---------------------------------------------------------------------------- the command line

def take(argv, name, default=None):
    if name in argv:
        i = argv.index(name)
        if i + 1 >= len(argv):
            stop(f"{name} needs a value.")
        value = argv[i + 1]
        del argv[i:i + 2]
        return value
    return default


def flag(argv, name):
    if name in argv:
        argv.remove(name)
        return True
    return False


def free_gb(path):
    probe = path
    while not os.path.exists(probe):
        probe = os.path.dirname(probe) or "."
    return shutil.disk_usage(probe).free / 1e9


def check(work_root):
    ok = True
    say(f"Python {platform.python_version()}: " + ("ok" if sys.version_info >= (3, 9) else "too old, 3.9 or later is needed"))
    ok &= sys.version_info >= (3, 9)
    git = shutil.which("git")
    say("git: " + ("ok" if git else "not found, install git"))
    ok &= bool(git)
    curl = shutil.which("curl")
    say("curl: " + ("ok" if curl else "not found, install curl"))
    ok &= bool(curl)
    try:
        say(f"Lean's installer for this computer: {elan_archive()}")
    except SystemExit as e:
        say(str(e))
        ok = False
    free = free_gb(work_root)
    say(f"Free disk where the work folder goes ({work_root}): {free:.0f} GB" + ("" if free >= 12 else ", a Lean proof that uses Mathlib needs about 12 GB"))
    ok &= free >= 12
    say("Docker (only for --docker): " + ("found" if shutil.which("docker") else "not found"))
    say("This computer can do a run." if ok else "This computer cannot do a run yet; see the lines above.")
    return 0 if ok else 1


def clean(work_root):
    size = 0
    for folder, _, files in os.walk(work_root):
        for name in files:
            try:
                size += os.path.getsize(os.path.join(folder, name))
            except OSError:
                pass
    shutil.rmtree(work_root, ignore_errors=True)
    say(f"Deleted {work_root} ({size / 1e9:.1f} GB).")
    docker = shutil.which("docker")
    if docker:
        names = subprocess.run([docker, "volume", "ls", "-q", "--filter", "name=papex-rerun-"],
                               capture_output=True, text=True).stdout.split()
        for name in names:
            subprocess.run([docker, "rm", "-f", name], capture_output=True)
            subprocess.run([docker, "volume", "rm", name], capture_output=True)
            say(f"Removed the container volume {name}.")
    return 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or "-h" in argv or "--help" in argv:
        say(__doc__.strip())
        return 0
    work_root = os.path.abspath(take(argv, "--work", os.path.join(HERE, "work")))

    phase = take(argv, "--phase")
    if phase:  # used by --docker inside the container
        spec_path = take(argv, "--spec")
        _, spec = load_json(spec_path, "The unit's file")
        check_spec(spec, spec_path)
        if phase == "fetch":
            seconds = fetch(spec, work_root)
            with open(os.path.join(work_root, "fetch-seconds"), "w") as fh:
                fh.write(str(round(seconds, 1)))
        elif phase == "build":
            record = build(spec, work_root)
            try:
                record["fetchSeconds"] = float(open(os.path.join(work_root, "fetch-seconds")).read())
            except (OSError, ValueError):
                record["fetchSeconds"] = 0.0
            with open(os.path.join(work_root, "record.json"), "w") as fh:
                json.dump(record, fh)
        else:
            stop("--phase is fetch or build.")
        return 0

    if flag(argv, "--check"):
        return check(work_root)
    if flag(argv, "--clean"):
        return clean(work_root)

    key = take(argv, "--key")
    api = api_address(take(argv, "--api", DEFAULT_API))
    use_docker = flag(argv, "--docker")
    agent_host = take(argv, "--agent-host")
    if agent_host and not AGENT_HOST_RE.match(agent_host):
        stop("--agent-host takes letters, digits, spaces and . _ - + ( ) / : only, 80 at most.")
    if len(argv) > 1 or (key and argv) or (not key and not argv) or any(a.startswith("-") for a in argv):
        stop("Give either --key KIT_KEY or one BATCH_FILE. See --help.")
    if sys.version_info < (3, 9):
        stop("This kit needs Python 3.9 or later.")

    kit = None
    if key:
        if not KEY_RE.match(key):
            stop("That is not a kit key. Copy the command again from your run's page on papex.org.")
        say("With the key the kit asks Papex what to run, says when it is done, and sends the result")
        say("file at the end. Nothing else leaves this computer.")
        say()
        kit = Kit(api, key)
        batch_path = fetch_batch(kit, work_root)
    else:
        batch_path = os.path.abspath(argv[0])
    _, batch = load_json(batch_path, "The batch file")
    if batch.get("schema") != BATCH_SCHEMA or not BATCH_RE.match(str(batch.get("batch"))) \
            or not isinstance(batch.get("units"), list) or not batch["units"]:
        stop("That is not a Papex batch file.")
    batch_key = batch["batch"]
    folder = os.path.join(batches_dir(work_root), batch_key)
    os.makedirs(folder, exist_ok=True)
    result_path = os.path.join(folder, f"{batch_key}.result.json")

    quiet = {"said": False}
    records = {}
    if kit:
        kit.progress(0, quiet)
    for number, unit in enumerate(batch["units"], 1):
        unit_key = str(unit.get("key"))
        spec_path, spec, digest = find_spec(batch, unit_key)
        work = os.path.join(work_root, "runs", unit_key)
        say(f"{spec.get('title', unit_key)}")
        say(f"  {spec['repo'][:-4]} at {spec['commit'][:12]}")
        need = float(spec.get("diskGb", 12))
        if not use_docker and not os.path.exists(os.path.join(work, "fetched.json")) and free_gb(work) < need:
            stop(f"This run needs about {need:.0f} GB of free disk and {free_gb(work):.0f} GB is free "
                 f"where the work folder goes ({work_root}). Free some, or name another folder with --work.")
        if use_docker:
            record = docker_run(spec_path, spec, work, "papex-rerun-" + re.sub(r"[^a-z0-9]+", "-", unit_key.lower()))
            record["mode"] = "docker"
        else:
            seconds = fetch(spec, work)
            record = build(spec, work)
            record["fetchSeconds"] = round(seconds, 1)
            record["mode"] = "native"
        record.update({"spec": digest, "commit": spec["commit"]})
        records[unit_key] = record
        if record["outcome"] == "PASS":
            say(f"  Passed in {minutes(record['buildSeconds'] + record['checkSeconds'])}.")
            for name, axioms in record["axioms"].items():
                say(f"  {name} rests on: {', '.join(axioms) if axioms else 'no axioms'}")
        else:
            say("  Did NOT pass: " + "; ".join(record["problems"]))
            say(f"  The log is {os.path.join(work, 'build.log')}")
        if kit:
            kit.progress(number, quiet)

    text = json.dumps(result_file(batch, records, agent_host), indent=1, ensure_ascii=False) + "\n"
    if len(text.encode()) > RESULT_MAX_BYTES:
        stop("The result file is larger than Papex takes. Tell Papex Labs: this is a fault of the kit.")
    with open(result_path, "w", encoding="utf-8") as fh:
        fh.write(text)
    say()
    say(f"Result file: {result_path}")
    if kit:
        send_result(kit, result_path)
    else:
        say("  Upload it on your run's page on papex.org, choose how you are shown, and send it.")
    say(f"The work folder holds Lean and Mathlib ({work_root}). Delete it with: python3 rerun.py --clean")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit("\nStopped. Run the same command again to go on.")
