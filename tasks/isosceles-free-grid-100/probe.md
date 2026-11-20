# Probe (G3) — isosceles-free-grid-100

Run on 2026-11-20, macOS, `python3 -I checker.py <file>` from this folder (Python 3.15.2;
the same outputs were also obtained with Python 3.9.6). All runs took well under one second.

## 1. The published object reproduces the published value

`best_known.json` holds `sol_100` exactly as published in the source notebook
(`experiments/subsets_of_the_grid_with_no_isosceles_triangles/...ipynb`, cell 1, repository
commit `8f447457957deac61e28bf1676746f0753b3b2f8`), parsed from the notebook JSON with
Python's `ast` (literals only; nothing from the download was executed).
Published value: 164 points (arXiv 2511.02864v3, appendix.tex line 1950: "...improved the
previous best construction of 160 points ... to 164 ...").

```
$ python3 checker.py best_known.json
{"valid": true, "score": 164, "reason": "164 distinct points in the 100x100 grid, no isosceles triangle (all 164 apexes checked with exact integers)"}
```

The objective is an integer count and every test is exact integer arithmetic (squared
distances), so no tolerance is involved. Score 164 = published value 164.

Independent cross-check (a separate script of ours, mirroring the source notebook's own test
over all ordered triples `itertools.permutations(points, 3)`, exact integers):
`points 164 distinct 164 range 0 99 violations_found 0`.
The same notebook's 64 x 64 construction `sol_64` has 112 points, matching the paper's 112.

## 2. Broken variants are rejected

Variant files are in `probe/` (made by our own script from `best_known.json`):

| file | what was changed |
|---|---|
| v1_wrong_n.json | declared grid size `n` set to 64 (wrong size) |
| v2_out_of_range.json | point 0 moved to x = 100 (outside 0..99) |
| v3_add_midpoint.json | added (78, 4), the midpoint of published points (67, 4) and (89, 4) (violated constraint) |
| v4_tampered_point.json | point 0 changed from (67, 4) to (67, 5) (tampered value) |
| v5_duplicate_point.json | last point repeated, so the list claims 165 entries |
| v6_non_integer.json | point 1 changed to (89.5, 4) |
| v7_claimed_score_ignored.json | extra field `"score": 999` added (must be ignored) |
| v8_truncated.json | file cut after 500 characters |

```
$ python3 checker.py probe/v1_wrong_n.json
{"valid": false, "score": null, "reason": "field n must be the integer 100"}
$ python3 checker.py probe/v2_out_of_range.json
{"valid": false, "score": null, "reason": "point 0 = (100, 4) is outside 0..99"}
$ python3 checker.py probe/v3_add_midpoint.json
{"valid": false, "score": null, "reason": "isosceles: |a-b| = |b-c| with a=[75, 97], b=[92, 51], c=[78, 4] (squared distance 2405)"}
$ python3 checker.py probe/v4_tampered_point.json
{"valid": false, "score": null, "reason": "isosceles: |a-b| = |b-c| with a=[67, 5], b=[91, 86], c=[7, 95] (squared distance 7137)"}
$ python3 checker.py probe/v5_duplicate_point.json
{"valid": false, "score": null, "reason": "point 164 = (3, 56) appears twice"}
$ python3 checker.py probe/v6_non_integer.json
{"valid": false, "score": null, "reason": "point 1 is not a pair of integers: [89.5, 4]"}
$ python3 checker.py probe/v7_claimed_score_ignored.json
{"valid": true, "score": 164, "reason": "164 distinct points in the 100x100 grid, no isosceles triangle (all 164 apexes checked with exact integers)"}
$ python3 checker.py probe/v8_truncated.json
{"valid": false, "score": null, "reason": "not valid JSON: Expecting value: line 1 column 501 (char 500)"}
```

Hand check of the v3 report: (75-92)^2 + (97-51)^2 = 289 + 2116 = 2405 and
(92-78)^2 + (51-4)^2 = 196 + 2209 = 2405. (The added point also makes the flat triple
(67,4), (78,4), (89,4); the checker stops at the first violation it meets.)

Seven variants rejected; v7 shows a claimed score in the file has no effect.

## 3. Is 164 still the best value stated anywhere? (searched 2026-11-20)

- The repository's `status.json` lists 59 under `"world_record"` (the repository's own label).
- Web searches for later 100 x 100 constructions found only asymptotic work (e.g. Yukai Song,
  "Sparse coloring for isosceles-free grids", arXiv 2610.04194 / NeurIPS 2026, which gives a
  lower bound of order n·sqrt(log log n / log n) and no 100 x 100 count). No claim above 164 was found.
