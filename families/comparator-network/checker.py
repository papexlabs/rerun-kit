#!/usr/bin/env python3
"""Family checker: comparator networks that sort, or that select the median.

    python3 checker.py <object.json> <params.json>

Prints exactly one JSON line {"valid": true|false, "score": <integer>|null, "reason": "..."} and exits 0.

params.json : {"inputs": n, "goal": "sort" | "median", "measure": "size" | "depth"}
object.json : {"inputs": n, "comparators": [[i, j], ...]}
              comparators in the order they act; each [i, j] has 0 <= i < j < n and puts the smaller of the two
              values on wire i and the larger on wire j. No other key, no other kind of value.

goal "sort"   : every input leaves wires 0..n-1 in increasing order.
goal "median" : odd n, wire (n-1)/2 holds the median of the inputs; even n, wires n/2-1 and n/2 hold the two
                middle values of the inputs, in either order. (Bert Dobbelaere's median selection networks.)
measure       : "size" = the number of comparators; "depth" = the number of layers, the longest chain of
                comparators in which each shares a wire with the one before it.

How it is checked: the 0-1 principle (a comparator network sorts, or selects, every input exactly when it does so
for every input of zeros and ones). All 0-1 inputs are run at once, one Python integer per wire, one bit per input.
The comparators that come first on both of their wires form a first layer; its outputs on 0-1 inputs are exactly
the vectors in which each of its pairs reads 00, 01 or 11, so only those 3^m * 2^(n-2m) vectors are run through
the rest of the network. Exact integer arithmetic, deterministic, standard library only, no network, no writes.
Reads only its two argument files. Refuses, with a reason and without running, any network whose check would
exceed the limits below.
"""
import json
import os
import sys

MAX_INPUTS = 32            # measured: see README.md
MAX_COMPARATORS = 1000
MAX_FILE_BYTES = 200000
CHUNK_POSITIONS = 1 << 22  # 0-1 inputs run together, one bit each, in one Python integer per wire
WORK_LIMIT = 2 * 10 ** 10  # (0-1 inputs to run) x (comparators after the first layer); measured: see README.md
GOALS = ("sort", "median")
MEASURES = ("size", "depth")


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
    if not isinstance(params, dict):
        raise Refused("params must be a JSON object {\"inputs\", \"goal\", \"measure\"}")
    if set(params) != {"inputs", "goal", "measure"}:
        raise Refused("params must hold exactly inputs, goal and measure")
    n, goal, measure = params["inputs"], params["goal"], params["measure"]
    if not is_int(n) or not 2 <= n <= MAX_INPUTS:
        raise Refused("params.inputs must be a whole number from 2 to %d (this checker's limit)" % MAX_INPUTS)
    if goal not in GOALS:
        raise Refused("params.goal must be \"sort\" or \"median\"")
    if measure not in MEASURES:
        raise Refused("params.measure must be \"size\" or \"depth\"")
    return n, goal, measure


def read_network(obj, n):
    if not isinstance(obj, dict):
        raise Refused("the object must be a JSON object {\"inputs\": n, \"comparators\": [[i, j], ...]}")
    extra = sorted(set(obj) - {"inputs", "comparators"})
    if extra:
        raise Refused("the object holds the key \"%s\", which the format does not name (only inputs, comparators)"
                      % str(extra[0])[:40])
    if "inputs" not in obj or "comparators" not in obj:
        raise Refused("the object must hold inputs and comparators")
    if not is_int(obj["inputs"]) or obj["inputs"] != n:
        raise Refused("inputs must be the whole number %d" % n)
    comps = obj["comparators"]
    if not isinstance(comps, list):
        raise Refused("comparators must be a list of [i, j] pairs")
    if len(comps) > MAX_COMPARATORS:
        raise Refused("the network has %d comparators; this checker takes at most %d" % (len(comps), MAX_COMPARATORS))
    network = []
    for k, c in enumerate(comps):
        if not isinstance(c, list) or len(c) != 2 or not is_int(c[0]) or not is_int(c[1]):
            raise Refused("comparator %d is not a pair [i, j] of whole numbers" % k)
        i, j = c
        if not (0 <= i < j < n):
            raise Refused("comparator %d is [%s, %s]; each needs 0 <= i < j < %d" % (k, i, j, n))
        network.append((i, j))
    return network


def depth_of(network, n):
    level = [0] * n
    deepest = 0
    for i, j in network:
        d = max(level[i], level[j]) + 1
        level[i] = level[j] = d
        if d > deepest:
            deepest = d
    return deepest


def repeat(unit, length, times):
    """unit (length bits) written `times` times one after another, lowest first."""
    result, pos, cur, cur_len = 0, 0, unit, length
    while times:
        if times & 1:
            result |= cur << pos
            pos += cur_len
        times >>= 1
        if times:
            cur |= cur << cur_len
            cur_len *= 2
    return result


