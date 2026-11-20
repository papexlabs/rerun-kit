# The finder: Papex's daily open-task cards

A program, run once a day, that turns public record tables into "open task" cards on Papex. Each card asks for
an object better than the best known one in a table, and the family's checker in `families/` decides whether an
object passes. A card is data only: the finder never writes checker code.

```
python3 finder/run.py --dry-run [--read-papex] [--max-new N] [--only SLUG]    nothing is sent
python3 finder/run.py --publish [--max-new N] [--only SLUG]                   publishes through runner/publisher.py
python3 finder/validate.py --family F                                         records checker evidence
cd finder/tests && python3 -m unittest                                        the tests; no network
```

`--publish` and `--read-papex` need `PAPEX_SHARED_WORK_PUBLISHER_TOKEN` in the environment; it is never printed.
Results go to `finder/out/` (`plan.json` with every decision and its reason, `cards/`, `objects/`, `dropped.json`,
`summary.md`), which git ignores.

## What it reads

| Family | Source | What is read |
|---|---|---|
| `comparator-network` | B. Dobbelaere's lists of sorting and median networks (bertdobbelaere.github.io) and his SorterHunter repository on GitHub | the two list pages, the repository's newest commit and file list (api.github.com), and one network file per card (raw.githubusercontent.com) |
| `sum-free-colouring` | Leaps in Bounds (leapsinbounds.org, and its repository on GitHub) | its data files `constants.json` and `sources.json`, and one certificate per card |
| `constant-weight-code` | A. E. Brouwer's table of constant weight codes (aeb.win.tue.nl/codes/Andw.html) | the table page and one code file per card |

How politely: robots.txt is read first on every host and obeyed; at least 1 second passes between two requests to
one host (longer when robots.txt asks for a crawl delay); a plain, generic User-Agent; no URL is read twice in a run;
every host has a request budget per run (`config.json`, `hostBudgets`); a downloaded copy is reused for a while
(pages 20 hours, objects 30 days, a repository's file list at a fixed commit for good). The program never reads
erdosproblems.com, coveringrepository.com or codetables.de, and reads arXiv only at `/abs/` and `/html/`.

Without a cache, one run sends about: Brouwer's site 8 requests (robots.txt, the table page, the code files of
the cards it makes), raw.githubusercontent.com up to 24 (one file per object), api.github.com 2, Dobbelaere's site
2 and Leaps in Bounds 2. (Measured on a run of 19 November 2026 that made 20 cards; a day of 5 cards needs fewer.)
That is more than a handful for Brouwer's site, so the daily workflow keeps the cache between runs; with it, a day
usually costs Brouwer's site one or two requests. The cache is never in the repository: it is
`$PAPEX_FINDER_CACHE`, else `~/.cache/papex-finder`.

## The gates

A table entry becomes a card only when every gate passes (`gates.py`); otherwise the reason is in `dropped.json`.

- **proved**: the source does not say the value is optimal, and no second source gives the exact value. "Exact" is
  read only from a strict mark: for Leaps in Bounds a whole number equal to both bounds; for Brouwer's table the
  dot (d = 4) or equal lower and upper bounds; for Dobbelaere's sorting list a bold bound. A lone number on Brouwer's
  table and a median comment that mentions optimality get no card and never close one.
- **limits**: the family's checker can take the entry's objects, including a better one.
- **second**: a second source (Leaps in Bounds for sorting networks) does not give a stronger value.
- **object**: the source's own best known object can be read and converted. Cards without a linked object are OFF
  for every family (`config.json`, "objectless"). When switched on, such a card also needs: a source that is the
  primary record, at least 10 values reproduced by the checker on real objects with no mismatch
  (`validation/<family>.json`), the value at most the table's upper bound, the neighbouring entries in the order the
  mathematics guarantees (`families.py`, `neighbours`), and the same value on two runs in a row.
- **size**: the object fits the card's `maxObjectBytes`.
- **checker**: the family's checker, run as the kit runs it (`python3 -I -S -B`, an empty folder, time and memory
  limits), passes the source's object with exactly the table's value.
- **texts**: the card's texts fit Papex's limits and use none of the words Papex never uses.

Entries below a configured size (median networks under 10 inputs) and entries a hand-built task already covers
(`config.json`, "covered") are left out.

## Pacing

