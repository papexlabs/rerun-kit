#!/usr/bin/env python3
"""The finder's daily program: public record tables in, Papex "open task" cards out. No person and no AI reads
prose on the way: adapters parse table cells and files, the gates compare parsed values and run the family's
reviewed checker on the source's own best known object, and cards are filled from templates.

    python3 finder/run.py --dry-run  [options]   nothing is sent
    python3 finder/run.py --publish  [options]   publishes and closes through the kit's publisher client
                                                 (env PAPEX_SHARED_WORK_PUBLISHER_TOKEN; never printed)

  --family F       only this family (comparator-network, sum-free-colouring, constant-weight-code)
  --max-new N      at most N new cards this run (default 5); next rounds and closes are not counted
  --first-batch N  launch day: N new cards, a balanced first set; refused when Papex already holds a card of
                   the finder's families
  --only SLUG      only this card (a slug such as sorting-network-13-size): decided, made and, with --publish,
                   sent, whatever the pacing; refused when today's sources have no entry of that name
  --published F    dry run only: what Papex holds, in the shape of GET /api/shared-work/publisher/tasks
                   (default: nothing). With --publish it is read from Papex through the kit's client.
  --read-papex     dry run only: read what Papex holds through the kit's client (needs the token), send nothing
  --kit PATH       the kit's folder (default: the kit this folder is in); its runner/publisher.py is the client
  --api URL        Papex's API (default https://api.papex.org)
  --cache DIR      downloads (default $PAPEX_FINDER_CACHE, else ~/.cache/papex-finder: never in the repository)
  --out DIR        results (default finder/out, which git ignores)
  --state FILE     first-seen dates of source states (default ./state/first-seen.json)
  --validation DIR evidence that each family's checker reproduces its source's values (default ./validation)
  --offline        read only the cache; no request is sent to any source

Selection (a rule): new cards are taken from families in turn, the family with the fewest open cards on Papex
first; inside a family from its sub-families in turn (sorting by size, sorting by depth, median by size, median by
depth; Schur, weak Schur; codes by distance), the one with the fewest open cards first; inside a sub-family,
entries with a recent improvement by a named person first, then smaller instances, then by slug.

Writes out/plan.json (every decision and its reason), out/cards/<slug>.json (publish bodies),
out/objects/<slug>.json (objects whose licence lets them be copied, NOTICE.txt), out/dropped.json, out/summary.md.

Decisions: publish-new; publish-next-round (the source moved past the card, the family checker changed, or the
accepted run the card's value came from no longer stands); pull (the source now gives the exact value); nothing;
waiting (not reached today); dropped (a gate failed); odd (a person should look).
"""

import argparse
import datetime
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.dont_write_bytecode = True
sys.path.insert(0, HERE)

import cards  # noqa: E402
import fetch  # noqa: E402
import gates  # noqa: E402
import records  # noqa: E402
from adapters import brouwer, dobbelaere, leaps  # noqa: E402
from common import CACHE, KIT, Unavailable, canonical_bytes, checker_sha256, sha256_hex  # noqa: E402
from families import ALL as FAMILIES, NO_OBJECT  # noqa: E402

ADAPTERS = {"dobbelaere": dobbelaere, "leaps": leaps, "brouwer": brouwer}
SITE = "https://papex.org"
PAPEX_LIST_RE = re.compile(r"^https://papex\.org/problems/([a-z0-9]+(?:-[a-z0-9]+)*)/shared-work/"
                           r"([a-z0-9]+(?:-[a-z0-9]+)*)$")
ACCEPTED_BY = "an accepted run on Papex"
TOKEN_ENV = "PAPEX_SHARED_WORK_PUBLISHER_TOKEN"
DEFAULT_KIT = KIT
DEFAULT_API = "https://api.papex.org"
NEXT_ROUND = ("candidate-moved", "candidate-refresh", "candidate-correct")


# ---------------------------------------------------------------------------- reading
def read_sources(fetcher, config, family_filter, today):
    rows, problems = [], []
    for fam_name, fc in config["families"].items():
        if family_filter and fam_name != family_filter:
            continue
        for src in fc["sources"]:
            try:
                got, probs = ADAPTERS[src].read_rows(fetcher, today)
            except Exception as e:  # a source that breaks is skipped today; the other sources still run
                problems.append({"source": src, "skipped": True,
                                 "reason": f"skipped today: {type(e).__name__}: {str(e)[:160]}"})
                continue
            rows += [r for r in got if isinstance(r, dict) and r.get("family") == fam_name]
            problems += probs
    if any(r["family"] == "comparator-network" and r["params"]["goal"] == "sort" for r in rows):
        second = leaps.sorting_secondary(fetcher)
        for r in rows:
            p = r["params"]
            if r["family"] == "comparator-network" and p["goal"] == "sort" and (p["inputs"], p["measure"]) in second:
                value, exact = second[(p["inputs"], p["measure"])]
                if value is not None:
                    r["secondary"].append({"name": "Leaps in Bounds", "value": str(value), "exact": exact,
                                           "url": f"{leaps.SITE}sorting-network-{p['measure']}-{p['inputs']}/"})
    return rows, problems


