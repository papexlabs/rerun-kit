#!/usr/bin/env python3
"""Family checker: binary constant-weight codes, A(n, d, w).

    python3 checker.py <object.json> <params.json>

Prints exactly one JSON line {"valid": true|false, "score": <integer>|null, "reason": "..."} and exits 0.

params.json : {"n": n, "d": d, "w": w}       (d even)
object.json : {"n": n, "d": d, "w": w, "codewords": [x_1, x_2, ..., x_M]}
              each x is a whole number 0 <= x < 2^n whose binary form has exactly w ones (bit i is coordinate i);
              no other key, no other kind of value.

Valid when the codewords are distinct, each has weight w, and any two differ in at least d coordinates.
Score: M, the number of codewords. A pass shows A(n, d, w) >= M.

How it is checked: two words of weight w differ in 2(w - s) coordinates when they share s ones, so they are too
close exactly when they share w - d/2 + 1 ones or more. The checker either compares every pair (the number of
shared ones counted exactly), or records every set of w - d/2 + 1 ones of every codeword and finds any set held
twice; it uses whichever takes fewer steps. Exact, deterministic, standard library only, no network, no writes;
reads only its two argument files. Refuses, with a reason and without running, a code whose check would exceed
the limits below.
"""
import itertools
import json
import os
import sys

MAX_LENGTH = 32
MAX_CODEWORDS = 20000
MAX_FILE_BYTES = 400000
PAIR_LIMIT = 4 * 10 ** 7    # pairs compared; measured: see README.md
SUBSET_LIMIT = 5 * 10 ** 6  # sets of shared ones listed and sorted (held in memory); measured: see README.md
POP16 = [bin(v).count("1") for v in range(1 << 16)]


def answer(valid, score, reason):
    sys.stdout.write(json.dumps({"valid": valid, "score": score, "reason": reason}) + "\n")
    sys.exit(0)


class Refused(Exception):
    pass


def _pairs(pairs):
    seen = {}
    for key, value in pairs:
        if key in seen:
            raise Refused("the key \"%s\" appears twice in one JSON object" % str(key)[:40])
        seen[key] = value
    return seen


def _constant(name):
    raise Refused("%s is not a number JSON allows" % name)


def read_json(raw, what):
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise Refused("%s is not UTF-8 text" % what)
    try:
        return json.loads(text, object_pairs_hook=_pairs, parse_constant=_constant)
    except Refused:
        raise
    except (ValueError, RecursionError):
        raise Refused("%s is not JSON" % what)


def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def popcount(x):
    return POP16[x & 0xFFFF] + POP16[(x >> 16) & 0xFFFF]


def read_params(params):
    if not isinstance(params, dict) or set(params) != {"n", "d", "w"}:
        raise Refused("params must be a JSON object with exactly n, d and w")
    n, d, w = params["n"], params["d"], params["w"]
    if not is_int(n) or not 1 <= n <= MAX_LENGTH:
        raise Refused("params.n must be a whole number from 1 to %d (this checker's limit)" % MAX_LENGTH)
    if not is_int(d) or d < 2 or d % 2 or d > 2 * n:
        raise Refused("params.d must be an even whole number from 2 to 2n")
    if not is_int(w) or not 0 <= w <= n:
        raise Refused("params.w must be a whole number from 0 to n")
    return n, d, w


def read_code(obj, n, d, w):
    if not isinstance(obj, dict):
        raise Refused("the object must be a JSON object {\"n\", \"d\", \"w\", \"codewords\": [...]}")
    extra = sorted(set(obj) - {"n", "d", "w", "codewords"})
    if extra:
        raise Refused("the object holds the key \"%s\", which the format does not name (only n, d, w, codewords)"
                      % str(extra[0])[:40])
    if set(obj) != {"n", "d", "w", "codewords"}:
        raise Refused("the object must hold n, d, w and codewords")
    for key, want in (("n", n), ("d", d), ("w", w)):
        if not is_int(obj[key]) or obj[key] != want:
            raise Refused("%s must be the whole number %d" % (key, want))
    words = obj["codewords"]
    if not isinstance(words, list):
        raise Refused("codewords must be a list of whole numbers")
    if len(words) > MAX_CODEWORDS:
        raise Refused("the code has %d codewords; this checker takes at most %d" % (len(words), MAX_CODEWORDS))
    top = 1 << n
    seen = set()
    for k, x in enumerate(words):
        if not is_int(x) or not 0 <= x < top:
            raise Refused("codeword %d is not a whole number from 0 to 2^%d - 1" % (k, n))
        if popcount(x) != w:
            raise Refused("codeword %d (%d) has weight %d, not %d" % (k, x, popcount(x), w))
        if x in seen:
            raise Refused("codeword %d (%d) appears twice" % (k, x))
        seen.add(x)
    return words


