# Probe (G3) — ring-loading-lower-bound, repaired 2026-11-20

Run on 2026-11-20, macOS, `python3 -I checker.py <file>` from this folder (Python 3.15.2; the same
outputs with the system Python 3.9.6). `probe/old/checker_before_repair.py` is the checker as it was
before this repair (k = 1..m−1), kept only for the comparisons. Output lines are copied as printed.

## 1. best_known.json gives exactly the best known value 9/8

`best_known.json` is our own 14-pair instance (how it was built: section 6). The best known value is
9/8 (issue #12 of the AlphaEvolve repository, the EinsteinArena leaderboard, Däubel's comment; see
`task.json`).

```
$ python3 checker.py best_known.json
{"valid": true, "score": 1.125, "exact": "9/8", "bestKnown": "9/8", "betterThanBestKnown": false, "reason": "m = 14 pairs (0 scaled so that u+v = 1); k = 1..m; exact minimum over all 2^14 sign choices: alpha = 9/8 = 1.125 exactly; so beta >= 9/8; equal to the best known 9/8, not above it (exact comparison)"}
```

Equal to 9/8, and correctly not "better". Independent plain enumeration (own script, exact
fractions, no pruning):
`m=14  k=1..m: 9/8 (1.125000000000000, attained by 44 sign vectors)   k=1..m-1: 9/8 (1.125000000000000)`.

## 2. Broken variants are rejected

Made from `best_known.json` by our own script; files in `probe/`.

| file | what was changed | result |
|---|---|---|
| v1_too_many_pairs.json | 21 pairs | rejected |
| v2_one_pair.json | 1 pair | rejected |
| v3_negative_u.json | first u = −1/16 | rejected |
| v4_nan.json | one v replaced by the literal NaN | rejected |
| v5_text_value.json | one u = "half" | rejected |
| v6_tampered_digit.json | pair 0 changed from (3/16, 13/16) to (4/16, 12/16) | valid, recomputed: 17/16, not better |
| v7_claimed_score_ignored.json | extra keys `"score": 1.5, "betterThanBestKnown": true` | ignored: 9/8, not better |
| v8_pair_scaled.json | pair 0 replaced by (3, 1) | scaled to (3/4, 1/4): 13/16 |

```
$ python3 checker.py probe/v1_too_many_pairs.json
{"valid": false, "score": null, "exact": null, "bestKnown": "9/8", "betterThanBestKnown": null, "reason": "need 2 <= m <= 20 pairs, got 21"}
$ python3 checker.py probe/v2_one_pair.json
{"valid": false, "score": null, "exact": null, "bestKnown": "9/8", "betterThanBestKnown": null, "reason": "need 2 <= m <= 20 pairs, got 1"}
$ python3 checker.py probe/v3_negative_u.json
{"valid": false, "score": null, "exact": null, "bestKnown": "9/8", "betterThanBestKnown": null, "reason": "pair 0 has a negative entry"}
$ python3 checker.py probe/v4_nan.json
{"valid": false, "score": null, "exact": null, "bestKnown": "9/8", "betterThanBestKnown": null, "reason": "not accepted: constant NaN is not allowed"}
$ python3 checker.py probe/v5_text_value.json
{"valid": false, "score": null, "exact": null, "bestKnown": "9/8", "betterThanBestKnown": null, "reason": "pair 2 u: cannot read 'half' as an exact rational"}
$ python3 checker.py probe/v6_tampered_digit.json
{"valid": true, "score": 1.0625, "exact": "17/16", "bestKnown": "9/8", "betterThanBestKnown": false, "reason": "m = 14 pairs (0 scaled so that u+v = 1); k = 1..m; exact minimum over all 2^14 sign choices: alpha = 17/16 = 1.0625 exactly; so beta >= 17/16; below the best known 9/8 (exact comparison)"}
$ python3 checker.py probe/v7_claimed_score_ignored.json
{"valid": true, "score": 1.125, "exact": "9/8", "bestKnown": "9/8", "betterThanBestKnown": false, "reason": "m = 14 pairs (0 scaled so that u+v = 1); k = 1..m; exact minimum over all 2^14 sign choices: alpha = 9/8 = 1.125 exactly; so beta >= 9/8; equal to the best known 9/8, not above it (exact comparison)"}
$ python3 checker.py probe/v8_pair_scaled.json
{"valid": true, "score": 0.8125, "exact": "13/16", "bestKnown": "9/8", "betterThanBestKnown": false, "reason": "m = 14 pairs (1 scaled so that u+v = 1); k = 1..m; exact minimum over all 2^14 sign choices: alpha = 13/16 = 0.8125 exactly; so beta >= 13/16; below the best known 9/8 (exact comparison)"}
```

