# Probe — erdos-483-schur-six-colours (re-run 2026-11-20, after re-sourcing)

Script: the task preparer's own probe script (scratch; not part of the task).
It runs `python3 -I <this folder>/checker.py <file>` as a subprocess on every case and, as an
independent cross-check, counts monochromatic triples (a, b, a+b), a <= b, with a plain double loop.
Interpreter: Python 3.15.2 (`python3`); `/usr/bin/python3` is 3.9.6.

## Source object
`best_known.json` holds the colouring of 1..538 from `schur6-538.word` in
https://github.com/mysticflounder/schur-538 (tag v1.2.0, commit 47c01b3; CC BY 4.0; read with
`gh api`), letters 1..6 renumbered 0..5. SHA-256 of the file as read:

```
9e149c007b778655afd199685ebcc76260604a44f4c322d8aa9a1d96afb71d20  schur6-538.word
```
which is the SHA-256 stated in the paper (paper/schur-six-538.md, Section 3). The word also equals
Figure 1 of the paper letter for letter.

## (1) Published object gives exactly the published value (538)
```
best_known.json (N=538)              exit=0 0.030s  {"valid": true, "score": 538, "reason": "all 6 colours are sum-free on 1..538 (a = b included); f(6) >= 539"}
   brute-force monochromatic triples: 0
```

## (2) Broken variants are rejected
```
v1_colour_of_2_set_to_colour_of_1    exit=0 0.030s  {"valid": false, "score": null, "reason": "colour 0 contains 1 + 1 = 2"}
   brute-force monochromatic triples: 81
v2_extend_to_539_with_colour_0       exit=0 0.028s  {"valid": false, "score": null, "reason": "colour 0 contains 1 + 538 = 539"}
   brute-force monochromatic triples: 60
v2_extend_to_539_with_colour_1       exit=0 0.029s  {"valid": false, "score": null, "reason": "colour 1 contains 2 + 537 = 539"}
   brute-force monochromatic triples: 42
v2_extend_to_539_with_colour_2       exit=0 0.029s  {"valid": false, "score": null, "reason": "colour 2 contains 6 + 533 = 539"}
   brute-force monochromatic triples: 28
v2_extend_to_539_with_colour_3       exit=0 0.029s  {"valid": false, "score": null, "reason": "colour 3 contains 4 + 535 = 539"}
   brute-force monochromatic triples: 33
v2_extend_to_539_with_colour_4       exit=0 0.030s  {"valid": false, "score": null, "reason": "colour 4 contains 5 + 534 = 539"}
   brute-force monochromatic triples: 31
v2_extend_to_539_with_colour_5       exit=0 0.032s  {"valid": false, "score": null, "reason": "colour 5 contains 145 + 394 = 539"}
   brute-force monochromatic triples: 61
v3_colour_value_6_at_100             exit=0 0.030s  {"valid": false, "score": null, "reason": "colour of 100 is not an integer in 0..5"}
v4_N538_but_537_colours              exit=0 0.028s  {"valid": false, "score": null, "reason": "colours must be a list of exactly N entries (colour of 1, 2, ..., N)"}
v5_k_is_5                            exit=0 0.026s  {"valid": false, "score": null, "reason": "k must be 6"}
v6_not_json                          exit=0 0.033s  {"valid": false, "score": null, "reason": "cannot read object as JSON: JSONDecodeError"}
v7_boolean_colour_at_10              exit=0 0.033s  {"valid": false, "score": null, "reason": "colour of 10 is not an integer in 0..5"}
v8_oversized_file                    exit=0 0.026s  {"valid": false, "score": null, "reason": "object file is 201645 bytes; limit is 200000"}
```
The checker and the independent triple count agree on every case where both apply
(0 triples ⇔ valid). Extending the published colouring by one number fails for all six colours.

## (3) The other published colourings give their published values
```
   (second McKenna word differs from best_known in 37 positions)
mckenna_second_word_b (N=538)        exit=0 0.035s  {"valid": true, "score": 538, "reason": "all 6 colours are sum-free on 1..538 (a = b included); f(6) >= 539"}
   brute-force monochromatic triples: 0
chen_zhu_long_537_from_paper_text    exit=0 0.031s  {"valid": true, "score": 537, "reason": "all 6 colours are sum-free on 1..537 (a = b included); f(6) >= 538"}
   brute-force monochromatic triples: 0
```
The 37 differing positions match the paper's sentence "differs from $W$ in 37 letters". The 537
colouring was rebuilt from the six lists printed in the proof of Theorem 1 of arXiv:2610.31362v1
(HTML text, CC BY 4.0; stated class sizes 76, 76, 88, 70, 76, 151 all matched). It is identical, at
all 537 positions, to the colouring the earlier version of this folder held.

## Limits observed
Every run above took under 0.04 s. The absolute worst case for N = 5000 is at most N²/2 = 12.5 million
pair tests, a few seconds, inside the 10-second limit (unchanged from the first probe; the checker was
not changed).

## Changed in the kit (20 Nov 2026)

An accepted object is shown publicly on Papex, so the checker now rejects an object with any key but k, N
and colours ("the object must hold exactly the keys k, N and colours"); nothing else in it changed.
`best_known.json` now holds the object only; where it comes from is in task.json's sources ("Where
best_known.json comes from"). The kit's limit for an object is 20,000 bytes as a result file carries it.

The probe files in `probe/` were built in the kit from the descriptions above (v1 to v7, and v9 with an
extra key) and give exactly the lines recorded above, which `probe/cases.json` holds. Not rebuilt here:
v8 (a file over 200,000 bytes), McKenna's second word and the 537 colouring of Chen, Zhu and Long, whose
objects this folder does not hold.

## Numbers of the wrong type are rejected (added in the kit, 20 Nov 2026)

The checker refused k = 6.0 before this was added (6.0 == 6 in Python); it now requires the integer 6. Each file is best_known.json with the one change named, run as the lint runs it:

```
t1_k_is_6_as_a_float                 exit=0 0.059s  {"valid": false, "score": null, "reason": "k must be 6"}
t2_k_is_true                         exit=0 0.056s  {"valid": false, "score": null, "reason": "k must be 6"}
t3_N_is_538_as_a_float               exit=0 0.062s  {"valid": false, "score": null, "reason": "N must be an integer between 1 and 5000"}
t4_colour_of_5_as_a_float            exit=0 0.061s  {"valid": false, "score": null, "reason": "colour of 5 is not an integer in 0..5"}
```
