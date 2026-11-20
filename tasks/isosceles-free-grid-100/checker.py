#!/usr/bin/env python3
"""Checker: isosceles-free subset of the 100 x 100 grid.

Object (JSON file given as argv[1]):
  {"n": 100, "points": [[x, y], ...]}
  x, y are integers with 0 <= x, y <= 99 (the grid {1..100}^2 shifted by -1, as the
  source publishes it; a shift changes no distance). Any other key makes the object
  invalid: an accepted object is shown publicly, so it holds nothing the format does not name.

Valid when the points are distinct and no three distinct points a, b, c have
|a - b| = |b - c| (this forbids every isosceles triangle, including the flat one
where b is the midpoint of a and c). Score = number of points (higher is better).

Exact integer arithmetic only (squared distances). Standard library only, no network,
reads only argv[1]. Prints one JSON line and exits 0.
"""
import json
import os
import sys

N = 100
MAX_BYTES = 200_000


def out(valid, score, reason):
    print(json.dumps({"valid": valid, "score": score, "reason": reason}))
    sys.exit(0)


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def main():
    if len(sys.argv) != 2:
        out(False, None, "usage: python3 checker.py object.json")
    path = sys.argv[1]
    try:
        size = os.path.getsize(path)
    except OSError as e:
        out(False, None, "cannot read file: %s" % e)
    if size > MAX_BYTES:
        out(False, None, "file is %d bytes; limit is %d" % (size, MAX_BYTES))
    try:
        with open(path, "r", encoding="utf-8") as f:
            obj = json.load(f)
    except (ValueError, OSError) as e:
        out(False, None, "not valid JSON: %s" % e)

    if not isinstance(obj, dict):
        out(False, None, "top level must be a JSON object")
    extra = sorted(set(obj) - {"n", "points"})
    if extra:
        out(False, None, "key %s is not part of the format (only n and points)" % json.dumps(extra[0][:40]))
    if obj.get("n") != N or not is_int(obj.get("n")):
        out(False, None, "field n must be the integer %d" % N)
    pts = obj.get("points")
    if not isinstance(pts, list) or len(pts) == 0:
        out(False, None, "field points must be a non-empty list")
    # From any one grid point only 3663 distinct nonzero squared distances occur in the
    # 100 x 100 grid, so a valid set has at most 3664 points (keeps the run short).
    if len(pts) > 3664:
        out(False, None, "%d points: more than 3664 points always repeat a distance from one point"
            % len(pts))

    seen = set()
    P = []
    for i, p in enumerate(pts):
        if not (isinstance(p, list) and len(p) == 2 and is_int(p[0]) and is_int(p[1])):
            out(False, None, "point %d is not a pair of integers: %r" % (i, p))
        x, y = p
        if not (0 <= x < N and 0 <= y < N):
            out(False, None, "point %d = (%d, %d) is outside 0..%d" % (i, x, y, N - 1))
        if (x, y) in seen:
            out(False, None, "point %d = (%d, %d) appears twice" % (i, x, y))
        seen.add((x, y))
        P.append((x, y))

    # For every apex b, the squared distances from b to all other points must be distinct.
    k = len(P)
    for j in range(k):
        bx, by = P[j]
        first = {}
        for i in range(k):
            if i == j:
                continue
            dx = P[i][0] - bx
            dy = P[i][1] - by
            d2 = dx * dx + dy * dy
            if d2 in first:
                a = P[first[d2]]
                c = P[i]
                out(False, None,
                    "isosceles: |a-b| = |b-c| with a=%s, b=%s, c=%s (squared distance %d)"
                    % (list(a), [bx, by], list(c), d2))
            first[d2] = i

    out(True, k, "%d distinct points in the %dx%d grid, no isosceles triangle "
                 "(all %d apexes checked with exact integers)" % (k, N, N, k))


if __name__ == "__main__":
    main()
