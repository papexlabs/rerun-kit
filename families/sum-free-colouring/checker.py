#!/usr/bin/env python3
"""Family checker: colourings of 1..N in which every colour is sum-free (Schur and weak Schur numbers).

    python3 checker.py <object.json> <params.json>

Prints exactly one JSON line {"valid": true|false, "score": <integer>|null, "reason": "..."} and exits 0.

params.json : {"colours": k, "weak": false | true}
object.json : {"k": k, "N": N, "colours": [c_1, c_2, ..., c_N]}
              c_i is a whole number from 0 to k - 1, the colour of the integer i. No other key, no other value.

weak false : no colour may hold a, b and c with a + b = c; a = b counts (so no colour holds both a and 2a).
             A pass shows the Schur number S(k) >= N.
weak true  : the same, but only for a != b. A pass shows the weak Schur number WS(k) >= N.
Score: N.

How it is checked: each colour is one Python integer with bit i set when i has that colour; for every member a of
a colour, (colour << a) & colour is the set of members c = a + b with b in the same colour. Exact, deterministic,
standard library only, no network, no writes; reads only its two argument files.
"""
import json
import os
import sys

MAX_COLOURS = 16
MAX_N = 50000
MAX_FILE_BYTES = 400000


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


def read_params(params):
    if not isinstance(params, dict) or set(params) != {"colours", "weak"}:
        raise Refused("params must be a JSON object with exactly colours and weak")
    k, weak = params["colours"], params["weak"]
    if not is_int(k) or not 1 <= k <= MAX_COLOURS:
        raise Refused("params.colours must be a whole number from 1 to %d" % MAX_COLOURS)
    if not isinstance(weak, bool):
        raise Refused("params.weak must be true or false")
    return k, weak


def read_colouring(obj, k):
    if not isinstance(obj, dict):
        raise Refused("the object must be a JSON object {\"k\": k, \"N\": N, \"colours\": [...]}")
    extra = sorted(set(obj) - {"k", "N", "colours"})
    if extra:
        raise Refused("the object holds the key \"%s\", which the format does not name (only k, N, colours)"
                      % str(extra[0])[:40])
    if set(obj) != {"k", "N", "colours"}:
        raise Refused("the object must hold k, N and colours")
    if not is_int(obj["k"]) or obj["k"] != k:
        raise Refused("k must be the whole number %d" % k)
    n = obj["N"]
    if not is_int(n) or not 1 <= n <= MAX_N:
        raise Refused("N must be a whole number from 1 to %d (this checker's limit)" % MAX_N)
    colours = obj["colours"]
    if not isinstance(colours, list) or len(colours) != n:
        raise Refused("colours must be a list of exactly N entries (the colours of 1, 2, ..., N)")
    for i, c in enumerate(colours, 1):
        if not is_int(c) or not 0 <= c < k:
            raise Refused("the colour of %d is not a whole number from 0 to %d" % (i, k - 1))
    return n, colours


def check(n, colours, k, weak):
    """None when every colour is (weakly) sum-free; else the first monochromatic a + b = c found."""
    members = [[] for _ in range(k)]
    for i, c in enumerate(colours, 1):
        members[c].append(i)
    for c in range(k):
        mask = 0
        for i in members[c]:
            mask |= 1 << i
        for a in members[c]:
            hits = (mask << a) & mask
            if weak:
                hits &= ~(1 << (2 * a))
            if hits:
                total = (hits & -hits).bit_length() - 1
                b = total - a
                return "colour %d holds %d, %d and %d = %d + %d" % (c, min(a, b), max(a, b), total, a, b)
    return None


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
        k, weak = read_params(read_json(raw_params, "the params file"))
        n, colours = read_colouring(read_json(raw_object, "the object file"), k)
        failure = check(n, colours, k, weak)
    except Refused as e:
        answer(False, None, str(e))
    except MemoryError:
        answer(False, None, "the checker ran out of memory on this object")
    except Exception:  # a broken object never makes the checker print anything but its one line
        answer(False, None, "the checker could not read this object")
    if failure:
        answer(False, None, failure)
    kind = "weakly sum-free (only a != b counts)" if weak else "sum-free (a = b counts)"
    name = "WS(%d)" % k if weak else "S(%d)" % k
    answer(True, n, "every one of the %d colours of 1..%d is %s, so %s >= %d; score = N = %d"
           % (k, n, kind, name, n, n))


if __name__ == "__main__":
    main()
