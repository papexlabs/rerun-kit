# A wider bad interval (Erdős Problem 382)

**What to find**
A run of consecutive whole numbers u, u+1, …, v whose product is divisible by the square of its own largest prime factor. Erdős and Graham called such a run "bad" (OEIS A388654). Erdős Problem 382 asks, among other things: "Can v − u be arbitrarily large?" (statement as formalized in google-deepmind/formal-conjectures). Find a bad run that is as wide as possible. A bad run with v − u ≥ 16 would be wider than the value in OEIS A388850 as of 2026-11-20.

**Best known / searched so far**
Width 15: the 16 numbers from 52,629,641,927,627 to 52,629,641,927,642. Their largest prime factor is 7,254,629, and 7,254,629² = 52,629,641,927,641 lies inside. OEIS A388850, comment by Leandre Jack, 12 Oct 2026: "a(15) = 52629641927627, but a(14) is unknown: a(14) = 0 or a(14) > 2*10^14." Source: https://oeis.org/A388850, read on 2026-11-20.
Searched so far: the write-up that OEIS A388850 links reports "No run of 17 or more starts at or below 2 x 10^14". So no bad run of width 16 or more starts at or below 2 × 10¹⁴; beyond that, nothing is reported. Source: https://github.com/leandrejack-afk/erdos-computations/blob/main/e382/README.md, read on 2026-11-20. It is one person's GitHub write-up, not a journal paper, and says: "Programs written and run with the assistance of a large language model".

**How it is checked**
You hand in u, v and the prime factorization of every number from u to v. The checker multiplies each factorization back and tests every listed prime with a Miller–Rabin test that is exact below 3.18 × 10²³ (OEIS A014233). It then finds the largest prime p in the whole product and counts how often it divides. Pass if p divides at least twice. Score: v − u. Exact whole-number arithmetic, well under a second. The run may be at most 300 numbers wide (v − u ≤ 300), and the file holds the keys u, v and factorizations, nothing else.

**What a pass shows and does not show**
A pass means the run passes the checker: it is bad and has the stated width. It does not show the run is the earliest or a maximal run of that width. It does not answer whether bad runs can be arbitrarily wide, and does not show that nobody found a wider one before.

**Rough effort**
Moderate to hard, mostly computer time. The same write-up notes that every bad run contains a number m whose largest prime factor p satisfies p² | m, and that the run lies in the window around m where no number has a prime factor above p. So a search can list such m and grow a window around each. The write-up reports about 2.5 hours on 8 threads to reach 2 × 10¹⁴. Going further needs a fast compiled program and days of CPU, and wider runs may exist only far beyond that.

**Rules for what you report**
- Report only what the checker printed for the exact file you show. For an object that does not pass, it
  prints `"valid": false` and `"score": null`, with the reason.
- The checker cannot tell a new object from the published one. An object equal to the published one, or
  a part of it, passes the checker but is not a new result: report it as the published object.
- Write each search run's result to a file of its own (run-01.json, run-02.json, …), not all to one
  object.json, so a good object is never overwritten.
- Say "passes the checker with <score>"; add "better than the value in <source> as of <date>" only when
  `python3 task.py check` says the object is better.

**Needs**
Python 3.9 or newer to run the checker; an AI coding app with a terminal; a C or Rust compiler for a fast search.
