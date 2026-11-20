#!/usr/bin/env python3
"""Decide the runs sent to the re-run lists and the open tasks of this kit. Papex Labs runs this; nobody accepts
a run by hand.

  PAPEX_SHARED_WORK_RUNNER_TOKEN=… [PAPEX_SHARED_WORK_PUBLISHER_TOKEN=…] python3 runner/runner.py [--post]
      [--api URL] [--list KEY]

Without --post it only prints what it would send. A re-run list keeps no proofs, so a sent run goes
straight to a decision. The rules for a re-run list, the same for every run:

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

A task list (tasks/<slug>/, see tasks/README.md) is decided by running the task's checker here, on the
object in the result file:

1. the result must come from a released task.py (runner/kits.sha256), name the list's one unit (the
   task) and the list must have been made from this runner's tasks/<slug>/manifest.ndjson;
2. extra.checkerSha256 must be this runner's checker.py, the object within maxObjectBytes and
   proof.sha256 the SHA-256 of its canonical bytes;
3. the checker, run here in a separate process with time and memory limits, must say the object
   passes, with exactly extra.score;
4. to improve a bound, the score must be strictly better than the list's best known value, read from
   Papex at that moment; a counterexample only has to pass;
5. the list must still be open, with no run accepted yet.
A family's task (a list whose task names a family, families/<family>/) is decided the same way with
this runner's own families/<family>/checker.py, which must be the version the list names (otherwise the
run waits and an ALERT says to deploy the newest kit), and the list's params read from Papex.
After an accepted run, and when PAPEX_SHARED_WORK_PUBLISHER_TOKEN is set, it publishes the task's next
round (best known: the run's score, Papex as the source) or, for a counterexample, closes the list. When
that step fails the verdict stands; every run of this program first retries what is left undone.
After 400 seconds it starts no more checkers: the task runs left stay SUBMITTED for the next run.

The tokens are read from the environment, sent as X-Papex-Runner-Token and as the publisher's bearer
token (headers that are never passed on: no redirect is followed at all), and never printed. --api must be an
https address (http only on this computer).

Every text taken from a result file, an object or a checker's output is made one clean line before it is
printed or sent (task.py's clean(): no control, format or bidi character, no escape sequence, cut to the
server's limit). One sent run never stops the others: when Papex refuses a verdict, or gives no answer
VERDICT_TRIES times in a row, an ALERT names the batch, it stays SUBMITTED, and the run goes on with the next.
"""

import argparse
import hashlib
import importlib.util
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.dirname(HERE)
LISTS = os.path.join(KIT, "lists")
TOKEN_ENV = "PAPEX_SHARED_WORK_RUNNER_TOKEN"
KIT_NAME = "papex-rerun-kit"
TASK_KIT_NAME = "papex-task-kit"
# A hosted run has about 600 s (runner/render_task.py). After BUDGET_SECONDS no new checker is started in this run:
# the runs of task lists that are left stay SUBMITTED for the next run, which the next sent run or the cron starts.
BUDGET_SECONDS = 400
STARTED = time.monotonic()  # set again when main() starts
VERDICT_TRIES = 3  # a verdict Papex gave no answer to (or a 5xx) is sent again, the very same body, this often in all
RETRY_PAUSE = 2.0  # seconds before the second try; twice that before the third
ISSUES = "https://github.com/papexlabs/rerun-kit/issues"


def _load(name, path):
    before = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = before
    return module


publisher = _load("papex_task_publisher", os.path.join(HERE, "publisher.py"))
taskkit = publisher.kit  # task.py next to this folder: the same reading of objects and the same checker run
PUBLISHER_TOKEN_ENV = publisher.TOKEN_ENV
clean = taskkit.clean


def say(line=""):
    """Prints a line of the runner's log, made safe for a terminal (task.py's printable())."""
    print(taskkit.printable(line), flush=True)