# ---------------------------------------------------------------------------- deciding
def published_index(published):
    index = {}
    for item in (published or {}).get("tasks", []):
        task = item.get("task") or {}
        if task.get("slug"):
            index.setdefault(task["slug"], []).append(item)
    return index


def round_of(item):
    return int((item.get("task") or {}).get("round") or 1)


def standing(lists):
    """The lists of a slug whose accepted run still stands (a taskResult with a score), latest round last."""
    return sorted((x for x in lists if (x.get("taskResult") or {}).get("score") is not None), key=round_of)


def accepted_best(score, problem_slug, key, accepted_at):
    """The best known value of a round whose value is an accepted run on Papex (the kit's publisher.accepted_best):
    dated the day the run was accepted, so a retry sends the same body."""
    on = accepted_at[:10] if isinstance(accepted_at, str) and re.match(r"\d{4}-\d{2}-\d{2}", accepted_at) \
        else records.utc_today()
    page = f"{SITE}/problems/{problem_slug}/shared-work/{key}"
    return {"value": str(score), "by": ACCEPTED_BY, "year": int(on[:4]), "sourceName": "Papex", "sourceUrl": page,
            "asOf": on, "objectUrl": page}


def covered_by(row, config):
    for c in config.get("covered", []):
        if c["family"] == row["family"] and c["params"] == row["params"]:
            return c["by"]
    return None


def below_floor(row, config):
    floor = config["families"].get(row["family"], {}).get("minInputs")
    if floor and row["family"] == "comparator-network":
        least = floor.get(row["params"]["goal"], 0)
        if row["params"]["inputs"] < least:
            return f"below the configured floor of {least} inputs ({config['families'][row['family']]['minInputsWhy']})"
    return None


def objectless_rule(row, config):
    """None when a card without a linked object may be considered for this row's family (the evidence is checked
    when the card is made); else why not."""
    rule = config["families"].get(row["family"], {}).get("objectless") or {}
    if not rule.get("tablePrimary"):
        return "this family's source is not the primary record of its values"
    if not rule.get("allow"):
        return "cards without a linked object are off for this family in config.json"
    return None


def no_object_reason(row, config):
    return f"{ADAPTERS[row['source']].NO_OBJECT}; {objectless_rule(row, config)}"


def decide(rows, published, config):
    """One decision per row, without any download: the cheap gates and the comparison with Papex."""
    index = published_index(published)
    decisions, seen = [], set()
    for row in rows:
        try:
            d = decide_row(row, index, config, seen)
        except Exception as e:  # a row that breaks the planner is dropped with its reason; the others go on
            d = {"slug": str(row.get("id"))[:80], "family": row.get("family"), "params": row.get("params"),
                 "row": None, "notes": [], "decision": "dropped", "gate": "entry",
                 "reason": f"the entry could not be decided ({type(e).__name__}: {str(e)[:120]})"}
        decisions.append(d)
    families_read = {r.get("family") for r in rows if isinstance(r, dict)}
    for slug, lists in sorted(index.items()):
        fam = (lists[0].get("task") or {}).get("family")
        if slug not in seen and fam in families_read and any(x.get("state") == "OPEN" for x in lists):
            decisions.append({"slug": slug, "family": fam, "params": (lists[0].get("task") or {}).get("params"),
                              "row": None, "notes": [], "decision": "odd",
                              "reason": "an open card of this family has no row in today's sources"})
    return decisions


def not_marked(row):
    """Why an entry gets no new card although it is not read as proved: the source hints at optimality without a
    strict mark (a median comment), or does not mark the entry either way (a lone number on Brouwer's table)."""
    if row.get("softExact"):
        return "the list's comment on this entry mentions optimality (not read as a proof: no card, never a close)"
    if row.get("exactUnclear"):
        return "the table shows a single number here, without marking it exact or open (no card, never a close)"
    return None


def decide_row(row, index, config, seen):
    fam = FAMILIES[row["family"]]
    slug = fam.slug(row["params"])
    seen.add(slug)
    d = {"slug": slug, "family": row["family"], "params": row["params"], "row": row, "notes": [],
         "subfamily": fam.subfamily(row["params"]), "noObject": not row.get("objectRef")}
    lists = index.get(slug, [])
    proved = gates.gate_proved(row)
    if lists:
        return decide_published(d, row, lists, proved, config)
    covered = covered_by(row, config)
    if proved:
        d.update(decision="nothing", gate="proved", reason=proved)
    elif not_marked(row):
        d.update(decision="nothing", gate="unmarked", reason=not_marked(row))
    elif covered:
        d.update(decision="nothing", gate="covered", reason=f"covered by {covered}")
    elif below_floor(row, config):
        d.update(decision="dropped", gate="floor", reason=below_floor(row, config))
    elif gates.gate_limits(fam, row):
        d.update(decision="dropped", gate="limits", reason=gates.gate_limits(fam, row))
    elif d["noObject"] and objectless_rule(row, config):
        d.update(decision="dropped", gate="object", reason=no_object_reason(row, config))
    else:
        second, notes = gates.gate_second(row)
        d["notes"] += notes
        if second:
            d.update(decision="dropped", reason=second, gate="second")
        else:
            d.update(decision="candidate-new", round=1, replaces=None)
    return d


