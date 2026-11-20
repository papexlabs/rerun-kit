#!/usr/bin/env python3
"""Checker of the toy family toy-sum-avoiding (for the kit's tests only; never published).

    python3 checker.py <object.json> <params.json>

params: {"limit": L, "total": T}, whole numbers, 2 <= L <= 1000, 2 <= T <= 2000. No other key.
object: {"numbers": [a, b, ...]}: distinct whole numbers from 1 to L, no two of them adding up to T. No other key.
Score: how many numbers (more is better). Prints one JSON line and exits 0.
"""
import json
import os
import sys


def out(valid, score, reason):
    print(json.dumps({"valid": valid, "score": score, "reason": reason}))
    sys.exit(0)


def whole(value):
    return isinstance(value, int) and not isinstance(value, bool)


def main():
    if len(sys.argv) != 3:
        out(False, None, "usage: python3 checker.py object.json params.json")
    object_path = sys.argv[1]
    params_path = sys.argv[2]
    for path in (object_path, params_path):
        if os.path.getsize(path) > 20000:
            out(False, None, "a file is larger than 20000 bytes")
    try:
        with open(object_path, "r", encoding="utf-8") as fh:
            obj = json.load(fh)
        with open(params_path, "r", encoding="utf-8") as fh:
            params = json.load(fh)
    except (ValueError, OSError) as e:
        out(False, None, "not valid JSON: %s" % e)
    if not isinstance(params, dict) or set(params) != {"limit", "total"} or not whole(params["limit"]) \
            or not whole(params["total"]) or not 2 <= params["limit"] <= 1000 or not 2 <= params["total"] <= 2000:
        out(False, None, "the params must be {\"limit\": L, \"total\": T} and nothing else")
    if not isinstance(obj, dict) or set(obj) != {"numbers"} or not isinstance(obj["numbers"], list):
        out(False, None, "the object must be {\"numbers\": [...]} and nothing else")
    limit, total = params["limit"], params["total"]
    seen = set()
    for i, x in enumerate(obj["numbers"]):
        if not whole(x) or not 1 <= x <= limit:
            out(False, None, "entry %d is not a whole number from 1 to %d" % (i, limit))
        if x in seen:
            out(False, None, "%d appears twice" % x)
        if total - x in seen:
            out(False, None, "%d and %d add up to %d" % (total - x, x, total))
        seen.add(x)
    out(True, len(seen), "%d distinct numbers from 1 to %d, no two adding up to %d" % (len(seen), limit, total))


if __name__ == "__main__":
    main()
