"""The publish request body of a card (CONTRACT.md, POST /api/shared-work/publisher/tasks), from a row that passed
the gates, and the calls that publish or close one through the kit's publisher client. A card is data only: the
family's reviewed checker does the checking.

Papex's rules (CONTRACT.md, Deviations, server items 16-17): round = the highest round of the slug + 1;
previousListKey is null in round 1 and `<slug>-r<round-1>` from round 2 on; replaces is that key or null; a retry must
send the very same body, so every text and the best known value's asOf are fixed for a given source state (texts
hold no value and no date; asOf is the date the finder first read that state, records.FirstSeen).
"""

import importlib.util
import json
import os
import sys

from common import checker_sha256
from families import LEAD

EXPECTED_SECONDS = 3600


def list_key(slug, round_):
    return f"{slug}-r{round_}"


def manifest_text(slug, checker_sha):
    return json.dumps({"key": slug, "kind": "find", "expectedSeconds": EXPECTED_SECONDS, "inputSha256": checker_sha},
                      separators=(",", ":")) + "\n"


def best_known(row, as_of, no_object=False):
    best = {"value": row["bestKnownValue"], "by": row["by"], "year": row["year"], "sourceName": row["sourceName"],
            "sourceUrl": row["sourceUrl"], "asOf": as_of}
    if row.get("objectUrl") and not no_object:
        best["objectUrl"] = row["objectUrl"]
    return best


def build(fam, row, round_=1, replaces=None, as_of=None, best=None, no_object=False):
    """The whole publish body for this row's card in round `round_` (replacing list `replaces`, or None).
    best: the round's bestKnown (default: the row's, read on as_of)."""
    p = row["params"]
    slug = fam.slug(p)
    previous = None if round_ == 1 else list_key(slug, round_ - 1)
    if round_ < 1 or replaces not in (None, previous):
        raise ValueError(f"round {round_} of {slug} can replace only {previous or 'no list'}, not {replaces}")
    as_of = as_of or row["readOn"]
    texts = fam.texts(row, p, no_object=no_object)
    checker_sha = checker_sha256(fam.name)
    task = {
        "slug": slug, "kind": "record", "objective": texts["objective"], "direction": row["direction"],
        "scoreLabel": texts["scoreLabel"], "bestKnown": best or best_known(row, as_of, no_object), "searched": None,
        "objectFormat": texts["objectFormat"], "shows": texts["shows"], "notCovered": texts["notCovered"],
        "alsoBelongsAt": texts["alsoBelongsAt"], "effort": texts["effort"],
        "maxObjectBytes": fam.max_object_bytes(p, row["bestKnownValue"]),
        "checkerSeconds": fam.checker_seconds(p), "checkerSha256": checker_sha,
        "round": round_, "previousListKey": previous, "family": fam.name, "params": dict(p)}
    problem = fam.problem(p, row, as_of)
    return {
        "problem": {"slug": problem["slug"], "create": problem["create"] if round_ == 1 else None},
        "list": {"key": list_key(slug, round_), "title": texts["title"], "shortTitle": texts["shortTitle"],
                 "description": texts["description"], "leadName": LEAD, "resultLine": texts["resultLine"],
                 "expectedSeconds": EXPECTED_SECONDS,
                 "howTo": {"requirements": texts["requirements"], "checkedHow": texts["checkedHow"],
                           "rulesUrl": None, "task": task}},
        "manifest": manifest_text(slug, checker_sha),
        "replaces": replaces}


# ---------------------------------------------------------------------------- the kit's publisher client
_LOADED = {}


def load_publisher(kit_path):
    """runner/publisher.py of the kit at kit_path, loaded by path once per process (it loads the kit's task.py next
    to it). Nothing is written in the kit's folder."""
    path = os.path.join(os.path.abspath(kit_path), "runner", "publisher.py")
    if path in _LOADED:
        return _LOADED[path]
    if not os.path.isfile(path):
        raise SystemExit(f"no publisher client at {path} (give the kit's folder with --kit)")
    before = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec = importlib.util.spec_from_file_location("papex_kit_publisher", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = before
    _LOADED[path] = module
    return module


def publish(client, body):
    """POST /api/shared-work/publisher/tasks through the kit's client: its answer, or the client's PublisherError."""
    return client.publish(body)


def close(client, problem_slug, list_key_, reason):
    """POST /api/shared-work/publisher/tasks/{problem}/{list}/close through the kit's client."""
    return client.close(problem_slug, list_key_, reason[:300])