- This is a search result, not a proof that no better set exists anywhere.

## 4. Limits

File limit 200,000 bytes; the work is O(k^2) for k points with an early exit at the first
repeated distance. From one point of the 100 x 100 grid only 3,663 distinct nonzero squared
distances occur (counted by our script), so more than 3,664 points can never be valid; the
checker rejects such inputs at once. Stated limit: 60 seconds.

## 5. Sources for each fact on the card (all fetched 2026-11-20)

- 164 points, "we believe this is still not optimal", previous 160: arXiv 2511.02864v3 TeX
  source (https://arxiv.org/e-print/2511.02864v3), appendix.tex line 1950 (quoted in task.json).
- Authors and title: repository README, "Bogdan Georgiev, Javier Gómez-Serrano, Terence Tao,
  Adam Zsolt Wagner -- Mathematical exploration and discovery at scale, 2025".
- PatternBoost authors and year: refs.bib entry `charton2024patternboost` in the same TeX source
  ("Charton, François and Ellenberg, Jordan S. and Wagner, Adam Zsolt and Williamson, Geordie",
  2024, arXiv:2411.00566).
- "after a few days" and the symmetry / near-the-edge advice: appendix.tex line 1950 ("we gave
  \AlphaEvolve the advice that the optimal constructions probably are close to having a
  four-fold symmetry, ... and that the optimal construction probably has most points near the
  edge of the grid. Using this advice, after a few days \AlphaEvolve found the elusive
  configuration of 112 points in the $64\times 64$ grid!").
- Licence: repository README, "All software is licensed under the Apache License, Version 2.0
  ... All other materials are licensed under the Creative Commons Attribution 4.0
  International License (CC-BY)."
- Checker run time: measured above.

## Gates not covered here

G4 (an independent second pass that rebuilds the card from the source) has not been run.

## Changed in the kit (20 Nov 2026)

An accepted object is shown publicly on Papex, so the checker now rejects any key the format does not name. `best_known.json` now holds the object only; where it came from (sol_100, notebook cell 1, commit 8f447457957d) is in task.json's sources. Nothing else in the checker changed. Run with `python3 -I -S -B checker.py <file>` (Python 3.15.2):

```
$ python3 checker.py best_known.json
{"valid": true, "score": 164, "reason": "164 distinct points in the 100x100 grid, no isosceles triangle (all 164 apexes checked with exact integers)"}
$ python3 checker.py probe/v7_extra_key.json
{"valid": false, "score": null, "reason": "key \"score\" is not part of the format (only n and points)"}
```

Every other probe file gives the line recorded above. The cases, with these lines, are in `probe/cases.json`.

## Numbers of the wrong type are rejected (added in the kit, 20 Nov 2026)

These were refused already; the files make sure they stay refused. Each file is best_known.json with the one change named, run as the lint runs it:

```
v9_n_is_100_as_a_float               exit=0 0.060s  {"valid": false, "score": null, "reason": "field n must be the integer 100"}
v10_n_is_true                        exit=0 0.057s  {"valid": false, "score": null, "reason": "field n must be the integer 100"}
v11_coordinate_is_true               exit=0 0.055s  {"valid": false, "score": null, "reason": "point 0 is not a pair of integers: [True, 4]"}
```
