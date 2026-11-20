# Probe (G3) — no-five-on-a-sphere-12

Run on 2026-11-20, macOS, `python3 -I checker.py <file>` from this folder (Python 3.15.2;
the published object gives the same output with Python 3.9.6).

## 1. The published object reproduces the published value

`best_known.json` holds `construction_n_12_12_12` exactly as published in the source notebook
(`experiments/no_5_on_a_sphere/no_5_on_a_sphere.ipynb`, cell 1, repository commit
`8f447457957deac61e28bf1676746f0753b3b2f8`), parsed from the notebook JSON with Python's `ast`
(literals only; nothing from the download was executed).
Published value: C(12) >= 33 (arXiv 2511.02864v3, appendix.tex line 1973).

```
$ python3 checker.py best_known.json
{"valid": true, "score": 33, "reason": "33 distinct points in the 12x12x12 grid; all 237336 five-point subsets have a nonzero exact determinant"}
```

C(33, 5) = 237,336, so every 5-point subset was tested. The test is exact integer arithmetic
(the source's own verifier uses the same determinant but in floating point with `np.isclose`).
Score 33 = published value 33. Run time 0.5 s.

Independent cross-check (a separate script of ours computing the full 5 x 5 determinant of every
5-subset by fraction-free Bareiss elimination) on all six constructions in the notebook:

```
construction_n_7_7_7@1 n 7 points 21 distinct 21 max coord 6 subsets tested 20349 zero dets 0
construction_n_8_8_8@1 n 8 points 23 distinct 23 max coord 7 subsets tested 33649 zero dets 0
construction_n_9_9_9@1 n 9 points 26 distinct 26 max coord 8 subsets tested 65780 zero dets 0
construction_n_10_10_10@1 n 10 points 28 distinct 28 max coord 9 subsets tested 98280 zero dets 0
construction_n_11_11_11@1 n 11 points 31 distinct 31 max coord 10 subsets tested 169911 zero dets 0
construction_n_12_12_12@1 n 12 points 33 distinct 33 max coord 11 subsets tested 237336 zero dets 0
```

These match the paper's 21, 23, 26, 28, 31, 33.

Why the determinant test is exact: the rows are (x, y, z, x²+y²+z², 1). The determinant is
zero exactly when some nonzero (a, b, c, e, d) has a·x + b·y + c·z + e·(x²+y²+z²) + d = 0 at all
five points: a sphere if e ≠ 0 (a sphere of radius 0 cannot hold five distinct points), a plane
if e = 0.

## 2. Broken variants are rejected

Variant files are in `probe/` (made by our own script from `best_known.json`):

| file | what was changed |
|---|---|
| v1_wrong_n.json | declared grid size `n` set to 11 (wrong size) |
| v2_out_of_range.json | point 0 moved to x = 12 (outside 0..11) |
| v3_add_point.json | added (0, 0, 0), the first free grid point (violated constraint) |
| v4_tampered_point.json | point 0 changed from (5, 9, 10) to (5, 9, 11) (tampered value) |
| v5_duplicate_point.json | last point repeated (34 entries) |
| v6_too_many_points.json | 16 free grid points added (49 points) |
| v7_five_coplanar.json | five points on the plane z = 0 |
| v8_five_cospherical.json | five points on the sphere of radius 3 about (5, 5, 5) |
| v9_float_coordinate.json | point 2 written as 11.0 instead of 11 |

```
$ python3 checker.py probe/v1_wrong_n.json
{"valid": false, "score": null, "reason": "field n must be the integer 12"}
$ python3 checker.py probe/v2_out_of_range.json
{"valid": false, "score": null, "reason": "point 0 = [12, 9, 10] is outside 0..11"}
$ python3 checker.py probe/v3_add_point.json
{"valid": false, "score": null, "reason": "5 points on one sphere or plane: [[5, 9, 10], [6, 10, 6], [7, 2, 0], [0, 9, 2], [0, 0, 0]]"}
$ python3 checker.py probe/v4_tampered_point.json
{"valid": false, "score": null, "reason": "5 points on one sphere or plane: [[5, 9, 11], [10, 5, 8], [4, 2, 1], [9, 0, 9], [8, 0, 11]]"}
$ python3 checker.py probe/v5_duplicate_point.json
{"valid": false, "score": null, "reason": "point 33 = [11, 0, 3] appears twice"}
$ python3 checker.py probe/v6_too_many_points.json
{"valid": false, "score": null, "reason": "49 points: more than 4n = 48 points always put 5 on one plane z = c"}
$ python3 checker.py probe/v7_five_coplanar.json
{"valid": false, "score": null, "reason": "5 points on one sphere or plane: [[0, 0, 0], [1, 0, 0], [0, 1, 0], [3, 5, 0], [7, 2, 0]]"}
$ python3 checker.py probe/v8_five_cospherical.json
{"valid": false, "score": null, "reason": "5 points on one sphere or plane: [[8, 5, 5], [5, 8, 5], [5, 5, 8], [2, 5, 5], [7, 6, 7]]"}
$ python3 checker.py probe/v9_float_coordinate.json
{"valid": false, "score": null, "reason": "point 2 is not a triple of integers: [11.0, 11, 2]"}
```

The three 5-point sets reported for v3, v4 and v8 were each re-tested by our separate
exact-fraction determinant: all three determinants are 0.

## 3. Is 33 still the best value stated anywhere? (searched 2026-11-20)

- The repository's `status.json` lists 60 under `"world_record"` (the repository's own label).
- Web searches found only asymptotic results for this family (Suk–White arXiv 2412.02866,
  Dong–Xu arXiv 2506.18113, Ghosal–Goenka–Keevash arXiv 2509.06935); none reports a set in
  the 12 x 12 x 12 grid. No claim above 33 was found.