At most 5 new cards a run (`--max-new`; the daily workflow takes 0 to 20 when run by hand). Families take turns: the family with the fewest open cards on Papex goes
first, then inside it the sub-family with the fewest (sorting by size, by depth; median by size, by depth; Schur,
weak Schur; codes by distance), then recent improvements by a named person, then smaller instances. Next rounds
(the source moved past a card, or the family's checker changed) and closes (the source now gives the exact value)
are never held back by the pacing.

## Closing and moving cards

A close needs the same reading of "exact" on two daily runs in a row (`state/first-seen.json` remembers it), and
at most 2 closes go out a run. When more than a fifth of a family's open cards (and more than one) would close or
move in one run, nothing changes for that family and `summary.md` asks a person to look (a layout change?). Before
a close or a round that replaces a list, that list is read again from Papex: a list that meanwhile got an accepted
run, or is no longer open, is left to the runner. A refusal from Papex is kept and not retried: 409
`SHARED_WORK_TASK_ROUND_WORSE` (the list holds an accepted run with a better score than the new round's best known
value) and 409 `SHARED_WORK_TASK_REPLACES_INVALID` (for a counterexample list: it holds an accepted run) both mean
the runner carries that list on.

## What it reads from a source

Every download has a size limit, a compressed witness is unpacked only up to a limit, and pages are split without
regular expressions that could run long. A malformed entry is dropped with its reason; a source that breaks is
skipped for the day (a line in `summary.md`) and the others still run. Names from a source (authors, contributors,
labels) reach a card only when they are plainly names; otherwise the card says "as listed in <source>". Links to
objects are built only from plain paths inside the source's own repository or site. Redirects are followed only to
https and only to the same host or a host in `hostBudgets`; every request is a plain GET.

## What it never does

- No AI in the loop: adapters parse table cells and files, the gates compare parsed values, and every text of a
  card comes from a template in `families.py`.
- No new checker code: a card names one of the reviewed checkers in `families/`, by its SHA-256.
- It never lowers a value Papex accepted: when Papex holds a better value than the source (an accepted run), the
  card stays as it is; when the source's own value drops, a person is asked (`summary.md`, "Needs a person").
- It never reopens a card that was closed.

## Pulling a card

```
PAPEX_SHARED_WORK_PUBLISHER_TOKEN=… python3 tools/pull_task.py <slug>-r<round> --problem <problem slug> --reason "…"
```

The problem's slug is in the card (`out/cards/<slug>.json`, `problem.slug`). A closed card stays closed: the finder
does not publish it again. To publish one named card by hand: `python3 finder/run.py --publish --only <slug>`.

## The daily workflow (`.github/workflows/finder.yml`)

It runs every day at 05:40 UTC and can be started by hand with two inputs: `max_new` (0 to 20, default 5) and
`dry_run` (default on: read Papex, publish nothing, commit nothing). Only one run goes at a time. Every action it
uses is pinned by its commit SHA. It has two jobs:

- **find** reads the sources and Papex and, unless it is a dry run, publishes. It is the only job that uses the
  GitHub Environment `finder`, where the publisher token is kept, and it may only read the repository (its checkout
  keeps no credentials). The download cache is kept between runs in the Actions cache, never in the repository. It
  writes the day's summary to the run's page and hands `finder/state`, `finder/validation` and the summary to the
  next job as the artifact `finder-state` (kept 7 days), also when it stopped with an error after publishing.
- **keep** is the only job that may write to the repository, and it never sees the publisher token. It runs on
  `main` after `find` (not after a dry run started by hand), copies the artifact into `finder/state/`,
  `finder/validation/` and `finder/log/YYYY-MM-DD.md`, and commits them as "Papex Labs" when they changed. When the
  branch moved on meanwhile it rebases and tries again, three times; if the push is still refused, the run fails and
  that day's state stays in the artifact.

### Setup, once, in the repository's settings

1. Settings → Environments → New environment, named `finder`.
2. In it, under "Deployment branches and tags", choose selected branches and allow `main` only.
3. In it, add the environment secret `PAPEX_SHARED_WORK_PUBLISHER_TOKEN`: the raw publisher token. (Papex's server
   holds only its SHA-256, `PAPEX_SHARED_WORK_PUBLISHER_TOKEN_SHA256`; the token is never printed.)
4. If `main` is protected against direct pushes, the `keep` job's push is refused: allow GitHub Actions to push to
   `main`, or the state is only kept in each run's artifact.

## Files kept in the repository

- `state/first-seen.json`: the day the finder first read each source state (a card's best known date is that day,
  so a retry sends the very same request and Papex answers "already"), and the readings of the last runs (a close
  needs the same reading on two runs in a row).
- `validation/<family>.json`: the evidence that each family's checker reproduces its source's values.
- `log/YYYY-MM-DD.md`: the day's summary, committed by the workflow's `keep` job.
