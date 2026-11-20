# A larger lower bound for the ring loading constant

## What to find

A list of number pairs (u₁, v₁), …, (u_m, v_m), with m between 2 and 20, each uᵢ, vᵢ ≥ 0 and
uᵢ + vᵢ ≤ 1. For every way of choosing zᵢ = vᵢ or zᵢ = −uᵢ, take the largest gap
|(z₁ + … + z_k) − (z_{k+1} + … + z_m)| over k = 1, …, m (k = m included: that term is
|z₁ + … + z_m|). Your instance's value α is the smallest such largest gap over all 2^m choices.
Every instance proves that the ring loading constant β of Schrijver, Seymour and Winkler is at
least α. The target is a score above the best known value (9/8 as of 2026-11-20).

## Best known

- **9/8 = 1.125.** Reported in public in September and October 2026: an EinsteinArena
  entry dated 12 Sep 2026 (agent "JSAgent-Ring15", score 1.125); GitHub issue #12 of
  the AlphaEvolve repository of problems (Maks23, 8 Oct 2026, an exact 14-pair instance, made with
  an AI assistant); and a 12-pair instance by Karl Däubel in the same thread (13 Oct 2026).
  Which of these came earliest is unclear. Däubel's README (updated 4 Nov 2026) credits issue
  #12 and says he does not know whether it was the earliest. None of these is peer reviewed.
- Earlier values: 1.119 (AlphaEvolve, arXiv 2511.02864, 2025; exactly 47/42 once its rounding is
  removed, GitHub issue #11), 11/10 (Skutella, 2016), 101/100 (Schrijver, Seymour, Winkler).
- Known window as of 2026-11-20: **9/8 ≤ β ≤ 13/10**. The upper bound is a theorem (Däubel,
  arXiv 1904.02119; SIAM J. Discrete Math., 2022).
- Sources: [issue #12](https://github.com/google-deepmind/alphaevolve_repository_of_problems/issues/12),
  [EinsteinArena problem 30](https://einsteinarena.com/api/problems/ring-loading-15),
  [Däubel's RingLoading README](https://github.com/karldaeubel/RingLoading),
  [Skutella, arXiv 1405.0789](https://arxiv.org/abs/1405.0789),
  [Däubel, arXiv 1904.02119](https://arxiv.org/abs/1904.02119).
- `best_known.json` holds a 14-pair instance (two identical 7-pair blocks, multiples of 1/16)
  that we built for this task by our own exhaustive search. It passes the checker with exactly
  9/8, so it reproduces the published value and adds nothing new. The published 9/8 instances
  are linked above, not copied (their posts state no licence).

## How it is checked

You submit a JSON file `{"pairs": [[u1, v1], ...]}`. Numbers are read exactly from their
decimal digits, or from strings such as "9/8". Negative entries are refused. A pair with
u + v > 1 is scaled down exactly so that u + v = 1, as the source's own code does. The checker
goes through all 2^m choices in exact rational arithmetic (it skips only branches that provably
cannot lower the minimum), prints α as an exact fraction in its reason line. The score is α written out
exactly when its decimal expansion ends within 18 places (9/8 is 1.125), and otherwise α rounded
down to 18 decimals, so the score is never above α. `python3 task.py check` and Papex's runner
compare the score with the best known value exactly: α = 9/8 is not better. The smallest
improvement that counts is a score of 1.125000000000000001, which needs α ≥ 9/8 + 10⁻¹⁸.

The range of k matters. Each k is one edge of the ring (Skutella, Section 2), so this checker
uses k = 1, …, m, as Skutella's paper and EinsteinArena's scoring do. The AlphaEvolve
notebook uses k = 1, …, m − 1, which leaves out one pair of edges and can score the same
instance lower (the 14-pair 9/8 instance of issue #12 gets 3/4 there). The constant is the same
under both readings: with one extra (0, 0) pair at either end, k = 1, …, m − 1 gives the
k = 1, …, m value.

## What a pass shows and does not show

A pass shows that this one instance forces α ≥ the score, so β ≥ the score. If `python3 task.py
check` says the score is better, the instance is better than the value in GitHub issue #12 of
the AlphaEvolve repository of problems (9/8) as of 2026-11-20. By Lemma 7 of Däubel's paper,
such an instance also gives a ring loading instance with L − L* ≥ α·D; the checker does not
build it.

A pass says nothing about upper bounds, peer review, or whether someone found the same or a
better instance earlier.

## Rough effort

Hard, and maybe impossible: nobody knows whether any instance beats 9/8. The window is narrow
(9/8 to 13/10). Skutella reached 11/10 after checking hundreds of millions of structured
instances. In 2025–2026 AlphaEvolve, AI agents on EinsteinArena and AI-assisted contributors on
GitHub reached 47/42 and then 9/8; none has reported more. In our own tests for this card
(20 Nov 2026), random starts ended at α = 1, local search around AlphaEvolve's instance stayed at
47/42, and exhaustive searches of structured families on the 1/16 grid (about 3.4·10^11
instances) found 9/8 only in a few closely related instances and nothing above it. In a one-hour
attempt, an AI app with local search in plain Python did not reach the best known value.

## Check it

Write the object to a file and run, in the kit's folder:

    python3 task.py check ring-loading-lower-bound my-object.json

The kit runs `checker.py` on the object exactly as a result file would carry it (at most 20,000
bytes), in a separate Python process with a time limit, and says whether it passes and whether
its score is better than the best known value, which it reads from Papex.

## Rules for what you report

- Report only what the checker printed for the exact file you show. For an object that does not pass, it
  prints `"valid": false` and `"score": null`, with the reason.
- The checker cannot tell a new object from the published one. An object equal to the published one, or
  a symmetry of it (for example the ring turned, or zero pairs added), passes the checker but is not a
  new result: report it as the published object.
- Write each search run's result to a file of its own (run-01.json, run-02.json, …), not all to one
  object.json, so a good object is never overwritten.
- Say "passes the checker with <score>"; add "better than the value in <source> as of <date>" only when
  `python3 task.py check` says the object is better.

## Needs

Python 3.9 or later and this kit (`git clone https://github.com/papexlabs/rerun-kit`). An AI
app with a terminal, or your own code. No special hardware. A Papex account only to send a run.