def decide_published(d, row, lists, proved, config):
    open_lists = [x for x in lists if x.get("state") == "OPEN"]
    top = max(round_of(x) for x in lists)
    if len(open_lists) != 1:
        d.update(decision="odd" if len(open_lists) > 1 else "nothing",
                 reason=("more than one open list for this card" if len(open_lists) > 1 else
                         "the card's lists are all closed; a closed card is not reopened automatically"))
        return d
    cur = open_lists[0]
    task = cur.get("task") or {}
    bk = task.get("bestKnown") or {}
    d["current"] = {"listKey": cur.get("listKey"), "problemSlug": cur.get("problemSlug"), "bestKnown": bk}
    direction = row["direction"]
    if task.get("family") != row["family"] or task.get("params") != row["params"]:
        return dict(d, decision="odd", reason="the open list's family or params differ from this row's")
    if cur.get("taskResult"):
        return dict(d, decision="nothing", reason="an accepted run on this round waits for the runner's next round")
    if proved:
        return dict(d, decision="pull", reason=proved, listKey=cur.get("listKey"), problemSlug=cur.get("problemSlug"))
    held = standing(lists)
    m = PAPEX_LIST_RE.match(bk.get("sourceUrl") or "")
    if m and bk.get("sourceName") == "Papex":
        ref = next((x for x in lists if x.get("listKey") == m.group(2)), None)
        if ref is None:
            return dict(d, decision="odd", reason=f"the card's best known value names {m.group(2)}, which the "
                                                  "publisher listing does not show")
        if not ref.get("taskResult"):
            last = held[-1] if held else None
            source_ok = not gates.gate_second(row)[0]
            if last and not (source_ok and not gates.better(last["taskResult"]["score"], row["bestKnownValue"],
                                                            direction)):
                tr = last["taskResult"]
                d.update(decision="candidate-correct", round=top + 1, replaces=cur.get("listKey"), papex=True,
                         best=accepted_best(tr["score"], last.get("problemSlug"), last.get("listKey"),
                                            tr.get("acceptedAt")),
                         reason=f"the accepted run on {ref.get('listKey')} no longer stands; the last value on Papex "
                                f"that stands is {tr['score']} ({last.get('listKey')})")
            elif source_ok:
                d.update(decision="candidate-correct", round=top + 1, replaces=cur.get("listKey"),
                         reason=f"the accepted run on {ref.get('listKey')} no longer stands; the source gives "
                                f"{row['bestKnownValue']}")
            else:
                d.update(decision="odd", reason=f"the accepted run on {ref.get('listKey')} no longer stands, and "
                                                "neither the source nor Papex has a value to put back")
            return d
    values = [("accepted", str(x["taskResult"]["score"])) for x in held]  # an accepted run first, on a tie
    values += [("card", str(bk["value"]))] if bk.get("value") is not None else []
    best = None
    for kind, v in values:
        if best is None or gates.better(v, best[1], direction):
            best = (kind, v)
    d["current"]["papexBest"] = best
    if best and gates.better(row["bestKnownValue"], best[1], direction):
        second, notes = gates.gate_second(row)
        d["notes"] += notes
        if second:
            return dict(d, decision="dropped", reason=second, gate="second")
        return dict(d, decision="candidate-moved", round=top + 1, replaces=cur.get("listKey"),
                    reason=f"the source moved from {best[1]} to {row['bestKnownValue']}")
    if best and gates.better(best[1], row["bestKnownValue"], direction):
        if best[0] == "card" and (bk.get("sourceName") or "") == row["sourceName"]:
            return dict(d, decision="odd", reason=(f"the source now gives {row['bestKnownValue']}, worse than the "
                                                   f"{best[1]} it gave when the card was made; the card is not "
                                                   "lowered: a person should look (a corrected or withdrawn value?)"))
        return dict(d, decision="nothing", reason=(f"Papex holds {best[1]} ({'an accepted run' if best[0] == 'accepted' else 'the card'}),"
                                                   f" better than the source's {row['bestKnownValue']}; never lowered"))
    if task.get("checkerSha256") != checker_sha256(row["family"]):
        return dict(d, decision="candidate-refresh", round=top + 1, replaces=cur.get("listKey"), keepBestKnown=bk,
                    reason="the family checker changed; the next round carries the new checker")
    return dict(d, decision="nothing", reason="the card is up to date")


# ---------------------------------------------------------------------------- selection
def subfamily_order(fam_name, candidates):
    fam = FAMILIES[fam_name]
    if fam_name == "constant-weight-code":
        return sorted({fam.subfamily(c["params"]) for c in candidates}, key=lambda s: int(s.split()[-1]))
    order = {"comparator-network": ["sorting by size", "sorting by depth", "median by size", "median by depth"],
             "sum-free-colouring": ["Schur", "weak Schur"]}.get(fam_name, [])
    return order + sorted({fam.subfamily(c["params"]) for c in candidates} - set(order))