def sha256_file(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


class ApiError(Exception):
    """An answer of Papex that is not a success (status, the answer's code), or no answer (status None)."""

    def __init__(self, status, code, text):
        super().__init__(text)
        self.status, self.code = status, code


class Api:
    def __init__(self, base, token):
        why = taskkit.api_problem(base)
        if why:
            raise SystemExit(f"--api (PAPEX_API) must be an https address such as https://api.papex.org: {why}.")
        self.base, self.token = base.rstrip("/"), token

    def _clean(self, text):
        return clean(text.replace(self.token, "[token]") if self.token else text, 600)

    def call(self, method, path, body=None):
        """Papex's answer as JSON; ApiError when it is not a success or there is none. Follows no redirect."""
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(self.base + path, data=data, method=method)
        request.add_header("Accept", "application/json")
        request.add_header("User-Agent", "papex-rerun-runner")
        request.add_unredirected_header("X-Papex-Runner-Token", self.token)
        if data is not None:
            request.add_header("Content-Type", "application/json")
        try:
            with taskkit.open_url(request, 60) as response:
                text = response.read(8 << 20).decode("utf-8", "replace")
        except urllib.error.HTTPError as error:
            try:
                said = error.read(65536).decode("utf-8", "replace")
            except OSError:
                said = ""
            try:
                code = json.loads(said).get("code")
            except (ValueError, AttributeError):
                code = None
            code = code if isinstance(code, str) and len(code) <= 80 else None
            raise ApiError(error.code, code, self._clean(f"{method} {path} answered {error.code}: {said}")) from None
        except Exception as error:  # noqa: BLE001 - no answer at all
            raise ApiError(None, None, self._clean(f"{method} {path}: no answer "
                                                   f"({getattr(error, 'reason', None) or error})")) from None
        try:
            return json.loads(text or "null")
        except ValueError:
            raise ApiError(None, None, f"{method} {path}: the answer was not JSON") from None

    def send(self, method, path, body):
        """call(), sent again with the very same body when Papex gave no answer or a 5xx: VERDICT_TRIES times in all
        at most. A refusal (4xx) is not sent again."""
        for attempt in range(1, VERDICT_TRIES + 1):
            try:
                return self.call(method, path, body)
            except ApiError as e:
                if attempt == VERDICT_TRIES or (e.status is not None and e.status < 500):
                    raise
                say(f"  {e}; sent again ({attempt + 1} of {VERDICT_TRIES})")
                time.sleep(RETRY_PAUSE * attempt)

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


def known_kits(name="rerun.py"):
    """The SHA-256 of every released version of the kit's file `name` (rerun.py or task.py) in kits.sha256, and of
    the one next to this runner."""
    kits = {"0x" + sha256_file(os.path.join(KIT, name))}
    try:
        with open(os.path.join(HERE, "kits.sha256")) as fh:
            kits |= {"0x" + line.split()[0] for line in fh
                     if line.strip() and not line.startswith("#") and line.split()[1:2] == [name]}
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


def decide(batch, lists, kits, tasks=None, read_page=None, accepted_now=None):
    """The one decision for a sent run: (route, body), (route, body, follow-up) for a task list, ("wait", why) when
    a task list's page could not be read, or None when its list is not of this repository."""
    units = lists.get(batch["list"]["sha256"])
    if units is None:
        if not tasks or batch.get("state") != "SUBMITTED":
            return None
        read_page = read_page or (lambda problem, key: (None, "no reader"))
        slug = task_of(batch, tasks)
        spec = local_spec(slug, tasks) if slug is not None else family_spec(batch, tasks, read_page)
        if spec is None or spec[0] == "wait":
            return spec
        return decide_task(batch, spec[1], tasks, read_page, accepted_now if accepted_now is not None else set())
    if batch["state"] != "SUBMITTED":
        return None
    result = json.loads(batch["resultText"])
    failure = check(result, units, kits)
    keys = [u["key"] for u in batch["units"]]
    in_result = {u.get("key"): u for u in result.get("units") or []}
    if failure:
        code, text, next_step = failure
        if code == "OUTCOME_UNEXPECTED":
            say(f"ALERT {batch['batchKey']}: a build is reported as failed. Look at this run and the list.")
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


# ---------------------------------------------------------------------------- open tasks

def known_tasks(root=None):
    """The task folders of this repository: their tasks, the SHA-256 of each manifest, and the released task.py."""
    root = root or taskkit.TASKS
    by_slug, by_sha = {}, {}
    for slug in taskkit.all_tasks(root):
        try:
            task = taskkit.load_task(slug, root)
            with open(os.path.join(root, slug, "manifest.ndjson"), "rb") as fh:
                manifest = fh.read()
        except (taskkit.TaskError, OSError) as e:
            say(f"ALERT tasks/{slug}: this runner cannot use it ({e})")
            continue
        if manifest.decode("utf-8", "replace") != taskkit.manifest_text(task):
            say(f"ALERT tasks/{slug}: manifest.ndjson is not the line task.json gives")
            continue
        by_slug[slug] = task
        by_sha["0x" + hashlib.sha256(manifest).hexdigest()] = slug
    return {"root": root, "bySlug": by_slug, "bySha": by_sha, "kits": known_kits("task.py"),
            "families": taskkit.FAMILIES}


def local_spec(slug, tasks):
    """("task", spec) for a list of a task folder of this repository."""
    with open(os.path.join(tasks["root"], slug, "manifest.ndjson"), "rb") as fh:
        manifest_sha = "0x" + hashlib.sha256(fh.read()).hexdigest()
    return "task", {"task": tasks["bySlug"][slug], "checker": os.path.join(tasks["root"], slug, "checker.py"),
                    "params": None, "manifestSha": manifest_sha, "page": None}


def family_spec(batch, tasks, read_page):
    """For a list that is no task folder of this repository: ("task", spec) when its page on Papex says it is the
    task of a family this runner has in the same version; ("wait", why) when that cannot be decided now; None when
    the list is no family's task."""
    lst = _dict(batch.get("list"))
    m = taskkit.LIST_KEY_RE.match(str(lst.get("key")))
    if not m or m.group("slug") in tasks["bySlug"]:
        return None
    page, why = read_page(lst.get("problemSlug"), lst.get("key"))
    if page is None:
        return "wait", f"its list's page could not be read ({why})"
    t = _dict(page).get("howTo")
    t = t.get("task") if isinstance(t, dict) else None
    if not isinstance(t, dict) or not t.get("family"):
        return None
    problems = taskkit.remote_problems(t)
    checker = taskkit.family_checker(str(t.get("family")), tasks["families"]) if not problems else None
    if problems or not os.path.isfile(checker) or "0x" + sha256_file(checker) != t.get("checkerSha256"):
        what = ("its task cannot be read (" + ", ".join(problems) + ")" if problems else
                f"this runner has no families/{t.get('family')}/checker.py in the version the list names; deploy the "
                "newest kit")
        say(f"ALERT {batch.get('batchKey')}: {what}")
        return "wait", what
    task = {"slug": t["slug"], "kind": t["kind"], "direction": t.get("direction"), "scoreLabel": t.get("scoreLabel"),
            "checkerSha256": t["checkerSha256"], "family": t["family"],
            "limits": {"maxObjectBytes": t["maxObjectBytes"], "checkerSeconds": t["checkerSeconds"]}}
    return "task", {"task": task, "checker": checker, "params": t.get("params") or {}, "manifestSha": None,
                    "page": (page, why)}


def task_of(batch, tasks):
    """The task a batch's list is a round of: by its manifest, or by its key and problem when the list was made
    with another manifest (another checker). None when the list is no task of this repository."""
    lst = batch.get("list") if isinstance(batch.get("list"), dict) else {}
    if lst.get("sha256") in tasks["bySha"]:
        return tasks["bySha"][lst["sha256"]]
    m = taskkit.LIST_KEY_RE.match(str(lst.get("key")))
    task = tasks["bySlug"].get(m.group("slug")) if m else None
    if task and task["problem"]["slug"] == lst.get("problemSlug"):
        return task["slug"]
    return None


RESULT_DEPTH = taskkit.MAX_DEPTH + 4  # the result file's own brackets around the object


def read_result(text):
    """The result file of a sent run as JSON, read as strictly as the kit reads an object; ObjectError if not."""
    if not isinstance(text, str):
        raise taskkit.ObjectError("there is no result file")
    if len(text) > taskkit.RESULT_MAX_BYTES:
        raise taskkit.ObjectError("it is larger than Papex takes")
    if taskkit.nesting(text) > RESULT_DEPTH:
        raise taskkit.ObjectError("its brackets go too deep")
    try:
        return json.loads(text, object_pairs_hook=taskkit._pairs, parse_constant=taskkit._constant,
                          parse_int=taskkit._int, parse_float=taskkit._float)
    except taskkit.ObjectError:
        raise
    except (ValueError, RecursionError) as e:
        raise taskkit.ObjectError(f"it is not JSON ({str(e)[:100]})")


def _dict(value):
    return value if isinstance(value, dict) else {}


def _list(value):
    return value if isinstance(value, list) else []


NEXT_STEP = {
    "TOOL_NOT_ALLOWED": "Get the newest kit (git pull) and write the result file again with python3 task.py result.",
    "INPUT_HASH_MISMATCH": "Write the result file again with python3 task.py result, and send it unchanged.",
    "TASK_RESULT_MISMATCH": "Write the result file again with python3 task.py result, and send it unchanged.",
    "TASK_CHECKER_CHANGED": "Get the newest kit (git pull), check the object again with python3 task.py check, and "
                            "take the task's open round to send it.",
    "TASK_NOT_VALID": "Check the object with python3 task.py check; a run can be sent once it passes.",
    "TASK_NOT_BETTER": "Search on: a run can be sent once python3 task.py check says the object is better.",
    "TASK_MOVED_ON": "Take the task's open round with the Papex connection, and send the result again with its batch "
                     "key (python3 task.py result).",
}


# The contract's sentence for each reason of a task run; the runner's reasonText starts with it, then says what
# exactly was found.
REASON_SENTENCE = {
    "TASK_NOT_VALID": "Papex ran the task's checker on the object and it was not accepted.",
    "TASK_NOT_BETTER": "The object passes the checker, but its score is not better than the best known value.",
    "TASK_MOVED_ON": "The task moved on to a new round while this run waited. Take the new round to send it.",
    "TASK_CHECKER_CHANGED": "The result was made with another version of the task's checker. Update the kit and run "
                            "it again.",
    "TASK_RESULT_MISMATCH": "The result file does not match its object (score or hash).",
}


REASON_LIMIT, NEXT_STEP_LIMIT, SUMMARY_LIMIT, CHECKED_LIMIT = 500, 300, 500, 160  # the server's, in UTF-16 units


def task_rejection(keys, code, detail):
    text = clean(REASON_SENTENCE.get(code, "") + " " + clean(detail), REASON_LIMIT)
    return "verdict", {
        "verdictId": str(uuid.uuid4()), "expectedState": "SUBMITTED", "outcome": "REJECTED", "reasonCode": code,
        "reasonText": text, "nextStepText": clean(NEXT_STEP[code], NEXT_STEP_LIMIT), "summaryText": None,
        "units": [{"key": k, "verdict": "NOT_ACCEPTED", "reason": "BATCH_REJECTED", "checkedWith": None} for k in keys],
        "keepChecks": []}, {"outcome": "REJECTED"}


def decide_task(batch, spec, tasks, read_page, accepted_now):
    """The decision for a sent run of a task list (the rules above): ("verdict", body, follow-up) or ("wait", why).
    spec: local_spec() or family_spec(). Never raises for anything in the result file."""
    task = spec["task"]
    slug = task["slug"]
    lst = _dict(batch.get("list"))
    keys = [u.get("key") for u in _list(batch.get("units")) if isinstance(u, dict)]
    try:
        result = read_result(batch.get("resultText"))
    except taskkit.ObjectError as e:
        return task_rejection(keys, "TASK_RESULT_MISMATCH", f"It could not be read: {e}.")
    result = _dict(result)
    units = [u for u in _list(result.get("units")) if isinstance(u, dict)]
    in_result = [u.get("key") for u in units if u.get("key") in keys] or keys
    tools = {t.get("name"): t for t in _list(_dict(result.get("env")).get("tools")) if isinstance(t, dict)}
    if _dict(tools.get(TASK_KIT_NAME)).get("sourceSha256") not in tasks["kits"]:
        return task_rejection(in_result, "TOOL_NOT_ALLOWED",
                              "The result was not written by a released version of the task kit (task.py).")
    if len(units) != 1 or units[0].get("key") != slug or units[0].get("outcome") != "PASS":
        return task_rejection(in_result, "INPUT_HASH_MISMATCH",
                              f"The result must name the list's one unit, {slug}, as PASS, and nothing else.")
    unit, extra = units[0], _dict(units[0].get("extra"))
    manifest_sha = spec["manifestSha"] or lst.get("sha256")  # a family's list: its task names the checker
    ours, theirs = task["checkerSha256"], extra.get("checkerSha256")
    if lst.get("sha256") != manifest_sha or theirs != ours:
        made_with = theirs if lst.get("sha256") == manifest_sha else "the list's"
        return task_rejection(in_result, "TASK_CHECKER_CHANGED",
                              f"It was made with {str(made_with)[:18]}…; Papex's runner has {ours[:18]}….")
    if extra.get("task") != slug or "object" not in extra:
        return task_rejection(in_result, "TASK_RESULT_MISMATCH",
                              "It does not hold the task's name and the object (extra.task, extra.object).")
    score = extra.get("score")
    if task["kind"] == "record" and not taskkit.is_decimal(score):
        return task_rejection(in_result, "TASK_RESULT_MISMATCH", "It gives no score as a decimal text.")
    if task["kind"] == "counterexample" and score is not None:
        return task_rejection(in_result, "TASK_RESULT_MISMATCH", "A counterexample's result gives no score.")
    try:
        data = taskkit.canonical_bytes(extra["object"])
    except (taskkit.ObjectError, ValueError, RecursionError) as e:
        return task_rejection(in_result, "TASK_RESULT_MISMATCH", f"The object cannot be written as JSON again ({e}).")
    limit = task["limits"]["maxObjectBytes"]
    if len(data) > limit:
        return task_rejection(in_result, "TASK_RESULT_MISMATCH",
                              f"The object is {len(data):,} bytes as carried; the task takes at most {limit:,}.")
    proof = _dict(unit.get("proof"))
    if proof.get("sha256") != "0x" + hashlib.sha256(data).hexdigest() or proof.get("bytes") != len(data):
        return task_rejection(in_result, "TASK_RESULT_MISMATCH",
                              "Its proof.sha256 and proof.bytes are not those of the object's canonical bytes.")
    keys_problem = taskkit.object_keys_problem(extra["object"], task) if task.get("objectKeys") else None
    if keys_problem:  # an accepted object is shown publicly: nothing in it the task's format does not name
        return task_rejection(in_result, "TASK_NOT_VALID", f"The object is not in the task's format: {keys_problem}.")
    run = taskkit.run_checker(spec["checker"], data, task["limits"]["checkerSeconds"], task["kind"],
                              params=spec["params"], sha256=task["checkerSha256"])
    if run.status == "fault":
        say(f"ALERT {clean(batch.get('batchKey'), 40)}: the checker of {slug} gave no answer on this object "
            f"({run.reason[:200]}). Look at this run.")
        return task_rejection(in_result, "TASK_NOT_VALID", f"The checker gave no answer: {run.reason[:300]}.")
    if run.status == "failed":
        return task_rejection(in_result, "TASK_NOT_VALID", f"The checker said: {run.reason[:380]}")
    if task["kind"] == "record" and run.score != score:
        return task_rejection(in_result, "TASK_RESULT_MISMATCH",
                              f"The object passes the checker with {run.score}, but the result file says {score}.")
    page, why = spec["page"] or read_page(lst.get("problemSlug"), lst.get("key"))
    page = _dict(page)
    page_list, howto = _dict(page.get("list")), _dict(page.get("howTo"))
    list_task = howto.get("task")
    if not isinstance(list_task, dict) or list_task.get("slug") != slug or not page_list.get("state"):
        return "wait", f"its list's page could not be read ({why or 'no task on the page'})"
    best = list_task.get("bestKnown")
    if task["kind"] == "record":
        if not (isinstance(best, dict) and taskkit.is_decimal(best.get("value"))):
            return "wait", "its list's page gives no best known value"
        if not taskkit.better(run.score, best["value"], task["direction"]):
            return task_rejection(in_result, "TASK_NOT_BETTER",
                                  f"Its score is {taskkit.value_text(run.score, task)}; the best known value is "
                                  f"{best['value']} ({best.get('sourceName')}, as of {best.get('asOf')}).")
    if page_list.get("state") != "OPEN" or page.get("taskResult") is not None or lst.get("key") in accepted_now:
        replaced = _dict(page_list.get("replacedBy")).get("key")
        return task_rejection(in_result, "TASK_MOVED_ON",
                              f"List {lst.get('key')} "
                              + ("already holds an accepted run." if page_list.get("state") == "OPEN" else
                                 f"is {str(page_list.get('state')).lower()}.")
                              + (f" The open round is {replaced}." if replaced else ""))
    checked = clean(f"the task's checker (checker.py {task['checkerSha256'][:14]}…) run again by Papex Labs: passes"
                    + (f", {run.score}" if run.score is not None else ""), CHECKED_LIMIT)
    if task["kind"] == "record":
        summary = (f"Papex Labs ran the task's checker on your object again: it passes, with "
                   f"{taskkit.value_text(run.score, task)}. That is better than the value in {best.get('sourceName')} "
                   f"as of {best.get('asOf')} ({best['value']}). The checker tests only what the task's card says; "
                   "this is not peer review.")
    else:
        summary = ("Papex Labs ran the task's checker on your object again: it passes, so the checker takes it as a "
                   "counterexample to the task's statement. The checker tests only what the task's card says; this is "
                   "not peer review.")
    body = {"verdictId": str(uuid.uuid4()), "expectedState": "SUBMITTED", "outcome": "ACCEPTED", "reasonCode": None,
            "reasonText": None, "nextStepText": None, "summaryText": clean(summary, SUMMARY_LIMIT),
            "units": [{"key": slug, "verdict": "ACCEPTED", "reason": None, "checkedWith": checked}], "keepChecks": []}
    follow = {"outcome": "ACCEPTED", "slug": slug, "kind": task["kind"], "problemSlug": lst.get("problemSlug"),
              "listKey": lst.get("key"), "listTask": list_task, "score": run.score, "keys": in_result, "page": page}
    return "verdict", body, follow


def page_reader(api):
    """read_page for decide(): the list's public page, (page, None) or (None, why). Never raises."""
    def read(problem, key):
        if not (isinstance(problem, str) and taskkit.SLUG_RE.match(problem) and isinstance(key, str)
                and taskkit.SLUG_RE.match(key)):
            return None, "the batch names no readable list"
        return taskkit.read_json_url(f"{api}/api/shared-work/problems/{problem}/lists/{key}", 30)
    return read


def follow_up(pub, tasks, problem_slug, list_key, list_task, score, page=None, read_page=None, accepted_at=None):
    """After an accepted run on a task list: publish the next round (to improve a bound) or close the list
    (counterexample). A task folder of this repository gives the next round's texts; a family's task takes them from
    its list's page on Papex. The new round's date is the day the run was accepted (accepted_at), so a retry sends
    the very same request (Papex answers it "already"). Prints what it did; never raises (a later run retries)."""
    on = accepted_at[:10] if isinstance(accepted_at, str) and taskkit._date(accepted_at[:10]) else None
    list_task = _dict(list_task)
    task = tasks["bySlug"].get(list_task.get("slug"))
    if task is None and not list_task.get("family"):
        say(f"ALERT {list_key}: an accepted run on a task this runner does not have; nothing published")
        return False
    try:
        if (task or list_task).get("kind") == "record":
            if not taskkit.is_decimal(score):
                say(f"ALERT {list_key}: the accepted run has no score; nothing published")
                return False
            if task is not None:
                body = publisher.next_round_body(task, list_task, score, problem_slug, list_key, on, tasks["root"])
            else:
                if not page and read_page:
                    page, why = read_page(problem_slug, list_key)
                if not page:
                    say(f"ALERT {list_key}: its page could not be read; the next run tries again")
                    return False
                best = publisher.accepted_best(score, problem_slug, list_key, on)
                body = publisher.family_round_body(page, problem_slug, list_task, best, list_key)
            answer = _dict(pub.publish(body))
            say(f"PUBLISHED {problem_slug}/{body['list']['key']}: best known {score}, replaces {list_key}"
                  + (" (it was already there)" if answer.get("already") else ""))
        else:
            pub.close(problem_slug, list_key, publisher.CLOSE_REASON)
            say(f"CLOSED {problem_slug}/{list_key}: a counterexample was accepted")
        return True
    except (publisher.PublisherError, ValueError, KeyError, TypeError, OSError) as e:
        say(f"ALERT {list_key}: the step after the accepted run did not go through ({e}); the next run tries again")
        return False


def catch_up(pub, tasks, read_page=None, only=None):
    """Every task list that holds an accepted run and is still open (or only the list `only`): do the step after it.
    Run first in every run (a retry of what an earlier run left undone) and after each accepted run."""
    try:
        items = pub.tasks("OPEN")
    except publisher.PublisherError as e:
        say(f"ALERT publisher: the task lists could not be read ({e})")
        return
    for item in items:
        result = _dict(item.get("taskResult"))
        if item.get("state") == "OPEN" and result and (only is None or item.get("listKey") == only):
            follow_up(pub, tasks, item.get("problemSlug"), item.get("listKey"), item.get("task"), result.get("score"),
                      read_page=read_page, accepted_at=result.get("acceptedAt"))


def post_task_verdict(api, batch, body, keys):
    """Posts a task verdict. When Papex refuses an acceptance because the list moved on meanwhile (409
    SHARED_WORK_TASK_MOVED_ON), the run is rejected as TASK_MOVED_ON instead. When Papex cannot read the list's task
    (409 SHARED_WORK_TASK_UNREADABLE) nothing is decided: ("LEFT", code). Returns (outcome, code)."""
    path = f"/api/admin/shared-work/batches/{batch['batchKey']}/verdict"
    try:
        api.send("POST", path, body)
        return body["outcome"], body.get("reasonCode")
    except ApiError as e:
        said = f"{e.code} {e}"
        if e.status == 409 and "SHARED_WORK_TASK_UNREADABLE" in said:  # Papex cannot read the list's task
            return "LEFT", "SHARED_WORK_TASK_UNREADABLE"
        if body["outcome"] != "ACCEPTED" or e.status != 409 or "SHARED_WORK_TASK_MOVED_ON" not in said:
            raise
    _, moved, _ = task_rejection(keys, "TASK_MOVED_ON", "Its list closed, or accepted another run, before this one.")
    api.send("POST", path, moved)
    return "REJECTED", "TASK_MOVED_ON"


def handle(api, pub, args, key, lists, kits, tasks, read_page, accepted_now):
    """Decides one sent run of the queue and, with --post, sends the decision. Returns "left" (a task list's run left
    for the next run), "decided" or None. Raises when Papex refuses the decision or gives no answer (main() then
    prints an ALERT and goes on with the next sent run)."""
    batch = api.call("GET", f"/api/admin/shared-work/batches/{key}")
    shown = clean(key, 40)
    if time.monotonic() - STARTED > BUDGET_SECONDS and batch.get("state") == "SUBMITTED" and \
            taskkit.LIST_KEY_RE.match(str(_dict(batch.get("list")).get("key"))):
        return "left"  # a task list's run would start a checker: it waits for the next run
    decision = decide(batch, lists, kits, tasks, read_page, accepted_now)
    if decision is None:
        say(f"{shown} {clean(batch.get('state'), 20)}: not a list of this kit")
        return None
    if decision[0] == "wait":
        say(f"{shown} {clean(batch.get('state'), 20)}: left for the next run, {clean(decision[1], 400)}")
        return None
    route, body = decision[0], decision[1]
    follow = decision[2] if len(decision) > 2 else None
    if not args.post:
        say(f"{shown}: {body['outcome']} {body.get('reasonCode') or ''}")
        say(json.dumps(body, indent=1, ensure_ascii=False))
        return "decided"
    if follow is not None:  # a task list: the line says what was posted
        outcome, code = post_task_verdict(api, batch, body, [u["key"] for u in body["units"]])
        if outcome == "LEFT":
            say(f"ALERT {shown} SUBMITTED: left for the next run, Papex cannot read its list's task (409 {code}); a "
                f"person looks at list {clean(follow.get('listKey'), 40)}")
            return "decided"
        say(f"{shown}: {outcome} {code or ''}")
        if outcome == "ACCEPTED":
            accepted_now.add(follow["listKey"])
            if pub:  # the step after it, with the date Papex gives the accepted run
                catch_up(pub, tasks, read_page, only=follow["listKey"])
        return "decided"
    api.send("POST", f"/api/admin/shared-work/batches/{key}/{route}", body)
    say(f"{shown}: {body['outcome']} {body.get('reasonCode') or ''}")
    return "decided"


def main(argv=None):
    parser = argparse.ArgumentParser(description="Re-run lists: acceptance runner")
    parser.add_argument("--api", default="https://api.papex.org")
    parser.add_argument("--list", default=None, help="only this list (key or id)")
    parser.add_argument("--post", action="store_true", help="send the decisions (default: print them)")
    parser.add_argument("--batch-file", default=None,
                        help="decide one runner batch view read from a file, and print it (no network, no token)")
    parser.add_argument("--list-page", default=None,
                        help="with --batch-file on a task list: the list's public page, read from a file")
    args = parser.parse_args(argv)
    global STARTED
    STARTED = time.monotonic()
    lists, kits, tasks = known_lists(), known_kits(), known_tasks()
    if args.batch_file:
        with open(args.batch_file) as fh:
            batch = json.load(fh)
        page = None
        if args.list_page:
            with open(args.list_page) as fh:
                page = json.load(fh)
        decision = decide(batch, lists, kits, tasks,
                          lambda problem, key: (page, None) if page is not None else (None, "no --list-page given"))
        say(json.dumps(decision[:2] if decision else None, indent=1, ensure_ascii=False))
        return 0
    token = os.environ.get(TOKEN_ENV, "").strip()
    if not token:
        raise SystemExit(f"Set {TOKEN_ENV}.")
    api = Api(args.api, token)
    publisher_token = os.environ.get(PUBLISHER_TOKEN_ENV, "").strip()
    pub = publisher.Publisher(args.api, publisher_token) if publisher_token and args.post else None
    read_page, accepted_now = page_reader(args.api.rstrip("/")), set()
    if pub:
        catch_up(pub, tasks, read_page)  # what an earlier run left undone after an accepted run
    left = seen = decided = failed = 0
    handled = set()
    try:
        for entry in api.queue(args.list):
            key = _dict(entry).get("batchKey")
            if key in handled:  # the queue's pages moved while this run decided: each batch once
                continue
            handled.add(key)
            seen += 1
            try:
                what = handle(api, pub, args, key, lists, kits, tasks, read_page, accepted_now)
            except Exception as e:  # noqa: BLE001 - one sent run never stops the others
                failed += 1
                say(f"ALERT {clean(key, 40)}: not decided in this run ({clean(e, 400)}); it stays SUBMITTED, and the "
                    "run goes on with the next")
                continue
            left += what == "left"
            decided += what == "decided"
    except ApiError as e:  # the queue itself could not be read: nothing can be decided
        raise SystemExit(str(e)) from None
    if left:
        say(f"TIME {left} runs of task lists left SUBMITTED for the next run (this run used its {BUDGET_SECONDS} s)")
    if failed:
        say(f"ALERT {failed} sent runs could not be decided in this run; the next run tries them again")
    if not decided and not left and not failed:  # a log line that shows the run happened
        say(f"nothing waiting: {seen} sent runs in the queue, none to decide; read {len(lists)} re-run lists and "
            f"{len(tasks['bySlug'])} task folders of this kit")
    return 0


if __name__ == "__main__":
    sys.exit(main())
