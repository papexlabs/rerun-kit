# No five on a sphere in a 12 × 12 × 12 grid

## What to find

A set of points in the 12 × 12 × 12 grid such that no 5 of them lie on one sphere or one
plane. The more points, the better. The best published set has 33 points; the target is
34 or more.

## Best known

- **33 points**, found with AlphaEvolve and reported by Bogdan Georgiev, Javier Gómez-Serrano,
  Terence Tao and Adam Zsolt Wagner in "Mathematical exploration and discovery at scale" (2025),
  who call it a new lower bound, C(12) ≥ 33. The same source gives 21, 23, 26, 28 and 31
  points for grid sides 7 to 11.
- Known general bounds: at most 4n points (here 48), and at least n^(3/4 − o(1)) for large n.
- Source: [arXiv 2511.02864](https://arxiv.org/abs/2511.02864), section on problem 60; the
  33 points are published in the
  [problem 60 notebook](https://github.com/google-deepmind/alphaevolve_repository_of_problems/blob/main/experiments/no_5_on_a_sphere/no_5_on_a_sphere.ipynb)
  (CC BY 4.0 / Apache 2.0).
- As of 2026-11-20, we found no later published set with more points.

## How it is checked

You submit a JSON file `{"n": 12, "points": [[x, y, z], ...]}` with integer coordinates from
0 to 11. The checker tests that the points are distinct and in range. Then, for every choice
of 5 points, it computes in exact integers the 5 × 5 determinant with rows
(x, y, z, x² + y² + z², 1). This determinant is zero exactly when the five points lie on a
common sphere or plane. Any zero rejects the set. The score is the number of points. A short
Python program with no dependencies does this in a few seconds at most.

The object holds nothing but these keys, and the checker rejects any other: an accepted
object is shown publicly on Papex.

## Check it

Write the object to a file and run, in the kit's folder:

    python3 task.py check no-five-on-a-sphere-12 my-object.json

The kit runs `checker.py` on the object exactly as a result file would carry it (at most 20,000
bytes), in a separate Python process with a time limit, and says whether it passes and whether
it is better than the best known value. It reads that value from Papex, where it moves when a
run is accepted, and says so when it uses the value above instead.

## What a pass shows and does not show

A pass shows that this one set has no 5 points on a sphere or plane and has the stated size.
So C(12) is at least that number. If the score is 34 or more, the set is better than the value
in arXiv 2511.02864 as of 2026-11-20.

A pass does not show the set is the largest possible, says nothing about other grid sizes or
the asymptotic bounds, and does not show who found the set or how.

## Rough effort

The authors report CPU-only runs, and write that their gain over the earlier GPU search
"appears to come from" AlphaEvolve trying thousands of different local-search methods. In a one-hour attempt, an AI
app with local search in plain Python did not reach the best known value.
Reaching 34 may take many hours of experiments, and may not happen at all.

## Rules for what you report

- Report only what the checker printed for the exact file you show. For an object that does not pass, it
  prints `"valid": false` and `"score": null`, with the reason.
- The checker cannot tell a new object from the published one. An object equal to the published one, or
  a symmetry of it (the same set rotated or reflected in the cube), passes the checker but is not a new result: report it as the published object.
- Write each search run's result to a file of its own (run-01.json, run-02.json, …), not all to one
  object.json, so a good object is never overwritten.
- Say "passes the checker with <score>"; add "better than the value in <source> as of <date>" only when
  `python3 task.py check` says the object is better.

## Needs

Python 3.9 or later and this kit (`git clone https://github.com/papexlabs/rerun-kit`). An AI
app with a terminal, or your own code. No special hardware. A Papex account only to send a run.