def order_new(candidates, config, published=None):
    """The order in which new cards are tried (see the module's docstring): families in turn, the one with the
    fewest open cards on Papex first; inside, sub-families in turn the same way; inside, recent then small."""
    open_count = {}
    for item in (published or {}).get("tasks", []):
        task = item.get("task") or {}
        if item.get("state") == "OPEN" and task.get("family") in FAMILIES and isinstance(task.get("params"), dict):
            try:
                sub = FAMILIES[task["family"]].subfamily(task["params"])
            except (KeyError, TypeError):
                continue
            open_count[task["family"]] = open_count.get(task["family"], 0) + 1
            open_count[(task["family"], sub)] = open_count.get((task["family"], sub), 0) + 1
    queues = {}
    for d in candidates:
        queues.setdefault(d["family"], {}).setdefault(d["subfamily"], []).append(d)
    for subs in queues.values():
        for q in subs.values():
            q.sort(key=lambda d: (not d["row"].get("recent"), d["row"].get("instanceSize") or 0, d["slug"]))
    fam_order = [f for f in config["familyOrder"] if f in queues] + sorted(f for f in queues
                                                                           if f not in config["familyOrder"])
    sub_orders = {f: subfamily_order(f, [d for q in queues[f].values() for d in q]) for f in queues}
    out = []
    while True:
        live = [f for f in fam_order if any(queues[f].values())]
        if not live:
            return out
        f = min(live, key=lambda f: (open_count.get(f, 0), fam_order.index(f)))
        subs = [s for s in sub_orders[f] if queues[f].get(s)]
        s = min(subs, key=lambda s: (open_count.get((f, s), 0), sub_orders[f].index(s)))
        out.append(queues[f][s].pop(0))
        open_count[f] = open_count.get(f, 0) + 1
        open_count[(f, s)] = open_count.get((f, s), 0) + 1


# ---------------------------------------------------------------------------- making a card
class Context:
    def __init__(self, fetcher, work, today, state, evidence, config):
        self.fetcher, self.work, self.today = fetcher, work, today
        self.state, self.evidence, self.config = state, evidence, config


def make_card(d, ctx):
    """Runs the gates that need the source's object (or, for a card without one, the family's evidence); fills d
    and returns True when the card can be made."""
    row = d["row"]
    fam = FAMILIES[row["family"]]
    if d.get("papex"):  # a correcting round back to an accepted run that still stands: Papex holds that object
        return finish(d, cards.build(fam, row, d["round"], d["replaces"], best=d["best"]), ctx)
    if d["decision"] == "candidate-refresh" and str((d.get("keepBestKnown") or {}).get("value")) != row["bestKnownValue"]:
        d.update(decision="odd", reason="the family checker changed but Papex's best known value is not the "
                                        "source's: a person should decide how to carry it")
        return False
    if d["noObject"]:
        why = objectless_rule(row, ctx.config)
        ok, good, bad = ctx.evidence.status(row["family"], checker_sha256(row["family"]), row.get("source"))
        d["evidence"] = {"reproduced": good, "mismatches": bad, "needed": records.MIN_EVIDENCE}
        if why or not ok:
            d.update(decision="dropped", gate="object",
                     reason=f"{ADAPTERS[row['source']].NO_OBJECT}; " + (why or (
                         f"its checker reproduced the table on {good} real objects with this checker version "
                         f"({bad} mismatches); {records.MIN_EVIDENCE} and none are needed")))
            return False
        problems = sanity_problems(row, ctx)
        if problems:
            d.update(decision="dropped", gate="sanity", reason=f"{ADAPTERS[row['source']].NO_OBJECT}; " + problems[0])
            d["sanity"] = problems
            return False
        as_of = ctx.state.as_of(row, ctx.today, no_object=True)
        return finish(d, cards.build(fam, row, d["round"], d["replaces"], as_of=as_of, no_object=True), ctx)
    adapter = ADAPTERS[row["source"]]
    try:
        obj, meta = adapter.fetch_object(ctx.fetcher, row)
    except fetch.FetchError as e:
        if "budget" in str(e):
            d.update(decision="waiting", reason=f"not reached today: {e}")
        else:
            d.update(decision="dropped", gate="object", reason=f"the source's object could not be read: {e}")
        return False
    except Unavailable as e:
        d.update(decision="dropped", gate="object", reason=str(e))
        return False
    except Exception as e:  # anything a source's file does to an adapter drops the row, never the run
        d.update(decision="dropped", gate="object", reason=f"the source's object could not be converted "
                                                            f"({type(e).__name__}: {str(e)[:120]})")
        return False
    try:
        data = canonical_bytes(obj)
    except (TypeError, ValueError, RecursionError) as e:
        d.update(decision="dropped", gate="object", reason=f"the source's object cannot be written as JSON "
                                                            f"({type(e).__name__})")
        return False
    limit = fam.max_object_bytes(row["params"], row["bestKnownValue"])
    if len(data) > limit:
        d.update(decision="dropped", gate="size", reason=f"the object is {len(data):,} bytes; the card takes {limit:,}")
        return False
    started = time.monotonic()
    why, answer = gates.gate_checker(row["family"], obj, row, fam.checker_seconds(row["params"]), ctx.work)
    d["checker"] = {"answer": answer, "seconds": round(time.monotonic() - started, 2)}
    sha = "0x" + sha256_hex(data)
    if answer.get("valid") is not None:
        ctx.evidence.add(row["family"], checker_sha256(row["family"]), row, sha, answer.get("score"), why is None,
                         ctx.today)
    if why:
        d.update(decision="dropped", gate="checker", reason=why)
        return False
    d["object"] = {"sha256": sha, "bytes": len(data), "readFrom": meta["url"], "licence": meta["licence"],
                   "copied": bool(meta["copyable"])}
    d["_object"] = obj if meta["copyable"] else None
    as_of = ctx.state.as_of(row, ctx.today)
    return finish(d, cards.build(fam, row, d["round"], d["replaces"], as_of=as_of), ctx)


