# Probe — erdos-382-wide-bad-interval (re-run 2026-11-20, after re-sourcing)

Script: the task preparer's own probe script (scratch; not part of the task).
It runs `python3 -I <this folder>/checker.py <file>` as a subprocess on each case. All factorizations
are made by the script's own code (trial division to 1000, deterministic Miller–Rabin with the first
13 prime bases, Pollard–Brent), which shares no code with the checker. Interpreter: Python 3.15.2.

## Source object
`best_known.json` is the run starting at a(15) = 52629641927627 of OEIS A388850 (CC BY-SA 4.0, read
from oeis/oeisdata), u = 52629641927627, v = u + 15, with factorizations of the 16 members. The
probe refactored all 16 members independently:
```
members whose factorization differs from our own: []
```

## (1) Published object gives exactly the published value (width 15)
```
best_known.json                        exit=0 0.031s  {"valid": true, "score": 15, "reason": "bad interval: largest prime 7254629 divides the product 2 times; v - u = 15"}
```
Consistency with the other published terms of A388850 (each run of n+1 integers starting at a(n)):
```
a(9)=4928180396                        exit=0 0.034s  {"valid": true, "score": 9, "reason": "bad interval: largest prime 70201 divides the product 2 times; v - u = 9"}
a(10)=40533366231                      exit=0 0.032s  {"valid": true, "score": 10, "reason": "bad interval: largest prime 201329 divides the product 2 times; v - u = 10"}
a(11)=111460496439                     exit=0 0.030s  {"valid": true, "score": 11, "reason": "bad interval: largest prime 333857 divides the product 2 times; v - u = 11"}
a(12)=436502026483                     exit=0 0.034s  {"valid": true, "score": 12, "reason": "bad interval: largest prime 660683 divides the product 2 times; v - u = 12"}
a(13)=17952448643078                   exit=0 0.032s  {"valid": true, "score": 13, "reason": "bad interval: largest prime 4237033 divides the product 2 times; v - u = 13"}
```
The largest primes 70201, 201329, 333857, 660683, 4237033 and 7254629 match the table in the
write-up that A388850 links (README at commit c643291).

## (2) Broken variants are rejected
```
v1_extend_right_to_v+1                 exit=0 0.030s  {"valid": false, "score": null, "reason": "not bad: largest prime 60962411 divides the product only once"}
v2_extend_left_to_u-1                  exit=0 0.031s  {"valid": false, "score": null, "reason": "not bad: largest prime 496506055921 divides the product only once"}
v3_wrong_exponent                      exit=0 0.030s  {"valid": false, "score": null, "reason": "factorization of 52629641927641: product is 7254629, not 52629641927641"}
v4_composite_listed_as_prime           exit=0 0.030s  {"valid": false, "score": null, "reason": "factorization of 52629641927641: 52629641927641 is not prime"}
v5_missing_member                      exit=0 0.030s  {"valid": false, "score": null, "reason": "factorizations must have exactly the keys u..v (missing ['52629641927630'], extra [])"}
v6_v_moved_without_factorization       exit=0 0.031s  {"valid": false, "score": null, "reason": "factorizations must have exactly the keys u..v (missing ['52629641927643'], extra [])"}
v7_width_15_at_10^15                   exit=0 0.030s  {"valid": false, "score": null, "reason": "not bad: largest prime 166666666666667 divides the product only once"}
v8_u_as_string                         exit=0 0.032s  {"valid": false, "score": null, "reason": "u and v must be integers"}
v9_beyond_proven_range                 exit=0 0.040s  {"valid": false, "score": null, "reason": "v must be below 3e23 (range where the primality test is proven)"}
v10_primes_not_increasing              exit=0 0.034s  {"valid": false, "score": null, "reason": "factorization of 52629641927627: primes must be strictly increasing"}
v11_not_json                           exit=0 0.030s  {"valid": false, "score": null, "reason": "cannot read object as JSON: JSONDecodeError"}
```
v1 and v2 (both with correct factorizations) also show the published run is maximal: each one-step
extension brings in a larger prime.

## (3) A sub-run is still bad (expected)
```
sub_[u,v-1]_width_14                   exit=0 0.030s  {"valid": true, "score": 14, "reason": "bad interval: largest prime 7254629 divides the product 2 times; v - u = 14"}
```
So the score rewards width only; maximality is not required for this task.

## Limits observed
The whole probe (19 checker runs plus factoring) took 0.65 s. The primality test uses the first 13
primes as Miller–Rabin bases and refuses v >= 3e23. That is below 318665857834031151167461, the
smallest odd composite that is a strong pseudoprime to the first 12 prime bases: OEIS A014233,
a(12), "from the Sorenson/Webster reference". This replaces the first probe's note that the bound
came "from the preparer's memory".

## Changed in the kit (20 Nov 2026)

An accepted object is shown publicly on Papex, so the checker now rejects an object with any key but u, v
and factorizations ("the object must hold exactly the keys u, v and factorizations"). The width allowed is
now v - u <= 300 (it was 1000), so that an object stays within the 100,000 bytes a result file may carry
for it: about 160 bytes per number at most near 3e23, so 301 numbers stay well under it. The best known
width is 15. Nothing else in the checker changed. `best_known.json` now holds the object only; where it
comes from is in task.json's sources ("Where best_known.json comes from").

The probe files in `probe/` were built in the kit from the descriptions above (v1 to v11, the sub-run of
width 14, and v12 with an extra key); the factorizations they need were computed again (Pollard-Brent,
deterministic Miller-Rabin) and the checker re-verifies them. Each gives exactly the line recorded above,
which `probe/cases.json` holds. Not rebuilt here: the runs at a(9) to a(13), whose factorizations this
folder does not hold.

## Numbers of the wrong type are rejected (added in the kit, 20 Nov 2026)

These were refused already; the files make sure they stay refused. Each file is best_known.json with the one change named, run as the lint runs it:

```
v13_u_as_a_float                     exit=0 0.061s  {"valid": false, "score": null, "reason": "u and v must be integers"}
v14_exponent_is_true                 exit=0 0.063s  {"valid": false, "score": null, "reason": "factorization of 52629641927627: each entry must be [p, e] with integers"}
v15_exponent_as_a_float              exit=0 0.060s  {"valid": false, "score": null, "reason": "factorization of 52629641927627: each entry must be [p, e] with integers"}
v16_prime_as_a_float                 exit=0 0.065s  {"valid": false, "score": null, "reason": "factorization of 52629641927627: each entry must be [p, e] with integers"}
```