## 3. Hostile inputs (each answered in about 0.04 s)

```
$ python3 checker.py probe/x1_exponent_number.json      # 1e999999999 as a JSON number
{"valid": false, "score": null, "exact": null, "bestKnown": "9/8", "betterThanBestKnown": null, "reason": "pair 0 u: exponent larger than 60"}
$ python3 checker.py probe/x2_exponent_string.json      # "1e-999999999" as a string
{"valid": false, "score": null, "exact": null, "bestKnown": "9/8", "betterThanBestKnown": null, "reason": "pair 0 u: exponent larger than 60"}
$ python3 checker.py probe/x3_long_decimal.json         # a 202-character decimal
{"valid": false, "score": null, "exact": null, "bestKnown": "9/8", "betterThanBestKnown": null, "reason": "pair 0 u: literal longer than 80 characters"}
$ python3 checker.py probe/x4_huge_integer.json         # a 4000-digit integer
{"valid": false, "score": null, "exact": null, "bestKnown": "9/8", "betterThanBestKnown": null, "reason": "pair 0 u: integer longer than 80 digits"}
$ python3 checker.py probe/x5_ratio_huge_parts.json     # "777…7/333…3", exactly 80 characters
{"valid": true, "score": 0.5, "exact": "1/2", "bestKnown": "9/8", "betterThanBestKnown": false, "reason": "m = 2 pairs (0 scaled so that u+v = 1); k = 1..m; exact minimum over all 2^2 sign choices: alpha = 1/2 = 0.5 exactly; so beta >= 1/2; below the best known 9/8 (exact comparison)"}
$ python3 checker.py probe/x5b_ratio_too_long.json      # the same with 81 characters
{"valid": false, "score": null, "exact": null, "bestKnown": "9/8", "betterThanBestKnown": null, "reason": "pair 0 u: literal longer than 80 characters"}
$ python3 checker.py probe/x6_denominator_bits.json     # twenty different 40-digit denominators
{"valid": false, "score": null, "exact": null, "bestKnown": "9/8", "betterThanBestKnown": null, "reason": "common denominator of all entries has more than 2048 bits (use shorter decimals or smaller fractions)"}
$ python3 checker.py probe/x7_nan.json
{"valid": false, "score": null, "exact": null, "bestKnown": "9/8", "betterThanBestKnown": null, "reason": "not accepted: constant NaN is not allowed"}
$ python3 checker.py probe/x8_infinity_string.json
{"valid": false, "score": null, "exact": null, "bestKnown": "9/8", "betterThanBestKnown": null, "reason": "pair 0 u: cannot read 'inf' as an exact rational"}
```

The old checker on x1 printed nothing within 60 s (`timeout 60 python3 -I
probe/old/checker_before_repair.py probe/x1_exponent_number.json` → exit 124 after 60 s); on
`1e-9999999` (one digit fewer) it needed 17.5 s before rejecting.

## 4. The k-range: old checker (k = 1..m−1) against new (k = 1..m)

