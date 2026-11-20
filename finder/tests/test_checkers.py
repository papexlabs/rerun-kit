"""The three family checkers: their probes, and brute-force comparisons on small random objects."""

import itertools
import json
import os
import random
import subprocess
import sys
import tempfile
import unittest

import helpers  # noqa: F401  (sets sys.path)
from common import checker_path

FAMILIES = ("comparator-network", "sum-free-colouring", "constant-weight-code")
WORK = tempfile.mkdtemp(prefix="finder-checker-")


def check(family, obj, params, raw=None):
    """The checker's answer for an object and params (JSON values, or raw object text)."""
    op, pp = os.path.join(WORK, "o.json"), os.path.join(WORK, "p.json")
    with open(op, "w") as fh:
        fh.write(raw if raw is not None else json.dumps(obj))
    with open(pp, "w") as fh:
        fh.write(json.dumps(params))
    out = subprocess.run([sys.executable, "-I", "-S", "-B", checker_path(family), op, pp], capture_output=True,
                         text=True, timeout=120)
    lines = [ln for ln in out.stdout.splitlines() if ln.strip()]
    assert out.returncode == 0 and len(lines) == 1, (out.returncode, out.stdout, out.stderr)
    return json.loads(lines[0])


class Probes(unittest.TestCase):
    def test_every_probe_gives_its_expected_line(self):
        for family in FAMILIES:
            probe = os.path.join(os.path.dirname(checker_path(family)), "probe")
            with open(os.path.join(probe, "cases.json")) as fh:
                cases = json.load(fh)["cases"]
            self.assertGreaterEqual(len(cases), 10)
            for c in cases:
                with self.subTest(family=family, object=c["object"], params=c["params"]):
                    with open(os.path.join(probe, c["object"])) as fh:
                        raw = fh.read()
                    with open(os.path.join(probe, c["params"])) as fh:
                        params = json.load(fh)
                    self.assertEqual(check(family, None, params, raw=raw), json.loads(c["line"]))


def run_network(net, values):
    v = list(values)
    for i, j in net:
        if v[i] > v[j]:
            v[i], v[j] = v[j], v[i]
    return v


