"""The planner: decisions (new, moved, proved optimal, Papex ahead, withdrawn runs), pacing across sub-families,
cards without a linked object, fixed bodies on a retry, and whole runs (dry, and --publish against a stand-in)."""

import json
import os
import tempfile
import unittest
import urllib.request
from unittest import mock

import helpers
import records
import run
from common import checker_sha256
from families import ALL as FAMILIES, NO_OBJECT


def load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh) if path.endswith(".json") else fh.read()


CONFIG = load(os.path.join(helpers.FINDER, "config.json"))
SLUG = "weak-schur-6-colours"
KIT = os.path.dirname(helpers.FINDER)  # the kit this finder is part of


def decide(rows, lists, config=CONFIG):
    return run.decide(rows, {"tasks": lists}, config)


class Decide(unittest.TestCase):
    def test_new(self):
        d = decide([helpers.row()], [])[0]
        self.assertEqual((d["decision"], d["round"], d["replaces"]), ("candidate-new", 1, None))

    def test_new_but_optimal_covered_below_floor_or_too_big(self):
        self.assertEqual(decide([helpers.row(proved=True)], [])[0]["decision"], "nothing")
        covered = helpers.row(params={"colours": 6, "weak": False}, value="538")
        self.assertIn("covered by", decide([covered], [])[0]["reason"])
        small = helpers.row(family="comparator-network", direction="min", value="7",
                            params={"inputs": 5, "goal": "median", "measure": "size"})
        self.assertEqual(decide([small], [])[0]["gate"], "floor")
        big = helpers.row(family="comparator-network", direction="min", value="300",
                          params={"inputs": 40, "goal": "sort", "measure": "size"})
        self.assertEqual(decide([big], [])[0]["gate"], "limits")

    def test_second_source_ahead_holds_a_new_card(self):
        r = helpers.row(secondary=[{"name": "Other", "value": "700", "exact": False, "url": "https://x"}])
        d = decide([r], [])[0]
        self.assertEqual((d["decision"], d["gate"]), ("dropped", "second"))

    def test_moved(self):
        d = decide([helpers.row(value="660")], [helpers.published_list(SLUG, SLUG + "-r1", value="650")])[0]
        self.assertEqual((d["decision"], d["round"], d["replaces"]), ("candidate-moved", 2, SLUG + "-r1"))
        self.assertIn("from 650 to 660", d["reason"])

    def test_moved_networks_go_down(self):
        p = {"inputs": 29, "goal": "sort", "measure": "size"}
        lst = helpers.published_list("sorting-network-29-size", "sorting-network-29-size-r1", value="164",
                                     family="comparator-network", params=p, direction="min")
        r = helpers.row(family="comparator-network", direction="min", value="163", params=p)
        self.assertEqual(decide([r], [lst])[0]["decision"], "candidate-moved")
        r = helpers.row(family="comparator-network", direction="min", value="165", params=p)
        self.assertIn("is not lowered", decide([r], [lst])[0]["reason"])  # the same source went backwards

    def test_proved_optimal_pulls_the_card(self):
        d = decide([helpers.row(proved=True)], [helpers.published_list(SLUG, SLUG + "-r1")])[0]
        self.assertEqual((d["decision"], d["listKey"]), ("pull", SLUG + "-r1"))
        r = helpers.row(secondary=[{"name": "OEIS (data)", "value": "650", "exact": True, "url": "https://x"}])
        self.assertEqual(decide([r], [helpers.published_list(SLUG, SLUG + "-r1")])[0]["decision"], "pull")

    def test_papex_ahead_of_the_source_is_never_lowered(self):
        lists = [helpers.published_list(SLUG, SLUG + "-r1", state="REPLACED", value="650",
                                        task_result=helpers.run_result("661")),
                 helpers.published_list(SLUG, SLUG + "-r2", value="661", round_=2, papex_from=SLUG + "-r1")]
        d = decide([helpers.row(value="655")], lists)[0]
        self.assertEqual(d["decision"], "nothing")
        self.assertIn("Papex holds 661", d["reason"])
        d = decide([helpers.row(value="670")], lists)[0]
        self.assertEqual((d["decision"], d["round"], d["replaces"]), ("candidate-moved", 3, SLUG + "-r2"))

    def test_an_accepted_run_waiting_for_the_runner_is_left_alone(self):
        lists = [helpers.published_list(SLUG, SLUG + "-r1", value="650", task_result=helpers.run_result("655"))]
        d = decide([helpers.row(value="652")], lists)[0]
        self.assertEqual(d["decision"], "nothing")
        self.assertIn("waits for the runner", d["reason"])

    def test_source_going_backwards_is_flagged_up_to_date_closed_and_checker_changed(self):
        d = decide([helpers.row(value="640")], [helpers.published_list(SLUG, SLUG + "-r1", value="650")])[0]
        self.assertEqual(d["decision"], "odd")
        self.assertIn("up to date", decide([helpers.row()], [helpers.published_list(SLUG, SLUG + "-r1")])[0]["reason"])
        d = decide([helpers.row()], [helpers.published_list(SLUG, SLUG + "-r1", state="CLOSED")])[0]
        self.assertIn("not reopened", d["reason"])
        d = decide([helpers.row()], [helpers.published_list(SLUG, SLUG + "-r1", checker_sha="0x" + "1" * 64)])[0]
        self.assertEqual((d["decision"], d["round"]), ("candidate-refresh", 2))

    def test_odd_cases(self):
        two = [helpers.published_list(SLUG, SLUG + "-r1"), helpers.published_list(SLUG, SLUG + "-r2", round_=2)]
        self.assertEqual(decide([helpers.row()], two)[0]["decision"], "odd")
        orphan = helpers.published_list("weak-schur-7-colours", "weak-schur-7-colours-r1",
                                        params={"colours": 7, "weak": True})
        ds = decide([helpers.row()], [orphan])
        self.assertIn("no row in today's sources", [d for d in ds if d["slug"] == "weak-schur-7-colours"][0]["reason"])