```
$ python3 checker.py probe/alphaevolve_m15.json                          # (a) AlphaEvolve's published 15 pairs
{"valid": true, "score": 1.11904756846927744, "exact": "874255912866623/781250000000000", "bestKnown": "9/8", "betterThanBestKnown": false, "reason": "m = 15 pairs (2 scaled so that u+v = 1); k = 1..m; exact minimum over all 2^15 sign choices: alpha = 874255912866623/781250000000000 = 1.11904756846927744 exactly; so beta >= 874255912866623/781250000000000; below the best known 9/8 (exact comparison)"}
$ python3 probe/old/checker_before_repair.py probe/alphaevolve_m15.json
{"valid": true, "score": 1.119047568469, "reason": "m = 15 pairs (2 scaled so that u+v = 1); exact minimum over all 2^15 sign choices: alpha = 1.119047568469277440000000000000... (rounded down to 30 decimals); score is alpha rounded down to 12 decimals, so C >= 1.119047568469"}

$ python3 checker.py best_known.json                                     # (b) a 9/8 instance
{"valid": true, "score": 1.125, "exact": "9/8", ... "equal to the best known 9/8, not above it (exact comparison)"}
$ python3 probe/old/checker_before_repair.py best_known.json
{"valid": true, "score": 1.125000000000, "reason": "m = 14 pairs (0 scaled so that u+v = 1); exact minimum over all 2^14 sign choices: alpha = 1.125000000000000000000000000000... (rounded down to 30 decimals); score is alpha rounded down to 12 decimals, so C >= 1.125000000000"}

$ python3 checker.py probe/c_turned6.json                                # (b') the same ring turned by 6 pairs
{"valid": true, "score": 1.125, "exact": "9/8", "bestKnown": "9/8", "betterThanBestKnown": false, "reason": "m = 14 pairs (0 scaled so that u+v = 1); k = 1..m; exact minimum over all 2^14 sign choices: alpha = 9/8 = 1.125 exactly; so beta >= 9/8; equal to the best known 9/8, not above it (exact comparison)"}
$ python3 probe/old/checker_before_repair.py probe/c_turned6.json
{"valid": true, "score": 0.750000000000, "reason": "m = 14 pairs (0 scaled so that u+v = 1); exact minimum over all 2^14 sign choices: alpha = 0.750000000000000000000000000000... (rounded down to 30 decimals); score is alpha rounded down to 12 decimals, so C >= 0.750000000000"}

$ python3 checker.py probe/c_turned6_padded_both_ends.json               # (c) (b') with (0, 0) at both ends
{"valid": true, "score": 1.125, "exact": "9/8", "bestKnown": "9/8", "betterThanBestKnown": false, "reason": "m = 16 pairs (0 scaled so that u+v = 1); k = 1..m; exact minimum over all 2^16 sign choices: alpha = 9/8 = 1.125 exactly; so beta >= 9/8; equal to the best known 9/8, not above it (exact comparison)"}
$ python3 probe/old/checker_before_repair.py probe/c_turned6_padded_both_ends.json
{"valid": true, "score": 1.125000000000, "reason": "m = 16 pairs (0 scaled so that u+v = 1); exact minimum over all 2^16 sign choices: alpha = 1.125000000000000000000000000000... (rounded down to 30 decimals); score is alpha rounded down to 12 decimals, so C >= 1.125000000000"}

$ python3 checker.py probe/c_turned6_padded_end_only.json                # (c') one (0, 0) at the end only
{"valid": true, "score": 1.125, "exact": "9/8", "bestKnown": "9/8", "betterThanBestKnown": false, "reason": "m = 15 pairs (0 scaled so that u+v = 1); k = 1..m; exact minimum over all 2^15 sign choices: alpha = 9/8 = 1.125 exactly; so beta >= 9/8; equal to the best known 9/8, not above it (exact comparison)"}
$ python3 probe/old/checker_before_repair.py probe/c_turned6_padded_end_only.json
{"valid": true, "score": 1.125000000000, "reason": "m = 15 pairs (0 scaled so that u+v = 1); exact minimum over all 2^15 sign choices: alpha = 1.125000000000000000000000000000... (rounded down to 30 decimals); score is alpha rounded down to 12 decimals, so C >= 1.125000000000"}
```

