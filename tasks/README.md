# Open tasks: the format

A task is one piece of new work on an open problem that a program can check: find an object better
than the best known one (kind `record`, shown as "Improve a bound"), or find an object that refutes a
statement (kind `counterexample`, shown as "Find a counterexample"). A person searches with their own
AI app or code. What they find is a small JSON file, the object. The task's `checker.py` decides
whether it passes. The kit (`task.py`) runs the checker on the person's computer; Papex's runner runs
the same checker again before a run is accepted.

On Papex a task is a shared-work list whose `howTo` carries the task. Its key is `<slug>-r<round>`.
When a run is accepted, the next round is published with the new best known value and the old list
closes, so each list holds at most one accepted run.

## A task's folder: `tasks/<slug>/`

| File | What it holds |
|---|---|
| `task.json` | Everything the task's card and list need (below). |
| `checker.py` | `python3 checker.py <object.json>` prints one JSON line `{"valid": true or false, "score": number or null, "reason": "…"}` and exits 0. |
| `best_known.json` | Record task: the best known object, exactly as its source publishes it. Counterexample task: only labelled objects for known-false variants of the statement (they must not pass the checker). |
| `manifest.ndjson` | The list's one manifest line. Written by `tools/import_task.py`, never by hand. |
| `card.md` | The card a person or an AI app reads: what to find, the best known value with its source and date, how it is checked, the check command, what a pass shows and does not show, rough effort, what is needed. |
| `probe.md` | What was run when the task was prepared, and what came out. |
| `probe/` | Broken or near-miss objects, their expected outputs in `probe/cases.json`, and for a counterexample task a small script that shows the checker can say yes on a known-false variant. |

Nothing else belongs in the folder.

## `task.json`

```json
{
  "schema": "papex-task/v1",
  "slug": "isosceles-free-grid-100",
  "kind": "record",
  "title": "…", "shortTitle": "…", "description": "…",
  "objective": "…", "direction": "max", "scoreLabel": "points",
  "bestKnown": {"value": "164", "by": "…", "year": 2025, "sourceName": "arXiv 2511.02864",
                "sourceUrl": "https://…", "asOf": "2026-11-20", "quote": "…", "note": "…"},
  "searched": null,
  "objectFormat": "…", "objectKeys": ["n", "points"], "shows": "…", "notCovered": "…", "alsoBelongsAt": "…", "effort": "…",
  "limits": {"maxObjectBytes": 20000, "checkerSeconds": 60},
  "resultLine": "Result: …", "requirements": "…", "checkedHow": "…", "expectedSeconds": 3600,
  "problem": {"slug": "…", "create": { …the body of POST /api/admin/problems… } },
  "sources": [{"fact": "…", "url": "https://…", "quote": "…", "fetchedOn": "2026-11-20", "note": "…"}],
  "checkerSha256": "0x…"
}
```