class Withdrawal(unittest.TestCase):
    """An open round whose best known value is an accepted run on Papex that no longer stands."""

    def test_back_to_the_source(self):
        lists = [helpers.published_list(SLUG, SLUG + "-r1", state="REPLACED", value="650", task_result=None),
                 helpers.published_list(SLUG, SLUG + "-r2", value="660", round_=2, papex_from=SLUG + "-r1")]
        d = decide([helpers.row(value="650")], lists)[0]
        self.assertEqual((d["decision"], d["round"], d["replaces"]), ("candidate-correct", 3, SLUG + "-r2"))
        self.assertNotIn("papex", d)
        self.assertIn("no longer stands", d["reason"])

    def test_back_to_the_last_papex_value_that_stands_when_it_is_better(self):
        lists = [helpers.published_list(SLUG, SLUG + "-r1", state="REPLACED", value="650",
                                        task_result=helpers.run_result("655", "2026-11-18T08:00:00Z")),
                 helpers.published_list(SLUG, SLUG + "-r2", state="REPLACED", value="655", round_=2,
                                        papex_from=SLUG + "-r1", task_result=None),
                 helpers.published_list(SLUG, SLUG + "-r3", value="660", round_=3, papex_from=SLUG + "-r2")]
        d = decide([helpers.row(value="650")], lists)[0]
        self.assertEqual((d["decision"], d["round"], d["replaces"], d["papex"]), ("candidate-correct", 4,
                                                                               SLUG + "-r3", True))
        self.assertEqual((d["best"]["value"], d["best"]["sourceName"], d["best"]["asOf"]), ("655", "Papex",
                                                                                        "2026-11-18"))
        self.assertTrue(d["best"]["sourceUrl"].endswith("/shared-work/" + SLUG + "-r1"))
        # the source is better than what stands: back to the source
        d = decide([helpers.row(value="657")], lists)[0]
        self.assertEqual(d["decision"], "candidate-correct")
        self.assertNotIn("papex", d)

    def test_the_correcting_round_is_a_full_publish_body(self):
        lists = [helpers.published_list(SLUG, SLUG + "-r1", state="REPLACED", value="650",
                                        task_result=helpers.run_result("655", "2026-11-18T08:00:00Z")),
                 helpers.published_list(SLUG, SLUG + "-r2", state="REPLACED", value="655", round_=2,
                                        papex_from=SLUG + "-r1", task_result=None),
                 helpers.published_list(SLUG, SLUG + "-r3", value="660", round_=3, papex_from=SLUG + "-r2")]
        d = decide([helpers.row(value="650")], lists)[0]
        ctx = run.Context(None, tempfile.mkdtemp(), "2026-11-20", records.FirstSeen(os.path.join(
            tempfile.mkdtemp(), "s.json")), records.Evidence(tempfile.mkdtemp()), CONFIG)
        self.assertTrue(run.make_card(d, ctx))
        task = d["body"]["list"]["howTo"]["task"]
        self.assertEqual((d["decision"], d["body"]["list"]["key"], d["body"]["replaces"]),
                         ("publish-next-round", SLUG + "-r4", SLUG + "-r3"))
        self.assertEqual((task["round"], task["previousListKey"], task["bestKnown"]["value"]), (4, SLUG + "-r3", "655"))
        self.assertIsNone(d["body"]["problem"]["create"])


