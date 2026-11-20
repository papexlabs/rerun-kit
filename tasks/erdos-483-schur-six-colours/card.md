# Six sum-free colours for 1..N (Schur numbers, S(6))

**What to find**
Colour every whole number from 1 to N with one of six colours so that no colour holds numbers x, y and x + y. The two numbers x and y may be the same, so a colour may not hold both x and 2x. Make N as large as you can. The largest possible N is the sixth Schur number S(6); only S(1) to S(5) are known (1, 4, 13, 44, 160; OEIS A045652). The problem is also listed as no. 483 in the Erdős problem database. Any colouring with N = 539 or more would be better than the value in the source below as of 2026-11-20.

**Best known**
N = 538, by Adam McKenna (2026, preprint on Zenodo, CC BY 4.0): "We give an explicit partition of {1, ..., 538} into six sum-free sets. This shows S(6) ≥ 538 and improves the bound S(6) ≥ 537 of Chen, Zhu and Long." Source: https://doi.org/10.5281/zenodo.23937655 (version 1.2.0 of 12 Nov 2026), read on 2026-11-20.
Before it: 537 by Zhiyang Chen, Ligeng Zhu and Fan Long (arXiv:2610.31362, 22 Oct 2026, CC BY 4.0), and 536 by Fredricksen and Sweet (2000). OEIS A045652 (last revised 23 Oct 2026) still lists 537. Both 2026 results are preprints. In OEIS A030126's convention (the smallest N that forces x + y = z in one colour), 538 means f(6) ≥ 539.

**How it is checked**
You hand in one JSON file with k = 6, N and the list of N colours, and nothing else. The checker goes through each colour and looks for any x ≤ y in that colour with x + y also in that colour. Plain whole-number arithmetic, no rounding, well under a second.

**What a pass shows and does not show**
A pass means the colouring passes the checker: 1..N splits into six sets with no x + y = z inside a set, so S(6) is at least N. It does not give the exact value of S(6), does not touch the growth question of Erdős problem 483 (is f(k) < cᵏ for some constant c?), and does not show that nobody found the same colouring earlier.

**Rough effort**
Hard. Starting points: McKenna's two colourings of 1..538 (they differ in 37 places) and the 131 different colourings of 1..537 reported by Chen, Zhu and Long. 539 may not exist at all. Expect long computer searches (SAT solvers, or local search from the published colourings), not a quick idea.

**Rules for what you report**
- Report only what the checker printed for the exact file you show. For an object that does not pass, it
  prints `"valid": false` and `"score": null`, with the reason.
- The checker cannot tell a new object from the published one. An object equal to the published one, or
  a symmetry of it (the same colouring with its colours renamed), passes the checker but is not a new result: report it as the published object.
- Write each search run's result to a file of its own (run-01.json, run-02.json, …), not all to one
  object.json, so a good object is never overwritten.
- Say "passes the checker with <score>"; add "better than the value in <source> as of <date>" only when
  `python3 task.py check` says the object is better.

**Needs**
Python 3.9 or newer to run the checker; an AI coding app with a terminal; a C compiler or a SAT solver helps for the search.
