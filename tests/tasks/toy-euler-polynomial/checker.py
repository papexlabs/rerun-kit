#!/usr/bin/env python3
"""Checker of the toy task toy-euler-polynomial (for the kit's tests only; never published).

Statement to refute: "n*n + n + 41 is prime for every whole number n from 0 to 1000."
Object: {"n": n}. Valid when 0 <= n <= 1000 and n*n + n + 41 is not prime. Score: null.
"""
import json
import os
import sys


def out(valid, score, reason):
    print(json.dumps({"valid": valid, "score": score, "reason": reason}))
    sys.exit(0)


def smallest_factor(value):
    """The smallest factor > 1 of value, or None when value is prime (value >= 2)."""
    d = 2
    while d * d <= value:
        if value % d == 0:
            return d
        d += 1
    return None


def main():
    if len(sys.argv) != 2:
        out(False, None, "usage: python3 checker.py object.json")
    path = sys.argv[1]
    if os.path.getsize(path) > 1000:
        out(False, None, "file is larger than 1000 bytes")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            obj = json.load(fh)
    except (ValueError, OSError) as e:
        out(False, None, "not valid JSON: %s" % e)
    if not isinstance(obj, dict) or set(obj) != {"n"}:
        out(False, None, "the object must be {\"n\": n} and nothing else")
    n = obj["n"]
    if not isinstance(n, int) or isinstance(n, bool) or not 0 <= n <= 1000:
        out(False, None, "n must be a whole number from 0 to 1000")
    value = n * n + n + 41
    factor = smallest_factor(value)
    if factor is None:
        out(False, None, "%d*%d + %d + 41 = %d is prime" % (n, n, n, value))
    out(True, None, "%d*%d + %d + 41 = %d = %d * %d" % (n, n, n, value, factor, value // factor))


if __name__ == "__main__":
    main()