class Pacing(unittest.TestCase):
    def cands(self):
        out = []
        for n in (13, 14, 15):
            for goal, measure in (("sort", "size"), ("sort", "depth"), ("median", "size"), ("median", "depth")):
                p = {"inputs": n, "goal": goal, "measure": measure}
                out.append(self.cand("comparator-network", p, n, recent=(goal == "median")))
        for k in (7, 8):
            for weak in (False, True):
                out.append(self.cand("sum-free-colouring", {"colours": k, "weak": weak}, 100 * k))
        for d in (6, 8, 10):
            for n in (20, 21):
                out.append(self.cand("constant-weight-code", {"n": n, "d": d, "w": 5}, n))
        return out

    @staticmethod
    def cand(family, params, size, recent=False):
        r = helpers.row(family=family, params=params, value=str(size), recent=recent,
                        direction="min" if family == "comparator-network" else "max")
        r["instanceSize"] = size
        return {"family": family, "slug": FAMILIES[family].slug(params), "row": r, "params": params,
                "subfamily": FAMILIES[family].subfamily(params)}

    def test_families_then_subfamilies_take_turns(self):
        order = run.order_new(self.cands(), CONFIG)
        first = [(c["family"], c["subfamily"]) for c in order[:9]]
        self.assertEqual(first, [("comparator-network", "sorting by size"), ("sum-free-colouring", "Schur"),
                                 ("constant-weight-code", "codes, distance 6"),
                                 ("comparator-network", "sorting by depth"), ("sum-free-colouring", "weak Schur"),
                                 ("constant-weight-code", "codes, distance 8"),
                                 ("comparator-network", "median by size"), ("sum-free-colouring", "Schur"),
                                 ("constant-weight-code", "codes, distance 10")])
        self.assertEqual(order[0]["slug"], "sorting-network-13-size")  # smaller first inside a sub-family
        five = [c["family"] for c in order[:5]]
        self.assertLessEqual(max(five.count(f) for f in set(five)), 2)  # no family fills a day of five

    def test_what_is_open_on_papex_counts(self):
        published = {"tasks": [helpers.published_list("sorting-network-20-size", "sorting-network-20-size-r1",
                                                       family="comparator-network",
                                                       params={"inputs": 20, "goal": "sort", "measure": "size"})]}
        order = run.order_new(self.cands(), CONFIG, published)
        self.assertEqual(order[0]["family"], "sum-free-colouring")  # comparator networks already have one open
        comp = [c["subfamily"] for c in order if c["family"] == "comparator-network"][:2]
        self.assertEqual(comp, ["sorting by depth", "median by size"])


ON = json.loads(json.dumps(CONFIG))
ON["families"]["constant-weight-code"]["objectless"]["allow"] = True


