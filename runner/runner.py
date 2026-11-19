#!/usr/bin/env python3
"""Decide the runs sent to the re-run lists of this kit. Papex Labs runs this; nobody accepts a run by hand.

  PAPEX_SHARED_WORK_RUNNER_TOKEN=… python3 runner/runner.py [--post] [--api URL] [--list KEY]

Without --post it only prints what it would send. A re-run list keeps no proofs, so a sent run goes
straight to a decision. The rules, the same for every run:

1. The result must come from a kit this repository knows (runner/kits.sha256 lists the SHA-256 of
   every released rerun.py; the one next to this file counts too).
2. Each unit must name the list's own file for that unit (its SHA-256 is in the manifest) and the
   commit that file names, and the Lean version must be the one the file names.
3. The build must have passed, with no problem reported, and each theorem must rest only on the
   axioms the file permits.
4. A run reported as FAILED rejects the batch and prints ALERT: a person looks at it and at the
   list. Nothing is published by this program.

What an accepted run says: the kit the person ran reported a passing build of exactly the files the
list names. The report is the kit's; this program compares it with the list's file and, when the
list has one, with the fingerprint of Papex Labs' own run. It cannot show that the person's
computer did the work, and the words it sends never say so.

The token is read from the environment, sent as X-Papex-Runner-Token and never printed.
"""

import argparse
import hashlib
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.dirname(HERE)
LISTS = os.path.join(KIT, "lists")
TOKEN_ENV = "PAPEX_SHARED_WORK_RUNNER_TOKEN"
KIT_NAME = "papex-rerun-kit"
ISSUES = "https://github.com/papexlabs/rerun-kit/issues"