| Field | Rule |
|---|---|
| `slug` | Lowercase letters, digits and single hyphens, at most 34 characters; the folder's name. |
| `kind` | `record` or `counterexample`. |
| `title` | At most 200 characters. The card's heading; no best known value in it (it changes). |
| `shortTitle` | At most 80. A few words; for a counterexample, what is searched for. |
| `description` | At most 300. One or two sentences for the list. |
| `objective` | At most 600. What to find and what it is scored by, in plain words. |
| `direction` | `max` or `min` for a record task; `null` for a counterexample. |
| `scorePlaces` | Optional, kit only: the most decimals a score has (0 for whole numbers, at most 18). `show` then says the smallest score that counts as better. |
| `scoreLabel` | Optional, at most 40: what the score counts (`points`). |
| `bestKnown` | Record task only (`null` otherwise). `value` is a decimal written as text (`"164"`, `"1.119047568469"`): exactly the checker's score on `best_known.json`. `by` at most 200, `sourceName` at most 120, `sourceUrl` https, `asOf` the date the value was read from the source. `quote` is the sentence that states the value; `note` (optional) says where in the source it stands, or how the value relates to the stated one. `quote` and `note` stay in the kit; Papex receives the other six. |
| `searched` | Optional, at most 400: what is already ruled out, with its source (counterexample). |
| `objectFormat` | At most 600. Exactly what the JSON file holds, and the size limit. |
| `objectKeys` | The object's keys: the only ones it may hold (below). Stays in the kit. |
| `shows`, `notCovered` | At most 400 each: what a pass shows, and what it does not show. |
| `alsoBelongsAt` | Optional, at most 300: where a result should also be reported. |
| `effort` | Optional, at most 200: rough effort, from the sources. |
| `limits` | `maxObjectBytes` 1 to 100,000 (the object's canonical bytes, below); `checkerSeconds` 1 to 120. |
| `resultLine` | At most 400, starting with `Result: `: what an accepted run says. |
| `requirements`, `checkedHow` | At most 600 each. |
| `expectedSeconds` | 1 to 604,800: the time a person may spend (the list's one unit). |
| `problem` | `slug` of the problem page, and `create`: the body of `POST /api/admin/problems` when the page does not exist yet (`null` when it does). |
| `sources` | Every quote used anywhere in the task, with its URL and the date it was read. |
| `checkerSha256` | `0x` and the SHA-256 of `checker.py`. Written by `tools/import_task.py`. |

The public texts (`title` … `checkedHow`) never use the words verified, confirmed, proved, record,
first, winner or leaderboard. They say "passes the checker" and "better than the value in <source>
as of <date>". Quotes from sources are other people's words and are not searched.

Lengths count as Papex's server counts them (UTF-16 code units). The list's whole `howTo`, as
`tools/publish_task.py` sends it in the task's longest round, must stay under 7,500 bytes (the server
stores at most 8,192); the lint measures it.

## The object holds nothing the format does not name

An accepted object is shown publicly on the task's page on Papex. So an object is a JSON object with
exactly the keys in `objectKeys`, and every value is one the format names: the checker rejects any
other key, and any value of a kind `objectFormat` does not describe (a text where a number belongs, a
text that is not a plain decimal or fraction, a third coordinate). "Other keys are ignored" is never
part of a format. The kit and the runner also refuse an object whose keys are not exactly
`objectKeys`, before the checker runs. The lint requires a probe file with an extra key that the
checker rejects, and tries `best_known.json` with one more key itself.

## The checker

- Python 3.9 or later, standard library only, deterministic, no network.
- Imports only `json`, `sys`, `os`, `math`, `fractions`, `decimal`, `itertools`, `functools`,
  `collections`, `heapq`, `bisect`, `re`. `os` only as `os.path.getsize`, `os.path.isfile` or
  `os.path.exists`; `sys` only for `argv`, `exit`, `stdout`, `stderr`, `setrecursionlimit` and the
  like.
- Opens one file, once, for reading: the object, named from `sys.argv[1]` (`path = sys.argv[1]`).
  No `exec`, `eval`, `compile`, `__import__`, `getattr`, no names or attributes with double
  underscores (but `__name__`), no writes.
- Prints exactly one line and exits 0, also for a broken object.
- `score` is exact: a whole number, or a decimal printed digit for digit (never a float that one
  Python could round differently from another). Plain decimals only, at most 18 digits on each side
  of the point. `null` for a counterexample.
- Exact arithmetic (integers, fractions) wherever the objective allows it.

The kit and the runner never run the checker on the person's file as it is. They read it as JSON
(refusing duplicate keys, NaN and Infinity, whole numbers over 4,300 digits and brackets nested more
than 64 deep), write it again as canonical bytes,
`json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)`, and run the checker on
those bytes, with `python3 -I -S -B`, in an empty folder of its own, with a minimal environment,
`checkerSeconds` of time, and on Linux a memory limit and no file writes. A JSON number is carried as
a double: a task whose objects need more digits says so in `objectFormat` (write them as strings).

## `probe/cases.json`

```json
{"cases": [
  {"file": "v1_wrong_n.json", "label": "declared grid size n set to 64",
   "expect": {"valid": false, "score": null, "reason": "field n must be the integer 100"}},
  {"file": "variant-r2.json", "label": "known-false variant: r = 2 on K5", "via": "variant_check.py",
   "expect": {"valid": true}}
]}
```

Every `.json` file in `probe/` is one case. `expect.valid` is required; `score` and `reason`, when
given, must match the checker's output exactly (`probe.md` records them). A case with `via` runs
`python3 probe/<via> checker.py <file>` instead of the checker: a small script that calls the
checker's own test on a variant the task itself refuses, and prints one line as a checker does. Only
the lint runs it; the kit and the runner never do.

- Every task: at least one rejected file holds a key the format does not name.
- Record task: at least three broken files rejected, `best_known.json` passes with exactly
  `bestKnown.value`, and `best_known.json` with one more key is rejected.
- Counterexample task: no object is known, by definition. At least three near misses rejected, at
  least one known-false variant accepted through its `via` script, and `best_known.json` (labelled
  variants only) rejected by the checker. No case may expect the checker itself to accept a file.

## The gates

```
python3 tools/task_lint.py tasks/<slug> [--python /usr/bin/python3]
```

It prints one line per check and exits 0 only when all pass: the files; `task.json` complete and
within the limits above; the `howTo` size; the words; unknown keys rejected; the checker's rules (read from its source);
`checkerSha256` in `task.json`, of `checker.py` and in the manifest agree; the manifest is the line
the kit writes; the best known object; every probe case; byte-identical output when each run is
repeated; every run within `checkerSeconds`; with `--python`, the same lines under another Python.
`tests/test_tasks.py` runs the lint over every folder here.

The gates do not replace a second, independent reading of the source (gate G4 of the plan): they
check the folder against itself and against what `probe.md` records.

## Importing a prepared folder: two commands

```
python3 tools/import_task.py /path/to/prepared/<slug>
python3 tools/task_lint.py tasks/<slug>
```

The first copies the folder in (`checker.py`, `best_known.json`, `card.md`, `probe.md`, `probe/`,
`task.json`), writes `checkerSha256` and `manifest.ndjson`, and writes `probe/cases.json` from the
`$ python3 checker.py probe/…` lines of `probe.md` when the folder has none. A `task.json` in the
earlier draft format (with `id`, `problemTitle`, `problemSource`) is converted where the conversion is
mechanical; every field it cannot fill is written as `TODO: …` and listed. It never changes a checker
or a value it copies. After filling in the TODOs (or after any change to `task.json` or
`checker.py`), `python3 tools/import_task.py tasks/<slug>` writes the hash and the manifest again.
The second command runs the gates.

## Families: tasks made by a program

A family is one reviewed checker that takes parameters; a task of a family is data only, published by a
program from public tables, and needs no folder here. `families/<family>/` holds:

| File | What it holds |
|---|---|
| `checker.py` | `python3 checker.py <object.json> <params.json>` prints one line as a task's checker does. Same rules, but it reads two files: `sys.argv[1]` (the object) and `sys.argv[2]` (the params), each opened once. It rejects any key, in the object or in the params, the format does not name. |
| `README.md` | The object's format, the params, and what a pass shows. |
| `probe/cases.json` | `{"checkerSeconds": 60, "cases": [{"object": "a.json", "params": "p.json", "label": "…", "line": "<the exact output line>"}]}`, with the object and params files next to it. |

A family's task on Papex carries `family`, `params` and `checkerSha256` = the SHA-256 of
`families/<family>/checker.py`. `task.py` uses it only when this kit's checker has that SHA-256 (else:
"this task needs a newer kit: git pull"); the runner the same, with its own copy (else the run waits and
an ALERT says to deploy the newest kit).

