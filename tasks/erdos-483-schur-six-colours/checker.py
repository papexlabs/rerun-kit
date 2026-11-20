#!/usr/bin/env python3
"""Checker for the task "Six sum-free colours for 1..N" (Erdős problem #483, Schur numbers).

Usage:  python3 checker.py object.json

The object is a JSON file:
    {"k": 6, "N": <int>, "colours": [c_1, c_2, ..., c_N]}
where c_i in {0, 1, 2, 3, 4, 5} is the colour of the integer i. No other key: an accepted
object is shown publicly, so it holds nothing the format does not name.

The object is valid when no colour class contains a, b, c with a + b = c
(a = b allowed, as in Schur's theorem). The score is N: a valid object
shows that the Schur number f(6) of problem #483 is at least N + 1.

Standard library only, exact integer arithmetic, deterministic, no network,
reads only the file given as argv[1]. Prints one JSON line and exits 0.
"""
import json
import os
import sys

K = 6
MAX_N = 5000
MAX_BYTES = 200_000


def out(valid, score, reason):
    print(json.dumps({"valid": valid, "score": score, "reason": reason}))
    sys.exit(0)


def check(obj):
    """Return (valid, score, reason). Pure function, no I/O."""
    if not isinstance(obj, dict):
        return False, None, "object must be a JSON object"
    if set(obj) != {"k", "N", "colours"}:
        return False, None, "the object must hold exactly the keys k, N and colours"
    k, n, colours = obj.get("k"), obj.get("N"), obj.get("colours")
    if not isinstance(k, int) or isinstance(k, bool) or k != K:
        return False, None, "k must be 6"
    if not isinstance(n, int) or isinstance(n, bool) or n < 1 or n > MAX_N:
        return False, None, "N must be an integer between 1 and %d" % MAX_N
    if not isinstance(colours, list) or len(colours) != n:
        return False, None, "colours must be a list of exactly N entries (colour of 1, 2, ..., N)"
    for i, c in enumerate(colours, start=1):
        if not isinstance(c, int) or isinstance(c, bool) or not (0 <= c < K):
            return False, None, "colour of %d is not an integer in 0..5" % i
    col = [None] + colours  # col[i] = colour of i
    classes = [[] for _ in range(K)]
    for i in range(1, n + 1):
        classes[col[i]].append(i)
    for c in range(K):
        members = classes[c]
        for idx, a in enumerate(members):
            for b in members[idx:]:          # a <= b, a = b included
                s = a + b
                if s > n:
                    break                     # members are increasing
                if col[s] == c:
                    return False, None, "colour %d contains %d + %d = %d" % (c, a, b, s)
    return True, n, "all 6 colours are sum-free on 1..%d (a = b included); f(6) >= %d" % (n, n + 1)


def main():
    if len(sys.argv) != 2:
        out(False, None, "usage: python3 checker.py object.json")
    path = sys.argv[1]
    try:
        size = os.path.getsize(path)
        if size > MAX_BYTES:
            out(False, None, "object file is %d bytes; limit is %d" % (size, MAX_BYTES))
        with open(path, "r", encoding="utf-8") as f:
            obj = json.load(f)
    except SystemExit:
        raise
    except Exception as e:  # unreadable or not JSON
        out(False, None, "cannot read object as JSON: %s" % type(e).__name__)
    try:
        valid, score, reason = check(obj)
    except Exception as e:
        out(False, None, "checker error on this object: %s" % type(e).__name__)
    out(valid, score, reason)


if __name__ == "__main__":
    main()
