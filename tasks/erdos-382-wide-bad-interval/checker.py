#!/usr/bin/env python3
"""Checker for the task "A wider bad interval" (Erdős problem #382).

Usage:  python3 checker.py object.json

An interval [u, v] of integers is "bad" when the largest prime p dividing
u * (u+1) * ... * v divides that product at least twice (p appears with
exponent >= 2). Problem #382 asks whether v - u can be arbitrarily large.

The object is a JSON file:
    {"u": <int>, "v": <int>,
     "factorizations": {"<m>": [[p1, e1], [p2, e2], ...], ...}}
with one entry for every integer m with u <= m <= v (keys are decimal strings),
listing the full prime factorization of m with primes in increasing order. No other
key: an accepted object is shown publicly, so it holds nothing the format does not name.
The width v - u is at most 300, so that an object stays within the 100,000 bytes a result
file may carry for it.

The checker verifies every factorization exactly (the product equals m, every
listed p is prime by a deterministic Miller-Rabin test that is proven correct
below 3.18e23, every exponent >= 1), finds the largest prime p in the whole
product and its total exponent. Valid when that exponent is >= 2.
Score = v - u (larger is better).

Standard library only, exact integer arithmetic, deterministic, no network,
reads only the file given as argv[1]. Prints one JSON line and exits 0.
"""
import json
import os
import sys

MAX_BYTES = 2_000_000
MAX_WIDTH = 300                        # v - u (at most 100,000 bytes of object; was 1000)
V_LIMIT = 300_000_000_000_000_000_000_000   # 3e23 < 318665857834031151167461 (see is_prime)
BASES = (2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41)


def out(valid, score, reason):
    print(json.dumps({"valid": valid, "score": score, "reason": reason}))
    sys.exit(0)


def is_prime(n):
    """Deterministic for n < 318665857834031151167461 (strong pseudoprime bound for the
    first 12 prime bases, Sorenson and Webster 2015); 13 bases are used here."""
    if n < 2:
        return False
    for p in BASES:
        if n % p == 0:
            return n == p
    d, s = n - 1, 0
    while d % 2 == 0:
        d //= 2
        s += 1
    for a in BASES:
        x = pow(a, d, n)
        if x == 1 or x == n - 1:
            continue
        for _ in range(s - 1):
            x = x * x % n
            if x == n - 1:
                break
        else:
            return False
    return True


def is_int(x):
    return isinstance(x, int) and not isinstance(x, bool)


def check(obj):
    """Return (valid, score, reason). Pure function, no I/O."""
    if not isinstance(obj, dict):
        return False, None, "object must be a JSON object"
    if set(obj) != {"u", "v", "factorizations"}:
        return False, None, "the object must hold exactly the keys u, v and factorizations"
    u, v, facs = obj.get("u"), obj.get("v"), obj.get("factorizations")
    if not (is_int(u) and is_int(v)):
        return False, None, "u and v must be integers"
    if not (2 <= u <= v):
        return False, None, "need 2 <= u <= v"
    if v >= V_LIMIT:
        return False, None, "v must be below 3e23 (range where the primality test is proven)"
    if v - u > MAX_WIDTH:
        return False, None, "v - u must be at most %d" % MAX_WIDTH
    if not isinstance(facs, dict):
        return False, None, "factorizations must be an object keyed by the decimal integers u..v"
    expected = {str(m) for m in range(u, v + 1)}
    if set(facs.keys()) != expected:
        missing = sorted(expected - set(facs.keys()), key=int)[:3]
        extra = sorted(set(facs.keys()) - expected)[:3]
        return False, None, "factorizations must have exactly the keys u..v (missing %s, extra %s)" % (missing, extra)
    prime_ok = {}
    largest, total = 0, 0
    for m in range(u, v + 1):
        f = facs[str(m)]
        if not isinstance(f, list) or not f:
            return False, None, "factorization of %d must be a non-empty list of [p, e]" % m
        prod, last = 1, 1
        for pe in f:
            if not (isinstance(pe, list) and len(pe) == 2 and is_int(pe[0]) and is_int(pe[1])):
                return False, None, "factorization of %d: each entry must be [p, e] with integers" % m
            p, e = pe
            if e < 1 or e > 200:
                return False, None, "factorization of %d: exponent of %d out of range" % (m, p)
            if p <= last:
                return False, None, "factorization of %d: primes must be strictly increasing" % m
            last = p
            if p > m:
                return False, None, "factorization of %d: factor %d exceeds m" % (m, p)
            if p not in prime_ok:
                prime_ok[p] = is_prime(p)
            if not prime_ok[p]:
                return False, None, "factorization of %d: %d is not prime" % (m, p)
            prod *= p ** e
            if prod > m:
                return False, None, "factorization of %d: product exceeds m" % m
        if prod != m:
            return False, None, "factorization of %d: product is %d, not %d" % (m, prod, m)
        largest = max(largest, f[-1][0])
    total = 0
    for m in range(u, v + 1):
        for p, e in facs[str(m)]:
            if p == largest:
                total += e
    if total >= 2:
        return True, v - u, ("bad interval: largest prime %d divides the product %d times; v - u = %d"
                             % (largest, total, v - u))
    return False, None, "not bad: largest prime %d divides the product only once" % largest


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
    except Exception as e:
        out(False, None, "cannot read object as JSON: %s" % type(e).__name__)
    try:
        valid, score, reason = check(obj)
    except Exception as e:
        out(False, None, "checker error on this object: %s" % type(e).__name__)
    out(valid, score, reason)


if __name__ == "__main__":
    main()
