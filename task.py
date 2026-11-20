#!/usr/bin/env python3
"""Try an open task from Papex: check an object you found, and write the result file of a run.

  python3 task.py list
  python3 task.py show TASK
  python3 task.py check TASK OBJECT.json
  python3 task.py result TASK OBJECT.json --batch BATCH_KEY --problem SLUG --list LIST_KEY [--agent-host NAME]

Each takes --api URL (default https://api.papex.org): where the current best known value is read.

A task asks for something new: an object better than the best known one ("Improve a bound") or an
object that refutes a statement ("Find a counterexample"). show prints a task's card: what to find,
the best known value and its source, the exact file format. A task is a folder in tasks/, or one of
Papex's open tasks of a family in families/: one checker that takes the task's parameters, so a new
task of a known family needs no new kit. list shows both.

check runs the checker on the object and says whether it passes and whether it is better than the
best known value. result does the same and, only when the object passes (and, to improve a bound, is
strictly better), writes the result file for a run taken through the Papex connection
(papex_take_shared_work). Nothing is sent: the AI app gives the file to the Papex connection
(papex_prepare_shared_work_batch), or you upload it on your run's page. Only you send it.

The checker runs in a separate Python process, in an empty folder of its own, with a time limit and
(where this computer allows it) a memory limit, on the object exactly as the result file carries it.
The best known value moves when a run is accepted: check and result read it from Papex when Papex
answers within a few seconds, and otherwise use the value in tasks/TASK/task.json. They say which.
list, show and check keep Papex's answer in work/cache/ for 5 minutes and say when they use that copy;
result always reads Papex anew.

Exit codes of check: 0 passes (and is better than the best known value); 2 passes but is not better;
3 does not pass; 1 the kit could not check.

Passing the checker shows what the task's card says it shows. It is not peer review.
Needs Python 3.9 or later. See tasks/README.md.
"""

import datetime
import decimal
import hashlib
import json
import os
import platform
import re
import signal
import subprocess
import sys
import tempfile
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
TASKS = os.path.join(HERE, "tasks")
FAMILIES = os.path.join(HERE, "families")
CACHE = os.path.join(HERE, "work", "cache", "open-lists.json")
CACHE_SECONDS = 300  # check, list and show use Papex's answer this long before reading it again; result never does
KIT_NAME = "papex-task-kit"
KIT_VERSION = "1"
TASK_SCHEMA = "papex-task/v1"
RESULT_SCHEMA = "papex-shared-work-result/v1"
DEFAULT_API = "https://api.papex.org"
SITE = "https://papex.org"
RESULT_MAX_BYTES = 262144
EXTRA_ALLOWANCE = 1024  # a unit's extra may hold the object and this much more (the contract)
MAX_OBJECT_BYTES = 100000
MAX_CHECKER_SECONDS = 120
MAX_DEPTH = 64  # brackets inside brackets
MAX_INT_DIGITS = 4300  # the longest whole number Python 3.11 and later read from text by default
OUTPUT_CAP = 65536  # what is read of a checker's output
MEMORY_BYTES = 1 << 30  # a checker's address space, where the system lets the kit limit it (Linux; not macOS)
LIVE_SECONDS = 4.0
LIVE_MAX_BYTES = 8 << 20
FIND_KIND = "find"

SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
BATCH_RE = re.compile(r"^b-[0-9a-f]{6,10}$")
AGENT_HOST_RE = re.compile(r"^[\w ._+()/:-]{1,80}$")
DECIMAL_RE = re.compile(r"^-?(0|[1-9][0-9]{0,17})(\.[0-9]{1,18})?$")  # no leading zero; see is_decimal
SHA256_RE = re.compile(r"^0x[0-9a-f]{64}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
LIST_KEY_RE = re.compile(r"^(?P<slug>[a-z0-9]+(?:-[a-z0-9]+)*)-r(?P<round>[1-9][0-9]{0,3})$")
FIELDS = {"mathematics", "computer-science", "physics", "cosmology", "astronomy", "biology", "neuroscience",
          "medicine", "chemistry", "earth-science"}
KIND_LABELS = {"record": "Improve a bound", "counterexample": "Find a counterexample"}
# Words a task's public texts never use (the contract's "Words on every surface"). Quotes from sources are not
# searched: they are other people's words.
NEVER_WORDS = re.compile(r"\b(verified|verifies|confirmed|proved|proven|records?|world[- ]records?|first|winners?|"
                         r"leaderboards?)\b", re.IGNORECASE)
PUBLIC_TEXTS = ("title", "shortTitle", "description", "objective", "scoreLabel", "searched", "objectFormat", "shows",
                "notCovered", "alsoBelongsAt", "effort", "resultLine", "requirements", "checkedHow")
TASK_KEYS = {"schema", "slug", "kind", "title", "shortTitle", "description", "objective", "direction", "scoreLabel",
             "bestKnown", "searched", "objectFormat", "objectKeys", "shows", "notCovered", "alsoBelongsAt", "effort",
             "limits", "scorePlaces",
             "resultLine", "requirements", "checkedHow", "expectedSeconds", "problem", "sources", "checkerSha256"}
BEST_KEYS = {"value", "by", "year", "sourceName", "sourceUrl", "asOf", "objectUrl", "quote", "note"}


def stop(message):
    raise SystemExit(printable(message))


def say(line=""):
    print(printable(line), flush=True)


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256_file(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def utf16_length(text):
    """Length as Papex's server counts it (Java strings: UTF-16 code units)."""
    return len(text.encode("utf-16-le")) // 2


def today():
    """Today's date in UTC (Papex's server takes a date at most a day ahead of it)."""
    return datetime.datetime.now(datetime.timezone.utc).date().isoformat()


def is_decimal(value):
    """A decimal as Papex takes it: written out, no leading zero, at most 18 digits on each side, never -0."""
    return isinstance(value, str) and bool(DECIMAL_RE.match(value)) and not (
        value.startswith("-") and decimal.Decimal(value) == 0)


def invisible(text):
    """The first control or format character in a text (a line break, a tab, a zero-width or bidi character), or
    None. Papex's server refuses them in a task's texts."""
    return next((c for c in text if unicodedata.category(c) in ("Cc", "Cf")), None)


# ---------------------------------------------------------------------------- texts from outside
#
# A text taken from a result file, an object, a params file, a checker's output or an answer of a server can hold
# anything: NUL, terminal escape sequences, bidi and zero-width characters, half a character. Before such a text is
# shown or sent anywhere it goes through printable() (a terminal line) or clean() (a text sent to Papex).

ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)?|\x1b[ -/]*[0-~]|\x9b[0-?]*[ -/]*[@-~]")
REPLACEMENT = "\ufffd"


def _shown(c):
    """c itself, or what is shown in its place."""
    if c in "\t\r\v\f":
        return " "
    category = unicodedata.category(c)
    if category[0] == "C" or category in ("Zl", "Zp"):  # control, format, surrogate, private use, unassigned
        return REPLACEMENT
    return c


def printable(text):
    """A text made safe for a terminal: escape sequences removed, every control, format (bidi, zero-width),
    surrogate, private-use or unassigned character replaced by U+FFFD; line breaks kept, tabs made spaces."""
    text = ANSI_RE.sub("", str(text))
    return "\n".join("".join(_shown(c) for c in line) for line in text.split("\n"))


def cut(text, limit):
    """text, cut to at most limit UTF-16 code units (how Papex's server counts) and never inside a character,
    ending in "…" when it was cut."""
    if utf16_length(text) <= limit:
        return text
    kept, used = [], 1  # room for the "…"
    for c in text:
        used += 2 if ord(c) > 0xFFFF else 1
        if used > limit:
            break
        kept.append(c)
    return "".join(kept).rstrip() + "…"


def clean(text, limit=None):
    """A text from outside, made one line safe to send to Papex: printable(), line breaks made spaces, runs of
    spaces made one; with limit, cut() to it."""
    text = re.sub(r"\s+", " ", printable(text).replace("\n", " ")).strip()
    return text if limit is None else cut(text, limit)


def quoted(text, limit=40):
    """A text from outside (a key of an object, say) quoted as JSON writes it with every character outside ASCII
    escaped: "a\\u0000b". Safe to show and to send; at most limit characters of the text are kept."""
    text = str(text)
    return json.dumps(text[:limit]) + ("…" if len(text) > limit else "")


# ---------------------------------------------------------------------------- a task's folder

class TaskError(Exception):
    """A task folder this kit cannot use."""


def task_folder(slug):
    return os.path.join(TASKS, slug)


def all_tasks(root=None):
    """The slugs of the task folders under root (default tasks/), in order."""
    root = root or TASKS
    try:
        names = sorted(os.listdir(root))
    except OSError:
        return []
    return [n for n in names if SLUG_RE.match(n) and os.path.isfile(os.path.join(root, n, "task.json"))]


def checker_sha256(folder):
    return "0x" + sha256_file(os.path.join(folder, "checker.py"))


def _text(task, key, limit, problems, required=True, where=""):
    value = task.get(key)
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            problems.append(f"{where}{key} is missing")
        return
    if not isinstance(value, str):
        problems.append(f"{where}{key} must be a text")
    elif utf16_length(value.strip()) > limit:
        problems.append(f"{where}{key} is {utf16_length(value.strip())} characters; at most {limit}")
    elif invisible(value.strip()):
        problems.append(f"{where}{key} holds the invisible character U+{ord(invisible(value.strip())):04X}")


def _date(value):
    if not isinstance(value, str) or not DATE_RE.match(value):
        return False
    try:
        datetime.date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _https(value):
    """An https address as Papex's server takes it: a host, no user part, no space, control character, quote,
    backtick or angle bracket."""
    if not isinstance(value, str) or not value.startswith("https://") or len(value) > 2000 \
            or any(c.isspace() or ord(c) < 32 or ord(c) == 127 or c in "\"'`<>" for c in value):
        return False
    try:
        parts = urllib.parse.urlsplit(value)
    except ValueError:
        return False
    return bool(parts.hostname) and "@" not in parts.netloc


def task_problems(task, folder=None):
    """Every way task.json falls short of the format in tasks/README.md (empty: none)."""
    problems = []
    if not isinstance(task, dict):
        return ["task.json must hold one JSON object"]
    for key in sorted(set(task) - TASK_KEYS):
        problems.append(f"{key} is not a field of task.json")
    if task.get("schema") != TASK_SCHEMA:
        problems.append(f"schema must be {TASK_SCHEMA}")
    slug = task.get("slug")
    if not isinstance(slug, str) or not SLUG_RE.match(slug) or len(slug) > 34:
        problems.append("slug must be lowercase letters, digits and single hyphens, at most 34 characters")
    elif folder and os.path.basename(os.path.normpath(folder)) != slug:
        problems.append(f"slug {slug} is not the folder's name")
    kind = task.get("kind")
    if kind not in KIND_LABELS:
        problems.append("kind must be record or counterexample")
    for key, limit in (("title", 200), ("shortTitle", 80), ("description", 300), ("objective", 600),
                       ("objectFormat", 600), ("shows", 400), ("notCovered", 400), ("resultLine", 400),
                       ("requirements", 600), ("checkedHow", 600)):
        _text(task, key, limit, problems)
    for key, limit in (("scoreLabel", 40), ("searched", 400), ("alsoBelongsAt", 300), ("effort", 200)):
        _text(task, key, limit, problems, required=False)
    if isinstance(task.get("resultLine"), str) and not task["resultLine"].strip().startswith("Result: "):
        problems.append("resultLine must start with \"Result: \"")
    direction, best = task.get("direction"), task.get("bestKnown")
    if kind == "record":
        if direction not in ("max", "min"):
            problems.append("direction must be max or min for a record task")
        if not isinstance(best, dict):
            problems.append("bestKnown is missing (a record task names its best known value)")
        else:
            for key in sorted(set(best) - BEST_KEYS):
                problems.append(f"bestKnown.{key} is not a field of bestKnown")
            if not is_decimal(best.get("value")):
                problems.append("bestKnown.value must be a decimal written as a text, such as \"164\" or \"1.119\" "
                                "(no leading zero, never -0)")
            _text(best, "by", 200, problems, where="bestKnown.")
            _text(best, "sourceName", 120, problems, where="bestKnown.")
            _text(best, "quote", 2000, problems, where="bestKnown.")
            _text(best, "note", 600, problems, required=False, where="bestKnown.")
            year = best.get("year")
            if year is not None and (not isinstance(year, int) or isinstance(year, bool) or not 1000 <= year <= 9999):
                problems.append("bestKnown.year must be a year such as 2025, or null")
            if not _https(best.get("sourceUrl")):
                problems.append("bestKnown.sourceUrl must be an https address")
            if best.get("objectUrl") is not None and not _https(best.get("objectUrl")):
                problems.append("bestKnown.objectUrl must be an https address, or absent")
            if not _date(best.get("asOf")):
                problems.append("bestKnown.asOf must be a date such as 2026-11-20")
    elif kind == "counterexample":
        if direction is not None:
            problems.append("direction must be null for a counterexample task")
        if best is not None:
            problems.append("bestKnown must be null for a counterexample task")
    keys = task.get("objectKeys")
    if not isinstance(keys, list) or not 1 <= len(keys) <= 20 or len(set(map(str, keys))) != len(keys) \
            or not all(isinstance(k, str) and 0 < len(k) <= 40 for k in keys):
        problems.append("objectKeys must list the object's keys, the only ones it may hold (1 to 20 names)")
    places = task.get("scorePlaces")
    if places is not None and (not isinstance(places, int) or isinstance(places, bool) or not 0 <= places <= 18):
        problems.append("scorePlaces must be the most decimals a score has, 0 to 18, or absent")
    limits = task.get("limits")
    if not isinstance(limits, dict) or set(limits) != {"maxObjectBytes", "checkerSeconds"}:
        problems.append("limits must hold maxObjectBytes and checkerSeconds")
    else:
        for key, high in (("maxObjectBytes", MAX_OBJECT_BYTES), ("checkerSeconds", MAX_CHECKER_SECONDS)):
            value = limits[key]
            if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= high:
                problems.append(f"limits.{key} must be a whole number from 1 to {high}")
    seconds = task.get("expectedSeconds")
    if not isinstance(seconds, int) or isinstance(seconds, bool) or not 1 <= seconds <= 604800:
        problems.append("expectedSeconds must be a whole number from 1 to 604800")
    problems += _problem_block(task.get("problem"))
    sources = task.get("sources")
    if not isinstance(sources, list) or not sources:
        problems.append("sources must list every quote used (fact, url, quote, fetchedOn)")
    else:
        for i, source in enumerate(sources):
            if not isinstance(source, dict) or set(source) - {"fact", "url", "quote", "fetchedOn", "note"}:
                problems.append(f"sources[{i}] must hold fact, url, quote, fetchedOn and an optional note")
                continue
            for key in ("fact", "quote"):
                if not isinstance(source.get(key), str) or not source[key].strip():
                    problems.append(f"sources[{i}].{key} is missing")
            if not _https(source.get("url")):
                problems.append(f"sources[{i}].url must be an https address")
            if not _date(source.get("fetchedOn")):
                problems.append(f"sources[{i}].fetchedOn must be a date")
    sha = task.get("checkerSha256")
    if not isinstance(sha, str) or not SHA256_RE.match(sha):
        problems.append("checkerSha256 must be 0x and 64 lowercase hex digits")
    elif folder and os.path.isfile(os.path.join(folder, "checker.py")) and sha != checker_sha256(folder):
        problems.append("checkerSha256 is not the SHA-256 of checker.py")
    for key in PUBLIC_TEXTS:
        value = task.get(key)
        if isinstance(value, str):
            for m in NEVER_WORDS.finditer(value):
                problems.append(f"{key} uses the word \"{m.group()}\", which Papex never uses")
    for key in sorted(TASK_KEYS):
        if isinstance(task.get(key), str) and "TODO" in task[key]:
            problems.append(f"{key} still holds TODO")
    return problems


def _problem_block(block):
    problems = []
    if not isinstance(block, dict) or set(block) != {"slug", "create"}:
        return ["problem must hold slug and create (null when the problem page exists)"]
    slug = block.get("slug")
    if not isinstance(slug, str) or not SLUG_RE.match(slug) or len(slug) > 120 or slug == "claims":
        problems.append("problem.slug must be a problem's slug")
    create = block.get("create")
    if create is None:
        return problems
    if not isinstance(create, dict):
        return problems + ["problem.create must be the body of POST /api/admin/problems, or null"]
    allowed = {"slug", "title", "question", "summary", "field", "sinceYear", "prize", "initialStatus"}
    for key in sorted(set(create) - allowed):
        problems.append(f"problem.create.{key} is not a field of a new problem")
    if create.get("slug") != slug:
        problems.append("problem.create.slug must be problem.slug")
    for key, limit in (("title", 200), ("question", 500), ("summary", 2000)):
        _text(create, key, limit, problems, where="problem.create.")
    if create.get("field") not in FIELDS:
        problems.append("problem.create.field must be one of Papex's fields (mathematics, computer-science, …)")
    since = create.get("sinceYear")
    if since is not None and (not isinstance(since, int) or isinstance(since, bool) or not -3000 <= since <= 2100):
        problems.append("problem.create.sinceYear must be a year or null")
    if create.get("prize") is not None:
        problems.append("problem.create.prize: a task's problem names no prize here (null)")
    status = create.get("initialStatus")
    if not isinstance(status, dict):
        return problems + ["problem.create.initialStatus is missing"]
    if status.get("status") != "OPEN":
        problems.append("problem.create.initialStatus.status must be OPEN (a task's new problem page starts open)")
    source = status.get("source")
    if not isinstance(source, dict) or set(source) != {"name", "list", "url"}:
        problems.append("problem.create.initialStatus.source must hold name, list and url")
    else:
        _text(source, "name", 200, problems, where="problem.create.initialStatus.source.")
        _text(source, "list", 200, problems, where="problem.create.initialStatus.source.")
        if not _https(source.get("url")):
            problems.append("problem.create.initialStatus.source.url must be an https address")
    if status.get("sourceDate") is not None and not _date(status.get("sourceDate")):
        problems.append("problem.create.initialStatus.sourceDate must be a date or null")
    if not _date(status.get("checkedOn")):
        problems.append("problem.create.initialStatus.checkedOn must be a date")
    return problems


def read_task_file(folder):
    path = os.path.join(folder, "task.json")
    try:
        with open(path, "rb") as fh:
            return json.loads(fh.read().decode("utf-8"), object_pairs_hook=_pairs)
    except (OSError, ValueError, ObjectError) as e:
        raise TaskError(f"{os.path.relpath(path)} could not be read ({e})")


def load_task(slug, root=None):
    """task.json of tasks/<slug>/, checked; TaskError when it is missing or falls short."""
    if not isinstance(slug, str) or not SLUG_RE.match(slug):
        raise TaskError("That is not a task's name (such as isosceles-free-grid-100). See: python3 task.py list")
    folder = os.path.join(root or TASKS, slug)
    if not os.path.isfile(os.path.join(folder, "task.json")):
        raise TaskError(f"This kit has no task {slug}. Get the newest kit (git pull), or see: python3 task.py list")
    task = read_task_file(folder)
    problems = task_problems(task, folder)
    if problems:
        raise TaskError(f"tasks/{slug}/task.json is not usable: {problems[0]}. Get the newest kit (git pull).")
    return task


def manifest_text(task):
    """The list's one manifest line: the unit is the task, its input the checker."""
    line = {"key": task["slug"], "kind": FIND_KIND, "expectedSeconds": task["expectedSeconds"],
            "inputSha256": task["checkerSha256"]}
    return json.dumps(line, separators=(",", ":")) + "\n"


def howto_task(task, round_=1, best=None, previous=None):
    """howTo.task as the contract has it, for one round. best: the bestKnown of that round (default: task.json's)."""
    best = best if best is not None else task.get("bestKnown")
    if best is not None:
        best = {k: best.get(k) for k in ("value", "by", "year", "sourceName", "sourceUrl", "asOf", "objectUrl")
                if k != "objectUrl" or best.get(k)}
    return {
        "slug": task["slug"], "kind": task["kind"], "objective": task["objective"].strip(),
        "direction": task.get("direction"), "scoreLabel": _blank(task.get("scoreLabel")), "bestKnown": best,
        "searched": _blank(task.get("searched")), "objectFormat": task["objectFormat"].strip(),
        "shows": task["shows"].strip(), "notCovered": task["notCovered"].strip(),
        "alsoBelongsAt": _blank(task.get("alsoBelongsAt")), "effort": _blank(task.get("effort")),
        "maxObjectBytes": task["limits"]["maxObjectBytes"], "checkerSeconds": task["limits"]["checkerSeconds"],
        "checkerSha256": task["checkerSha256"], "round": round_, "previousListKey": previous}


def _blank(value):
    return value.strip() if isinstance(value, str) and value.strip() else None


def value_text(value, task):
    label = task.get("scoreLabel")
    return f"{value} {label}" if label else str(value)


# ---------------------------------------------------------------------------- an object

class ObjectError(Exception):
    """An object file the kit does not take, and why (in plain words)."""


def _pairs(pairs):
    seen = {}
    for key, value in pairs:
        if key in seen:
            raise ObjectError(f"the key {quoted(key)} appears twice in one object")
        seen[key] = value
    return seen


def _constant(name):
    raise ObjectError(f"{name} is not a number JSON allows")


def _int(text):
    if len(text.lstrip("-")) > MAX_INT_DIGITS:
        raise ObjectError(f"a whole number has more than {MAX_INT_DIGITS} digits")
    return int(text)


def _float(text):
    value = float(text)
    if value != value or value in (float("inf"), float("-inf")):
        raise ObjectError(f"the number {text[:40]} is too large to carry")
    return value


STRING_RE = re.compile(r'"(?:[^"\\]|\\.)*"', re.DOTALL)


def nesting(text):
    """How deep brackets go inside brackets, strings left out."""
    depth = deepest = 0
    for m in re.finditer(r"[\[\]{}]", STRING_RE.sub('""', text)):
        if m.group() in "[{":
            depth += 1
            deepest = max(deepest, depth)
        else:
            depth -= 1
    return deepest


def canonical_bytes(obj):
    """The object's canonical bytes: what is hashed, measured and given to the checker (the contract)."""
    try:
        json.dumps(obj, ensure_ascii=False).encode("utf-8")
    except UnicodeEncodeError:
        raise ObjectError("a text holds half of a character (an unpaired surrogate)")
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii")


def read_object(raw, max_bytes):
    """(object, canonical bytes) of an object file's bytes, or ObjectError saying why not."""
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise ObjectError("it is not UTF-8 text")
    depth = nesting(text)
    if depth > MAX_DEPTH:
        raise ObjectError(f"its brackets go {depth} deep; at most {MAX_DEPTH}")
    try:
        obj = json.loads(text, object_pairs_hook=_pairs, parse_constant=_constant, parse_int=_int,
                         parse_float=_float)
    except ObjectError:
        raise
    except (ValueError, RecursionError) as e:
        raise ObjectError(f"it is not JSON ({str(e)[:120]})")
    try:
        data = canonical_bytes(obj)
    except (ValueError, RecursionError) as e:
        raise ObjectError(f"it cannot be written as JSON again ({str(e)[:120]})")
    if len(data) > max_bytes:
        raise ObjectError(f"it is {len(data):,} bytes as the result file carries it; this task takes at most "
                          f"{max_bytes:,}")
    return obj, data


def object_keys_problem(obj, task):
    """Why the object's keys are not exactly the task's objectKeys (None: they are). An accepted object is shown
    publicly, so it holds nothing the format does not name; the checker rejects other keys too."""
    keys = task["objectKeys"]
    if not isinstance(obj, dict):
        return "it is not a JSON object {" + ", ".join(f'"{k}": …' for k in keys) + "}"
    unknown = sorted(set(obj) - set(keys))
    if unknown:
        return f"it holds the key {quoted(unknown[0])}, which the task's format does not name (only " \
               + ", ".join(keys) + ")"
    missing = [k for k in keys if k not in obj]
    if missing:
        return f"it has no key \"{missing[0]}\""
    return None


def same_numbers(raw, data):
    """True when the canonical bytes hold the same numbers as the file (a JSON number with more digits than
    a double keeps is carried rounded)."""
    def exact(text):
        return json.loads(text, parse_float=decimal.Decimal, parse_int=decimal.Decimal)
    try:
        return exact(raw.decode("utf-8")) == exact(data.decode("ascii"))
    except (ValueError, RecursionError, decimal.InvalidOperation):
        return True


# ---------------------------------------------------------------------------- the checker

class Run:
    """One run of a checker: status passed, failed (the object does not pass) or fault (no clean answer). reason is
    the checker's reason made one clean line (clean()), to show or send; said is the reason exactly as given, to
    compare; output is what the checker printed, as it printed it."""

    def __init__(self, status, score=None, reason="", seconds=0.0, output=b""):
        self.status, self.score, self.seconds, self.output = status, score, seconds, output
        self.said, self.reason = reason, clean(reason, 1000)

    @property
    def passed(self):
        return self.status == "passed"

    def __repr__(self):
        return f"Run({self.status}, score={self.score!r}, reason={self.reason[:80]!r}, {self.seconds:.2f} s)"


class _Number(str):
    """A JSON number exactly as the checker printed it."""


# Started in place of the checker: limits this process (CPU seconds, address space, no file writes, no core
# file, few open files, no new processes), then becomes the checker with exec. No code runs in the forked
# child before exec, so this is safe in a program with threads (the hosted runner).
LAUNCHER = """import os, sys
try:
    import resource
except ImportError:
    resource = None
names = ("RLIMIT_CPU", "RLIMIT_AS", "RLIMIT_FSIZE", "RLIMIT_CORE", "RLIMIT_NOFILE", "RLIMIT_NPROC")
for name, value in zip(names, map(int, sys.argv[1].split(","))) if resource else ():
    which = getattr(resource, name, None)
    if which is None:
        continue
    try:
        soft, hard = resource.getrlimit(which)
        value = value if hard == resource.RLIM_INFINITY else min(value, hard)
        resource.setrlimit(which, (value, value))
    except (ValueError, OSError):
        pass
os.execv(sys.executable, [sys.executable, "-I", "-S", "-B"] + sys.argv[2:])
"""


def _kill(proc):
    try:
        if os.name == "posix":
            os.killpg(proc.pid, signal.SIGKILL)
        else:
            proc.kill()
    except (OSError, ProcessLookupError):
        pass


def _collect(proc, deadline, cap):
    """The child's stdout and stderr (at most cap bytes each) and why it was stopped: None, "time" or "output"."""
    if os.name != "posix":
        try:
            out, err = proc.communicate(timeout=max(0.1, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            _kill(proc)
            out, err = proc.communicate()
            return out[:cap], err[:cap], "time"
        return out[:cap], err[:cap], "output" if len(out) > cap else None
    import selectors
    buffers = {proc.stdout: bytearray(), proc.stderr: bytearray()}
    why = None
    with selectors.DefaultSelector() as sel:
        for stream in buffers:
            sel.register(stream, selectors.EVENT_READ)
        while sel.get_map() and why is None:
            left = deadline - time.monotonic()
            if left <= 0:
                why = "time"
                break
            for key, _ in sel.select(min(left, 1.0)):
                chunk = os.read(key.fd, 65536)
                if not chunk:
                    sel.unregister(key.fileobj)
                    continue
                buffers[key.fileobj] += chunk
                if len(buffers[key.fileobj]) > cap:
                    why = "output"
                    break
    if why is None:
        try:
            proc.wait(timeout=max(0.05, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            why = "time"
    if why is not None:
        _kill(proc)
    proc.wait()
    for stream in buffers:
        stream.close()
    return bytes(buffers[proc.stdout][:cap]), bytes(buffers[proc.stderr][:cap]), why


def run_checker(checker, data, seconds, kind, args=(), python=None, memory=MEMORY_BYTES, params=None, sha256=None):
    """Run `python3 -I -S -B checker [args] object.json [params.json]` on the canonical bytes `data` (and, for a
    family's checker, the task's params, written as canonical bytes too), in an empty folder of its own, with a
    minimal environment, stdin closed, `seconds` of wall-clock time and (where the system allows) CPU, memory,
    file-write and process limits. The checker's file is read once and run from a private copy of those bytes;
    with sha256 ("0x…"), only when they are that version. Never raises for anything the object or the checker
    does."""
    python = python or sys.executable
    try:
        with open(checker, "rb") as fh:
            code = fh.read()
    except OSError as e:
        return Run("fault", reason=f"its file could not be read ({e.strerror or e})")
    if sha256 is not None and "0x" + sha256_bytes(code) != sha256:
        return Run("fault", reason=f"{os.path.basename(checker)} is not the version the task names (its SHA-256 "
                                   "differs); get the kit's own file again (git pull)")
    work = tempfile.mkdtemp(prefix="papex-task-")
    try:
        cwd = os.path.join(work, "empty")
        os.mkdir(cwd, 0o700)
        script = os.path.join(work, "checker.py")  # the bytes read above, which nothing else can change
        with open(script, "wb") as fh:
            fh.write(code)
        path = os.path.join(work, "object.json")
        with open(path, "wb") as fh:
            fh.write(data)
        target = [script, *args, path]
        if params is not None:
            target.append(os.path.join(work, "params.json"))
            with open(target[-1], "wb") as fh:
                fh.write(params if isinstance(params, bytes) else canonical_bytes(params))
        if os.name == "posix":
            limits = ",".join(str(v) for v in (int(seconds) + 1, memory, 0, 0, 64, 0))
            cmd = [python, "-I", "-S", "-B", "-c", LAUNCHER, limits, *target]
        else:
            cmd = [python, "-I", "-S", "-B", *target]
        env = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}
        if os.name != "posix":
            env["SYSTEMROOT"] = os.environ.get("SYSTEMROOT", "")
        start = time.monotonic()
        try:
            proc = subprocess.Popen(cmd, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, close_fds=True, start_new_session=os.name == "posix")
        except OSError as e:
            return Run("fault", reason=f"it could not be started ({e})")
        out, err, why = _collect(proc, start + seconds, OUTPUT_CAP)
        took = time.monotonic() - start
    finally:
        _remove_tree(work)
    if why == "time":
        return Run("fault", reason=f"it did not finish within {seconds} s", seconds=took, output=out)
    if why == "output":
        return Run("fault", reason=f"it printed more than {OUTPUT_CAP // 1024} KB", seconds=took, output=out)
    if proc.returncode != 0:
        last = [line for line in err.decode("utf-8", "replace").splitlines() if line.strip()][-1:]
        if proc.returncode < 0:
            what = {getattr(signal, "SIGXCPU", None): "it used up its CPU time",
                    signal.SIGKILL: "it was stopped (out of memory or time)"}.get(-proc.returncode,
                                                                                 f"signal {-proc.returncode}")
        else:
            what = f"it stopped with exit code {proc.returncode}"
        return Run("fault", reason=what + (f": {last[0].strip()[:200]}" if last else ""), seconds=took, output=out)
    answer, why = read_answer(out)
    if answer is None:
        return Run("fault", reason=why, seconds=took, output=out)
    if not answer["valid"]:
        return Run("failed", reason=answer["reason"], seconds=took, output=out)
    score = None if kind == "counterexample" else answer["score"]
    if kind == "record" and score is None:
        return Run("fault", reason="it said the object passes but gave no score", seconds=took, output=out)
    return Run("passed", score=score, reason=answer["reason"], seconds=took, output=out)


def _remove_tree(path):
    """Removes the run's own temporary folder (made by mkdtemp above; nothing else)."""
    for base, dirs, files in os.walk(path, topdown=False):
        for name in files:
            try:
                os.unlink(os.path.join(base, name))
            except OSError:
                pass
        for name in dirs:
            try:
                os.rmdir(os.path.join(base, name))
            except OSError:
                pass
    try:
        os.rmdir(path)
    except OSError:
        pass


def read_answer(out):
    """The checker's one line as {valid, score (decimal text or None), reason}, or (None, why)."""
    try:
        text = out.decode("utf-8")
    except UnicodeDecodeError:
        return None, "its output is not UTF-8 text"
    lines = [line for line in text.split("\n") if line.strip()]
    if len(lines) != 1:
        return None, f"it printed {len(lines)} lines instead of one"
    try:
        answer = json.loads(lines[0], object_pairs_hook=_pairs, parse_int=_Number, parse_float=_Number,
                            parse_constant=_constant)
    except (ValueError, RecursionError, ObjectError):
        return None, "its line is not JSON"
    if not isinstance(answer, dict) or set(answer) != {"valid", "score", "reason"}:
        return None, "its line is not {\"valid\", \"score\", \"reason\"}"
    if not isinstance(answer["valid"], bool) or not isinstance(answer["reason"], str) \
            or isinstance(answer["reason"], _Number):
        return None, "its line does not say valid true or false, with a reason"
    score = answer["score"]
    if score is not None and not (isinstance(score, _Number) and is_decimal(str(score))):
        return None, "its score is not a plain decimal number (such as 164 or 1.119047568469)"
    return {"valid": answer["valid"], "score": None if score is None else str(score),
            "reason": answer["reason"]}, None


def smallest_better(task, best):
    """The smallest score that counts as better than best, as text, when the task says how many decimals a score
    has (scorePlaces); else None."""
    places = task.get("scorePlaces")
    if not isinstance(places, int) or not is_decimal(best):
        return None
    step = decimal.Decimal(1).scaleb(-places)
    value = decimal.Decimal(best) + (step if task.get("direction") == "max" else -step)
    return f"{value:.{places}f}"


def better(score, best, direction):
    """True when score is strictly better than best (decimal texts) in the task's direction."""
    s, b = decimal.Decimal(score), decimal.Decimal(best)
    return s > b if direction == "max" else s < b


# ---------------------------------------------------------------------------- the best known value on Papex

LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1")


def api_problem(url):
    """None when url is an address Papex's API may have: https with a host and no user part (http only on this
    computer); else why not."""
    try:
        parts = urllib.parse.urlsplit(str(url))
        host = parts.hostname
    except ValueError:
        return "it is not an address"
    if "@" in parts.netloc or not host or parts.query or parts.fragment:
        return "it is not an address of the form https://api.papex.org"
    if parts.scheme == "https" or (parts.scheme == "http" and host in LOCAL_HOSTS):
        return None
    return "it is not https (http only on this computer)"


def api_address(url):
    if api_problem(url) is None:
        return url.rstrip("/")
    stop("--api takes an https address, for example https://api.papex.org (http only on this computer).")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Follows no redirect: the 3xx answer itself is the answer (an HTTPError)."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_URLOPEN = urllib.request.urlopen
_NO_REDIRECT = urllib.request.build_opener(_NoRedirect)


def open_url(request, timeout):
    """urlopen for Papex's API that follows no redirect: a 3xx answer is an HTTPError, and nothing is sent to the
    address it names. (A stand-in for urllib.request.urlopen put in place by the tests is used as it is.)"""
    if urllib.request.urlopen is not _URLOPEN:
        return urllib.request.urlopen(request, timeout=timeout)
    return _NO_REDIRECT.open(request, timeout=timeout)


def read_json_url(url, timeout, cap=LIVE_MAX_BYTES):
    """GET url as JSON, following no redirect; (answer, None) or (None, why). Never raises."""
    req = urllib.request.Request(url, headers={"User-Agent": f"{KIT_NAME}/{KIT_VERSION}",
                                               "Accept": "application/json"})
    try:
        with open_url(req, timeout) as answer:
            body = answer.read(cap + 1)
    except urllib.error.HTTPError as e:
        return None, f"it answered {e.code}" + (" (a redirect, which the kit does not follow)"
                                                 if 300 <= e.code < 400 else "")
    except Exception as e:  # noqa: BLE001 - a failed read only means the kit uses its own value
        why = re.sub(r"^\[Errno -?\d+\] ", "", str(getattr(e, "reason", None) or e)).strip()
        return None, clean(why[:120] or type(e).__name__).lower()
    if len(body) > cap:
        return None, "its answer was too large"
    try:
        return json.loads(body.decode("utf-8")), None
    except (ValueError, RecursionError):
        return None, "its answer was not JSON"


def live_rounds(api, slug, timeout=LIVE_SECONDS):
    """The open rounds of a task on Papex, newest first, as [{listKey, problemSlug, round, bestKnown,
    checkerSha256}], or (None, why) when Papex could not be read. A best-effort read: never raises."""
    answer, why = read_json_url(api + "/api/shared-work/lists", timeout)
    if answer is None:
        return None, why
    return rounds_in(answer, slug)


def rounds_in(answer, slug):
    """live_rounds() on the answer of GET /api/shared-work/lists."""
    items = answer.get("lists") if isinstance(answer, dict) else None
    if not isinstance(items, list):
        return None, "its answer had no lists"
    found = []
    for item in items:
        task = item.get("task") if isinstance(item, dict) else None
        if not isinstance(task, dict) or task.get("slug") != slug:
            continue
        best = task.get("bestKnown")
        if best is not None and not (isinstance(best, dict) and is_decimal(best.get("value"))):
            continue
        rnd = task.get("round")
        found.append({"listKey": str(item.get("key")), "problemSlug": str(item.get("problemSlug")),
                      "round": rnd if isinstance(rnd, int) else 0, "bestKnown": best,
                      "checkerSha256": task.get("checkerSha256")})
    found.sort(key=lambda r: -r["round"])
    return found, None


def _read_cache(api):
    """(answer, age in seconds) of the last answer of GET /api/shared-work/lists from this api, or None."""
    try:
        with open(CACHE, encoding="utf-8") as fh:
            kept = json.load(fh)
        age = time.time() - float(kept["at"])
        if kept.get("api") == api and age >= 0 and isinstance(kept.get("answer"), dict):
            return kept["answer"], age
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


def _write_cache(api, answer):
    try:
        os.makedirs(os.path.dirname(CACHE), exist_ok=True)
        part = CACHE + ".part"
        with open(part, "w", encoding="utf-8") as fh:
            json.dump({"api": api, "at": time.time(), "answer": answer}, fh)
        os.replace(part, CACHE)
    except OSError:
        pass


def age_text(seconds):
    seconds = int(seconds)
    if seconds < 120:
        return f"{seconds} s"
    if seconds < 7200:
        return f"{seconds // 60} min"
    return f"{seconds // 3600} h" if seconds < 172800 else f"{seconds // 86400} days"


def open_lists(api, fresh=False):
    """Papex's open lists (GET /api/shared-work/lists) as (answer, copy, why). A copy of the last answer, kept in
    work/cache/ for CACHE_SECONDS, is used instead of a new read unless fresh; copy then says how old it is. why says
    why Papex could not be read; the answer is then an older copy (not when fresh) or None. Never raises."""
    kept = _read_cache(api)
    if kept and not fresh and kept[1] <= CACHE_SECONDS:
        return kept[0], f"a copy read {age_text(kept[1])} ago", None
    answer, why = read_json_url(api + "/api/shared-work/lists", LIVE_SECONDS)
    if isinstance(answer, dict) and isinstance(answer.get("lists"), list):
        _write_cache(api, answer)
        return answer, None, None
    why = why or "its answer had no lists"
    if kept and not fresh:
        return kept[0], f"a copy read {age_text(kept[1])} ago", why
    return None, None, why


# ---------------------------------------------------------------------------- a family's task, read from Papex
#
# A family is one reviewed checker that takes parameters (families/<family>/checker.py, run as
# `python3 checker.py <object.json> <params.json>`). A card of a family is data only: Papex's open list carries the
# task, its params and the checker's SHA-256, and the kit runs its own copy of that checker when the SHA-256 agrees.

def family_checker(family, root=None):
    return os.path.join(root or FAMILIES, family, "checker.py")


def remote_problems(t):
    """Why a task read from Papex (howTo.task of a family's list) is not one the kit can use (empty: none)."""
    if not isinstance(t, dict):
        return ["no task"]
    problems = []
    if not isinstance(t.get("slug"), str) or not SLUG_RE.match(t["slug"]) or len(t["slug"]) > 34:
        problems.append("slug")
    if t.get("kind") not in KIND_LABELS:
        problems.append("kind")
    if t.get("kind") == "record" and (t.get("direction") not in ("max", "min") or not isinstance(t.get("bestKnown"), dict)
                                      or not is_decimal(t["bestKnown"].get("value"))):
        problems.append("direction or bestKnown")
    family = t.get("family")
    if not isinstance(family, str) or not SLUG_RE.match(family) or len(family) > 40:
        problems.append("family")
    params = t.get("params", {})
    if not isinstance(params, dict) or len(json.dumps(params)) > 1024 or not all(
            isinstance(k, str) and (isinstance(v, (str, bool)) or (isinstance(v, int))) for k, v in params.items()):
        problems.append("params")
    for key, high in (("maxObjectBytes", MAX_OBJECT_BYTES), ("checkerSeconds", MAX_CHECKER_SECONDS)):
        if not isinstance(t.get(key), int) or isinstance(t.get(key), bool) or not 1 <= t[key] <= high:
            problems.append(key)
    if not isinstance(t.get("checkerSha256"), str) or not SHA256_RE.match(t["checkerSha256"]):
        problems.append("checkerSha256")
    for key in ("objective", "objectFormat", "shows", "notCovered", "scoreLabel", "effort", "searched", "alsoBelongsAt"):
        if t.get(key) is not None and not isinstance(t[key], str):
            problems.append(key)
    return problems


def remote_task(item):
    """The task of one of Papex's open lists (a family's card) as task.py uses a task; TaskError if unusable."""
    t = item.get("task") if isinstance(item, dict) else None
    problems = remote_problems(t)
    if problems:
        raise TaskError(f"Papex's task is not one this kit can read ({', '.join(problems)}). Get the newest kit "
                        "(git pull).")
    text = (lambda key: t[key].strip() if isinstance(t.get(key), str) and t[key].strip() else None)
    return {"source": "papex", "slug": t["slug"], "kind": t["kind"],
            "title": item.get("title") if isinstance(item.get("title"), str) else t["slug"],
            "objective": text("objective"), "direction": t.get("direction"), "scoreLabel": text("scoreLabel"),
            "bestKnown": t.get("bestKnown"), "searched": text("searched"), "objectFormat": text("objectFormat"),
            "shows": text("shows"), "notCovered": text("notCovered"), "alsoBelongsAt": text("alsoBelongsAt"),
            "effort": text("effort"),
            "limits": {"maxObjectBytes": t["maxObjectBytes"], "checkerSeconds": t["checkerSeconds"]},
            "checkerSha256": t["checkerSha256"], "family": t["family"], "params": t.get("params") or {},
            "problem": {"slug": str(item.get("problemSlug")), "create": None},
            "problemTitle": item.get("problemTitle"), "round": t.get("round"), "listKey": str(item.get("key"))}


def open_items(answer, slug=None):
    """The open lists in an answer that carry a task (of this slug), newest round first."""
    items = answer.get("lists") if isinstance(answer, dict) else None
    found = [i for i in items or [] if isinstance(i, dict) and isinstance(i.get("task"), dict)
             and (slug is None or i["task"].get("slug") == slug)]
    return sorted(found, key=lambda i: -(i["task"].get("round") if isinstance(i["task"].get("round"), int) else 0))


def family_state(t):
    """None when this kit has the checker a family's task names; else why not."""
    family = t.get("family")
    path = family_checker(family) if isinstance(family, str) and SLUG_RE.match(family) else None
    if not path or not os.path.isfile(path):
        return f"this kit has no family {family}"
    if "0x" + sha256_file(path) != t.get("checkerSha256"):
        return f"its checker is another version than this kit's families/{family}/checker.py"
    return None


def find_task(slug, api, fresh=False):
    """(task, answer, copy, why): tasks/<slug>/ first; otherwise the open family task of that name on Papex, whose
    checker this kit must have in the same version. answer, copy and why are open_lists()'s."""
    if not isinstance(slug, str) or not SLUG_RE.match(slug):
        stop("That is not a task's name (such as isosceles-free-grid-100). See: python3 task.py list")
    if os.path.isfile(os.path.join(TASKS, slug, "task.json")):
        try:
            task = load_task(slug)
        except TaskError as e:
            stop(str(e))
        answer, copy, why = open_lists(api, fresh)
        if copy and not why and not open_items(answer, slug):  # the copy may predate the task's open round
            answer, copy, why = _fresh_or(api, answer, copy, why)
        return task, answer, copy, why
    answer, copy, why = open_lists(api, fresh)
    if copy and not open_items(answer, slug):  # not in the copy: read Papex once more before saying it is not there
        answer, copy, why = _fresh_or(api, answer, copy, why)
    if answer is None:
        stop(f"This kit has no folder for task {slug}, and Papex could not be reached to read it ({why}). Run the same "
             "command again when Papex can be reached.")
    items = open_items(answer, slug)
    if not items:
        stop(f"This kit has no task {slug}, and Papex lists no open task of that name. See: python3 task.py list")
    if not items[0]["task"].get("family"):
        stop(f"Task {slug} needs a newer kit: git pull (it is open on Papex, and this kit has no folder for it).")
    state = family_state(items[0]["task"])
    if state:
        stop(f"Task {slug} needs a newer kit: git pull ({state}).")
    try:
        return remote_task(items[0]), answer, copy, why
    except TaskError as e:
        stop(str(e))


def _fresh_or(api, answer, copy, why):
    """A new read of Papex's open lists, or the copy as it was when Papex cannot be read."""
    new = open_lists(api, fresh=True)
    return new if new[0] is not None else (answer, copy, why or new[2])


def checker_of(task):
    """(the checker's path, the params it takes or None) of a task."""
    if task.get("family"):
        return family_checker(task["family"]), task.get("params") or {}
    return os.path.join(TASKS, task["slug"], "checker.py"), None


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


def result_file(task, obj, data, run, batch, problem, list_key, agent_host=None, list_sha=None):
    """The result file of a task run (schema papex-shared-work-result/v1, the contract's shape). list_sha: the
    list's sha256 as Papex gives it (a family task, which has no manifest in this kit)."""
    env = {"os": platform.platform()[:120], "cpu": cpu_name()[:120]}
    if agent_host:
        env["agentHost"] = agent_host
    env["tools"] = [{"name": "python", "version": platform.python_version()},
                    {"name": KIT_NAME, "version": KIT_VERSION,
                     "sourceSha256": "0x" + sha256_file(os.path.abspath(__file__))}]
    extra = {"task": task["slug"], "checkerSha256": task["checkerSha256"], "score": run.score, "object": obj}
    unit = {"key": task["slug"], "outcome": "PASS", "seconds": round(run.seconds, 3),
            "proof": {"sha256": "0x" + sha256_bytes(data), "bytes": len(data)},
            "checks": [{"tool": "checker.py", "result": "passed"}], "extra": extra}
    if list_sha is None:
        with open(os.path.join(TASKS, task["slug"], "manifest.ndjson"), "rb") as fh:
            list_sha = "0x" + sha256_bytes(fh.read())
    return {"schema": RESULT_SCHEMA, "problem": problem, "list": list_key, "listSha256": list_sha, "batch": batch,
            "env": env, "units": [unit]}


def extra_bytes(extra):
    return len(json.dumps(extra, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))


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


def read_object_file(path, task):
    """(object, canonical bytes, raw bytes) of the object file, or (None, why, None)."""
    limit = task["limits"]["maxObjectBytes"]
    cap = max(1 << 20, 16 * limit)
    try:
        with open(path, "rb") as fh:
            raw = fh.read(cap + 1)
    except OSError as e:
        stop(f"The object file could not be read ({e.strerror or e}).")
    if len(raw) > cap:
        return None, f"the file is larger than {cap:,} bytes", None
    try:
        obj, data = read_object(raw, limit)
    except ObjectError as e:
        return None, str(e), None
    why = object_keys_problem(obj, task) if task.get("objectKeys") else None
    if why:
        return None, why, None
    return obj, data, raw


def best_known(task, rounds, list_key=None):
    """(bestKnown, where it was read, the open round's list key or None, the open round's checker or None)."""
    if rounds:
        chosen = next((r for r in rounds if r["listKey"] == list_key), None) if list_key else rounds[0]
        if chosen:
            return chosen["bestKnown"], f"read from Papex (list {chosen['listKey']})", chosen["listKey"], \
                chosen.get("checkerSha256")
    if task.get("source") == "papex":
        return task.get("bestKnown"), f"read from Papex (list {task['listKey']})", task["listKey"], task["checkerSha256"]
    return task.get("bestKnown"), "from this kit's task.json", None, None


def where_text(where, rounds, copy, why):
    """Where the best known value came from, said plainly: Papex now, a copy of its answer, or this kit's file and
    why."""
    now = f"; Papex could not be reached now: {why}" if why else ""
    if rounds is None:
        return where + f"; Papex could not be reached ({why})"
    if "task.json" in where:
        return where + "; Papex lists no open round of this task" + (f" (in {copy}{now})" if copy else " right now")
    return where + (f", {copy}" + (f" (Papex could not be reached now: {why})" if why else "") if copy else "")


def describe_best(task, best, where):
    say(f"  Best known: {value_text(best['value'], task)} ({best['sourceName']}, as of {best['asOf']}), by {best['by']}"
        + (f", {best['year']}" if best.get("year") else ""))
    say(f"              {where[0].upper() + where[1:]}")


def seconds_text(seconds):
    return "under 0.1 s" if seconds < 0.1 else f"{seconds:.1f} s"


def title_line(task):
    family = f", family {task['family']}" if task.get("family") else ""
    say(f"{task['title']}  ({task['slug']}, {KIND_LABELS[task['kind']]}{family})")


def head(task, path, data, raw):
    title_line(task)
    say(f"  Object: {path}, {len(data):,} bytes as the result file carries it")
    if raw is not None and not same_numbers(raw, data):
        say("  Note: some numbers in the file have more digits than a JSON number keeps; the checker ran on them as")
        say("  the result file carries them (rounded). Write such a number as a text to keep every digit.")


def checker_line(run, task):
    if run.status == "passed":
        what = value_text(run.score, task) if run.score is not None else "accepted"
        say(f"  Checker: passes, {what} ({seconds_text(run.seconds)})")
    elif run.status == "failed":
        say(f"  Checker: does not pass: {run.reason[:300]}")
    else:
        say(f"  Checker: stopped without an answer: {run.reason[:300]}")


def check_object(task, path):
    obj, data, raw = read_object_file(path, task)
    if obj is None:
        title_line(task)
        say(f"  Object: {path}: {data}")
        return None, None, None
    head(task, path, data, raw)
    checker, params = checker_of(task)
    run = run_checker(checker, data, task["limits"]["checkerSeconds"], task["kind"], params=params,
                      sha256=task["checkerSha256"])
    checker_line(run, task)
    return obj, data, run


def wrap(text, indent="  ", width=100):
    import textwrap
    return textwrap.fill(" ".join(str(text).split()), width=width, initial_indent=indent, subsequent_indent=indent)


def cmd_list(api):
    """The tasks of this kit and the open tasks on Papex, both kinds; grouped by problem when there are many."""
    answer, copy, why = open_lists(api)
    rows, broken = [], []
    for slug in all_tasks():
        try:
            task = load_task(slug)
        except TaskError as e:
            broken.append(str(e))
            continue
        rounds = rounds_in(answer, slug)[0] if answer is not None else None
        best, _, key, _ = best_known(task, rounds)
        rows.append((task["problem"]["slug"], slug, task, best, f"Papex: {key}" if key else "this kit"))
    local = {r[1] for r in rows}
    for item in open_items(answer):
        slug = item["task"].get("slug")
        if slug in local or not isinstance(slug, str):
            continue
        local.add(slug)
        state = family_state(item["task"]) if item["task"].get("family") else "this kit has no folder for it"
        try:
            task = remote_task(item) if not state else None
        except TaskError as e:
            task, state = None, str(e)
        rows.append((str(item.get("problemSlug")), slug, task, task and task.get("bestKnown"),
                     f"Papex: {item.get('key')}" + (f"; needs a newer kit: git pull ({state})" if state else "")))
    if not rows:
        stop("This kit has no tasks, and Papex lists no open task. Get the newest kit (git pull).")
    width = max(len(r[1]) for r in rows)
    say(f"Open tasks: {sum(1 for r in rows if r[4] == 'this kit' or r[2] and r[2].get('source') != 'papex')} in this "
        f"kit's tasks/, {sum(1 for r in rows if r[2] is None or r[2].get('source') == 'papex')} more open on Papex")

    def row(r):
        problem, slug, task, best, where = r
        if task is None:
            return f"  {slug:<{width}}  {where}"
        value = "none known" if task["kind"] == "counterexample" else \
            f"best known {value_text(best['value'], task)} ({best['sourceName']}, as of {best['asOf']})"
        return f"  {slug:<{width}}  {KIND_LABELS[task['kind']]:<21}  {value}  [{where}]"

    if len(rows) > 10:
        for problem in sorted({r[0] for r in rows}):
            say()
            say(problem)
            for r in sorted((r for r in rows if r[0] == problem), key=lambda r: r[1]):
                say(row(r))
    else:
        say()
        for r in rows:
            say(row(r))
    say()
    if answer is None:
        say(f"Papex could not be reached ({why}): the values are this kit's own, and Papex's open tasks are not shown.")
    elif copy:
        say(f"Papex's open tasks from {copy}" + (f" (Papex could not be reached now: {why})." if why else "."))
    for line in broken:
        say(line)
    say("One task's card: python3 task.py show <task>")
    say("Check an object: python3 task.py check <task> <object.json>")
    return 0


# What two one-hour attempts by AI apps taught (20 Nov 2026): said by show, and on every card.
REPORT_RULES = (
    "Report only what the checker printed for the exact file you show. For an object that does not pass, it prints "
    "\"valid\": false and \"score\": null, with the reason.",
    "The checker cannot tell a new object from the published one. An object equal to the published one, or a symmetry "
    "of it, passes the checker but is not a new result: report it as the published object.",
    "Write each search run's result to a file of its own (run-01.json, run-02.json, ...), not all to one object.json, "
    "so a good object is never overwritten.",
    "Say \"passes the checker with <score>\"; add \"better than the value in <source> as of <date>\" only when "
    "python3 task.py check says the object is better.")


def wrap_rule(rule):
    import textwrap
    return textwrap.fill(rule, width=100, initial_indent="  - ", subsequent_indent="    ")


def cmd_show(task, answer, copy, why):
    """The card of one task in plain text."""
    rounds = rounds_in(answer, task["slug"])[0] if answer is not None else None
    title_line(task)
    title = task.get("problemTitle") or (task["problem"].get("create") or {}).get("title")
    say(f"  Problem: {title} ({task['problem']['slug']})" if title else f"  Problem: {task['problem']['slug']}")
    say()
    say("What to find")
    say(wrap(task.get("objective") or "(not given)"))
    say()
    if task["kind"] == "record":
        best, where, key, _ = best_known(task, rounds)
        say("Best known")
        say(f"  {value_text(best['value'], task)} · {best['by']}" + (f", {best['year']}" if best.get("year") else "")
            + f" · read {best['asOf']}")
        say(f"  Source: {best['sourceName']}, {best['sourceUrl']}")
        say(f"  ({where_text(where, rounds, copy, why)})")
        need = "above" if task["direction"] == "max" else "below"
        smallest = smallest_better(task, best["value"])
        say(f"  Better means a score strictly {need} {best['value']}, compared exactly"
            + (f"; the smallest score that counts is {smallest}." if smallest else "."))
    else:
        say("Best known")
        say("  None: a counterexample is found or not.")
        if task.get("searched"):
            say(wrap("Searched so far: " + task["searched"]))
    if task["kind"] == "record":
        best = best_known(task, rounds)[0]
        if best.get("objectUrl"):
            say(f"  The best known object is published at {best['objectUrl']}")
        if task.get("source") != "papex":
            say(f"  An object with the best known value, in this kit: "
                f"{os.path.relpath(os.path.join(TASKS, task['slug'], 'best_known.json'))}")
    say()
    say("The object")
    say(wrap(task.get("objectFormat") or "(see the card on Papex)"))
    if task.get("family"):
        say(f"  Checked by families/{task['family']}/checker.py with params {json.dumps(task.get('params') or {})}")
    say()
    say("What a pass shows")
    say(wrap(task.get("shows") or "(not given)"))
    say("What it does not show")
    say(wrap(task.get("notCovered") or "(not given)"))
    if task.get("effort"):
        say("Rough effort")
        say(wrap(task["effort"]))
    if task.get("alsoBelongsAt"):
        say("Also belongs at")
        say(wrap(task["alsoBelongsAt"]))
    say()
    say("Rules for what you report")
    for rule in REPORT_RULES:
        say(wrap_rule(rule))
    say()
    key = rounds[0]["listKey"] if rounds else task.get("listKey") or f"{task['slug']}-r1"
    problem = rounds[0]["problemSlug"] if rounds else task["problem"]["slug"]
    say("Next")
    say(f"  python3 task.py check {task['slug']} my-object.json")
    say(f"  python3 task.py result {task['slug']} my-object.json --batch <batch key> --problem {problem} --list {key} "
        "--agent-host \"<app's name>\"")
    say("  (result only after taking a run with the Papex connection: papex_take_shared_work, units 1)")
    return 0


def cmd_check(task, path, answer, copy, why):
    obj, data, run = check_object(task, path)
    if run is None or run.status != "passed":
        say("Does not pass the checker." if run is None or run.status == "failed" else
            "The checker gave no answer, so the object does not pass.")
        say("  (For an object that does not pass, the checker prints \"score\": null: it has no score.)")
        return 3
    rounds = rounds_in(answer, task["slug"])[0] if answer is not None else None
    if task["kind"] == "counterexample":
        if rounds and rounds[0].get("checkerSha256") != task["checkerSha256"]:
            say("  Papex's open list uses another version of this task's checker. Get the newest kit (git pull).")
        say("Passes the checker: the task's checker takes it as a counterexample.")
        next_steps(task, path, rounds)
        return 0
    best, where, key, papex_checker = best_known(task, rounds)
    describe_best(task, best, where_text(where, rounds, copy, why))
    if papex_checker and papex_checker != task["checkerSha256"]:
        say("  Papex's open round uses another version of this task's checker. Get the newest kit (git pull).")
    if not better(run.score, best["value"], task["direction"]):
        need = "more" if task["direction"] == "max" else "less"
        say(f"Passes the checker with {value_text(run.score, task)}, which is not better than the best known "
            f"{best['value']}. A better object needs {need} than {best['value']}.")
        if decimal.Decimal(run.score) == decimal.Decimal(best["value"]):
            say("  The same score as the published object: this may be the published object itself, or a symmetry of "
                "it. That is not a new result; report it as the published object.")
        return 2
    say(f"Passes the checker with {value_text(run.score, task)}: better than the value in {best['sourceName']} "
        f"as of {best['asOf']} ({best['value']}).")
    next_steps(task, path, rounds)
    return 0


def next_steps(task, path, rounds):
    problem = rounds[0]["problemSlug"] if rounds else task["problem"]["slug"]
    key = rounds[0]["listKey"] if rounds else task.get("listKey") or f"{task['slug']}-r1"
    say("To send it: take a run with the Papex connection (papex_take_shared_work, problem "
        f"{problem}, list {key}, units 1), then")
    say(f"  python3 task.py result {task['slug']} {path} --batch <batch key> --problem {problem} --list {key} "
        "--agent-host \"<app's name>\"")
    if not rounds and task.get("source") != "papex":
        say("  (Papex lists no open round of this task right now: a run can be taken only while one is open.)")


def list_page(api, problem, key):
    """The list's page on Papex: (sha256, state, task) or stop() saying why not."""
    page, why = read_json_url(f"{api}/api/shared-work/problems/{problem}/lists/{key}", LIVE_SECONDS * 2)
    lst = page.get("list") if isinstance(page, dict) else None
    task = (page.get("howTo") or {}).get("task") if isinstance(page, dict) and isinstance(page.get("howTo"), dict) \
        else None
    if not isinstance(lst, dict) or not isinstance(lst.get("sha256"), str) or not SHA256_RE.match(lst["sha256"]):
        stop(f"No result file was written: Papex's page of list {key} could not be read ({why or 'no list on it'}). "
             "Run the same command again.")
    return lst["sha256"], lst.get("state"), task


def cmd_result(task, path, argv, api, answer, why):
    batch, problem, list_key = take(argv, "--batch"), take(argv, "--problem"), take(argv, "--list")
    agent_host = take(argv, "--agent-host")
    work_root = os.path.abspath(take(argv, "--work", os.path.join(HERE, "work")))
    if argv:
        stop(f"Unknown: {' '.join(argv)}. See --help.")
    if None in (batch, problem, list_key):
        stop("result needs --batch, --problem and --list: the batch key, problem and list the Papex connection "
             "gave when it took the run.")
    if not BATCH_RE.match(batch):
        stop("That is not a batch key (such as b-7f3a21). Use the batch key the Papex connection gave.")
    if problem != task["problem"]["slug"]:
        stop(f"Task {task['slug']} belongs to problem {task['problem']['slug']}, not {problem}.")
    m = LIST_KEY_RE.match(list_key)
    if not m or m.group("slug") != task["slug"]:
        stop(f"The lists of task {task['slug']} are named {task['slug']}-r1, {task['slug']}-r2, …; not {list_key}.")
    if agent_host is not None and not AGENT_HOST_RE.match(agent_host):
        stop("--agent-host takes letters, digits, spaces and . _ - + ( ) / : only, 80 at most.")
    obj, data, run = check_object(task, path)
    if run is None or run.status != "passed":
        stop("No result file was written: the object does not pass the checker.")
    rounds = rounds_in(answer, task["slug"])[0] if answer is not None else None
    if rounds:
        mine = next((r for r in rounds if r["listKey"] == list_key), None)
        if mine is None:
            other = rounds[0]
            stop(f"No result file was written: the task moved on. List {list_key} is no longer open; the open round "
                 f"is {other['listKey']}" + (f", with best known {other['bestKnown']['value']}"
                                             if other.get("bestKnown") else "")
                 + ". Take that round with the Papex connection and run result again with its batch key.")
        if mine.get("checkerSha256") != task["checkerSha256"]:
            stop("No result file was written: Papex's list uses another version of this task's checker. Get the "
                 "newest kit (git pull) and run the same command again.")
    list_sha = None
    if task.get("source") == "papex":  # a family's task: this kit has no manifest of its list; Papex's page has
        list_sha, state, page_task = list_page(api, problem, list_key)
        if state != "OPEN" or not isinstance(page_task, dict) or page_task.get("checkerSha256") != task["checkerSha256"]:
            stop(f"No result file was written: list {list_key} is not open with this task's checker on Papex.")
    if task["kind"] == "record":
        best, where, _, _ = best_known(task, rounds, list_key)
        describe_best(task, best, where_text(where, rounds, None, why))
        if not better(run.score, best["value"], task["direction"]):
            stop(f"No result file was written: {value_text(run.score, task)} passes the checker but is not better "
                 f"than the best known {best['value']}.")
    result = result_file(task, obj, data, run, batch, problem, list_key, agent_host, list_sha)
    if extra_bytes(result["units"][0]["extra"]) > task["limits"]["maxObjectBytes"] + EXTRA_ALLOWANCE:
        stop("No result file was written: the object is too large for the result file.")
    text = json.dumps(result, indent=1, ensure_ascii=False) + "\n"
    if len(text.encode("utf-8")) > RESULT_MAX_BYTES:
        stop("No result file was written: it would be larger than Papex takes (256 KB).")
    folder = os.path.join(work_root, "batches", batch)
    os.makedirs(folder, exist_ok=True)
    out = os.path.join(folder, f"{batch}.result.json")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(text)
    if task["kind"] == "record":
        say(f"Passes the checker with {value_text(run.score, task)}: better than the value in {best['sourceName']} "
            f"as of {best['asOf']} ({best['value']}).")
    else:
        say("Passes the checker: the task's checker takes it as a counterexample.")
    if rounds is None:
        say("  Papex could not be reached to read the open round; Papex's runner compares with the value on Papex.")
    elif not rounds:
        say("  Papex lists no open round of this task right now: the result can be sent only while one is open.")
    say()
    say(f"Result file: {out}")
    say("  The AI app that took the run gives the result file, exactly as it is, to the Papex connection")
    say(f"  (papex_prepare_shared_work_batch, batch {batch}), or you upload it on your run's page.")
    say("  Only you send it: on that page on papex.org, choose how you are shown, and press Send.")
    return 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help", "help"):
        say(__doc__.strip())
        return 0
    if sys.version_info < (3, 9):
        stop("This kit needs Python 3.9 or later.")
    command = argv.pop(0)
    api = api_address(take(argv, "--api", DEFAULT_API))
    if command == "list":
        if argv:
            stop("list takes no other arguments. See --help.")
        return cmd_list(api)
    if command == "show":
        if len(argv) != 1 or argv[0].startswith("-"):
            stop("show needs a task: python3 task.py show TASK. See --help.")
        return cmd_show(*find_task(argv[0], api))
    if command not in ("check", "result"):
        stop("The commands are list, show, check and result. See --help.")
    if len(argv) < 2 or argv[0].startswith("-") or argv[1].startswith("-"):
        stop(f"{command} needs a task and an object file: python3 task.py {command} TASK OBJECT.json. See --help.")
    slug, path = argv.pop(0), argv.pop(0)
    if command == "check":
        if argv:
            stop(f"Unknown: {' '.join(argv)}. See --help.")
        return _check(slug, path, api)
    task, answer, _, why = find_task(slug, api, fresh=True)  # result reads Papex anew: never a copy
    return cmd_result(task, path, argv, api, answer, why)


def _check(slug, path, api):
    task, answer, copy, why = find_task(slug, api)
    return cmd_check(task, path, answer, copy, why)


if __name__ == "__main__":
    sys.exit(main())
