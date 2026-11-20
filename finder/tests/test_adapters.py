"""The source adapters against saved or hand-written copies of the sources (no network)."""

import json
import unittest

import helpers
from adapters import brouwer, dobbelaere, leaps
from common import Unavailable, canonical_bytes
from gates import run_checker

import tempfile

WORK = tempfile.mkdtemp(prefix="finder-adapters-")


def by_params(rows):
    return {json.dumps(r["params"], sort_keys=True): r for r in rows}


def key(**p):
    return json.dumps(p, sort_keys=True)


class Dobbelaere(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.f = helpers.offline_fetcher(helpers.dobbelaere_pages())
        cls.rows, cls.problems = dobbelaere.read_rows(cls.f, "2026-11-20")
        cls.idx = by_params(cls.rows)

    def test_rows_and_proofs_of_optimality(self):
        self.assertEqual(self.problems, [])
        self.assertEqual(len(self.rows), 12)  # 4 sorting sizes x 2 measures + 2 median sizes x 2
        r = self.idx[key(inputs=4, goal="sort", measure="size")]
        self.assertTrue(r["provedOptimal"])
        r = self.idx[key(inputs=13, goal="sort", measure="size")]
        self.assertFalse(r["provedOptimal"])
        self.assertEqual(r["upperOrLowerLimit"], 44)
        self.assertEqual(r["bestKnownValue"], str(len(helpers.batcher(13))))
        self.assertTrue(self.idx[key(inputs=13, goal="sort", measure="depth")]["provedOptimal"])
        median3 = self.idx[key(inputs=3, goal="median", measure="size")]  # a comment that mentions optimality:
        self.assertEqual((median3["provedOptimal"], median3["softExact"]), (False, True))  # no card, never a close
        self.assertFalse(self.idx[key(inputs=11, goal="median", measure="size")]["provedOptimal"])

    def test_recent_entries_come_from_the_dated_history(self):
        self.assertTrue(self.idx[key(inputs=20, goal="sort", measure="size")]["recent"])
        self.assertFalse(self.idx[key(inputs=13, goal="sort", measure="size")]["recent"])  # 2019: too old
        self.assertTrue(self.idx[key(inputs=11, goal="median", measure="depth")]["recent"])  # "between 10 and 12"

    def test_credit_comes_from_the_comments_cell(self):
        self.assertTrue(self.idx[key(inputs=20, goal="sort", measure="size")]["by"].startswith("SorterHunter"))
        self.assertTrue(self.idx[key(inputs=20, goal="sort", measure="depth")]["by"].startswith("EM14 (as given"))
        self.assertTrue(self.idx[key(inputs=4, goal="sort", measure="size")]["by"].startswith("B. Dobbelaere"))

    def test_object_is_converted_and_passes_with_the_table_value(self):
        r = self.idx[key(inputs=20, goal="sort", measure="size")]
        obj, meta = dobbelaere.fetch_object(self.f, r)
        self.assertEqual(obj, {"inputs": 20, "comparators": helpers.batcher(20)})
        self.assertTrue(meta["copyable"])
        answer = run_checker("comparator-network", canonical_bytes(obj), r["params"], 60, WORK)
        self.assertEqual(str(answer["score"]), r["bestKnownValue"])
        self.assertIn("/blob/master/Networks/Sorters/", r["objectUrl"])  # a path that stays the same

    def test_a_file_whose_hash_does_not_match_the_tree_is_refused(self):
        r = dict(self.idx[key(inputs=20, goal="sort", measure="size")])
        r["objectRef"] = dict(r["objectRef"], blob="0" * 40)
        with self.assertRaises(Exception):
            dobbelaere.fetch_object(self.f, r)

    def test_bounds_cells(self):
        self.assertEqual(dobbelaere.bounds("<b>25</b>"), (25, 25, True))
        self.assertEqual(dobbelaere.bounds("44&hellip;45"), (44, 45, False))
        with self.assertRaises(Unavailable):
            dobbelaere.bounds("about 44")


class Leaps(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.f = helpers.offline_fetcher(helpers.leaps_pages())
        cls.rows, cls.problems = leaps.read_rows(cls.f, "2026-11-20")
        cls.idx = {r["constant"]: r for r in cls.rows}

    def test_rows(self):
        self.assertEqual(self.problems, [])
        self.assertEqual(sorted(self.idx), ["schur-5", "schur-6", "schur-9", "weak-schur-6", "weak-schur-7"])
        self.assertTrue(self.idx["schur-5"]["provedOptimal"])
        s6 = self.idx["schur-6"]
        self.assertEqual((s6["bestKnownValue"], s6["provedOptimal"], s6["upperOrLowerLimit"]), ("538", False, 1836))
        self.assertEqual(s6["by"], "A. McKenna")
        self.assertEqual(s6["year"], 2026)
        self.assertIsNone(self.idx["schur-9"]["objectRef"])  # literature only: no witness

    def test_oeis_as_second_source(self):
        self.assertEqual(self.idx["schur-5"]["secondary"][0]["exact"], True)
        self.assertEqual(self.idx["schur-5"]["secondary"][0]["value"], "160")
        sec = self.idx["schur-6"]["secondary"][0]
        self.assertEqual((sec["value"], sec["exact"]), ("537", False))  # the largest "a(6) >= v"
        self.assertEqual(self.idx["weak-schur-6"]["secondary"][0]["value"], "646")
        self.assertEqual(self.idx["weak-schur-7"]["secondary"][0]["value"], "2146")

    def test_witness_is_read_and_passes_with_the_table_value(self):
        r = self.idx["weak-schur-6"]
        obj, meta = leaps.fetch_object(self.f, r)
        self.assertEqual((obj["k"], obj["N"]), (6, 650))
        answer = run_checker("sum-free-colouring", canonical_bytes(obj), r["params"], 30, WORK)
        self.assertEqual(answer["score"], 650)
        self.assertTrue(meta["copyable"])

    def test_no_witness_means_no_object(self):
        with self.assertRaises(Unavailable):
            leaps.fetch_object(self.f, self.idx["schur-9"])

    def test_sorting_values_as_second_source(self):
        second = leaps.sorting_secondary(self.f)
        self.assertEqual(second[(12, "size")], (39, True))
        self.assertFalse(second[(20, "size")][1])

    def test_certificate_reader(self):
        fields = leaps.yaml_fields("constant: schur-3\nbound: lower\nvalue: 13\nkind: witness\nwitness:\n"
                                   "  format: coloring\n  data: '0110222220110'\nnotes: >-\n  a long note\n"
                                   "  over two lines\nsubmitted_by: x\n")
        self.assertEqual(fields["witness.format"], "coloring")
        self.assertEqual(fields["witness.data"], "0110222220110")
        self.assertEqual(fields["notes"], "a long note\nover two lines")
        with self.assertRaises(Unavailable):
            leaps.yaml_fields("witness:\n  file:\n    deeper: 1\n")

    def test_authors(self):
        self.assertEqual(leaps.authors("Z. Chen, L. Zhu and F. Long, A new lower bound, arXiv."),
                         "Z. Chen, L. Zhu and F. Long")
        self.assertEqual(leaps.authors("S.E. Rodrigo, A new lower bound for WS(6)."), "S.E. Rodrigo")
        self.assertIsNone(leaps.authors("Trivial or easy."))


class Brouwer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.f = helpers.offline_fetcher(helpers.brouwer_pages())
        cls.rows, cls.problems = brouwer.read_rows(cls.f, "2026-11-20")
        cls.idx = by_params(cls.rows)

    def test_cells(self):
        self.assertEqual(len(self.problems), 1)  # the "??" cell
        self.assertIn("not understood", self.problems[0]["reason"])
        self.assertTrue(self.idx[key(n=7, d=4, w=3)]["provedOptimal"])  # "7." (the dot)
        h8 = self.idx[key(n=8, d=4, w=4)]
        self.assertFalse(h8["provedOptimal"])
        self.assertIsNone(h8["upperOrLowerLimit"])  # d = 4: lower bounds only
        pg = self.idx[key(n=13, d=6, w=4)]
        self.assertEqual((pg["bestKnownValue"], pg["upperOrLowerLimit"], pg["provedOptimal"]), ("13", 15, False))
        single = self.idx[key(n=14, d=6, w=4)]  # a single number: not marked exact or open
        self.assertEqual((single["provedOptimal"], single["exactUnclear"]), (False, True))
        no_upper = self.idx[key(n=14, d=6, w=5)]
        self.assertEqual((no_upper["provedOptimal"], no_upper["upperOrLowerLimit"]), (False, None))  # "28-..."
        self.assertIsNone(self.idx[key(n=13, d=6, w=5)]["objectRef"])  # no link

    def test_credit_from_the_legend(self):
        h8 = self.idx[key(n=8, d=4, w=4)]
        self.assertEqual((h8["by"], h8["year"], h8["recent"]), ("Ann Body (as given on Brouwer's table)", 2026, True))
        pg = self.idx[key(n=13, d=6, w=4)]
        self.assertEqual((pg["by"], pg["year"], pg["recent"]), ("Olga Lder (as given on Brouwer's table)", 1999, False))
        self.assertIn("construction s", self.idx[key(n=13, d=6, w=5)]["by"])

    def test_codes_are_read_in_both_formats_and_pass(self):
        for p, want in ((key(n=8, d=4, w=4), 14), (key(n=13, d=6, w=4), 13)):
            r = self.idx[p]
            obj, meta = brouwer.fetch_object(self.f, r)
            self.assertEqual(len(obj["codewords"]), want)
            self.assertFalse(meta["copyable"])  # no licence: linked, never copied
            answer = run_checker("constant-weight-code", canonical_bytes(obj), r["params"], 60, WORK)
            self.assertEqual(str(answer["score"]), r["bestKnownValue"])

    def test_orbit_representatives_are_binary_numbers(self):
        # generator (0,1) fixes {0,1} and {2,3}: read as a binary number "0011" is {0,1} = 3, not {2,3} = 12
        self.assertEqual(brouwer.parse_code("$EXEC orbit\n(0,1)\n..\n0011\n", 4, 2), [3])
        self.assertEqual(sorted(brouwer.parse_code("$EXEC orbit\n(0,2)\n..\n0011\n", 4, 2)), [3, 6])
        with self.assertRaises(Unavailable):
            brouwer.parse_code("$SOMETHING\n1\n", 4, 2)

    def test_cell_grammar(self):
        c = brouwer.parse_cell('<a href="cwc/d6/x">133</a><sup>R</sup>-183<sup>Cha</sup>')
        self.assertEqual((c["lower"], c["upper"], c["href"], c["lowerLabels"], c["upperLabels"]),
                         (133, 183, "cwc/d6/x", ["R"], ["Cha"]))
        c = brouwer.parse_cell('<a href="cwc/d4/i24.6">7084</a>.<sup>g</sup>')
        self.assertTrue(c["dot"])
        self.assertIsNone(brouwer.parse_cell("&nbsp;"))


if __name__ == "__main__":
    unittest.main()
