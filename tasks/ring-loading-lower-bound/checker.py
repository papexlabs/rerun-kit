#!/usr/bin/env python3
"""Checker: lower bound for the ring loading constant (Schrijver-Seymour-Winkler beta,
called C in problem 61 of the AlphaEvolve repository of problems).

Object (JSON file given as argv[1]):
  {"pairs": [[u1, v1], [u2, v2], ..., [um, vm]]}     with 2 <= m <= 20
  Each u, v is a JSON number written in decimal (read exactly, digit for digit, never
  through binary floating point) or a string "p/q" or a decimal string. u, v >= 0.
  An exponent (1e-05) is accepted only if its size is at most 60. No other key: an
  accepted object is shown publicly, so it holds nothing the format does not name.

Instance used: as in the source's own scoring code, a pair with u + v > 1 is scaled
exactly to (u/(u+v), v/(u+v)); every other pair is used as given, so every scored
instance satisfies u_i + v_i <= 1. Zero pairs (0, 0) are allowed; they never change
the score.

Score (Skutella's "additive performance", arXiv 1405.0789, Section 2):
  alpha = min over all 2^m choices z_i in {v_i, -u_i} of
          max over k = 1..m of | (z_1 + ... + z_k) - (z_{k+1} + ... + z_m) |.
The term k changes the load on edge {k, k+1} of the ring (and minus it on the opposite
edge), so k = 1..m covers all 2m edges. The k = m term is |z_1 + ... + z_m|.
Every instance shows beta >= alpha.
(The AlphaEvolve notebook's compute_alpha_exact uses k = 1..m-1 only, which leaves out
two edges of the ring and can score the same instance lower; see RESOURCED.md.)

All arithmetic is exact (integers after clearing denominators). The search is a full
enumeration of the 2^m choices with a safe pruning rule (a branch is cut only when a
lower bound for all its completions is already >= the best value found).

Output: one JSON line {"valid", "score", "reason"}, exit 0. The reason gives alpha as an
exact reduced fraction. score is alpha written exactly when its decimal expansion ends
within 18 places (9/8 is 1.125), otherwise alpha rounded DOWN to 18 decimals: never above
alpha, so a score above the best known value always means alpha is above it. The kit and
Papex's runner compare the score with the best known value exactly; the checker does not
(the best known value moves from round to round).

Standard library only, no network, reads only argv[1].
"""
import json
import os
import re
import sys
from fractions import Fraction
from math import gcd

MAX_BYTES = 20_000
MIN_M, MAX_M = 2, 20
MAX_LITERAL = 80
MAX_EXPONENT = 60
MAX_DEN_BITS = 2048
EXACT_PLACES = 18  # the most decimals a score may have on Papex
ROUND_PLACES = 18

DECIMAL_RE = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE]([+-]?\d+))?$")
RATIO_RE = re.compile(r"^[+-]?\d+\s*/\s*[+-]?\d+$")


def out(valid, score, reason):
    # score is passed preformatted (decimal text) or None, so no binary rounding occurs
    print('{"valid": %s, "score": %s, "reason": %s}'
          % ("true" if valid else "false", "null" if score is None else score, json.dumps(reason)))
    sys.exit(0)


class BadLiteral(ValueError):
    pass


def literal_to_fraction(s):
    """Exact rational from a decimal or p/q literal, with a bounded exponent."""
    s = s.strip()
    if len(s) > MAX_LITERAL:
        raise BadLiteral("literal longer than %d characters" % MAX_LITERAL)
    m = DECIMAL_RE.match(s)
    if m:
        if m.group(1) is not None and abs(int(m.group(1))) > MAX_EXPONENT:
            raise BadLiteral("exponent larger than %d" % MAX_EXPONENT)
        return Fraction(s)
    if RATIO_RE.match(s):
        try:
            return Fraction(s.replace(" ", ""))
        except ZeroDivisionError:
            raise BadLiteral("zero denominator")
    raise BadLiteral("cannot read %r as an exact rational" % s)


def json_float(s):
    return ("float", s)


def reject_constant(name):
    raise BadLiteral("constant %s is not allowed" % name)


def to_fraction(v, where):
    if isinstance(v, bool):
        out(False, None, "%s: booleans are not numbers" % where)
    if isinstance(v, int):
        if abs(v) >= 10 ** MAX_LITERAL:
            out(False, None, "%s: integer longer than %d digits" % (where, MAX_LITERAL))
        return Fraction(v)
    if isinstance(v, tuple) and len(v) == 2 and v[0] == "float":
        text = v[1]
    elif isinstance(v, str):
        text = v
    else:
        out(False, None, "%s: expected a number or a string, got %s" % (where, type(v).__name__))
    try:
        return literal_to_fraction(text)
    except BadLiteral as e:
        out(False, None, "%s: %s" % (where, e))


def floor_decimal(num, den, places):
    """num/den >= 0 rounded down to `places` decimals, as text."""
    q = (num * 10 ** places) // den
    s = str(q).rjust(places + 1, "0")
    return s[:-places] + "." + s[-places:]