def finish(d, body, ctx):
    texts = gates.gate_texts(body)
    if texts:
        d.update(decision="dropped", gate="texts", reason=texts)
        return False
    d["body"] = body
    d["decision"] = "publish-new" if d["decision"] == "candidate-new" else "publish-next-round"
    d["listKey"] = body["list"]["key"]
    return True


# ---------------------------------------------------------------------------- sending (--publish only)
def still_ours(client, list_key):
    """None when the list `list_key` is, on Papex right now, OPEN and without an accepted run; else why it must be
    left alone (an accepted run is the runner's to carry into the next round)."""
    try:
        fresh = [x for x in client.tasks() if x.get("listKey") == list_key]
    except Exception as e:
        return f"Papex could not be read again before changing {list_key} ({str(e)[:120]})"
    if not fresh:
        return f"{list_key} is no longer in Papex's list of task lists"
    if fresh[0].get("state") != "OPEN":
        return f"{list_key} is {fresh[0].get('state')} now"
    if fresh[0].get("taskResult"):
        return f"{list_key} now holds an accepted run: the runner carries it into the next round"
    return None


# Papex's refusals of a round that replaces a list holding an accepted run (server, 20 Nov): the runner's job.
REFUSALS = {
    "SHARED_WORK_TASK_ROUND_WORSE": "Papex refused it (SHARED_WORK_TASK_ROUND_WORSE): the list holds an accepted run "
                                    "with a better score than this round's best known value; the runner carries it "
                                    "into the next round",
    "SHARED_WORK_TASK_REPLACES_INVALID": "Papex refused it (SHARED_WORK_TASK_REPLACES_INVALID): the list cannot be "
                                         "replaced (for a counterexample list: it holds an accepted run)",
}


def send(decisions, client):
    """Closes first, then next rounds, then new cards; each outcome is kept in its decision. Never raises.
    Before a close or a round that replaces a list, that list is read again from Papex: a list that meanwhile got an
    accepted run, or is no longer open, is left alone. Papex's own refusal (409, e.g. SHARED_WORK_TASK_ROUND_WORSE or
    SHARED_WORK_TASK_REPLACES_INVALID) is kept as such, never retried."""
    order = ([d for d in decisions if d["decision"] == "pull"] +
             [d for d in decisions if d["decision"] == "publish-next-round"] +
             [d for d in decisions if d["decision"] == "publish-new"])
    for d in order:
        target = d.get("listKey") if d["decision"] == "pull" else (d.get("body") or {}).get("replaces")
        if target:
            why = still_ours(client, target)
            if why:
                d["sent"] = {"held": why}
                continue
        try:
            if d["decision"] == "pull":
                answer = cards.close(client, d["problemSlug"], d["listKey"],
                                     f"The source now gives the exact value: {d['reason']}")
                d["sent"] = {"state": (answer or {}).get("state")}
            else:
                answer = cards.publish(client, d["body"]) or {}
                d["sent"] = {"listKey": answer.get("listKey"), "already": bool(answer.get("already")),
                             "path": answer.get("path")}
        except Exception as e:  # the client's PublisherError, or anything else: recorded, the run goes on
            status, code = getattr(e, "status", None), getattr(e, "code", None)
            if status == 409:
                d["sent"] = {"held": REFUSALS.get(code, f"Papex refused it ({code or 409}): {str(e)[:200]}"),
                             "status": status, "code": code}
            else:
                d["sent"] = {"error": str(e)[:300], "status": status, "code": code}


# ---------------------------------------------------------------------------- pacing and sanity
MAX_CLOSES = 2  # closes a run may send
CHANGE_SHARE = 0.2  # more than this share of a family's open cards closing or moving in one run: held for a person


def guarded(fn, d, ctx):
    """fn(d, ctx), with anything it raises turned into a dropped row: one bad entry never stops the run."""
    try:
        return fn(d, ctx)
    except Exception as e:
        d.update(decision="dropped", gate="entry", reason=f"the card could not be made ({type(e).__name__}: "
                                                          f"{str(e)[:120]})")
        return False


def proved_key(row):
    return "proved|" + row["id"] + "|" + row["bestKnownValue"]