def comb(a, b):
    if b < 0 or b > a:
        return 0
    r = 1
    for i in range(b):
        r = r * (a - i) // (i + 1)
    return r


def check(words, n, d, w):
    """None when every two codewords differ in at least d coordinates; else the first pair found too close."""
    m = len(words)
    share = w - d // 2 + 1  # sharing this many ones or more means a distance below d
    if share <= 0:
        return None if m <= 1 else "any two words of weight %d differ in at most %d < %d coordinates" % (w, 2 * w, d)
    drop = w - share  # = d/2 - 1: a word's sets of `share` ones are the word less `drop` of its ones
    pair_steps = m * (m - 1) // 2
    subset_steps = m * comb(w, drop)
    if subset_steps <= SUBSET_LIMIT and subset_steps <= pair_steps:
        parts = []
        for x in words:
            ones = [1 << b for b in range(n) if (x >> b) & 1]
            for removed in itertools.combinations(ones, drop):
                parts.append(x ^ sum(removed))
        parts.sort()
        for k in range(1, len(parts)):
            if parts[k] == parts[k - 1]:
                part = parts[k]
                i, j = [t for t, x in enumerate(words) if x & part == part][:2]
                return pair_text(words, i, j, w)
        return None
    if pair_steps > PAIR_LIMIT:
        raise Refused("checking this code means comparing %d pairs of codewords, more than this checker's limit of "
                      "%d" % (pair_steps, PAIR_LIMIT))
    limit = share - 1
    for i in range(m):
        x = words[i]
        for j in range(i + 1, m):
            if popcount(x & words[j]) > limit:
                return pair_text(words, i, j, w)
    return None


def pair_text(words, i, j, w):
    s = popcount(words[i] & words[j])
    return "codewords %d (%d) and %d (%d) share %d ones, so they differ in only %d coordinates" % (
        i, words[i], j, words[j], s, 2 * (w - s))


def main():
    if len(sys.argv) != 3:
        answer(False, None, "usage: python3 checker.py <object.json> <params.json>")
    object_path = sys.argv[1]
    params_path = sys.argv[2]
    try:
        for path, what in ((object_path, "the object file"), (params_path, "the params file")):
            if not os.path.isfile(path):
                raise Refused("%s cannot be read" % what)
            if os.path.getsize(path) > MAX_FILE_BYTES:
                raise Refused("%s is larger than %d bytes" % (what, MAX_FILE_BYTES))
        with open(object_path, "rb") as fh:
            raw_object = fh.read(MAX_FILE_BYTES + 1)
        with open(params_path, "rb") as fh:
            raw_params = fh.read(MAX_FILE_BYTES + 1)
        n, d, w = read_params(read_json(raw_params, "the params file"))
        words = read_code(read_json(raw_object, "the object file"), n, d, w)
        failure = check(words, n, d, w)
    except Refused as e:
        answer(False, None, str(e))
    except MemoryError:
        answer(False, None, "the checker ran out of memory on this object")
    except Exception:  # a broken object never makes the checker print anything but its one line
        answer(False, None, "the checker could not read this object")
    if failure:
        answer(False, None, failure)
    m = len(words)
    answer(True, m, "%d distinct codewords of length %d and weight %d, any two at distance at least %d, so "
                    "A(%d,%d,%d) >= %d; score = %d" % (m, n, w, d, n, d, w, m, m))


if __name__ == "__main__":
    main()