`probe/c_padded_both_ends.json` and `probe/c_padded_end_only.json` (best_known.json itself padded)
give 9/8 under both checkers as well.

| instance | old (k = 1..m−1) | new (k = 1..m) |
|---|---|---|
| (a) AlphaEvolve, 15 pairs | 1.119047568469 (rounded) | 874255912866623/781250000000000 |
| (b) best_known.json | 9/8 | 9/8 |
| (b') best_known.json turned by 6 pairs (the same ring) | 3/4 | 9/8 |
| (c) (b') with (0, 0) at both ends | 9/8 | 9/8 |
| (c') (b') with one (0, 0) at the end | 9/8 | 9/8 |

Reading: the k = 1..m value does not depend on where the ring is cut; the old value does, and a zero
pair at an end restores it. Plain enumeration agrees on every line (`c_turned6`: k = 1..m 9/8,
k = 1..m−1 3/4; `c_turned6_padded_end_only`: 9/8 and 9/8; AlphaEvolve: the same fraction under both).

The published 9/8 instances, scored in a scratch folder and not copied here: issue #12's 14 pairs,
old 0.75 / new 9/8; issue #12 padded to 16 pairs, 9/8 / 9/8; Däubel's 12 pairs, 0.75 / 9/8;
EinsteinArena entry 2576, 1.0 / 9/8.

## 5. Cross-checks of the checker

- Plain brute force (own script, exact fractions, no pruning) against `checker.py` on 300 random
  instances, m = 2..11, denominators 7, 16, 84, 1000, with zero pairs and pairs needing scaling:
  `tests 300 mismatches 0` (exact value and `betterThanBestKnown`).
- Ring symmetry: on 40 random instances, turning the ring by one pair never changed the k = 1..m
  value (40/40) and changed the k = 1..m−1 value in 24/40.

## 6. How best_known.json was built (own search, no copied numbers)

Exhaustive enumeration with our own C program (`exhaust3e.c`, compiled locally) and Python
(`exhaust.py`), each validated against a plain Python count on smaller families (identical numbers
checked and identical hit counts, e.g. 7,381,125 checked / 2,003,400 hits on one test shard). An
instance is a hit when no sign choice has all terms ≤ 17/16, i.e. α ≥ 9/8. Families (all on the
1/16 grid unless noted; "full" = u + v = 1 at alternate block positions):

- two identical 6-pair blocks; also B then B with u, v swapped; also B then its mirror: 3.5·10^10
  each shape — hits: only Däubel's published 12-pair instance and its mirror images;
- three identical 6-pair blocks (m = 18); 3 to 6 blocks of 3, 4 or 5 pairs (repeated and swapped
  shapes); mirror shapes with 5-pair blocks; odd palindromes with 11 pairs (all pairs) and 13 pairs
  (even 16(u+v)); on the 1/8 grid, two 6-pair blocks and smaller block families: no hits;
- two identical 7-pair blocks with even 16(u+v) (and the swapped and mirror shapes): 4.4·10^10 each —
  hits in three symmetry classes: Däubel's 12 pairs plus a full pair (0, 1) in each block (two
  classes, not used: they contain his instance), and the class of `best_known.json`.

In total about 3.4·10^11 instances; no instance above 9/8 in any family. `best_known.json` is the
second of the six hits printed by `./exhaust3e_c 16 7 2 0 0 17 3 10 1` (the fifth is the same
instance with u and v swapped; the other four contain Däubel's instance). It is not equivalent to issue #12's
instance, Däubel's instance or EinsteinArena entry 2576 under turning the ring, reversal, swapping u
and v, or deleting zero pairs, and none of them appears in it after deleting one or two pairs; five of
its seven block pairs are pairs of Däubel's block. Code and logs: kept by the task preparer, not part of the kit.

## 7. Limits

File limit 20,000 bytes; 2 ≤ m ≤ 20; each literal at most 80 characters; exponents at most 60; the
common denominator of all entries at most 2,048 bits. Measured on m = 20 stress inputs (all
(1/2, 1/2); all zeros; alternating (1/4, 3/4)/(3/4, 1/4); five random ones on the 1/1000 grid; random
full pairs on the 1/997 grid; 1/p for the first 20 primes; tiny fractions near 10⁻⁶) and on 9/8
instances padded with zero pairs to m = 20: 0.03–0.18 s each. Stated limit: 60 s.

## Gates not covered here

G4 (an independent second pass that rebuilds the card from the sources) has not been run on this
repaired version.

## Changed in the kit (20 Nov 2026)

- The checker prints the kit's three keys only: `valid`, `score`, `reason`. The exact fraction stays in the
  reason. The comparison with the best known value left the checker: `task.py check` and Papex's runner compare
  the score with the round's best known value, which moves from round to round.
- `score` is alpha written exactly when its decimal expansion ends within 18 places (it was 30), otherwise alpha
  rounded DOWN to 18 decimals (it was 12): a score on Papex has at most 18 decimals. A rounded-down score is
  never above alpha, so nothing is called better that is not. The smallest improvement on 9/8 that counts is a
  score of 1.125000000000000001 (alpha >= 9/8 + 10^-18).
- An accepted object is shown publicly, so the checker rejects any key but `pairs`;
  `v7_claimed_score_ignored.json` is here `v7_extra_keys.json` and is now rejected. `best_known.json` and
  `probe/alphaevolve_m15.json` hold the object only; their provenance is in task.json's sources.
- `probe/old/` (the checker before the repair) is not part of the kit's folder; it stays in the repaired
  folder this one was made from.

The new lines (Python 3.15.2), which `probe/cases.json` holds:

```
$ python3 checker.py best_known.json
{"valid": true, "score": 1.125, "reason": "m = 14 pairs (0 scaled so that u+v = 1); k = 1..m; exact minimum over all 2^14 sign choices: alpha = 9/8 = 1.125 exactly; so beta >= 9/8"}
$ python3 checker.py probe/v1_too_many_pairs.json
{"valid": false, "score": null, "reason": "need 2 <= m <= 20 pairs, got 21"}
$ python3 checker.py probe/v2_one_pair.json
{"valid": false, "score": null, "reason": "need 2 <= m <= 20 pairs, got 1"}
$ python3 checker.py probe/v3_negative_u.json
{"valid": false, "score": null, "reason": "pair 0 has a negative entry"}
$ python3 checker.py probe/v4_nan.json
{"valid": false, "score": null, "reason": "not accepted: constant NaN is not allowed"}
$ python3 checker.py probe/v5_text_value.json
{"valid": false, "score": null, "reason": "pair 2 u: cannot read 'half' as an exact rational"}
$ python3 checker.py probe/v6_tampered_digit.json
{"valid": true, "score": 1.0625, "reason": "m = 14 pairs (0 scaled so that u+v = 1); k = 1..m; exact minimum over all 2^14 sign choices: alpha = 17/16 = 1.0625 exactly; so beta >= 17/16"}
$ python3 checker.py probe/v7_extra_keys.json
{"valid": false, "score": null, "reason": "the object must hold exactly the key pairs"}
$ python3 checker.py probe/v8_pair_scaled.json
{"valid": true, "score": 0.8125, "reason": "m = 14 pairs (1 scaled so that u+v = 1); k = 1..m; exact minimum over all 2^14 sign choices: alpha = 13/16 = 0.8125 exactly; so beta >= 13/16"}
$ python3 checker.py probe/x1_exponent_number.json
{"valid": false, "score": null, "reason": "pair 0 u: exponent larger than 60"}
$ python3 checker.py probe/x2_exponent_string.json
{"valid": false, "score": null, "reason": "pair 0 u: exponent larger than 60"}
$ python3 checker.py probe/x3_long_decimal.json
{"valid": false, "score": null, "reason": "pair 0 u: literal longer than 80 characters"}
$ python3 checker.py probe/x4_huge_integer.json
{"valid": false, "score": null, "reason": "pair 0 u: integer longer than 80 digits"}
$ python3 checker.py probe/x5_ratio_huge_parts.json
{"valid": true, "score": 0.5, "reason": "m = 2 pairs (0 scaled so that u+v = 1); k = 1..m; exact minimum over all 2^2 sign choices: alpha = 1/2 = 0.5 exactly; so beta >= 1/2"}
$ python3 checker.py probe/x5b_ratio_too_long.json
{"valid": false, "score": null, "reason": "pair 0 u: literal longer than 80 characters"}
$ python3 checker.py probe/x6_denominator_bits.json
{"valid": false, "score": null, "reason": "common denominator of all entries has more than 2048 bits (use shorter decimals or smaller fractions)"}
$ python3 checker.py probe/x7_nan.json
{"valid": false, "score": null, "reason": "not accepted: constant NaN is not allowed"}
$ python3 checker.py probe/x8_infinity_string.json
{"valid": false, "score": null, "reason": "pair 0 u: cannot read 'inf' as an exact rational"}
$ python3 checker.py probe/alphaevolve_m15.json
{"valid": true, "score": 1.11904756846927744, "reason": "m = 15 pairs (2 scaled so that u+v = 1); k = 1..m; exact minimum over all 2^15 sign choices: alpha = 874255912866623/781250000000000 = 1.11904756846927744 exactly; so beta >= 874255912866623/781250000000000"}
$ python3 checker.py probe/c_padded_both_ends.json
{"valid": true, "score": 1.125, "reason": "m = 16 pairs (0 scaled so that u+v = 1); k = 1..m; exact minimum over all 2^16 sign choices: alpha = 9/8 = 1.125 exactly; so beta >= 9/8"}
$ python3 checker.py probe/c_padded_end_only.json
{"valid": true, "score": 1.125, "reason": "m = 15 pairs (0 scaled so that u+v = 1); k = 1..m; exact minimum over all 2^15 sign choices: alpha = 9/8 = 1.125 exactly; so beta >= 9/8"}
$ python3 checker.py probe/c_turned6.json
{"valid": true, "score": 1.125, "reason": "m = 14 pairs (0 scaled so that u+v = 1); k = 1..m; exact minimum over all 2^14 sign choices: alpha = 9/8 = 1.125 exactly; so beta >= 9/8"}
$ python3 checker.py probe/c_turned6_padded_both_ends.json
{"valid": true, "score": 1.125, "reason": "m = 16 pairs (0 scaled so that u+v = 1); k = 1..m; exact minimum over all 2^16 sign choices: alpha = 9/8 = 1.125 exactly; so beta >= 9/8"}
$ python3 checker.py probe/c_turned6_padded_end_only.json
{"valid": true, "score": 1.125, "reason": "m = 15 pairs (0 scaled so that u+v = 1); k = 1..m; exact minimum over all 2^15 sign choices: alpha = 9/8 = 1.125 exactly; so beta >= 9/8"}
```

## Numbers of the wrong type are rejected (added in the kit, 20 Nov 2026)

These were refused already; the files make sure they stay refused. Each file is best_known.json with the one change named, run as the lint runs it:

```
v9_u_is_true                         exit=0 0.068s  {"valid": false, "score": null, "reason": "pair 0 u: booleans are not numbers"}
v10_v_is_false                       exit=0 0.065s  {"valid": false, "score": null, "reason": "pair 0 v: booleans are not numbers"}
```
