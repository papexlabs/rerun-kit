"""The gates a row must pass before a card is made from it. Each gate returns None (pass) or the reason it drops
the row. Nothing here reads prose: every check compares parsed values.

  proved       the source does not say the value is optimal (nor does a second source give the exact value)
  limits       the family's checker can take the entry's objects, including a better one
  second       a second source does not give a stronger value than the primary (if it gives a weaker one, the
               difference is recorded and the primary is used)
  object       the source's own best known object can be had and converted
  size         the object fits the card's maxObjectBytes
  checker      the family's checker, run on the source's own object, passes it with exactly the table's value
  texts        the card's texts fit the server's limits, and no public text uses a word Papex never uses
"""

import json
import os
import re
import subprocess
import sys
from decimal import Decimal

from common import canonical_bytes, checker_path, utf16_length

NEVER_WORDS = re.compile(r"\b(verified|verifies|confirmed|proved|proven|records?|world[- ]records?|first|winners?|"
                         r"leaderboards?)\b", re.IGNORECASE)
PUBLIC_TEXTS = ("title", "shortTitle", "description", "objective", "scoreLabel", "searched", "objectFormat", "shows",
                "notCovered", "alsoBelongsAt", "effort", "resultLine", "requirements", "checkedHow")
HOWTO_MAX = 7500  # the kit lint's margin under the server's 8,192 bytes
LIMITS = {"title": 200, "shortTitle": 80, "description": 300, "objective": 600, "objectFormat": 600, "shows": 400,
          "notCovered": 400, "resultLine": 400, "requirements": 600, "checkedHow": 600, "scoreLabel": 40,
          "searched": 400, "alsoBelongsAt": 300, "effort": 200}


def better(a, b, direction):
    """True when value a is strictly better than value b."""
    a, b = Decimal(str(a)), Decimal(str(b))
    return a < b if direction == "min" else a > b


def gate_proved(row):
    if row["provedOptimal"]:
        return "the source says this value is optimal"
    for s in row.get("secondary") or []:
        if s.get("exact"):
            return f"{s['name']} gives the exact value {s['value']}"
    return None


def gate_limits(fam, row):
    return fam.static_problem(row["params"], row["bestKnownValue"])


def gate_second(row):
    """(reason or None, notes): drop when a second source is ahead of the primary."""
    notes = []
    for s in row.get("secondary") or []:
        if better(s["value"], row["bestKnownValue"], row["direction"]):
            return (f"{s['name']} gives {s['value']}, better than the primary's {row['bestKnownValue']}: held until "
                    "they agree"), notes
        if s["value"] != row["bestKnownValue"]:
            notes.append(f"{s['name']} gives {s['value']}; the primary's {row['bestKnownValue']} is used")
        else:
            notes.append(f"{s['name']} agrees ({s['value']})")
    if not row.get("secondary"):
        notes.append("no second source for this entry")
    return None, notes


def run_checker(family, obj_bytes, params, seconds, work_dir, python=None):
    """{valid, score, reason} of the family checker on the object's canonical bytes, run as the kit runs it:
    python3 -I -S -B, a folder of its own, a minimal environment, a time limit (and on Linux a memory limit)."""
    os.makedirs(work_dir, exist_ok=True)
    obj_path = os.path.join(work_dir, f"{family}.object.json")
    params_path = os.path.join(work_dir, f"{family}.params.json")
    with open(obj_path, "wb") as fh:
        fh.write(obj_bytes)
    with open(params_path, "wb") as fh:
        fh.write(canonical_bytes(params))
    cwd = os.path.join(work_dir, "empty")
    os.makedirs(cwd, exist_ok=True)

    def limit():
        try:
            import resource
            resource.setrlimit(resource.RLIMIT_AS, (1 << 30, 1 << 30))
        except (ImportError, ValueError, OSError):
            pass

    cmd = [python or sys.executable, "-I", "-S", "-B", checker_path(family), obj_path, params_path]
    try:
        proc = subprocess.run(cmd, cwd=cwd, env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"},
                              stdin=subprocess.DEVNULL, capture_output=True, timeout=seconds,
                              preexec_fn=limit if sys.platform.startswith("linux") else None)
    except subprocess.TimeoutExpired:
        return {"valid": False, "score": None, "reason": f"the checker did not finish within {seconds} s"}
    finally:
        with open(obj_path, "wb"):  # emptied after use: an object whose licence forbids copying is not kept
            pass
    lines = [ln for ln in proc.stdout.decode("utf-8", "replace").splitlines() if ln.strip()]
    if proc.returncode != 0 or len(lines) != 1:
        return {"valid": False, "score": None, "reason": f"the checker failed (exit {proc.returncode})"}
    try:
        answer = json.loads(lines[0])
    except ValueError:
        return {"valid": False, "score": None, "reason": "the checker's line is not JSON"}
    return answer


