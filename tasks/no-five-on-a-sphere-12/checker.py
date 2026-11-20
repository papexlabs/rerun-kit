#!/usr/bin/env python3
"""Checker: "no 5 on a sphere" in the 12 x 12 x 12 grid.

Object (JSON file given as argv[1]):
  {"n": 12, "points": [[x, y, z], ...]}
  x, y, z are integers with 0 <= x, y, z <= 11 (the grid {1..12}^3 shifted by -1, as
  the source publishes it; a shift moves spheres to spheres and planes to planes).
  Any other key makes the object invalid: an accepted object is shown publicly, so it holds
  nothing the format does not name.

Valid when the points are distinct and no 5 of them lie on one sphere or one plane.
Score = number of points (higher is better).

Test used, exactly as in the source's verifier but in exact integers: five points
p1..p5 lie on a common sphere or plane if and only if the 5x5 determinant with rows
(x, y, z, x^2 + y^2 + z^2, 1) is zero. Every 5-point subset is tested. To keep the
run short the determinant is expanded along the fifth row: for each 4-point subset the
five cofactors are computed once, then each later point costs one dot product.

More than 4n points can never be valid (some plane z = c would hold 5 of them), so such
objects are rejected without the full search. Standard library only, no network, reads
only argv[1]. Prints one JSON line and exits 0.
"""
import itertools
import json
import os
import sys

N = 12
MAX_POINTS = 4 * N
MAX_BYTES = 20_000


def out(valid, score, reason):
    print(json.dumps({"valid": valid, "score": score, "reason": reason}))
    sys.exit(0)


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def det3(a, b, c):
    return (a[0] * (b[1] * c[2] - b[2] * c[1])
            - a[1] * (b[0] * c[2] - b[2] * c[0])
            + a[2] * (b[0] * c[1] - b[1] * c[0]))


def det4(r):
    # Laplace expansion along the first row of a 4x4 integer matrix.
    total = 0
    for j in range(4):
        if r[0][j] == 0:
            continue
        minor = [[r[i][k] for k in range(4) if k != j] for i in (1, 2, 3)]
        term = r[0][j] * det3(minor[0], minor[1], minor[2])
        total += term if j % 2 == 0 else -term
    return total


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
    if not is_int(obj.get("n")) or obj.get("n") != N:
        out(False, None, "field n must be the integer %d" % N)
    pts = obj.get("points")
    if not isinstance(pts, list) or len(pts) == 0:
        out(False, None, "field points must be a non-empty list")
    if len(pts) > MAX_POINTS:
        out(False, None, "%d points: more than 4n = %d points always put 5 on one plane z = c"
            % (len(pts), MAX_POINTS))

    seen = set()
    rows = []
    for i, p in enumerate(pts):
        if not (isinstance(p, list) and len(p) == 3 and all(is_int(v) for v in p)):
            out(False, None, "point %d is not a triple of integers: %r" % (i, p))
        x, y, z = p
        if not all(0 <= v < N for v in (x, y, z)):
            out(False, None, "point %d = %s is outside 0..%d" % (i, p, N - 1))
        if (x, y, z) in seen:
            out(False, None, "point %d = %s appears twice" % (i, p))
        seen.add((x, y, z))
        rows.append((x, y, z, x * x + y * y + z * z, 1))

    k = len(rows)
    tested = 0
    for quad in itertools.combinations(range(k), 4):
        R = [rows[q] for q in quad]
        # cofactors of the fifth row in the 5x5 matrix [R; r]
        cof = []
        for c in range(5):
            minor = [[row[j] for j in range(5) if j != c] for row in R]
            sign = 1 if (4 + c) % 2 == 0 else -1
            cof.append(sign * det4(minor))
        last = quad[3]
        for m in range(last + 1, k):
            r = rows[m]
            d = r[0] * cof[0] + r[1] * cof[1] + r[2] * cof[2] + r[3] * cof[3] + r[4] * cof[4]
            tested += 1
            if d == 0:
                bad = [list(pts[q]) for q in quad] + [list(pts[m])]
                out(False, None, "5 points on one sphere or plane: %s" % bad)

    out(True, k, "%d distinct points in the %dx%dx%d grid; all %d five-point subsets have "
                 "a nonzero exact determinant" % (k, N, N, N, tested))


if __name__ == "__main__":
    main()
