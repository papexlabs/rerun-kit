"""The gates: optimality, the second source, the checker on the source's own object, and the card texts."""

import copy
import tempfile
import unittest

import helpers
import cards
import gates
from adapters import leaps
from families import ALL as FAMILIES

WORK = tempfile.mkdtemp(prefix="finder-gates-")


class Values(unittest.TestCase):
    def test_better(self):
        self.assertTrue(gates.better("651", "650", "max"))
        self.assertFalse(gates.better("650", "650", "max"))
        self.assertTrue(gates.better("163", "164", "min"))
        self.assertFalse(gates.better("1.5", "1.25", "min"))


class Proved(unittest.TestCase):
    def test_source_or_second_source(self):
        self.assertIsNotNone(gates.gate_proved(helpers.row(proved=True)))
        self.assertIsNone(gates.gate_proved(helpers.row()))
        r = helpers.row(secondary=[{"name": "OEIS A1 (data)", "value": "650", "exact": True, "url": "https://x"}])
        self.assertIn("exact value", gates.gate_proved(r))


class Second(unittest.TestCase):
    def test_ahead_behind_equal_none(self):
        def sec(v):
            return [{"name": "Other", "value": v, "exact": False, "url": "https://x"}]
        why, notes = gates.gate_second(helpers.row(value="650", secondary=sec("660")))
        self.assertIn("held until they agree", why)
        why, notes = gates.gate_second(helpers.row(value="650", secondary=sec("646")))
        self.assertIsNone(why)
        self.assertIn("is used", notes[0])
        why, notes = gates.gate_second(helpers.row(value="650", secondary=sec("650")))
        self.assertIn("agrees", notes[0])
        why, notes = gates.gate_second(helpers.row(value="650"))
        self.assertEqual(notes, ["no second source for this entry"])
        why, notes = gates.gate_second(helpers.row(family="comparator-network", direction="min", value="164",
                                                   params={"inputs": 29, "goal": "sort", "measure": "size"},
                                                   secondary=sec("163")))
        self.assertIsNotNone(why)  # smaller is better for networks


class Checker(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        f = helpers.offline_fetcher(helpers.leaps_pages())
        rows, _ = leaps.read_rows(f, "2026-11-20")
        cls.row = [r for r in rows if r["constant"] == "weak-schur-6"][0]
        cls.obj, _ = leaps.fetch_object(f, cls.row)

    def test_passes_with_exactly_the_table_value(self):
        why, answer = gates.gate_checker("sum-free-colouring", self.obj, self.row, 30, WORK)
        self.assertIsNone(why)
        self.assertEqual(answer["score"], 650)

    def test_a_different_table_value_is_dropped(self):
        r = dict(self.row, bestKnownValue="651")
        why, _ = gates.gate_checker("sum-free-colouring", self.obj, r, 30, WORK)
        self.assertIn("not the table's 651", why)

    def test_a_broken_object_is_dropped(self):
        broken = dict(self.obj, colours=[0] * 650)
        why, _ = gates.gate_checker("sum-free-colouring", broken, self.row, 30, WORK)
        self.assertIn("rejects the source's own object", why)


class Texts(unittest.TestCase):
    def body(self, family, params, value, direction):
        r = helpers.row(family=family, params=params, value=value, direction=direction, sourceName="Some table",
                        by="A. Person", objectUrl="https://example.org/o.json")
        return cards.build(FAMILIES[family], r)

    def test_every_family_card_fits_at_its_largest(self):
        for family, params, value, direction in (
                ("comparator-network", {"inputs": 32, "goal": "median", "measure": "depth"}, "999", "min"),
                ("sum-free-colouring", {"colours": 16, "weak": True}, "49000", "max"),
                ("constant-weight-code", {"n": 32, "d": 18, "w": 16}, "19999", "max")):
            body = self.body(family, params, value, direction)
            self.assertIsNone(gates.gate_texts(body), (family, gates.gate_texts(body)))
            self.assertLessEqual(gates.howto_bytes(body["list"]["howTo"]), gates.HOWTO_MAX)
            self.assertLessEqual(len(body["list"]["howTo"]["task"]["slug"]), 34)
            self.assertEqual(body["list"]["key"], body["list"]["howTo"]["task"]["slug"] + "-r1")

    def test_words_lengths_and_shapes_are_refused(self):
        base = self.body("sum-free-colouring", {"colours": 6, "weak": True}, "650", "max")
        b = copy.deepcopy(base)
        b["list"]["description"] = "A verified world record, the first."
        why = gates.gate_texts(b)
        for word in ("verified", "world record", "first"):
            self.assertIn(f'"{word}"', why)
        b = copy.deepcopy(base)
        b["list"]["title"] = "x" * 201
        self.assertIn("title is 201 characters", gates.gate_texts(b))
        b = copy.deepcopy(base)
        b["list"]["resultLine"] = "An accepted run."
        self.assertIn("Result: ", gates.gate_texts(b))
        b = copy.deepcopy(base)
        b["list"]["howTo"]["task"]["slug"] = "x" * 35
        self.assertIn("slug", gates.gate_texts(b))
        b = copy.deepcopy(base)
        b["list"]["howTo"]["task"]["bestKnown"]["by"] = "proved by a person"
        self.assertIn("bestKnown.by", gates.gate_texts(b))
        b = copy.deepcopy(base)
        for where, field, limit in ((b["list"]["howTo"], "checkedHow", 600), (b["list"]["howTo"], "requirements", 600),
                                    (b["list"]["howTo"]["task"], "objective", 600),
                                    (b["list"]["howTo"]["task"], "objectFormat", 600),
                                    (b["list"]["howTo"]["task"], "shows", 400),
                                    (b["list"]["howTo"]["task"], "notCovered", 400),
                                    (b["list"]["howTo"]["task"], "effort", 200)):
            where[field] = "\u00e9" * limit  # within each field's limit, but two bytes each in UTF-8
        self.assertIn("howTo is", gates.gate_texts(b))

    def test_manifest_names_the_family_checker(self):
        from common import checker_sha256
        body = self.body("constant-weight-code", {"n": 24, "d": 6, "w": 6}, "532", "max")
        line = body["manifest"]
        self.assertTrue(line.endswith("\n"))
        self.assertIn(checker_sha256("constant-weight-code"), line)
        self.assertEqual(body["list"]["howTo"]["task"]["checkerSha256"], checker_sha256("constant-weight-code"))
        self.assertEqual(body["list"]["howTo"]["task"]["family"], "constant-weight-code")
        self.assertEqual(body["list"]["howTo"]["task"]["params"], {"n": 24, "d": 6, "w": 6})


class Limits(unittest.TestCase):
    def test_static_limits(self):
        net, sf, cw = (FAMILIES[n] for n in ("comparator-network", "sum-free-colouring", "constant-weight-code"))
        self.assertIsNone(net.static_problem({"inputs": 32, "goal": "sort", "measure": "size"}, "185"))
        self.assertIn("above the checker's limit", net.static_problem({"inputs": 33, "goal": "sort",
                                                                       "measure": "size"}, "199"))
        self.assertIsNone(sf.static_problem({"colours": 9, "weak": True}, "22620"))
        self.assertIn("100,000", sf.static_problem({"colours": 11, "weak": False}, "40000"))
        self.assertIsNone(cw.static_problem({"n": 22, "d": 6, "w": 9}, "1827"))
        self.assertIn("100,000", cw.static_problem({"n": 26, "d": 6, "w": 13}, "16254"))
        self.assertIsNotNone(cw.static_problem({"n": 24, "d": 4, "w": 12}, "151484"))


if __name__ == "__main__":
    unittest.main()
