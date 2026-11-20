"""The reviewer's findings of 20 Nov, one test each: malformed sources, unbounded inputs, strict readings of
"exact" and paced closes, third-party names, links built from paths, and the fetcher's redirects."""

import gzip
import io
import json
import os
import tempfile
import time
import unittest
import urllib.error

import helpers
import fetch
import records
import run
from adapters import brouwer, dobbelaere, leaps
from common import Unavailable, safe_name, safe_path

CONFIG = run.read_json(os.path.join(helpers.FINDER, "config.json"))
FIXTURES = helpers.FIXTURES


def leaps_with(change):
    """An offline fetcher holding the Leaps fixture, its constants.json changed by change(constants)."""
    pages = helpers.leaps_pages()
    constants = json.loads(pages[leaps.DATA + "constants.json"])
    change(constants)
    pages[leaps.DATA + "constants.json"] = json.dumps(constants)
    return helpers.offline_fetcher(pages)


# ---------------------------------------------------------------------------- 3: one bad entry, not the whole run
class MalformedEntries(unittest.TestCase):
    def test_a_bad_leaps_entry_is_dropped_and_the_others_read(self):
        def spoil(c):
            c["schur-6"]["certificates"] = ["not an object", 7, None]
            c["schur-6"]["updates"] = [["a", "list"]]
            c["weak-schur-7"] = ["the whole entry is a list"]
        f = leaps_with(spoil)
        rows, problems = leaps.read_rows(f, "2026-11-20")
        names = {r["constant"] for r in rows}
        self.assertIn("schur-6", names)  # read, with no credit it could trust
        self.assertTrue(rows and "weak-schur-6" in names and "schur-9" in names)
        self.assertNotIn("weak-schur-7", names)
        self.assertTrue([p for p in problems if p.get("row") == "weak-schur-7"])
        s6 = [r for r in rows if r["constant"] == "schur-6"][0]
        self.assertTrue(s6["by"].startswith("as listed in") or s6["by"] == "A. McKenna")

    def test_a_list_valued_source_falls_back_to_the_source_name(self):
        pages = helpers.leaps_pages()
        sources = json.loads(pages[leaps.DATA + "sources.json"])
        sources["mckenna-2026"] = ["a", "list"]
        pages[leaps.DATA + "sources.json"] = json.dumps(sources)
        rows, _ = leaps.read_rows(helpers.offline_fetcher(pages), "2026-11-20")
        s6 = [r for r in rows if r["constant"] == "schur-6"][0]
        self.assertEqual(s6["by"], "as listed in Leaps in Bounds, Schur numbers")

    def test_a_source_that_raises_is_skipped_and_the_others_run(self):
        class Broken:
            NO_OBJECT = "x"

            @staticmethod
            def read_rows(fetcher, today):
                raise KeyError("a field that is not there")
        saved = run.ADAPTERS["brouwer"]
        run.ADAPTERS["brouwer"] = Broken
        try:
            pages = {}
            pages.update(helpers.dobbelaere_pages())
            pages.update(helpers.leaps_pages())
            out = tempfile.mkdtemp()
            self.assertEqual(run.main(["--dry-run", "--offline", "--cache", helpers.offline_fetcher(pages).cache_dir,
                                       "--out", out, "--state", os.path.join(out, "s.json"),
                                       "--validation", os.path.join(out, "v"), "--max-new", "2"]), 0)
        finally:
            run.ADAPTERS["brouwer"] = saved
        plan = run.read_json(os.path.join(out, "plan.json"))
        self.assertTrue([p for p in plan["sourceProblems"] if p.get("source") == "brouwer" and p.get("skipped")])
        self.assertEqual(plan["counts"].get("publish-new"), 2)  # the other two families still made cards
        with open(os.path.join(out, "summary.md")) as fh:
            self.assertIn("source brouwer: skipped today", fh.read())

    def test_an_object_that_breaks_the_card_drops_only_that_row(self):
        class Odd:
            NO_OBJECT = "x"

            @staticmethod
            def fetch_object(fetcher, row):
                return {"k": 6, "N": 1, "colours": {1, 2}}, {"url": "https://x", "licence": None, "copyable": True}
        d = run.decide([helpers.row(source="odd")], {"tasks": []}, CONFIG)[0]
        run.ADAPTERS["odd"] = Odd
        try:
            ctx = run.Context(None, tempfile.mkdtemp(), "2026-11-20",
                              records.FirstSeen(os.path.join(tempfile.mkdtemp(), "s.json")),
                              records.Evidence(tempfile.mkdtemp()), CONFIG)
            self.assertFalse(run.guarded(run.make_card, d, ctx))
        finally:
            del run.ADAPTERS["odd"]
        self.assertEqual((d["decision"], d["gate"]), ("dropped", "object"))
        d = {"decision": "candidate-new", "row": None}
        self.assertFalse(run.guarded(run.make_card, d, None))  # anything raised inside: a dropped row
        self.assertEqual(d["gate"], "entry")

    def test_code_words_are_checked_against_their_length(self):
        with self.assertRaises(Unavailable):
            brouwer.parse_code("$BASE=16\n" + "F" * 5000 + "\n", 20, 6)
        with self.assertRaises(Unavailable):
            brouwer.parse_code("$BASE=16\nFFFFFF\n", 20, 6)  # 24 bits for a word of length 20
        with self.assertRaises(Unavailable):
            brouwer.parse_code("$BASE=2\n" + "1" * 21 + "\n", 20, 6)
        self.assertEqual(brouwer.parse_code("$BASE=16\nFC000\n0003F\n", 20, 6), [0xFC000, 0x3F])