def observe(rows, state):
    """Today's readings, for "the same reading on two runs in a row": every row's state, and every proof read."""
    for r in rows:
        state.observe(records.FirstSeen.key(r, no_object=not r.get("objectRef")))
        if gates.gate_proved(r):
            state.observe(proved_key(r))


def pace_changes(decisions, published, state, today):
    """Holds back what a layout or schema change could do to a whole family at once:
      - a family where more than 20% of its open cards would close or move today (and more than one) is left as it
        is and flagged for a person;
      - a close goes out only when the run before today's read the same proof (two runs in a row);
      - at most MAX_CLOSES closes a run (the rest wait)."""
    open_count = {}
    for item in published.get("tasks", []):
        fam = (item.get("task") or {}).get("family")
        if item.get("state") == "OPEN" and fam in FAMILIES:
            open_count[fam] = open_count.get(fam, 0) + 1
    changing = {}
    for d in decisions:
        if d["decision"] in ("pull",) + NEXT_ROUND:
            changing.setdefault(d["family"], []).append(d)
    for fam, ds in changing.items():
        n = open_count.get(fam, 0)
        if len(ds) > 1 and n and len(ds) > CHANGE_SHARE * n:
            for d in ds:
                d.update(decision="odd", held=d["decision"],
                         reason=f"held: {len(ds)} of the {n} open cards of {fam} would close or move today; a "
                                "person should look at the source first (a layout change?)")
    closes = []
    for d in decisions:
        if d["decision"] != "pull":
            continue
        if not state.seen_on_previous_run(proved_key(d["row"]), today):
            d.update(decision="waiting", gate="close-pending",
                     reason="the source gives the exact value today; the card is closed only when the next daily "
                            "run reads the same")
        else:
            closes.append(d)
    for d in sorted(closes, key=lambda d: d["slug"])[MAX_CLOSES:]:
        d.update(decision="waiting", gate="close-pending", reason=f"at most {MAX_CLOSES} closes a run")


def sanity_problems(row, ctx):
    """For a card without a linked object: the value is not above the table's own upper bound, it fits the
    neighbouring entries by the relations the mathematics guarantees (families.py, neighbours), and the same state
    was read on the run before today's."""
    fam = FAMILIES[row["family"]]
    v = int(row["bestKnownValue"])
    out = []
    up = row.get("upperOrLowerLimit")
    if row["direction"] == "max" and isinstance(up, int) and v > up:
        out.append(f"the value {v} is above the table's upper bound {up}")
    index = getattr(ctx, "index", {}).get(row["family"], {})
    for params, rel, why in fam.neighbours(row["params"]):
        other = index.get(json.dumps(params, sort_keys=True))
        if other is None:
            continue
        w = int(other["bestKnownValue"])
        if (rel == "ge" and v < w) or (rel == "le" and v > w):
            out.append(f"the value {v} does not fit {fam.slug(params)} ({w}): {why}")
    if not ctx.state.seen_on_previous_run(records.FirstSeen.key(row, no_object=True), ctx.today):
        out.append("the run before today's did not read the same value (a card without an object needs two runs "
                   "in a row)")
    return out


# ---------------------------------------------------------------------------- the run
def run(args):
    config = read_json(os.path.join(HERE, "config.json"))
    today = records.utc_today()
    out = os.path.abspath(args.out)
    work = os.path.join(out, "work")
    for sub in ("", "cards", "objects", "work"):
        os.makedirs(os.path.join(out, sub), exist_ok=True)
    fetcher = fetch.Fetcher(args.cache, budgets=dict(config["hostBudgets"]),
                            default_budget=config["defaultHostBudget"], offline=args.offline)
    client = None
    if args.publish or args.read_papex:
        token = os.environ.get(TOKEN_ENV, "")
        if not token.strip():
            raise SystemExit(f"--publish and --read-papex need the publisher token in the environment ({TOKEN_ENV}).")
        publisher = cards.load_publisher(args.kit)
        reader = publisher.Publisher(args.api, token)
        try:
            published = {"tasks": reader.tasks()}
        except Exception as e:
            raise SystemExit(f"Papex's list of task lists could not be read: {str(e)[:300]}")
        client = reader if args.publish else None
    else:
        published = read_json(args.published) if args.published else {"tasks": []}
    max_new = args.max_new
    if args.first_batch is not None:
        mine = [x for x in published.get("tasks", []) if (x.get("task") or {}).get("family") in FAMILIES]
        if mine:
            raise SystemExit(f"--first-batch is for the launch day: Papex already holds {len(mine)} lists of the "
                             "finder's families (use --max-new).")
        max_new = args.first_batch
    state = records.FirstSeen(args.state)
    evidence = records.Evidence(args.validation)
    ctx = Context(fetcher, work, today, state, evidence, config)
    started = time.monotonic()
    rows, problems = read_sources(fetcher, config, args.family, today)
    decisions = decide(rows, published, config)
    if args.only:  # one named card, whatever the pacing
        decisions = [d for d in decisions if d["slug"] == args.only]
        if not decisions:
            raise SystemExit(f"--only {args.only}: today's sources have no entry of that name (see out/plan.json of a "
                             "dry run for the names).")
        max_new = max(max_new, 1)
    ctx.index = {}
    for r in rows:
        ctx.index.setdefault(r["family"], {})[json.dumps(r["params"], sort_keys=True)] = r
    observe(rows, state)
    pace_changes(decisions, published, state, today)
    for d in decisions:  # next rounds first: they are not counted against the new cards
        if d["decision"] in NEXT_ROUND:
            guarded(make_card, d, ctx)
    news = order_new([d for d in decisions if d["decision"] == "candidate-new"], config, published)
    made = 0
    for d in news:
        if made >= max_new:
            d.update(decision="waiting", reason=f"not reached today: {max_new} new cards a run")
            continue
        made += guarded(make_card, d, ctx)
    if client is not None:
        send(decisions, client)
    state.finish(today)
    state.save()
    evidence.save()
    report = objectless_report(decisions, config, evidence)
    write_outputs(out, today, decisions, problems, fetcher, rows, args, time.monotonic() - started, max_new, report)
    return 0