- This is a search result, not a proof that no better set exists anywhere.

## 4. Limits

File limit 20,000 bytes; at most 48 points are accepted for the full test. A full scan of 48
points (all 1,712,304 five-point subsets, measured with a copy of the checker whose early
exit was disabled) took 2.4 s. Stated limit: 60 seconds.

## 5. Sources for each fact on the card (all fetched 2026-11-20)

- 33 points, and 21, 23, 26, 28, 31 for n = 7..11; earlier PatternBoost values 20, 22, 25, 27
  for n = 7..10; CPU evaluators: arXiv 2511.02864v3 TeX source
  (https://arxiv.org/e-print/2511.02864v3), appendix.tex line 1973.
- Upper bound 4n and the bounds c·sqrt(n) and n^(3/4 − o(1)): same line ("$c\sqrt{n}\leq
  C(n)\leq 4n$ ... improved ... to $n^{\frac{3}{4}-o(1)}\leq C(n)$").
- Authors and title: repository README. Licence: repository README (Apache 2.0 for software,
  CC BY 4.0 for other materials).

## Gates not covered here

G4 (an independent second pass that rebuilds the card from the source) has not been run.

## Changed in the kit (20 Nov 2026)

An accepted object is shown publicly on Papex, so the checker now rejects any key the format does not name. `best_known.json` now holds the object only; where it came from (construction_n_12_12_12, notebook cell 1, commit 8f447457957d) is in task.json's sources. Nothing else in the checker changed. Run with `python3 -I -S -B checker.py <file>` (Python 3.15.2):

```
$ python3 checker.py best_known.json
{"valid": true, "score": 33, "reason": "33 distinct points in the 12x12x12 grid; all 237336 five-point subsets have a nonzero exact determinant"}
$ python3 checker.py probe/v10_extra_key.json
{"valid": false, "score": null, "reason": "key \"note\" is not part of the format (only n and points)"}
```

Every other probe file gives the line recorded above. The cases, with these lines, are in `probe/cases.json`.

## Numbers of the wrong type are rejected (added in the kit, 20 Nov 2026)

These were refused already; the files make sure they stay refused. Each file is best_known.json with the one change named, run as the lint runs it:

```
v11_n_is_12_as_a_float               exit=0 0.056s  {"valid": false, "score": null, "reason": "field n must be the integer 12"}
v12_n_is_true                        exit=0 0.058s  {"valid": false, "score": null, "reason": "field n must be the integer 12"}
v13_coordinate_is_true               exit=0 0.060s  {"valid": false, "score": null, "reason": "point 0 is not a triple of integers: [True, 9, 10]"}
```
