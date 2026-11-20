"""What the finder keeps between runs: the date it first saw each source state (so a card's asOf, and with it the
whole publish body, is the same on every retry), and the evidence that a family's checker reproduces the values of
real published objects (validation/<family>.json), which decides whether cards without a linked object are allowed.
"""

import datetime
import json
import os

from common import params_key

MIN_EVIDENCE = 10


def _read(path, default):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def _write(path, value):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".part"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(value, fh, indent=1, ensure_ascii=False, sort_keys=True)
        fh.write("\n")
    os.replace(tmp, path)


class FirstSeen:
    """What the finder remembers between runs (state/first-seen.json):
      seen      {state key: the date (UTC) the finder first read that source state}. A source state is a row's value
                with its object (or "no object"): while it does not change, neither does the card's asOf.
      lastSeen  {key: the last few distinct dates a run read it}, for "the same reading on two runs in a row"
                (a close, a card without a linked object)
      runs      the dates the finder ran (the last 60)."""

    def __init__(self, path):
        self.path = path
        data = _read(path, {})
        self.seen = data.get("seen", {}) if isinstance(data.get("seen"), dict) else {}
        self.last = data.get("lastSeen", {}) if isinstance(data.get("lastSeen"), dict) else {}
        self.runs = [r for r in data.get("runs", []) if isinstance(r, str)] if isinstance(data.get("runs"), list) else []
        self.now = set()
        self.changed = False

    @staticmethod
    def key(row, no_object=False):
        return "|".join([row["id"], row["bestKnownValue"], "no-object" if no_object else (row.get("objectUrl") or "")])

    def as_of(self, row, today, no_object=False):
        k = self.key(row, no_object)
        if k not in self.seen:
            self.seen[k] = today
            self.changed = True
        return self.seen[k]

    def observe(self, key):
        self.now.add(key)

    def previous_run(self, today):
        before = [r for r in self.runs if r < today]
        return max(before) if before else None

    def seen_on_previous_run(self, key, today):
        """True when the run before today's read the same key (the same reading on two runs in a row)."""
        prev = self.previous_run(today)
        return prev is not None and prev in (self.last.get(key) or [])

    def finish(self, today):
        """Records today's readings and today's run (called once, at the end of a run)."""
        for k in self.now:
            dates = [d for d in (self.last.get(k) or []) if isinstance(d, str) and d != today]
            self.last[k] = sorted(dates + [today])[-3:]
        if today not in self.runs:
            self.runs = sorted(self.runs + [today])[-60:]
        keep = set(self.runs)
        self.last = {k: v for k, v in self.last.items() if any(d in keep for d in v)}
        self.changed = True

    def save(self):
        if self.changed:
            _write(self.path, {"schema": "papex-finder-first-seen/v2", "seen": self.seen, "lastSeen": self.last,
                               "runs": self.runs})


class Evidence:
    """validation/<family>.json: objects of a family's source that its checker was run on, with the outcome."""

    def __init__(self, folder):
        self.folder = folder
        self.files = {}

    def _file(self, family):
        if family not in self.files:
            self.files[family] = _read(os.path.join(self.folder, family + ".json"),
                                       {"schema": "papex-finder-evidence/v1", "family": family, "records": []})
            self.files[family]["_changed"] = False
        return self.files[family]

    def add(self, family, checker_sha, row, sha256, score, reproduced, on):
        data = self._file(family)
        record = {"checkerSha256": checker_sha, "params": row["params"], "source": row.get("source"),
                  "objectUrl": row.get("objectUrl"), "sha256": sha256, "tableValue": row["bestKnownValue"],
                  "score": None if score is None else str(score), "result": "reproduced" if reproduced else "mismatch",
                  "checkedOn": on}
        same = [r for r in data["records"] if r["checkerSha256"] == checker_sha and r["sha256"] == sha256
                and params_key(r["params"]) == params_key(row["params"])]
        if not same:
            data["records"].append(record)
            data["_changed"] = True

    def status(self, family, checker_sha, source=None):
        """(ok, reproduced, mismatches) for this checker version (and source, when given)."""
        records = [r for r in self._file(family)["records"] if r["checkerSha256"] == checker_sha
                   and (source is None or r.get("source") == source)]
        good = sum(r["result"] == "reproduced" for r in records)
        bad = sum(r["result"] == "mismatch" for r in records)
        return good >= MIN_EVIDENCE and bad == 0, good, bad

    def save(self):
        for family, data in self.files.items():
            if data.pop("_changed", False):
                data["records"].sort(key=lambda r: (r["checkerSha256"], params_key(r["params"]), r["sha256"]))
                _write(os.path.join(self.folder, family + ".json"), data)
            data["_changed"] = False


def utc_today():
    return datetime.datetime.now(datetime.timezone.utc).date().isoformat()