class ComparatorNetwork(unittest.TestCase):
    def brute(self, net, n, goal):
        for perm in itertools.permutations(range(n)):
            out = run_network(net, perm)
            if goal == "sort" and out != sorted(out):
                return False
            if goal == "median":
                if n % 2 and out[n // 2] != n // 2:
                    return False
                if n % 2 == 0 and {out[n // 2 - 1], out[n // 2]} != {n // 2 - 1, n // 2}:
                    return False
        return True

    def test_random_networks_agree_with_all_permutations(self):
        rng = random.Random(7)
        agree = valid_seen = 0
        for n in (3, 4, 5, 6):
            for _ in range(60):
                net = [sorted(rng.sample(range(n), 2)) for _ in range(rng.randint(0, 3 * n))]
                if rng.random() < 0.4:
                    net += helpers.batcher(n)
                if rng.random() < 0.2:
                    rng.shuffle(net)
                for goal in ("sort", "median"):
                    want = self.brute(net, n, goal)
                    got = check("comparator-network", {"inputs": n, "comparators": net},
                                {"inputs": n, "goal": goal, "measure": "size"})
                    self.assertEqual(got["valid"], want, (n, goal, net, got))
                    if want:
                        valid_seen += 1
                        self.assertEqual(got["score"], len(net))
                    agree += 1
        self.assertGreater(valid_seen, 20)

    def test_depth_is_the_layer_count(self):
        for n in (5, 9, 16):
            net = helpers.batcher(n)
            got = check("comparator-network", {"inputs": n, "comparators": net},
                        {"inputs": n, "goal": "sort", "measure": "depth"})
            self.assertTrue(got["valid"])
            self.assertEqual(got["score"], helpers.depth(net, n))

    def test_the_example_input_in_a_failure_really_fails(self):
        net = helpers.batcher(10)[:-2]
        got = check("comparator-network", {"inputs": 10, "comparators": net},
                    {"inputs": 10, "goal": "sort", "measure": "size"})
        self.assertFalse(got["valid"])
        bits = got["reason"].split("0-1 input ")[1].split(" ")[0]
        out = run_network(net, [int(b) for b in bits])
        self.assertNotEqual(out, sorted(out))

    def test_refuses_above_its_limits_without_running(self):
        got = check("comparator-network", {"inputs": 33, "comparators": [[0, 1]]},
                    {"inputs": 33, "goal": "sort", "measure": "size"})
        self.assertIn("limit", got["reason"])
        # 32 inputs that open with a chain, not a full layer: 3 x 2^30 vectors to run
        net = [[i, i + 1] for i in range(31)] + helpers.batcher(32)
        got = check("comparator-network", {"inputs": 32, "comparators": net},
                    {"inputs": 32, "goal": "sort", "measure": "size"})
        self.assertFalse(got["valid"])
        self.assertIn("more than this checker's limit", got["reason"])


class SumFree(unittest.TestCase):
    def brute(self, colours, weak):
        n = len(colours)
        col = [None] + colours
        for a in range(1, n + 1):
            for b in range(a, n + 1):
                if a + b <= n and col[a] == col[b] == col[a + b] and not (weak and a == b):
                    return False
        return True

    def test_random_colourings_agree_with_brute_force(self):
        rng = random.Random(11)
        valid_seen = 0
        for _ in range(400):
            k = rng.randint(1, 3)
            n = rng.randint(1, 24)
            base = helpers.schur_colouring(k) + [0] * 40
            colours = base[:n] if rng.random() < 0.5 else [rng.randrange(k) for _ in range(n)]
            for weak in (False, True):
                want = self.brute(colours, weak)
                got = check("sum-free-colouring", {"k": k, "N": n, "colours": colours}, {"colours": k, "weak": weak})
                self.assertEqual(got["valid"], want, (k, colours, weak, got))
                if want:
                    valid_seen += 1
                    self.assertEqual(got["score"], n)
        self.assertGreater(valid_seen, 50)


class ConstantWeight(unittest.TestCase):
    def brute(self, words, d):
        return all(bin(a ^ b).count("1") >= d for a, b in itertools.combinations(words, 2))

    def test_random_codes_agree_with_brute_force_both_ways(self):
        rng = random.Random(13)
        for _ in range(300):
            n = rng.randint(4, 12)
            w = rng.randint(1, n - 1)
            d = 2 * rng.randint(1, min(w, n - w))
            pool = [sum(1 << i for i in c) for c in itertools.combinations(range(n), w)]
            words = rng.sample(pool, min(len(pool), rng.randint(1, 12)))
            want = self.brute(words, d)
            got = check("constant-weight-code", {"n": n, "d": d, "w": w, "codewords": words}, {"n": n, "d": d, "w": w})
            self.assertEqual(got["valid"], want, (n, d, w, words, got))
            if want:
                self.assertEqual(got["score"], len(words))

    def test_greedy_codes_are_valid_with_both_methods(self):
        # a greedy (lexicode) constant-weight code; small d uses the sorted sets, large d the pairs
        for n, d, w in ((12, 4, 5), (14, 6, 6), (16, 10, 8), (16, 12, 8)):
            code = []
            for c in itertools.combinations(range(n), w):
                x = sum(1 << i for i in c)
                if all(bin(x ^ y).count("1") >= d for y in code):
                    code.append(x)
            got = check("constant-weight-code", {"n": n, "d": d, "w": w, "codewords": code}, {"n": n, "d": d, "w": w})
            self.assertTrue(got["valid"], got)
            self.assertEqual(got["score"], len(code))
            x = code[0]
            near = x ^ (x & -x) ^ (1 << max(i for i in range(n) if not x >> i & 1))  # distance 2 from x
            got = check("constant-weight-code", {"n": n, "d": d, "w": w, "codewords": code + [near]},
                        {"n": n, "d": d, "w": w})
            self.assertFalse(got["valid"], got)

    def test_refuses_above_its_step_limits(self):
        rng = random.Random(5)
        words = set()
        while len(words) < 9000:
            words.add(sum(1 << b for b in rng.sample(range(32), 16)))
        got = check("constant-weight-code", {"n": 32, "d": 16, "w": 16, "codewords": sorted(words)},
                    {"n": 32, "d": 16, "w": 16})
        self.assertFalse(got["valid"])
        self.assertIn("more than this checker's limit", got["reason"])


class Lint(unittest.TestCase):
    def test_family_lint_passes(self):
        kit = os.path.dirname(helpers.FINDER)
        families = [os.path.join(kit, "families", f) for f in ("comparator-network", "sum-free-colouring",
                                                               "constant-weight-code")]
        out = subprocess.run([sys.executable, "-I", "-B", os.path.join(kit, "tools", "task_lint.py"), "--family",
                              *families], capture_output=True, text=True, timeout=900)
        self.assertEqual(out.returncode, 0, out.stdout[-2000:])


if __name__ == "__main__":
    unittest.main()