def gate_checker(family, obj, row, seconds, work_dir):
    data = canonical_bytes(obj)
    answer = run_checker(family, data, row["params"], seconds, work_dir)
    if not answer.get("valid"):
        return f"the checker rejects the source's own object: {answer.get('reason', '')[:200]}", answer
    if str(answer.get("score")) != row["bestKnownValue"]:
        return (f"the checker gives {answer.get('score')} on the source's own object, not the table's "
                f"{row['bestKnownValue']}"), answer
    return None, answer


def gate_texts(body):
    """Server limits and the words rule, on a publish body (cards.py)."""
    lst = body["list"]
    task = lst["howTo"]["task"]
    problems = []
    texts = {"title": lst["title"], "shortTitle": lst["shortTitle"], "description": lst["description"],
             "resultLine": lst["resultLine"], "requirements": lst["howTo"]["requirements"],
             "checkedHow": lst["howTo"]["checkedHow"]}
    for key in ("objective", "scoreLabel", "searched", "objectFormat", "shows", "notCovered", "alsoBelongsAt",
                "effort"):
        if task.get(key) is not None:
            texts[key] = task[key]
    for key, value in texts.items():
        if utf16_length(value) > LIMITS[key]:
            problems.append(f"{key} is {utf16_length(value)} characters; at most {LIMITS[key]}")
        for m in NEVER_WORDS.finditer(value):
            problems.append(f"{key} uses the word \"{m.group()}\"")
    for key in ("by", "sourceName"):
        for m in NEVER_WORDS.finditer(task["bestKnown"][key] or ""):
            problems.append(f"bestKnown.{key} uses the word \"{m.group()}\"")
    if not lst["resultLine"].startswith("Result: "):
        problems.append("resultLine must start with \"Result: \"")
    if len(task["slug"]) > 34 or not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", task["slug"]):
        problems.append("slug must be lowercase words joined by hyphens, at most 34 characters")
    if len(task["bestKnown"]["by"]) > 200 or len(task["bestKnown"]["sourceName"]) > 120:
        problems.append("bestKnown.by (200) or sourceName (120) is too long")
    if len(json.dumps(task["params"], separators=(",", ":")).encode("utf-8")) > 1024:
        problems.append("params is over 1,024 bytes")
    size = howto_bytes(lst["howTo"])
    if size > HOWTO_MAX:
        problems.append(f"howTo is {size} bytes in its longest round; at most {HOWTO_MAX}")
    if len(body["manifest"].encode("utf-8")) > 16384:
        problems.append("the manifest is over 16,384 bytes")
    return "; ".join(problems) or None


def howto_bytes(howto):
    """The largest the howTo gets: this round, and a late round whose best known value is an accepted run."""
    late = dict(howto)
    task = dict(howto["task"])
    best = dict(task["bestKnown"])
    best.update({"value": "-" + "9" * 18 + "." + "9" * 18, "by": "an accepted run on Papex", "year": 9999,
                 "sourceName": "Papex", "asOf": "2026-11-20",
                 "sourceUrl": "https://papex.org/problems/" + "x" * 60 + "/shared-work/" + task["slug"] + "-r9998"})
    task.update({"bestKnown": best, "round": 9999, "previousListKey": task["slug"] + "-r9998"})
    late["task"] = task
    return max(len(json.dumps(h, ensure_ascii=False).encode("utf-8")) for h in (howto, late))