# ---------------------------------------------------------------------------- 4: bounded work
class Bounded(unittest.TestCase):
    def test_a_compressed_witness_is_unpacked_only_up_to_a_limit(self):
        bomb = gzip.compress(b"0" * (40 * 1024 * 1024))
        with self.assertRaises(Unavailable):
            leaps.bounded_decompress(bomb, "w.txt.gz", limit=1024 * 1024)
        self.assertEqual(leaps.bounded_decompress(gzip.compress(b"0120"), "w.gz"), b"0120")

    def test_history_ranges_are_cut_to_the_input_counts_the_lists_have(self):
        page = ("<h3>History</h3><table><tr><td>2026-11-01</td><td>Improvements for sizes between 2 and 30000000, and "
                "2 ... 30000000 inputs.</td></tr></table>")
        started = time.monotonic()
        found = dobbelaere.history_inputs(page, "2026-11-20")
        self.assertLess(time.monotonic() - started, 1.0)
        self.assertEqual(found, set(range(2, dobbelaere.MAX_INPUTS + 1)))

    def test_pathological_pages_parse_in_linear_time(self):
        page = "<h3>Summary table</h3><table>" + "<tr><td>" * 200000 + "</table>"
        started = time.monotonic()
        with self.assertRaises(Unavailable):
            dobbelaere.summary_table(page)
        page = '<a name="d6"><table><tr><th>n\\w</th><th>4</th></tr>' + "<tr><th>9</th><td>" * 100000 + "</table>"
        try:
            brouwer.tables(page)
        except Unavailable:
            pass
        self.assertLess(time.monotonic() - started, 3.0)

    def test_every_body_has_a_size_limit(self):
        big = b"x" * (fetch.MAX_BYTES + 10)

        class Opener:
            def open(self, request, timeout=None):
                if request.full_url.endswith("robots.txt"):
                    raise urllib.error.HTTPError(request.full_url, 404, "x", {}, io.BytesIO(b""))
                return helpers_response(200, big)
        f = fetch.Fetcher(tempfile.mkdtemp(), opener=Opener(), sleep=lambda s: None)
        with self.assertRaises(fetch.FetchError):
            f.get("https://j.org/big")
        self.assertEqual(len(f.get("https://j.org/big2", max_bytes=len(big))[1]), len(big))


def helpers_response(status, body, headers=None):
    class R:
        def __init__(self):
            self.status, self.headers = status, headers or {}

        def read(self, n=-1):
            return body if n < 0 else body[:n]

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False
    return R()


