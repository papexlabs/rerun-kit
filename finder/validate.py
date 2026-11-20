#!/usr/bin/env python3
"""Records evidence that a family's checker reproduces its source's values on real published objects, in
validation/<family>.json (which object, its sha256, the table's value, the checker's score, the checker's
version). The daily program allows cards without a linked object for a family only when that file (or the run
itself) holds at least 10 reproduced values for the current checker and no mismatch (config.json, "objectless").

    python3 validate.py --family F [--max N] [--cache DIR] [--offline] [--validation DIR]

It reads the source's table, takes the entries that link an object (smallest first), reads up to N objects
(through the cache; --offline: only what the cache holds, no request), runs the checker on each and records the
outcome. Nothing is published; no card is made.
"""

import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.dont_write_bytecode = True
sys.path.insert(0, HERE)

import fetch  # noqa: E402
import gates  # noqa: E402
import records  # noqa: E402
import run  # noqa: E402
from common import CACHE, Unavailable, canonical_bytes, checker_sha256, sha256_hex  # noqa: E402
from families import ALL as FAMILIES  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--family", required=True, choices=sorted(FAMILIES))
    ap.add_argument("--max", type=int, default=20)
    ap.add_argument("--cache", default=CACHE)
    ap.add_argument("--validation", default=os.path.join(HERE, "validation"))
    ap.add_argument("--work", default=os.path.join(HERE, "out", "work"))
    ap.add_argument("--offline", action="store_true")
    args = ap.parse_args(argv)
    config = run.read_json(os.path.join(HERE, "config.json"))
    fetcher = fetch.Fetcher(args.cache, budgets=dict(config["hostBudgets"]),
                            default_budget=config["defaultHostBudget"], offline=args.offline)
    today = records.utc_today()
    rows, problems = run.read_sources(fetcher, config, args.family, today)
    fam = FAMILIES[args.family]
    evidence = records.Evidence(args.validation)
    sha_checker = checker_sha256(args.family)
    linked = sorted((r for r in rows if r.get("objectRef") and not fam.static_problem(r["params"], r["bestKnownValue"])),
                    key=lambda r: (r.get("instanceSize") or 0, r["id"]))
    done = 0
    for row in linked:
        if done >= args.max:
            break
        try:
            obj, _ = run.ADAPTERS[row["source"]].fetch_object(fetcher, row)
        except (fetch.FetchError, Unavailable) as e:
            print(f"skip {fam.slug(row['params'])}: {str(e)[:100]}")
            continue
        why, answer = gates.gate_checker(args.family, obj, row, fam.checker_seconds(row["params"]), args.work)
        if answer.get("valid") is None:
            continue
        evidence.add(args.family, sha_checker, row, "0x" + sha256_hex(canonical_bytes(obj)), answer.get("score"),
                     why is None, today)
        done += 1
        print(f"{'ok  ' if why is None else 'FAIL'} {fam.slug(row['params'])}: table {row['bestKnownValue']}, "
              f"checker {answer.get('score')}")
    evidence.save()
    ok, good, bad = evidence.status(args.family, sha_checker)
    print(f"{args.family}: {good} values reproduced, {bad} mismatches for checker {sha_checker[:14]}… "
          f"({'enough' if ok else 'not enough'} for cards without a linked object)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