class NoObject(unittest.TestCase):
    """Cards without a linked object: off by default; when on, evidence and three sanity gates."""

    def ctx(self, evidence_records=10, mismatches=0, seen_yesterday=True, rows=()):
        ev = records.Evidence(tempfile.mkdtemp())
        sha = checker_sha256("constant-weight-code")
        for i in range(evidence_records + mismatches):
            row = helpers.row(family="constant-weight-code", params={"n": 10 + i, "d": 6, "w": 4}, value="5",
                              source="brouwer")
            ev.add("constant-weight-code", sha, row, "0x%064x" % i, 5, i < evidence_records, "2026-11-20")
        state = records.FirstSeen(os.path.join(tempfile.mkdtemp(), "s.json"))
        if seen_yesterday:
            state.observe(records.FirstSeen.key(self.row(), no_object=True))
            state.finish("2026-11-19")
        ctx = run.Context(None, tempfile.mkdtemp(), "2026-11-20", state, ev, ON)
        ctx.index = {"constant-weight-code": {json.dumps(r["params"], sort_keys=True): r for r in rows}}
        return ctx

    def row(self, value="532", upper=680, n=24):
        return helpers.row(family="constant-weight-code", params={"n": n, "d": 6, "w": 6}, value=value,
                           objectRef=None, source="brouwer", sourceName="A. E. Brouwer, table of constant weight codes",
                           objectUrl=None, upperOrLowerLimit=upper, labels=["s"])

    def test_off_by_default_for_every_family(self):
        for fam in CONFIG["families"].values():
            self.assertFalse(fam["objectless"]["allow"])
        d = decide([self.row()], [])[0]
        self.assertEqual((d["decision"], d["gate"]), ("dropped", "object"))
        self.assertIn("off for this family", d["reason"])

    def test_allowed_when_on_with_evidence_and_sane_values(self):
        d = decide([self.row()], [], ON)[0]
        self.assertEqual((d["decision"], d["noObject"]), ("candidate-new", True))
        self.assertTrue(run.make_card(d, self.ctx()))
        best = d["body"]["list"]["howTo"]["task"]["bestKnown"]
        self.assertNotIn("objectUrl", best)
        self.assertIn(NO_OBJECT, d["body"]["list"]["description"])
        self.assertIsNone(run.gates.gate_texts(d["body"]))

    def test_refused_with_too_little_evidence_or_a_mismatch(self):
        for good, bad in ((9, 0), (12, 1)):
            d = decide([self.row()], [], ON)[0]
            self.assertFalse(run.make_card(d, self.ctx(good, bad)))
            self.assertEqual(d["gate"], "object")
            self.assertIn("reproduced the table on", d["reason"])

    def test_sanity_upper_bound_neighbours_and_two_runs(self):
        d = decide([self.row(value="700", upper=680)], [], ON)[0]
        self.assertFalse(run.make_card(d, self.ctx()))
        self.assertIn("above the table's upper bound", d["reason"])
        # A(25,6,6) >= A(24,6,6): a longer table entry below this one does not fit (append a 0 to every word)
        longer = helpers.row(family="constant-weight-code", params={"n": 25, "d": 6, "w": 6}, value="500")
        d = decide([self.row()], [], ON)[0]
        self.assertFalse(run.make_card(d, self.ctx(rows=[longer])))
        self.assertEqual(d["gate"], "sanity")
        self.assertIn("constant-weight-code-25-6-6", d["reason"])
        fits = helpers.row(family="constant-weight-code", params={"n": 25, "d": 6, "w": 6}, value="700")
        d = decide([self.row()], [], ON)[0]
        self.assertTrue(run.make_card(d, self.ctx(rows=[fits])))
        d = decide([self.row()], [], ON)[0]  # read for the first time today: wait for a second run
        self.assertFalse(run.make_card(d, self.ctx(seen_yesterday=False)))
        self.assertIn("two runs in a row", d["reason"])

    def test_not_the_primary_record(self):
        s9 = helpers.row(params={"colours": 9, "weak": False}, value="17803", objectRef=None)
        d = decide([s9], [], ON)[0]
        self.assertEqual(d["decision"], "dropped")
        self.assertIn("not the primary record", d["reason"])


class FixedBodies(unittest.TestCase):
    def test_as_of_is_the_day_the_source_state_was_first_read(self):
        path = os.path.join(tempfile.mkdtemp(), "seen.json")
        state = records.FirstSeen(path)
        r = helpers.row(value="650")
        self.assertEqual(state.as_of(r, "2026-11-20"), "2026-11-20")
        state.save()
        again = records.FirstSeen(path)
        self.assertEqual(again.as_of(r, "2026-11-23"), "2026-11-20")  # same state: same date
        self.assertEqual(again.as_of(helpers.row(value="651"), "2026-11-23"), "2026-11-23")  # moved: new date

    def test_the_same_source_state_gives_the_same_body_on_another_day(self):
        fam = FAMILIES["sum-free-colouring"]
        a = run.cards.build(fam, dict(helpers.row(), readOn="2026-11-20", recent=True), as_of="2026-11-20")
        b = run.cards.build(fam, dict(helpers.row(), readOn="2026-12-01", recent=False), as_of="2026-11-20")
        self.assertEqual(a, b)

    def test_texts_hold_no_value_and_no_date(self):
        # the kit's next round after an accepted run keeps the old list's texts, so they must not name a value
        fam = FAMILIES["constant-weight-code"]
        r = helpers.row(family="constant-weight-code", params={"n": 24, "d": 6, "w": 6}, value="531977",
                        readOn="2031-07-15")
        body = run.cards.build(fam, r, as_of="2031-07-15")
        lst, task = body["list"], body["list"]["howTo"]["task"]
        texts = [lst[k] for k in ("title", "shortTitle", "description", "resultLine")]
        texts += [task[k] for k in ("objective", "shows", "notCovered", "effort", "alsoBelongsAt")]
        for t in texts:
            self.assertNotIn("531977", t)
            self.assertNotIn("2031", t)


