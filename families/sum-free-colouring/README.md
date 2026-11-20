# Family: sum-free-colouring

Schur numbers S(k) and weak Schur numbers WS(k). One checker, many cards; a card is data only:
`{"colours": k, "weak": false | true}`. The score is N, larger is better.

## The object

```json
{"k": 3, "N": 13, "colours": [0, 1, 1, 0, 2, 2, 2, 2, 2, 0, 1, 1, 0]}
```

(the colours of 1, ..., 13: {1, 4, 10, 13}, {2, 3, 11, 12}, {5, 6, 7, 8, 9}; so S(3) >= 13)

- `k`: the whole number k of the card's params.
- `N`: a whole number from 1 to 50,000.
- `colours`: exactly N whole numbers from 0 to k - 1; the i-th is the colour of the integer i (i from 1).
- No other key and no other kind of value (`1.0`, `"1"` or `true` are refused). An accepted object is shown publicly.

## What it checks

- `weak: false` (Schur): no colour holds a, b and c with a + b = c, where a and b may be equal (so no colour holds
  both a and 2a). This is the convention of Leaps in Bounds ("with x = y allowed") and of OEIS A045652. A pass shows
  S(k) >= N.
- `weak: true` (weak Schur): the same, counting only a != b. Leaps in Bounds: "counting only solutions with x != y";
  OEIS A072842: "never have a+b=c for any distinct elements a, b, c in one subset". A pass shows WS(k) >= N.
- How: each colour is one Python integer with bit i set when i has that colour; for each member a, `(colour << a) &
  colour` is the set of members a + b with b in the same colour (for weak, the bit of 2a is cleared). Exact; the
  reason of a failure names the colour and the three numbers.

## What a pass shows, and what it does not

A pass shows that this one colouring of 1..N has no colour holding x, y and x + y (x = y included, or only x != y),
so S(k) >= N (or WS(k) >= N). With N above the card's best known value, it is better than the value in the named
source as of the date shown. It says nothing about the exact value, other numbers of colours, or who found it. It is
not peer review.

## Limits, measured

| limit | value |
|---|---|
| colours k | 1 to 16 |
| N | 1 to 50,000 |
| object file | 400,000 bytes (a card takes at most 100,000) |

Measured on 20 Nov 2026 (Apple M5, heavily loaded): a valid 11-colouring of 1..50,000 (no early exit, the worst
case) takes 0.18 s CPU (strong) and 0.33 s (weak), 19 MB; Python 3.9.6 gives the same line in 0.19 s. The object
size (about 2 bytes per number) is the real limit: a card's `maxObjectBytes` stays within the contract's 100,000.

## Probes

Good objects: the classic construction (1, 4, 13, 40, 121, ...) for S(3) >= 13, S(4) >= 40, S(5) >= 121; WS(2) >= 8
with {1, 2, 4, 8} and {3, 5, 6, 7} (which fails in the strong sense: 4 + 4 = 8); the S(6) >= 538 and WS(6) >= 650
witnesses from Leaps in Bounds (MIT License, Copyright (c) 2025 Daniel Munro; S(6): A. McKenna 2026, WS(6): S. E.
Rodrigo 2026). Broken ones: a monochromatic sum, N not matching the list, wrong k, colours out of range, N = 0,
N over the limit, an extra key, wrong types, broken params.
