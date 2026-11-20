# Papex re-run kit

Run a published, machine-checkable result on your own computer, and add your run to its list on
[papex.org](https://papex.org).

A passing run shows that Lean accepts a proof of the sentence in the list's statement file, on your
computer. It is not peer review, and it does not say that the sentence is the problem.

## What you need

- macOS or Linux (on Windows: WSL), Python 3.9 or later, git and curl.
- About 12 GB of free disk and a few minutes. Most of the space is Mathlib's ready-made build.
- A Papex account, to start a run and to choose how you are shown.

## Run

```
git clone https://github.com/papexlabs/rerun-kit && cd rerun-kit
python3 rerun.py --check
python3 rerun.py --key <kit key>
```

The last command, with a key for your run in it, is on your run's page on papex.org. Copy it from
there. When the kit has finished, go back to the page, choose how you are shown, and press Send.

In a terminal the kit draws the run. In a pipe, with `NO_COLOR` set or with `--plain`, it prints
plain lines instead; both say the same.

## What the kit does

1. It asks Papex what to run and reads the list's file in `lists/`: the repository, the commit, the
   SHA-256 of every file to be built, the Lean version, the theorem, and the axioms it may rest on.
2. It downloads Lean's installer (elan, one fixed version, checked by SHA-256), the repository at
   that commit, and Mathlib's ready-made build. Everything goes into `work/` next to the kit.
   Nothing is installed anywhere else, and `python3 rerun.py --clean` deletes it.
3. It stops unless every file to be built has the SHA-256 the list names, unless the files Lake
   reads hold nothing the kit does not know, and unless a text search of the Lean files finds none
   of the words the kit knows can make a build run code of the file or a program (see below).
4. It builds the proof with Lean and asks Lean which axioms the theorem rests on. The build is
   `lake build`, followed by the targets the list's file names, if any: when `lakefile.toml` names
   no default targets, a bare `lake build` builds nothing.
5. It writes a result file: passed or failed, the axioms, the versions, the seconds, and a
   fingerprint of what was built.

## What leaves your computer

With `--key`: when the run is done, and the result file. Nothing else. The key is never written to
a file or printed. The result file holds no name; it names your operating system and processor.

Without a key (`python3 rerun.py ~/Downloads/<batch file>`) the kit sends nothing, and you upload
the result file on the page yourself. With `--batch` (below) it sends nothing either.

## With an AI app

An AI app that has the Papex connection and a terminal (Claude Code, Codex or Cursor, for example)
can do a run for you. It takes the run with the connection's tool `papex_take_shared_work`, which
gives it the batch key, the problem and the list, and runs the kit with them (`--docker` works too):

```
python3 rerun.py --batch <batch key> --problem <problem> --list <list> --agent-host "<app's name>"
```

The kit writes the batch file from its own list files (only for a list of one unit) and sends
nothing. The app gives the result file, as the kit wrote it, to `papex_prepare_shared_work_batch`,
and it waits on your run's page. You read it there, choose how you are shown, and send it. Only you
can send it.

## A build can run code

Building a Lean file can run programs written in that file, and Lake's build files can tell Lean to
load one. So the kit builds only what the list names, file by file, by SHA-256: Lean's own release,
Mathlib's release, and the proof's files at one commit. Before it builds anything, it stops if

- a file differs from the SHA-256 the list names;
- the project has a `lakefile.lean` (a build file written as a program) or no `lakefile.toml`;
- `lakefile.toml` uses a key or a Lean option the kit does not know (among them `moreLeanArgs`,
  `weakLeanArgs`, `moreLinkArgs`, `precompileModules`, `plugins`, `dynlibs`, a moved `buildDir` or
  `packagesDir`, and options such as `debug.skipKernelTC`, which turns off Lean's kernel check);
- the project requires anything but Mathlib from leanprover-community, or `lake-manifest.json` has a
  package that is not a git commit of leanprover-community or leanprover on GitHub;
- a file of Lake's own folder `.lake` is part of the repository, or `lean-toolchain` names another
  Lean version than the list;
- a Lean file imports anything but Mathlib and the proof's own files, or writes an import the kit
  cannot read (a `«name»`, two imports on one line). One module of Lean itself may be imported by its
  exact name: `Lean.Elab.Tactic.Omega`, the code of Lean's `omega` tactic, which `import Mathlib`
  brings in too;
- a Lean file contains a word that can make a build run code the file wrote or start a program:
  commands and tactics that run code (`#eval`, `run_cmd`, `run_tac`, `by_elab`, `#guard`,
  `decide +native` …), new syntax and macros (`syntax`, `macro`, `elab`, `binder_predicate`,
  simprocs), anything that starts with `unsafe` or `Lean`, `extern`, `IO`, attributes that register
  code (`@[init]`, `@[tactic]`, `@[norm_num]`, `@[aesop]` …), commands of Mathlib's libraries that
  start programs or use the network (`#leansearch`, `#loogle`, `#clear_deprecations`, `bv_decide`),
  options of `linarith` and rules added to `aesop` (both can be code); the full lists are
  `FORBIDDEN`, `FORBIDDEN_SPANS` and `CODE_ATTRIBUTES` in `rerun.py`;
- a Lean file sets a Lean option that `lakefile.toml` may not set either (`set_option
  debug.skipKernelTC`, for one, turns off Lean's kernel check).

Anything the kit cannot read, it refuses. The search is a text search, not an audit. Its words were
drawn from the sources of Lean 4.35, Mathlib and Mathlib's libraries, but a text search cannot show
that a build runs no code of the file, and new versions of Lean or Mathlib can add new ways. It is
one of several layers: Papex Labs chooses each list and the kit pins every file by SHA-256, the files
Lake reads may hold nothing the kit does not know, the search, and with `--docker` the build runs in
a container whose network is cut. Lean and Mathlib come from their own release pages and are trusted
as any Lean user trusts them.

If you would rather not build other people's files on your computer directly, use

```
python3 rerun.py --key <kit key> --docker
```

It needs Docker. The download happens inside a container, the container's network is cut, and only
then is the proof built.

## How a run is checked

Papex Labs compares what your kit reported with the list's file and with its own run: the commit,
the Lean version, that the build passed, and that the theorem rests only on the permitted axioms.
The report comes from the kit you ran; nobody can show from it that your computer did the work.
The list therefore says "people who ran it", and nothing more.

The comparison is `runner/runner.py`, and its rules are the ones written there; nobody accepts a run by
hand. Papex Labs runs it as a hosted task that Papex's server starts when a run is sent
(`runner/render_task.py`), with a scheduled run as a fallback.

## Lists in this kit

| Problem | List | What is built |
|---|---|---|
| Erdős problem 824 | `lean-rerun-v1` | The Lean proof in `daizisheng/erdos-824` at `b4b7099b`: a lower bound for the number of coprime pairs with equal sum of divisors, **assuming** a hypothesis on primes p with smooth p + 1. The hypothesis is not proved; the problem is open. |
| Collatz conjecture | `lean-rerun-first-passage-v1` | The Lean proof in `shaikidris/FirstPassageLinearTransport-Palomar` at `dcd32c0f`: polylogarithmic descent for almost all Collatz orbits in natural density, within logarithmically many steps. It is about almost all orbits; the conjecture is open. |

## Open tasks

An open task asks for something new on an open problem: an object better than the best known one
("Improve a bound"), or an object that refutes a statement ("Find a counterexample"). What you find is
a small JSON file. A short program, the task's checker, decides whether it passes. A task is either a
folder of this kit (`tasks/<task>/`, with its card `card.md`) or one of Papex's open tasks of a family:
one reviewed checker in `families/<family>/` that takes the task's parameters, so a new task of a known
family needs no new kit.

Three families are here: `comparator-network` (sorting and median networks), `sum-free-colouring` (Schur and weak
Schur numbers) and `constant-weight-code` (binary codes of constant weight). A daily program, `finder/`, reads
B. Dobbelaere's lists of networks, Leaps in Bounds and A. E. Brouwer's table of codes, and publishes at most five
new cards a day of these families. In the daily run a card is made only for an entry whose source links its object,
and only after the family's checker passes that object with exactly the table's value (`finder/README.md`). Objects
copied from other sources are credited in `NOTICE`.

```
python3 task.py list
python3 task.py show <task>
python3 task.py check <task> my-object.json
python3 task.py result <task> my-object.json --batch <batch key> --problem <problem> --list <list> --agent-host "<app's name>"
```

`list` shows both kinds of task, with their best known values (grouped by problem when there are
many). `show` prints one task's card: what to find, the best known value with who found it, its source
and the date it was read, where the best known object is published, the exact file format, what a pass
shows and does not show, and the next two commands. `check` runs the task's checker on your object
and says one of three things: it does not pass (and why); it passes but is not better than the best
known value (with both numbers); it passes and is better (and what to do next). Try as many objects as
you like; nothing is sent. `result` writes the result file of a run you took with the Papex connection
(`papex_take_shared_work`), and only when the object passes and, to improve a bound, is strictly
better. As with a re-run, the AI app gives that file to `papex_prepare_shared_work_batch`, and only
you send it.

The checker runs in a separate Python process, in an empty folder, with a time limit, on the object
exactly as the result file carries it. The best known value moves when a run is accepted: `check` and
`result` read it from Papex when Papex answers within a few seconds, and otherwise use the value in the
task's folder; they say which. `list`, `show` and `check` keep Papex's answer for 5 minutes in `work/`
and say when they use that copy; `result` always reads Papex anew. A family's task needs Papex: when
its checker is not the version this kit has, the kit says "this task needs a newer kit: git pull". When you send a run, Papex Labs runs the same checker again on the
object in your result file and compares its score with the best known value on Papex at that moment.
An accepted object is shown publicly on the task's page, so it holds only what the format names.

A pass shows what the task's card says it shows: that this one object passes the task's checker, with
its score, and, if it was accepted, that the score was better than the value in the named source as
of that date. It does not show that the object is the best possible, it is not peer review, and it
says nothing about who found the object or how. `tasks/README.md` describes a task's folder, a
family's folder and the gates both pass before anything is published.

## Making a list's file

`python3 tools/make_spec.py SEED.json OUT.spec.json` fetches a repository at a commit, without
building anything, and writes the SHA-256 of every file under the project folder. It writes nothing
if the kit would stop a run of it.

`python3 tests/test_release.py OUT_DIR` runs the cases for what the kit refuses and for the batch
file it writes with `--batch`; nothing is built and nothing is sent. `python3 tests/test_tasks.py
OUT_DIR` runs the cases for open tasks: the gates over every folder in `tasks/`, `task.py`, and the
runner's decisions on task lists against a stand-in Papex. `cd finder/tests && python3 -m unittest` runs the
finder's cases, with no network. `python3 tools/task_lint.py --family families/*` runs the family gates.