def fixture_cache():
    pages = {}
    pages.update(helpers.dobbelaere_pages())
    pages.update(helpers.leaps_pages())
    pages.update(helpers.brouwer_pages())
    return helpers.offline_fetcher(pages).cache_dir


def args(out, *more):
    return ["--offline", "--cache", CACHE, "--out", out, "--state", os.path.join(out, "seen.json"),
            "--validation", os.path.join(out, "validation"), *more]


CACHE = fixture_cache()


class WholeRun(unittest.TestCase):
    def test_dry_run_writes_every_output(self):
        out = tempfile.mkdtemp(prefix="finder-run-")
        published = os.path.join(out, "published.json")
        with open(published, "w") as fh:
            json.dump({"tasks": [helpers.published_list(SLUG, SLUG + "-r1", value="640")]}, fh)
        self.assertEqual(run.main(["--dry-run", *args(out, "--published", published, "--max-new", "3")]), 0)
        plan = load(os.path.join(out, "plan.json"))
        by = {d["slug"]: d for d in plan["decisions"]}
        self.assertEqual(by[SLUG]["decision"], "publish-next-round")  # 640 on Papex, 650 in the table
        self.assertEqual(plan["counts"]["publish-new"], 3)
        self.assertEqual(len(os.listdir(os.path.join(out, "cards"))), 4)
        for name in os.listdir(os.path.join(out, "cards")):
            body = load(os.path.join(out, "cards", name))
            self.assertIsNone(run.gates.gate_texts(body))
            self.assertEqual(body["list"]["howTo"]["task"]["checkerSha256"],
                             checker_sha256(body["list"]["howTo"]["task"]["family"]))
        nxt = load(os.path.join(out, "cards", SLUG + ".json"))
        self.assertEqual((nxt["replaces"], nxt["list"]["key"]), (SLUG + "-r1", SLUG + "-r2"))
        self.assertEqual(nxt["list"]["howTo"]["task"]["previousListKey"], SLUG + "-r1")
        self.assertIsNone(nxt["problem"]["create"])
        self.assertFalse([o for o in os.listdir(os.path.join(out, "objects")) if o.startswith("constant-weight")])
        summary = load(os.path.join(out, "summary.md"))
        self.assertLessEqual(len(summary.splitlines()), 25)
        self.assertIn("Requests to the source sites: none.", summary)
        self.assertTrue(os.path.isfile(os.path.join(out, "validation", "comparator-network.json")))
        # a second run that makes fewer cards sets the earlier ones aside (nothing is deleted)
        run.main(["--dry-run", *args(out, "--published", published, "--max-new", "1")])
        self.assertEqual(len(os.listdir(os.path.join(out, "cards"))), 2)

    def test_first_batch_is_balanced_and_only_for_the_launch(self):
        out = tempfile.mkdtemp(prefix="finder-first-")
        self.assertEqual(run.main(["--dry-run", *args(out, "--first-batch", "4")]), 0)
        plan = load(os.path.join(out, "plan.json"))
        made = [d for d in plan["decisions"] if d["decision"] == "publish-new"]
        self.assertEqual(len(made), 4)
        self.assertEqual(len({d["family"] for d in made}), 3)
        self.assertIn("sorting-network-13-size", [d["slug"] for d in made])
        published = os.path.join(out, "published.json")
        with open(published, "w") as fh:
            json.dump({"tasks": [helpers.published_list(SLUG, SLUG + "-r1")]}, fh)
        with self.assertRaises(SystemExit):
            run.main(["--dry-run", *args(out, "--first-batch", "4", "--published", published)])


