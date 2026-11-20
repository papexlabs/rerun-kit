# Family: constant-weight-code

Binary constant-weight codes, A(n, d, w). One checker, many cards; a card is data only: `{"n": n, "d": d, "w": w}`
with d even. The score is the number of codewords, larger is better.

## The object

```json
{"n": 7, "d": 4, "w": 3, "codewords": [11, 22, 44, 49, 69, 88, 98]}
```

(the seven lines of the Fano plane: words of length 7 and weight 3, any two at distance 4)

- `n`, `d`, `w`: the whole numbers of the card's params.
- `codewords`: whole numbers x with `0 <= x < 2^n` whose binary form has exactly w ones; bit i (value 2^i) is
  coordinate i. Distinct. At most 20,000.
- No other key and no other kind of value (`11.0`, `"0001011"` or `true` are refused). An accepted object is shown
  publicly. Numbers stay below 2^32, so they are exact in every JSON reader.

## What it checks

The words are distinct, each has weight w, and any two differ in at least d coordinates. Two words of weight w that
share s ones differ in 2(w - s) coordinates, so they are too close exactly when they share w - d/2 + 1 ones or more.
The checker uses whichever way takes fewer steps: compare every pair (the shared ones counted exactly), or list, for
every word, each set of w - d/2 + 1 of its ones, sort the list and look for a set held twice. A failure names two
codewords that are too close.

## What a pass shows, and what it does not

A pass shows that this one set of words has the stated size, length n, weight w and minimum distance at least d, so
A(n, d, w) >= its size. With more words than the card's best known value, it is better than the value in the named
source as of the date shown. It says nothing about the exact value of A(n, d, w) or other parameters, nor who found
the code. Brouwer's table is updated from e-mail, so a better code may exist that is not on the page yet. It is not
peer review.

## Limits, measured

| limit | value |
|---|---|
| length n | 1 to 32 (codewords below 2^32) |
| distance d | even, 2 to 2n |
| codewords | 20,000 |
| pairs compared (when that way is used) | 4 x 10^7 |
| sets listed and sorted (held in memory) | 5 x 10^6 |
| object file | 400,000 bytes (a card takes at most 100,000) |

Measured on 20 Nov 2026 (Apple M5, heavily loaded): at the pair limit (8,944 words of weight 16 in length 32),
5.0 s CPU (5.4 to 7.6 s wall), 18 MB; Python 3.9.6: 7.6 s CPU. At the set limit (4,385 words, d = 8, w = 20,
1,140 sets each), 1.5 s CPU, 236 MB; Python 3.9.6: 1.7 s, 235 MB. An earlier version kept the sets in a Python set: at
4 x 10^7 sets it used 5.4 GB, so the sets are now listed and sorted, and the limit is 5 x 10^6 (under 400 MB).
The finder offers a card only when a code with one more word still fits these limits. The real codes on Brouwer's
table that have cards are far below them (seconds at most).

## Licence of the source's codes

Brouwer's page states no licence, so the finder reads its codes to check them, links them (`bestKnown.objectUrl`) and
keeps only their sha256; it does not copy them.

## Probes

Good objects (all built here, none copied): the 759 octads of the extended Golay code (A(24,8,8) >= 759), the 13
lines of the projective plane of order 3 (A(13,6,4) >= 13), the 7 lines of the Fano plane (A(7,4,3) >= 7), and the
weight-6 words of length 20 whose positions sum to 0 mod 20 (distance 4). Broken ones: a repeated word, a word too
close, a word of the wrong weight, wrong n, a word too long or negative, an extra key, a missing key, wrong types,
broken params.
