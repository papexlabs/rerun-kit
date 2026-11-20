# Isosceles-free points in a 100 × 100 grid

## What to find

A set of points in the 100 × 100 grid with no isosceles triangle: no three distinct points
a, b, c with |a − b| = |b − c|. Flat triangles count too, so no point may be the exact
midpoint of two others. The more points, the better. The best published set has 164 points;
the target is 165 or more.

## Best known

- **164 points**, found with AlphaEvolve and reported by Bogdan Georgiev, Javier Gómez-Serrano,
  Terence Tao and Adam Zsolt Wagner in "Mathematical exploration and discovery at scale" (2025).
  The authors write that they "believe this is still not optimal". The previous set had 160
  points (PatternBoost, Charton, Ellenberg, Wagner, Williamson, 2024).
- Source: [arXiv 2511.02864](https://arxiv.org/abs/2511.02864), section on problem 59; the
  164 points are published in the
  [problem 59 notebook](https://github.com/google-deepmind/alphaevolve_repository_of_problems/blob/main/experiments/subsets_of_the_grid_with_no_isosceles_triangles/subsets_of_the_grid_with_no_isosceles_triangles.ipynb)
  (CC BY 4.0 / Apache 2.0).
- As of 2026-11-20, we found no later published set with more points.

## How it is checked

You submit a JSON file `{"n": 100, "points": [[x, y], ...]}` with integer coordinates from
0 to 99. The checker tests that the points are distinct and in range, then, for every point b,
computes the squared distance to every other point in exact integers and rejects the set if
any two of those distances are equal. The score is the number of points. A short Python
program with no dependencies does this in under a second.

The object holds nothing but these keys, and the checker rejects any other: an accepted
object is shown publicly on Papex.

## Check it

Write the object to a file and run, in the kit's folder:

    python3 task.py check isosceles-free-grid-100 my-object.json

The kit runs `checker.py` on the object exactly as a result file would carry it (at most 20,000
bytes), in a separate Python process with a time limit, and says whether it passes and whether
it is better than the best known value. It reads that value from Papex, where it moves when a
run is accepted, and says so when it uses the value above instead.

## What a pass shows and does not show

A pass shows that this one set has no isosceles triangle and has the stated size. So
C(100) is at least that number. If the score is 165 or more, the set is better than the value
in arXiv 2511.02864 as of 2026-11-20.

A pass does not show the set is the largest possible, says nothing about other grid sizes or
the asymptotic question, and does not show who found the set or how.

## Rough effort

The authors report that AlphaEvolve took a few days to reach 112 points on the 64 × 64 grid,
using hints about near four-fold symmetry and few points near the centre. Beating 164 may take many hours of experiments, and may not
happen at all.

## Rules for what you report

- Report only what the checker printed for the exact file you show. For an object that does not pass, it
  prints `"valid": false` and `"score": null`, with the reason.
- The checker cannot tell a new object from the published one. An object equal to the published one, or
  a symmetry of it (the same set rotated, reflected or moved in the grid), passes the checker but is not a new result: report it as the published object.
- Write each search run's result to a file of its own (run-01.json, run-02.json, …), not all to one
  object.json, so a good object is never overwritten.
- Say "passes the checker with <score>"; add "better than the value in <source> as of <date>" only when
  `python3 task.py check` says the object is better.

## Needs

Python 3.9 or later and this kit (`git clone https://github.com/papexlabs/rerun-kit`). An AI
app with a terminal, or your own code. No special hardware. A Papex account only to send a run.