@unittest.skipUnless(os.path.isfile(os.path.join(KIT, "runner", "publisher.py")), "the kit is not next to the finder")
class Publish(unittest.TestCase):
    def setUp(self):
        run.cards.load_publisher(KIT)  # loaded before a stand-in takes urlopen's place, as in the kit's own tests
        self.saved_urlopen, self.saved_env = urllib.request.urlopen, os.environ.get(run.TOKEN_ENV)
        os.environ[run.TOKEN_ENV] = helpers.PUBLISHER_TOKEN

    def tearDown(self):
        urllib.request.urlopen = self.saved_urlopen
        if self.saved_env is None:
            os.environ.pop(run.TOKEN_ENV, None)
        else:
            os.environ[run.TOKEN_ENV] = self.saved_env

    def papex(self, lists=()):
        stand_in = helpers.StandInPapex(lists)
        urllib.request.urlopen = stand_in.urlopen
        return stand_in

    def publish(self, out, *more):
        return run.main(["--publish", "--kit", KIT, "--api", "https://papex.test", *args(out, *more)])

    def test_publishes_reads_back_and_does_not_repeat(self):
        sort4 = {"inputs": 4, "goal": "sort", "measure": "size"}  # the fixture table marks 5 as exact (bold)
        p = self.papex([helpers.published_list(SLUG, SLUG + "-r1", value="640"),
                        helpers.published_list("sorting-network-4-size", "sorting-network-4-size-r1", value="5",
                                               family="comparator-network", params=sort4, direction="min")])
        out = tempfile.mkdtemp(prefix="finder-pub-")
        with mock.patch.object(run.records, "utc_today", return_value="2026-11-20"):
            self.assertEqual(self.publish(out, "--max-new", "3"), 0)
        posts = [r for r in p.requests if r["method"] == "POST"]
        self.assertEqual(p.requests[0]["method"], "GET")  # what Papex holds is read first
        self.assertTrue(all(r["auth"] == "Bearer " + helpers.PUBLISHER_TOKEN for r in p.requests))
        self.assertFalse([r for r in posts if r["path"].endswith("/close")])  # one reading of "exact": no close yet
        self.assertEqual(p.lists[SLUG + "-r1"]["state"], "REPLACED")
        self.assertEqual(p.lists[SLUG + "-r2"]["state"], "OPEN")
        self.assertEqual(len([k for k, x in p.lists.items() if x["task"]["round"] == 1 and x["state"] == "OPEN"]),
                         4)
        for name in ("plan.json", "summary.md", "dropped.json"):
            self.assertNotIn(helpers.PUBLISHER_TOKEN, load(os.path.join(out, name)) if name.endswith("md")
                             else json.dumps(load(os.path.join(out, name))))
        before = len(p.requests)
        with mock.patch.object(run.records, "utc_today", return_value="2026-11-21"):
            self.assertEqual(self.publish(out, "--max-new", "3"), 0)  # the next day
        again = [r for r in p.requests[before:] if r["method"] == "POST"]
        self.assertTrue(again[0]["path"].endswith("/sorting-network-4-size-r1/close"))  # the same reading twice
        self.assertEqual(p.lists["sorting-network-4-size-r1"]["state"], "CLOSED")
        keys = [r["body"]["list"]["key"] for r in again[1:]]
        self.assertTrue(keys)
        self.assertFalse(set(keys) & {r["body"]["list"]["key"] for r in posts if "list" in (r["body"] or {})})

    def test_a_list_that_got_an_accepted_run_meanwhile_is_left_to_the_runner(self):
        p = self.papex([helpers.published_list(SLUG, SLUG + "-r1", value="640")])
        reads = {"n": 0}
        real_tasks = p.tasks

        def tasks_then_accepted():  # the run is read at the start; then a run is accepted on r1
            reads["n"] += 1
            if reads["n"] == 2:
                p.lists[SLUG + "-r1"]["taskResult"] = helpers.run_result("645")
            return real_tasks()
        p.tasks = tasks_then_accepted
        out = tempfile.mkdtemp(prefix="finder-race-")
        self.assertEqual(self.publish(out, "--max-new", "0"), 0)
        self.assertFalse([r for r in p.requests if r["method"] == "POST"])  # nothing replaced it
        plan = load(os.path.join(out, "plan.json"))
        d = [d for d in plan["decisions"] if d["slug"] == SLUG][0]
        self.assertIn("accepted run", d["sent"]["held"])
        self.assertIn(SLUG, load(os.path.join(out, "summary.md")))

    def test_a_refusal_409_is_kept_not_retried(self):
        for code, words in (("SHARED_WORK_TASK_ROUND_WORSE", "the runner carries it"),
                            ("SHARED_WORK_TASK_REPLACES_INVALID", "cannot be replaced")):
            p = self.papex([helpers.published_list(SLUG, SLUG + "-r1", value="640")])
            p.refuse_replacing = code
            out = tempfile.mkdtemp(prefix="finder-409-")
            self.assertEqual(self.publish(out, "--max-new", "0"), 0)
            posts = [r for r in p.requests if r["method"] == "POST"]
            self.assertEqual(len(posts), 1)  # sent once, never retried
            d = [d for d in load(os.path.join(out, "plan.json"))["decisions"] if d["slug"] == SLUG][0]
            self.assertEqual((d["sent"]["status"], d["sent"]["code"]), (409, code))
            self.assertIn(words, d["sent"]["held"])
            self.assertEqual(p.lists[SLUG + "-r1"]["state"], "OPEN")

    def test_a_lost_answer_is_safe_to_retry(self):
        p = self.papex()
        p.lose_answer = True
        out = tempfile.mkdtemp(prefix="finder-lost-")
        self.publish(out, "--max-new", "1")
        plan = load(os.path.join(out, "plan.json"))
        made = [d for d in plan["decisions"] if d["decision"] == "publish-new"][0]
        self.assertIn("error", made["sent"])
        body = [r["body"] for r in p.requests if r["method"] == "POST"][0]
        # the very same body again: Papex answers "already"
        p.lose_answer = False
        request = urllib.request.Request("https://papex.test/api/shared-work/publisher/tasks",
                                         data=json.dumps(body).encode(), method="POST",
                                         headers={"Authorization": "Bearer " + helpers.PUBLISHER_TOKEN})
        self.assertTrue(json.loads(p.urlopen(request).read())["already"])
        # the next run reads the list back from Papex and leaves it alone (no 409 for a changed body)
        self.publish(out, "--max-new", "1")
        plan = load(os.path.join(out, "plan.json"))
        again = [d for d in plan["decisions"] if d["slug"] == made["slug"]][0]
        self.assertEqual((again["decision"], again["reason"]), ("nothing", "the card is up to date"))
        self.assertFalse([d for d in plan["decisions"] if "error" in (d.get("sent") or {})])

    def test_no_token_no_run(self):
        os.environ.pop(run.TOKEN_ENV, None)
        self.papex()
        with self.assertRaises(SystemExit):
            self.publish(tempfile.mkdtemp())

    def test_only_publishes_one_named_card(self):
        p = self.papex()
        out = tempfile.mkdtemp(prefix="finder-only-")
        self.assertEqual(self.publish(out, "--max-new", "0", "--only", "constant-weight-code-13-6-4"), 0)
        posts = [r for r in p.requests if r["method"] == "POST"]
        self.assertEqual([r["body"]["list"]["key"] for r in posts], ["constant-weight-code-13-6-4-r1"])
        with self.assertRaises(SystemExit):  # a name today's sources do not have
            self.publish(tempfile.mkdtemp(), "--only", "sorting-network-99-size")

    def test_read_papex_reads_and_sends_nothing(self):
        p = self.papex([helpers.published_list(SLUG, SLUG + "-r1", value="640")])
        out = tempfile.mkdtemp(prefix="finder-read-")
        self.assertEqual(run.main(["--dry-run", "--read-papex", "--kit", KIT, "--api", "https://papex.test",
                                   *args(out, "--max-new", "2")]), 0)
        self.assertEqual([r["method"] for r in p.requests], ["GET"])
        plan = load(os.path.join(out, "plan.json"))
        self.assertEqual(plan["mode"], "dry-run")
        self.assertTrue([d for d in plan["decisions"] if d["slug"] == SLUG and d["decision"] == "publish-next-round"])


if __name__ == "__main__":
    unittest.main()