def plan(network, n):
    """(digits, rest): digits = [(radix, [(wire, values per state)])], rest = comparators after the first layer."""
    first = {}
    for k, (i, j) in enumerate(network):
        first.setdefault(i, k)
        first.setdefault(j, k)
    layer = [k for k, (i, j) in enumerate(network) if first[i] == k and first[j] == k]
    in_layer = set(layer)
    rest = [c for k, c in enumerate(network) if k not in in_layer]
    digits, covered = [], set()
    for k in layer:
        i, j = network[k]
        digits.append((3, [(i, (0, 0, 1)), (j, (0, 1, 1))]))
        covered.update((i, j))
    for w in range(n):
        if w not in covered:
            digits.append((2, [(w, (0, 1))]))
    digits.sort(key=lambda d: min(w for w, _ in d[1]))
    return digits, rest


def check(network, n, goal):
    """None when the network does what `goal` asks for every input; else a reason naming one 0-1 input."""
    if goal == "median" and n < 3:
        return "a median network needs at least 3 inputs"
    digits, rest = plan(network, n)
    total = 1
    for radix, _ in digits:
        total *= radix
    work = total * max(1, len(rest))
    if work > WORK_LIMIT:
        raise Refused("checking this network means running %d 0-1 inputs through %d comparators, more than this "
                      "checker's limit of %d; start the network with a full layer of comparators on disjoint wires "
                      "so fewer inputs need to be run" % (total, len(rest), WORK_LIMIT))
    low, high, block = [], [], 1
    for d in digits:
        if not high and block * d[0] <= CHUNK_POSITIONS:
            low.append(d)
            block *= d[0]
        else:
            high.append(d)
    every = (1 << block) - 1
    patterns, stride = {}, 1
    for radix, wires in low:
        span = radix * stride
        run = (1 << stride) - 1
        for wire, values in wires:
            unit = 0
            for state in range(radix):
                if values[state]:
                    unit |= run << (state * stride)
            patterns[wire] = repeat(unit, span, block // span)
        stride = span
    planes = []  # the number of ones among the low wires, bit-sliced
    if goal == "median":
        for _, wires in low:
            for wire, _ in wires:
                carry = patterns[wire]
                for b in range(len(planes)):
                    planes[b], carry = planes[b] ^ carry, planes[b] & carry
                if carry:
                    planes.append(carry)
    cache = {}

    def at_least(t):
        """Positions whose low wires hold at least t ones."""
        if t <= 0:
            return every
        if t >= 1 << len(planes):
            return 0
        if t not in cache:
            greater, equal = 0, every
            for b in range(len(planes) - 1, -1, -1):
                p = planes[b]
                if (t >> b) & 1:
                    equal &= p
                else:
                    greater |= equal & p
                    equal &= ~p
            cache[t] = greater | equal
        return cache[t]

    states = [0] * len(high)
    while True:
        wire = [0] * n
        ones_high = 0
        for (radix, wires), state in zip(high, states):
            for w, values in wires:
                if values[state]:
                    wire[w] = every
                    ones_high += 1
        for w, p in patterns.items():
            wire[w] = p
        for i, j in rest:
            a, b = wire[i], wire[j]
            wire[i], wire[j] = a & b, a | b
        bad, what = 0, ""
        if goal == "sort":
            for k in range(n - 1):
                bad = wire[k] & ~wire[k + 1]
                if bad:
                    what = "leaves wire %d above wire %d" % (k, k + 1)
                    break
        elif n % 2:
            mid = n // 2
            bad = wire[mid] ^ at_least((n + 1) // 2 - ones_high)
            what = "does not leave the median on wire %d" % mid
        else:
            a, b = n // 2 - 1, n // 2
            bad = ((wire[a] & wire[b]) ^ at_least(n // 2 + 1 - ones_high)) | \
                  ((wire[a] | wire[b]) ^ at_least(n // 2 - ones_high))
            what = "does not leave the two middle values on wires %d and %d" % (a, b)
        if bad:
            return "the network %s for the 0-1 input %s (wire 0 on the left)" % (what, example(bad, low, high, states, n))
        k = len(high) - 1
        while k >= 0:
            states[k] += 1
            if states[k] < high[k][0]:
                break
            states[k] = 0
            k -= 1
        if k < 0:
            return None


def example(bad, low, high, states, n):
    """The 0-1 input at the lowest position of `bad` (it is also the first layer's output there)."""
    pos = (bad & -bad).bit_length() - 1
    bits = [0] * n
    for radix, wires in low:
        state = pos % radix
        pos //= radix
        for w, values in wires:
            bits[w] = values[state]
    for (radix, wires), state in zip(high, states):
        for w, values in wires:
            bits[w] = values[state]
    return "".join(str(b) for b in bits)


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
        n, goal, measure = read_params(read_json(raw_params, "the params file"))
        network = read_network(read_json(raw_object, "the object file"), n)
        failure = check(network, n, goal)
    except Refused as e:
        answer(False, None, str(e))
    except MemoryError:
        answer(False, None, "the checker ran out of memory on this object")
    except Exception:  # a broken object never makes the checker print anything but its one line
        answer(False, None, "the checker could not read this object")
    if failure:
        answer(False, None, failure)
    size, depth = len(network), depth_of(network, n)
    score = size if measure == "size" else depth
    job = "sorts every input" if goal == "sort" else "selects the median of every input"
    answer(True, score, "the network on %d inputs %s (0-1 principle, all inputs); %d comparators, %d layers; "
                        "score = %s = %d" % (n, job, size, depth, measure, score))


if __name__ == "__main__":
    main()
