# Family: comparator-network

Sorting networks and median selection networks. One checker, many cards; a card is data only:
`{"inputs": n, "goal": "sort" | "median", "measure": "size" | "depth"}`. The score is smaller-is-better.

## The object

```json
{"inputs": 4, "comparators": [[0, 1], [2, 3], [0, 2], [1, 3], [1, 2]]}
```

- `inputs`: the whole number n of the card's params.
- `comparators`: the comparators in the order they act. Each `[i, j]` has `0 <= i < j < n`; it puts the smaller of
  the two values on wire `i` and the larger on wire `j`. At most 1,000 comparators.
- No other key and no other kind of value: whole numbers only (`4.0`, `"4"` or `true` are refused). An accepted
  object is shown publicly.

## What it checks

- goal `sort`: every input leaves wires `0..n-1` in increasing order.
- goal `median`: for odd n, wire `(n-1)/2` holds the median of the inputs; for even n, wires `n/2-1` and `n/2` hold
  the two middle values, in either order. This is what B. Dobbelaere's median page means ("For an even number of
  inputs, the average of the two outputs still needs to be computed by the application. Note that in this case, the
  two outputs are usually not ordered."). Every median network in his repository with up to 36 inputs passes this
  definition with the size and depth its file name gives (checked on 20 Nov 2026).
- How: the 0-1 principle (a comparator network sorts, or selects, every input exactly when it does so for every input
  of zeros and ones; it holds for selection because comparators commute with every monotone map). All 0-1 inputs run
  at once, one Python integer per wire, one bit per input. The comparators that are the earliest on both of their
  wires form an opening layer; its outputs are exactly the vectors in which each of its pairs reads 00, 01 or 11, so only
  `3^m * 2^(n-2m)` vectors are run through the rest. For the median, the number of ones of each input is kept in
  bit-sliced counters and compared with the wire(s) exactly.
- When it fails, the reason names one 0-1 input (wire 0 on the left) on which the network goes wrong.

## The score

`size` = the number of comparators. `depth` = the number of layers: the longest chain of comparators in which each
shares a wire with the one before it (the usual "as soon as possible" layering).

## What a pass shows, and what it does not

A pass shows that this one network sorts (or selects the median of) every input of n values, and has the stated
number of comparators and layers. With a score below the card's best known value, it is better than the value in
the named source as of the date shown. It says nothing about the least possible size or depth, nothing about other
input counts, and not who found the network or how. It is not peer review.

## Limits, measured

The checker refuses, with a reason and without running, anything above:

| limit | value |
|---|---|
| inputs | 2 to 32 |
| comparators | 1,000 |
| work = (0-1 vectors to run) x (comparators after the opening layer) | 2 x 10^10 |
| object file | 200,000 bytes |

Measured on 20 Nov 2026 (Apple M5; the machine was heavily loaded, load average about 30 on 10 cores, so wall time
is about twice CPU time). Batcher's networks, laid out in layers, goal sort:

| n | work | CPU | wall | peak memory |
|---|---|---|---|---|
| 24 | 3^12 x 115 = 6.1e7 | 0.03 s | 0.05 s | 35 MB |
| 28 | 3^14 x 147 = 7.0e8 | 0.10 s | 0.12 s | 66 MB |
| 32 | 3^16 x 175 = 7.5e9 | 0.42 s | 0.5 to 0.8 s | 45 to 53 MB |
| 34 | 3^17 x 202 = 2.6e10 | 1.8 s | 2.1 to 4.5 s | 45 to 56 MB |
| 36 | 3^18 x 223 = 8.6e10 | 7.4 s | 10 to 18 s | 45 to 56 MB |

The limit is set at n = 32 and 2 x 10^10 work, about 1.5 s of CPU here, so that a small shared server several times
slower still finishes well inside the card's `checkerSeconds` (60 s for n = 29 to 32, 30 s below) and far inside
400 MB. n = 33 to 36 would fit in about 60 s only on a server at most 4 to 8 times slower than this machine; that was
not measured, so they are not offered. A network that does not open with a full layer needs up to
`2^n` vectors and is refused above the work limit (the reason says to start with a full layer).

## Probes

`probe/cases.json` lists each probe: an object file, a params file and the checker's expected line. Good objects:
sorting networks on 4, 8, 24 and 32 inputs (Batcher's, generated here) and median networks for 4, 5, 6 and 9 inputs
from B. Dobbelaere's SorterHunter repository (MIT License, Copyright (c) 2017 bertdobbelaere). Broken ones: wrong
size, a missing comparator, a median network used as a sorter, an extra key, wrong types, out-of-range wires, a
reversed pair, broken params.