def sha256_file(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


class Api:
    def __init__(self, base, token):
        self.base, self.token = base.rstrip("/"), token

    def call(self, method, path, body=None):
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(self.base + path, data=data, method=method)
        request.add_header("Accept", "application/json")
        request.add_header("User-Agent", "papex-rerun-runner")
        request.add_header("X-Papex-Runner-Token", self.token)
        if data is not None:
            request.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return json.loads(response.read().decode() or "null")
        except urllib.error.HTTPError as error:
            raise SystemExit(f"{method} {path} answered {error.code}: {error.read().decode('utf-8', 'replace')[:500]}")

    def queue(self, list_key):
        page = 0
        while True:
            query = {"state": "SUBMITTED", "page": page, "size": 100}
            if list_key:
                query["list"] = list_key
            answer = self.call("GET", "/api/admin/shared-work/batches?" + urllib.parse.urlencode(query))
            yield from answer["content"]
            page += 1
            if page >= answer["totalPages"]:
                return


def known_kits():
    kits = {"0x" + sha256_file(os.path.join(KIT, "rerun.py"))}
    try:
        with open(os.path.join(HERE, "kits.sha256")) as fh:
            kits |= {"0x" + line.split()[0] for line in fh if line.strip() and not line.startswith("#")}
    except OSError:
        pass
    return kits


def known_lists():
    """Every list of this repository: list sha256 -> unit key -> {line, spec, reference}."""
    found = {}
    for problem in sorted(os.listdir(LISTS)):
        folder = os.path.join(LISTS, problem)
        for name in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
            if not name.endswith(".manifest.ndjson"):
                continue
            list_key = name[:-len(".manifest.ndjson")]
            units = {}
            with open(os.path.join(folder, name)) as fh:
                for line in fh:
                    if not line.strip():
                        continue
                    entry = json.loads(line)
                    base = os.path.join(folder, list_key, entry["key"])
                    with open(base + ".spec.json") as spec:
                        units[entry["key"]] = {"line": entry, "spec": json.load(spec), "reference": None}
                    try:
                        with open(base + ".reference.json") as ref:
                            units[entry["key"]]["reference"] = json.load(ref).get("outputSha256")
                    except OSError:
                        pass
            found["0x" + sha256_file(os.path.join(folder, name))] = units
    return found


def check(result, units, kits):
    """None when every unit of the result passes the rules above, else (code, text, next step)."""
    tools = {t.get("name"): t for t in (result.get("env") or {}).get("tools") or []}
    kit = tools.get(KIT_NAME)
    if not kit or kit.get("sourceSha256") not in kits:
        return ("TOOL_NOT_ALLOWED", "The result was not written by a released version of the re-run kit.",
                "Get the newest kit (git pull) and run it again.")
    lean = (tools.get("lean") or {}).get("version") or ""
    if not result.get("units"):
        return ("NOT_VERIFIED", "The result holds no run.", "Run the kit again.")
    for unit in result["units"]:
        known = units.get(unit.get("key"))
        if not known:
            return ("INPUT_HASH_MISMATCH", "The result names a unit that is not in the list.", "Run the kit again.")
        spec, extra = known["spec"], unit.get("extra") or {}
        if extra.get("spec") != known["line"]["inputSha256"] or extra.get("commit") != spec["commit"]:
            return ("INPUT_HASH_MISMATCH", "The run was not made from the files the list names.",
                    "Get the newest kit (git pull) and run it again.")
        version = spec["toolchain"].split(":v")[-1]
        if f"version {version}," not in lean:
            return ("TOOL_NOT_ALLOWED", f"The run did not use Lean {version}.",
                    "Run the kit again; it installs the right Lean itself.")
        if unit.get("outcome") != "PASS":
            return ("OUTCOME_UNEXPECTED", "The kit reported that the build did not pass.",
                    f"Please keep the work folder and open an issue at {ISSUES}.")
        axioms = extra.get("axioms") or {}
        permitted = set(spec["permittedAxioms"])
        for theorem in spec["theorems"]:
            listed = axioms.get(theorem["name"])
            if not isinstance(listed, list) or not set(listed) <= permitted:
                return ("NOT_VERIFIED", "The result does not show the theorem resting on the permitted axioms only.",
                        f"Please keep the work folder and open an issue at {ISSUES}.")
        said = {c.get("tool"): c.get("result") for c in unit.get("checks") or []}
        if extra.get("problems") or said.get("lake build") != "passed" or said.get("#print axioms") != "permitted":
            return ("NOT_VERIFIED", "The result does not say that the build and the axioms check passed.",
                    "Run the kit again.")
    return None


def decide(batch, lists, kits):
    """The one decision for a sent run: (route, body), or None when its list is not of this repository."""
    units = lists.get(batch["list"]["sha256"])
    if units is None or batch["state"] != "SUBMITTED":
        return None
    result = json.loads(batch["resultText"])
    failure = check(result, units, kits)
    keys = [u["key"] for u in batch["units"]]
    in_result = {u.get("key"): u for u in result.get("units") or []}
    if failure:
        code, text, next_step = failure
        if code == "OUTCOME_UNEXPECTED":
            print(f"ALERT {batch['batchKey']}: a build is reported as failed. Look at this run and the list.")
        return "verdict", {
            "verdictId": str(uuid.uuid4()), "expectedState": "SUBMITTED", "outcome": "REJECTED",
            "reasonCode": code, "reasonText": text, "nextStepText": next_step, "summaryText": None,
            "units": [{"key": k, "verdict": "NOT_ACCEPTED", "reason": "BATCH_REJECTED", "checkedWith": None}
                      for k in keys if k in in_result],
            "keepChecks": []}
    verdicts, same = [], 0
    for key in keys:
        unit = in_result.get(key)
        if not unit:
            continue
        version = units[key]["spec"]["toolchain"].split(":v")[-1]
        reference = units[key]["reference"]
        equal = bool(reference) and unit["proof"]["sha256"] == reference
        same += equal
        verdicts.append({"key": key, "verdict": "ACCEPTED", "reason": None,
                         "checkedWith": (f"the participant's kit with Lean {version}; Papex Labs compared its report "
                                         "with the list's file" + ("; same fingerprint as Papex Labs' run" if equal else ""))})
    count = len(verdicts)
    summary = ("Papex Labs compared your kit's report with the list's file: the same files, the same Lean "
               "version, a build that passed, and only the permitted axioms.")
    if same == count:
        summary += " What your computer built has the same fingerprint as Papex Labs' own run."
    return "verdict", {"verdictId": str(uuid.uuid4()), "expectedState": "SUBMITTED", "outcome": "ACCEPTED",
                       "reasonCode": None, "reasonText": None, "nextStepText": None, "summaryText": summary,
                       "units": verdicts, "keepChecks": []}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Re-run lists: acceptance runner")
    parser.add_argument("--api", default="https://api.papex.org")
    parser.add_argument("--list", default=None, help="only this list (key or id)")
    parser.add_argument("--post", action="store_true", help="send the decisions (default: print them)")
    parser.add_argument("--batch-file", default=None,
                        help="decide one runner batch view read from a file, and print it (no network, no token)")
    args = parser.parse_args(argv)
    lists, kits = known_lists(), known_kits()
    if args.batch_file:
        with open(args.batch_file) as fh:
            print(json.dumps(decide(json.load(fh), lists, kits), indent=1, ensure_ascii=False))
        return 0
    token = os.environ.get(TOKEN_ENV, "").strip()
    if not token:
        raise SystemExit(f"Set {TOKEN_ENV}.")
    api = Api(args.api, token)
    for entry in api.queue(args.list):
        batch = api.call("GET", f"/api/admin/shared-work/batches/{entry['batchKey']}")
        decision = decide(batch, lists, kits)
        if decision is None:
            print(f"{batch['batchKey']} {batch['state']}: not a list of this kit")
            continue
        route, body = decision
        print(f"{batch['batchKey']}: {body['outcome']} {body.get('reasonCode') or ''}")
        if args.post:
            api.call("POST", f"/api/admin/shared-work/batches/{batch['batchKey']}/{route}", body)
        else:
            print(json.dumps(body, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