```
python3 tools/import_family.py /path/to/<family>        # copies it in, probe cases in the layout above
python3 tools/task_lint.py --family families/<family>    # the gates (the importer runs them too)
```

The family gates: the files; `README.md`; the checker's rules; every probe case gives exactly its
line; at least one case passes and three are rejected; a passing case gives the same line on the
canonical bytes; one more key in the object, and in the params, of a passing case is rejected; the
same output twice; the time limit; with `--python`, the same lines under another Python.
`tools/import_family.py` also reads probe cases laid out as one folder per case
(`probe/<case>/object.json`, `params.json`, `expected…`), as flat files (`<case>.object.json`,
`<case>.params.json`, `<case>.expected…`), or in a `cases.json` with other field names or inline
objects; it says which layout it read.

## Publishing and pulling

```
PAPEX_SHARED_WORK_PUBLISHER_TOKEN=… python3 tools/publish_task.py tasks/<slug> [--dry-run]
PAPEX_SHARED_WORK_PUBLISHER_TOKEN=… python3 tools/pull_task.py <slug>-r<round> --reason "…" [--dry-run]
```

`publish_task.py` runs the gates first and publishes nothing when one fails. It publishes round 1 by
default; `--round N --replaces <slug>-r<N-1>` publishes a later round with `task.json`'s best known
value, and with `--best-value V` the value of the run accepted on the replaced list (Papex as the
source, that list's page as its address). `--round N` without `--replaces` publishes a pulled card
again. Papex's rules: one open round per task, rounds numbered without gaps, `previousListKey` the
round before (from round 2), and the same request twice answers "already" (any other request under a
key in use is refused). `--dry-run` prints the request and sends nothing. The token is read from the
environment and never printed.

When an accepted run is withdrawn, `tools/revert_round.py <problem> <list key of that run> [--dry-run]`
publishes the next round with the best known value that held before it, read from Papex's publisher
listing.

After an accepted run, the runner publishes the next round itself (or, for a counterexample, closes
the list) when it has the publisher token; when that step fails, its next run retries it with the very
same request (the new round is dated the day Papex accepted the run). A run on a list whose task
Papex cannot read stays SUBMITTED with an ALERT. After 400 seconds the runner starts no new checker;
the task runs left wait for its next run.

## Changing a checker

A list freezes its manifest, and the manifest names the checker's SHA-256. After `checker.py`
changes, runs on the open list are rejected as made with another checker (`TASK_CHECKER_CHANGED`).
Publish the next round with the new checker (`--round N --replaces …`), which closes the old list.
When `task.py` itself changes, add the new version's SHA-256 to `runner/kits.sha256`; the lines of
earlier versions stay, so results written with them are still taken.