def objectless_report(decisions, config, evidence):
    """Per family: whether cards without a linked object are allowed, the evidence, how many entries such cards
    would add (those that pass every other gate), and the ones that look weakest (old constructions, wide gaps)."""
    out = {}
    for name in FAMILIES:
        rows = [d for d in decisions if d["family"] == name and d.get("noObject") and d.get("row")
                and (d["decision"] in ("candidate-new", "publish-new", "waiting", "publish-next-round")
                     or (d["decision"] == "dropped" and d.get("gate") == "object"))]
        ok, good, bad = evidence.status(name, checker_sha256(name))
        rule = config["families"].get(name, {}).get("objectless") or {}

        def gap(d):
            r = d["row"]
            up = r.get("upperOrLowerLimit")
            return (up / int(r["bestKnownValue"])) if up and int(r["bestKnownValue"]) else 0.0

        old = [d for d in rows if not d["row"].get("recent")]
        weakest = sorted(old, key=lambda d: -gap(d))[:10]
        out[name] = {"allowed": bool(rule.get("allow")), "tablePrimary": bool(rule.get("tablePrimary")),
                     "why": rule.get("why"), "evidence": {"reproduced": good, "mismatches": bad, "enough": ok},
                     "entries": len(rows),
                     "weakest": [{"slug": d["slug"], "value": d["row"]["bestKnownValue"],
                                  "upper": d["row"].get("upperOrLowerLimit"), "by": d["row"]["by"],
                                  "labels": d["row"].get("labels")} for d in weakest]}
    return out


# ---------------------------------------------------------------------------- outputs
def read_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def write_json(path, value):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(value, fh, indent=1, ensure_ascii=False)


def public_decision(d):
    row = d.get("row") or {}
    keep = {k: v for k, v in d.items() if k not in ("row", "body", "_object", "keepBestKnown")}
    if row:
        keep["source"] = {k: row.get(k) for k in ("bestKnownValue", "direction", "by", "year", "sourceName",
                                                   "sourceUrl", "objectUrl", "objectLicence", "provedOptimal",
                                                   "upperOrLowerLimit", "readOn", "recent", "labels", "secondary")}
    return keep


