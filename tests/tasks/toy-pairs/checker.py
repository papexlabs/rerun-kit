#!/usr/bin/env python3
"""Checker of the toy task toy-pairs (for the kit's tests only; never published).

Object: {"numbers": [a, b, ...]}: distinct whole numbers from 1 to 30, no two of them adding up to 31.
Score: how many numbers (more is better; 15 is the most there can be).
"""
import json
import os
import sys


def out(valid, score, reason):
    print(json.dumps({"valid": valid, "score": score, "reason": reason}))
    sys.exit(0)


def main():
    if len(sys.argv) != 2:
        out(False, None, "usage: python3 checker.py object.json")
    path = sys.argv[1]
    if os.path.getsize(path) > 4000:
        out(False, None, "file is larger than 4000 bytes")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            obj = json.load(fh)
    except (ValueError, OSError) as e:
        out(False, None, "not valid JSON: %s" % e)
    if not isinstance(obj, dict) or set(obj) != {"numbers"} or not isinstance(obj["numbers"], list):
        out(False, None, "the object must be {\"numbers\": [...]} and nothing else")
    seen = set()
    for i, x in enumerate(obj["numbers"]):
        if not isinstance(x, int) or isinstance(x, bool) or not 1 <= x <= 30:
            out(False, None, "entry %d is not a whole number from 1 to 30" % i)
        if x in seen:
            out(False, None, "%d appears twice" % x)
        if 31 - x in seen:
            out(False, None, "%d and %d add up to 31" % (31 - x, x))
        seen.add(x)
    out(True, len(seen), "%d distinct numbers from 1 to 30, no two adding up to 31" % len(seen))


if __name__ == "__main__":
    main()