def exact_decimal(fr, max_places):
    """fr >= 0 as an exact decimal string if it has at most max_places decimals, else None."""
    d = fr.denominator
    twos = fives = 0
    while d % 2 == 0:
        d //= 2
        twos += 1
    while d % 5 == 0:
        d //= 5
        fives += 1
    if d != 1:
        return None
    places = max(twos, fives)
    if places > max_places:
        return None
    if places == 0:
        return str(fr.numerator) + ".0"
    return floor_decimal(fr.numerator, fr.denominator, places)


def check(obj):
    if not isinstance(obj, dict):
        out(False, None, "top level must be a JSON object")
    if set(obj) != {"pairs"}:
        out(False, None, "the object must hold exactly the key pairs")
    pairs = obj.get("pairs")
    if not isinstance(pairs, list):
        out(False, None, "field pairs must be a list of [u, v] pairs")
    m = len(pairs)
    if not (MIN_M <= m <= MAX_M):
        out(False, None, "need %d <= m <= %d pairs, got %d" % (MIN_M, MAX_M, m))

    U, V = [], []
    scaled = 0
    for i, p in enumerate(pairs):
        if not (isinstance(p, list) and len(p) == 2):
            out(False, None, "pair %d is not a list [u, v]" % i)
        u = to_fraction(p[0], "pair %d u" % i)
        v = to_fraction(p[1], "pair %d v" % i)
        if u < 0 or v < 0:
            out(False, None, "pair %d has a negative entry" % i)
        s = u + v
        if s > 1:
            u, v = u / s, v / s
            scaled += 1
        U.append(u)
        V.append(v)

    # clear denominators: everything becomes an integer multiple of 1/D
    D = 1
    for x in U + V:
        d = x.denominator
        D = D * d // gcd(D, d)
        if D.bit_length() > MAX_DEN_BITS:
            out(False, None, "common denominator of all entries has more than %d bits "
                             "(use shorter decimals or smaller fractions)" % MAX_DEN_BITS)
    Ui = [int(x * D) for x in U]
    Vi = [int(x * D) for x in V]

    # suffix sums for the range of the final total T
    sufU = [0] * (m + 1)
    sufV = [0] * (m + 1)
    for i in range(m - 1, -1, -1):
        sufU[i] = sufU[i + 1] + Ui[i]
        sufV[i] = sufV[i + 1] + Vi[i]

    # Work with 2*S_k and T (units of 1/D): the term for k is |2*S_k - T|, k = 1..m.
    best = [None]   # smallest max_k |2 S_k - T| found so far

    def lower_bound(depth, S, lo2, hi2):
        # Every completion has its total T in [Tlo, Thi]. The values 2*S_k fixed so far
        # (k = 1..depth) have min lo2 and max hi2. For every completion,
        # max_k |2 S_k - T| >= max(T - lo2, hi2 - T) >= max(Tlo - lo2, hi2 - Thi),
        # and the k = m term is |T| >= the distance from 0 to [Tlo, Thi].
        Tlo = S - sufU[depth]
        Thi = S + sufV[depth]
        lb = max(Tlo, -Thi, 0)
        if lo2 is not None:
            lb = max(lb, Tlo - lo2, hi2 - Thi)
        return lb

    def dfs(depth, S, lo2, hi2):
        if depth == m:
            T = S                      # 2*S_m = 2T lies in [lo2, hi2], so this includes |T|
            val = max(T - lo2, hi2 - T)
            if best[0] is None or val < best[0]:
                best[0] = val
            return
        if best[0] is not None and lower_bound(depth, S, lo2, hi2) >= best[0]:
            return
        # a (0, 0) pair has one choice only (both are 0), so it is not explored twice
        choices = (0,) if (Ui[depth] == 0 and Vi[depth] == 0) else (Vi[depth], -Ui[depth])
        for z in choices:
            S2 = S + z                 # the prefix sum S_k with k = depth + 1 (k = 1..m)
            t = 2 * S2
            nlo = t if (lo2 is None or t < lo2) else lo2
            nhi = t if (hi2 is None or t > hi2) else hi2
            dfs(depth + 1, S2, nlo, nhi)

    dfs(0, 0, None, None)
    alpha = Fraction(best[0], D)
    exact = str(alpha)                 # "9/8", or "1" for an integer
    dec = exact_decimal(alpha, EXACT_PLACES)
    if dec is not None:
        score = dec
        how = "alpha = %s = %s exactly" % (exact, dec)
    else:
        score = floor_decimal(alpha.numerator, alpha.denominator, ROUND_PLACES)
        how = ("alpha = %s = %s... (score is alpha rounded down to %d decimals)"
               % (exact, floor_decimal(alpha.numerator, alpha.denominator, 30), ROUND_PLACES))
    out(True, score,
        "m = %d pairs (%d scaled so that u+v = 1); k = 1..m; exact minimum over all 2^%d sign "
        "choices: %s; so beta >= %s" % (m, scaled, m, how, exact))


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
            text = f.read()
        obj = json.loads(text, parse_float=json_float, parse_constant=reject_constant)
    except BadLiteral as e:
        out(False, None, "not accepted: %s" % e)
    except (ValueError, OSError, RecursionError) as e:
        out(False, None, "not valid JSON: %s" % e)
    try:
        check(obj)
    except SystemExit:
        raise
    except Exception as e:  # never crash: report and exit 0
        out(False, None, "checker error on this object: %s" % type(e).__name__)


if __name__ == "__main__":
    main()