# ---------------------------------------------------------------------------- 5: strict "exact", paced closes
class StrictExact(unittest.TestCase):
    def test_leaps_reads_exact_only_from_a_whole_number_equal_to_both_bounds(self):
        bound = {"latex": "160", "decimal_approx": 160}
        for value in ({}, "", False, 0, {"latex": ""}, {"latex": "161"}, None, [160], {"latex": "160.0"}):
            self.assertFalse(leaps.exact_reading({"exact_value": value}, 160, 160), value)
        self.assertTrue(leaps.exact_reading({"exact_value": bound}, 160, 160))
        self.assertFalse(leaps.exact_reading({"exact_value": bound}, 160, 161))

    def test_brouwer_reads_exact_only_from_its_own_marks(self):
        cell = brouwer.parse_cell("40-40")
        self.assertEqual(brouwer.exact_reading(6, cell), (True, 40, False))
        self.assertEqual(brouwer.exact_reading(6, brouwer.parse_cell("40")), (False, None, True))  # not marked
        self.assertEqual(brouwer.exact_reading(4, brouwer.parse_cell("40.")), (True, None, False))  # the dot
        self.assertEqual(brouwer.exact_reading(4, brouwer.parse_cell("40")), (False, None, False))

    def test_an_unmarked_entry_neither_gets_a_card_nor_closes_one(self):
        r = helpers.row(family="constant-weight-code", params={"n": 14, "d": 6, "w": 4}, value="14",
                        exactUnclear=True, source="brouwer")
        self.assertEqual(run.decide([r], {"tasks": []}, CONFIG)[0]["gate"], "unmarked")
        lst = helpers.published_list("constant-weight-code-14-6-4", "constant-weight-code-14-6-4-r1", value="14",
                                     family="constant-weight-code", params={"n": 14, "d": 6, "w": 4})
        self.assertNotEqual(run.decide([r], {"tasks": [lst]}, CONFIG)[0]["decision"], "pull")


class PacedChanges(unittest.TestCase):
    def setUp(self):
        self.state = records.FirstSeen(os.path.join(tempfile.mkdtemp(), "s.json"))

    def pulls(self, n, open_lists):
        rows = [helpers.row(params={"colours": k, "weak": True}, value=str(10 * k), proved=True) for k in range(n)]
        lists = [helpers.published_list(f"weak-schur-{k}-colours", f"weak-schur-{k}-colours-r1", value=str(10 * k),
                                        params={"colours": k, "weak": True}) for k in range(open_lists)]
        return rows, {"tasks": lists}

    def run_day(self, rows, published, today):
        ds = run.decide(rows, published, CONFIG)
        run.observe(rows, self.state)
        run.pace_changes(ds, published, self.state, today)
        self.state.finish(today)
        return ds

    def test_a_close_needs_the_same_reading_on_two_runs_in_a_row_and_at_most_two_a_run(self):
        rows, published = self.pulls(3, 20)
        day1 = self.run_day(rows, published, "2026-11-20")
        self.assertEqual([d["decision"] for d in day1 if d["slug"].startswith("weak-schur-")][:3], ["waiting"] * 3)
        day2 = self.run_day(rows, published, "2026-11-21")
        pulls = [d for d in day2 if d["decision"] == "pull"]
        self.assertEqual(len(pulls), 2)  # at most two closes a run; the third waits
        self.assertEqual(len([d for d in day2 if d.get("gate") == "close-pending"]), 1)

    def test_a_family_where_more_than_a_fifth_would_change_is_held(self):
        rows, published = self.pulls(3, 10)
        self.run_day(rows, published, "2026-11-20")
        day2 = self.run_day(rows, published, "2026-11-21")
        held = [d for d in day2 if d["decision"] == "odd" and d.get("held") == "pull"]
        self.assertEqual(len(held), 3)
        self.assertIn("would close or move today", held[0]["reason"])
        rows, published = self.pulls(1, 3)  # a single change is never held
        self.run_day(rows, published, "2026-11-22")
        day = self.run_day(rows, published, "2026-11-23")
        self.assertEqual([d["decision"] for d in day if d["slug"] == "weak-schur-0-colours"], ["pull"])