def write_outputs(out, today, decisions, problems, fetcher, rows, args, seconds, max_new, report):
    counts = {}
    for d in decisions:
        counts[d["decision"]] = counts.get(d["decision"], 0) + 1
    plan = {"schema": "papex-finder-plan/v2", "date": today, "mode": "publish" if args.publish else "dry-run",
            "family": args.family, "maxNew": max_new, "firstBatch": args.first_batch, "published": args.published,
            "counts": dict(sorted(counts.items())), "requests": fetcher.summary(), "sourceProblems": problems,
            "objectless": report, "decisions": [public_decision(d) for d in decisions]}
    write_json(os.path.join(out, "plan.json"), plan)
    dropped = [{"slug": d["slug"], "family": d["family"], "params": d["params"], "gate": d.get("gate"),
                "reason": d["reason"], "sourceValue": (d.get("row") or {}).get("bestKnownValue")}
               for d in decisions if d["decision"] == "dropped"]
    write_json(os.path.join(out, "dropped.json"), {"date": today, "dropped": dropped})
    made = [d for d in decisions if d["decision"] in ("publish-new", "publish-next-round")]
    set_aside(out, {d["slug"] + ".json" for d in made})
    notice = ["Objects in this folder are copied from sources whose licence allows it, with attribution:", ""]
    for d in made:
        write_json(os.path.join(out, "cards", d["slug"] + ".json"), d["body"])
        if d.get("_object") is not None:
            with open(os.path.join(out, "objects", d["slug"] + ".json"), "wb") as fh:
                fh.write(canonical_bytes(d["_object"]))
            notice.append(f"{d['slug']}.json  from {d['object']['readFrom']}  licence: {d['object']['licence']}")
    with open(os.path.join(out, "objects", "NOTICE.txt"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(notice) + "\n")
    with open(os.path.join(out, "summary.md"), "w", encoding="utf-8") as fh:
        fh.write(summary_text(today, decisions, fetcher, args, max_new, problems))


def set_aside(out, keep):
    """Moves an earlier run's cards and objects that this run does not make into out/previous/<time>/ (nothing is
    deleted), so out/cards and out/objects hold exactly this run's files."""
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    for sub in ("cards", "objects"):
        folder = os.path.join(out, sub)
        for name in sorted(os.listdir(folder)):
            if name.endswith(".json") and name not in keep:
                target = os.path.join(out, "previous", stamp, sub)
                os.makedirs(target, exist_ok=True)
                os.replace(os.path.join(folder, name), os.path.join(target, name))


def _bk_text(bk):
    who = bk["by"] + (f", {bk['year']}" if bk.get("year") else "")
    return f"best known {bk['value']} ({who}; {bk['sourceName']})"


def _sent(d):
    s = d.get("sent")
    if s is None:
        return ""
    if s.get("error"):
        return " [send failed: " + s["error"][:80] + "]"
    if s.get("held"):
        return " [held: " + s["held"][:80] + "]"
    return " [already there]" if s.get("already") else ""


def summary_text(today, decisions, fetcher, args, max_new, problems=()):
    """About 25 lines of plain English."""
    by = {}
    for d in decisions:
        by.setdefault(d["decision"], []).append(d)
    new, moved, pulled = by.get("publish-new", []), by.get("publish-next-round", []), by.get("pull", [])
    sent = "published" if args.publish else "would be published (dry run: nothing was sent)"
    lines = [f"# Finder, {today}", "", f"{len(new)} new cards {sent}:"]
    for d in new[:20]:
        bk = d["body"]["list"]["howTo"]["task"]["bestKnown"]
        lines.append(f"- {d['body']['list']['title']}: {_bk_text(bk)}{_sent(d)}")
    if len(new) > 20:
        lines.append(f"- and {len(new) - 20} more (plan.json)")
    if moved:
        lines.append(f"{len(moved)} cards move to a new round:")
        for d in moved[:3]:
            lines.append(f"- {d['body']['list']['title']}: {d['reason']}{_sent(d)}")
    if pulled:
        lines.append(f"{len(pulled)} cards are closed because the source now gives the exact value:")
        for d in pulled[:3]:
            lines.append(f"- {d['slug']}{_sent(d)}")
    odd = [(d["slug"], d["reason"]) for d in by.get("odd", [])]
    odd += [(d["slug"], d["reason"]) for d in by.get("dropped", []) if d.get("gate") == "second"]
    odd += [(d["slug"], (d.get("sent") or {}).get("error") or (d.get("sent") or {}).get("held"))
            for d in decisions if (d.get("sent") or {}).get("error") or (d.get("sent") or {}).get("held")]
    odd += [(f"source {p.get('source')}", p["reason"]) for p in problems if not p.get("row")]  # a source skipped
    lines.append(f"Needs a person: {len(odd)}." + ("" if odd else " Nothing looks odd."))
    for slug, why in odd[:4]:
        lines.append(f"- {slug}: {why}"[:200])
    if len(odd) > 4:
        lines.append(f"- and {len(odd) - 4} more (plan.json)")
    pending = [d for d in by.get("waiting", []) if d.get("gate") == "close-pending"]
    if pending:
        lines.append(f"Closes waiting for the same reading on the next run, or for room: {len(pending)}.")
    waiting = len(by.get("waiting", [])) - len(pending)
    lines.append(f"Waiting for a later day: {waiting} entries that passed the quick checks ({max_new} new cards a run). "
                 f"Dropped by a check: {len(by.get('dropped', []))} (dropped.json).")
    req = fetcher.summary()["requests"]
    lines.append("Requests to the source sites: " + (", ".join(f"{h} {c}" for h, c in req.items()) or "none") + ".")
    return "\n".join(lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--publish", action="store_true")
    ap.add_argument("--family", choices=sorted(FAMILIES))
    ap.add_argument("--max-new", type=int, default=5)
    ap.add_argument("--first-batch", type=int)
    ap.add_argument("--only")
    ap.add_argument("--published")
    ap.add_argument("--read-papex", action="store_true")
    ap.add_argument("--kit", default=DEFAULT_KIT)
    ap.add_argument("--api", default=DEFAULT_API)
    ap.add_argument("--cache", default=CACHE)
    ap.add_argument("--out", default=os.path.join(HERE, "out"))
    ap.add_argument("--state", default=os.path.join(HERE, "state", "first-seen.json"))
    ap.add_argument("--validation", default=os.path.join(HERE, "validation"))
    ap.add_argument("--offline", action="store_true")
    args = ap.parse_args(argv)
    if args.max_new < 0 or (args.first_batch is not None and args.first_batch < 1):
        ap.error("--max-new must be 0 or more, --first-batch 1 or more")
    if args.publish and (args.published or args.read_papex):
        ap.error("--published and --read-papex are for a dry run; --publish reads Papex itself")
    if args.published and args.read_papex:
        ap.error("--published and --read-papex are two ways to say what Papex holds: give one")
    if args.only is not None and not re.match(r"^[a-z0-9]+(-[a-z0-9]+)*$", args.only):
        ap.error("--only takes a card's slug, such as sorting-network-13-size")
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