# ---------------------------------------------------------------------------- 8: names, 9: paths
class NamesAndPaths(unittest.TestCase):
    def test_only_plain_names_reach_a_card(self):
        for bad in ("{'name': 'x'}", "https://evil.example/x", "see <b>me</b>", "a‮b", "line\nbreak",
                    "x" * 101, "", None, ["A. B"], 12):
            self.assertIsNone(safe_name(bad), bad)
        for good in ("A. McKenna", "Patric R. J. Östergård", "李 小龍", "O’Brien", "Van Voorhis (4,4) merge"):
            self.assertEqual(safe_name(good), good)

    def test_a_certificate_submitter_that_is_not_a_name_falls_back(self):
        def spoil(c):
            for cert in c["schur-6"]["certificates"]:
                if cert.get("value") == 538:
                    cert["role"] = "discovery"
                    cert["submitted_by"] = {"name": "x"}
        rows, _ = leaps.read_rows(leaps_with(spoil), "2026-11-20")
        s6 = [r for r in rows if r["constant"] == "schur-6"][0]
        self.assertEqual(s6["by"], "as listed in Leaps in Bounds, Schur numbers")
        self.assertNotIn("{", json.dumps(s6["by"]))

    def test_brouwer_labels_with_markup_fall_back(self):
        refs = {"Xy": "<a href='https://evil'>click</a> me, email 2026"}
        cell = brouwer.parse_cell("120<sup>Xy</sup>-130")
        by, _, _ = brouwer.credit(cell, 20, 6, refs, {})
        self.assertEqual(by, "as listed in " + brouwer.SOURCE_NAME)

    def test_dobbelaere_reference_keys_lose_their_brackets_and_odd_text_falls_back(self):
        self.assertTrue(dobbelaere.by_line("sort", "depth", "Size ubound: x, depth ubound: [EM14]").startswith("EM14 ("))
        self.assertTrue(dobbelaere.by_line("sort", "size", "Size ubound: <script>x").startswith("as listed in"))

    def test_links_are_built_only_from_plain_paths_inside_the_source(self):
        self.assertIsNone(safe_path("certificates/schur/../../../evil/x.yml", "certificates/schur/"))
        self.assertIsNone(safe_path("certificates/schur/%2e%2e/x.yml", "certificates/schur/"))
        self.assertIsNone(safe_path("/certificates/schur/x.yml", "certificates/schur/"))

        def spoil(c):
            for cert in c["weak-schur-6"]["certificates"]:
                cert["path"] = "certificates/weak-schur/../../../other-repo/x.yml"
        rows, _ = leaps.read_rows(leaps_with(spoil), "2026-11-20")
        ws6 = [r for r in rows if r["constant"] == "weak-schur-6"][0]
        self.assertIsNone(ws6["objectUrl"])
        self.assertIsNone(ws6["objectRef"])
        with self.assertRaises(Unavailable):
            leaps.fetch_object(None, dict(ws6, objectRef={"path": "certificates/weak-schur/../../x.yml"}))
        for href in ("../evil/x", "https://evil.example/x", "cwc/d6/../../../x"):
            cell = brouwer.parse_cell(f'<a href="{href}">13</a>-15')
            self.assertIsNone(safe_path(cell["href"], "cwc/", max_segments=4))


# ---------------------------------------------------------------------------- 10: redirects
class Redirects(unittest.TestCase):
    def fetcher(self, location, budgets=None):
        class Opener:
            def __init__(self):
                self.calls = []

            def open(self, request, timeout=None):
                self.calls.append((request.full_url, request.get_method(), sorted(request.header_items()),
                                   request.data))
                if request.full_url.endswith("robots.txt"):
                    raise urllib.error.HTTPError(request.full_url, 404, "x", {}, io.BytesIO(b""))
                if request.full_url == "https://a.org/x":
                    raise urllib.error.HTTPError(request.full_url, 302, "x", {"Location": location}, io.BytesIO(b""))
                return helpers_response(200, b"there")
        opener = Opener()
        return fetch.Fetcher(tempfile.mkdtemp(), budgets=budgets or {}, opener=opener, sleep=lambda s: None), opener

    def test_only_https_and_only_known_hosts(self):
        f, opener = self.fetcher("http://a.org/y")
        with self.assertRaises(fetch.FetchError):
            f.get("https://a.org/x")
        f, opener = self.fetcher("https://elsewhere.example/y")
        with self.assertRaises(fetch.FetchError):
            f.get("https://a.org/x")
        self.assertNotIn("https://elsewhere.example/y", [c[0] for c in opener.calls])
        f, opener = self.fetcher("https://b.org/y", budgets={"b.org": 4})
        self.assertEqual(f.text("https://a.org/x")[0], "there")
        f, opener = self.fetcher("/same-host")
        self.assertEqual(f.text("https://a.org/x")[0], "there")

    def test_a_plain_get_and_nothing_else(self):
        f, opener = self.fetcher("/same-host")
        f.get("https://a.org/x")
        for url, method, headers, data in opener.calls:
            self.assertEqual((method, data), ("GET", None))
            self.assertEqual({k.lower() for k, _ in headers}, {"user-agent", "accept-encoding"})
        with self.assertRaises(fetch.FetchError):
            f.get("http://a.org/plain-http")


class Config(unittest.TestCase):
    def test_no_internal_folder_names(self):
        with open(os.path.join(helpers.FINDER, "config.json")) as fh:
            self.assertNotIn("takepart", fh.read())


if __name__ == "__main__":
    unittest.main()
