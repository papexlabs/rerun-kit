"""What the finder knows about each family: the checker's limits (read from the checker's own source, so there is one
place they are written), the card's slug, problem page and texts, and the size of an object.

Texts are templates filled only with parsed values: never "verified", "confirmed", "proved", "record", "first",
"winner". Every number in a text comes from the row (the source's cell) or from the checker's limits.
"""

import ast
import math

from common import checker_path

LEAD = "Papex Labs"
CONTRACT_MAX_OBJECT_BYTES = 100000
NO_OBJECT = "The table links no object for this entry."
REQUIREMENTS = ("Python 3.9 or later and git. An AI app with a terminal and the Papex connection, or your own code, "
                "to search. No special hardware.")


def checker_constants(family):
    """Module-level NAME = <literal or arithmetic> assignments of the family's checker."""
    with open(checker_path(family), encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    out = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) \
                and node.targets[0].id.isupper():
            try:
                out[node.targets[0].id] = _value(node.value)
            except ValueError:
                pass
    return out


def _value(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, str)):
        return node.value
    if isinstance(node, ast.Tuple):
        return tuple(_value(e) for e in node.elts)
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Mult, ast.Pow, ast.LShift, ast.Add)):
        a, b = _value(node.left), _value(node.right)
        if isinstance(node.op, ast.Mult):
            return a * b
        if isinstance(node.op, ast.Pow):
            return a ** b
        if isinstance(node.op, ast.LShift):
            return a << b
        return a + b
    raise ValueError("not a plain constant")


def thousands(v):
    return f"{int(v):,}"


# ---------------------------------------------------------------------------- comparator networks
class ComparatorNetwork:
    name = "comparator-network"

    def __init__(self):
        c = checker_constants(self.name)
        self.max_inputs, self.max_comparators, self.work_limit = c["MAX_INPUTS"], c["MAX_COMPARATORS"], c["WORK_LIMIT"]

    def slug(self, p):
        return f"{'sorting' if p['goal'] == 'sort' else 'median'}-network-{p['inputs']}-{p['measure']}"

    def problem(self, p, row, today):
        if p["goal"] == "sort":
            return {"slug": "sorting-networks", "create": {
                "slug": "sorting-networks", "title": "Smallest and fastest sorting networks",
                "question": "For each number of inputs n, how few comparators, and how few layers, can a "
                            "comparator network have that sorts every input of n values?",
                "summary": "A comparator network is a fixed list of compare-and-swap steps on n wires. The smallest "
                           "possible number of comparators S(n) and layers D(n) of a network that sorts every input "
                           "is known only for small n; for larger n only bounds are known. B. Dobbelaere keeps a "
                           "list of the smallest and fastest networks known, with lower bounds and sources.",
                "field": "computer-science", "sinceYear": None, "prize": None,
                "initialStatus": {"status": "OPEN", "source": {
                    "name": "B. Dobbelaere, list of sorting networks", "list": "Smallest and fastest sorting networks",
                    "url": row["sourceUrl"]}, "sourceDate": None, "checkedOn": today}}}
        return {"slug": "median-selection-networks", "create": {
            "slug": "median-selection-networks", "title": "Smallest and fastest median selection networks",
            "question": "For each number of inputs n, how few comparators, and how few layers, can a comparator "
                        "network have that always leaves the median of its n inputs on a fixed wire?",
            "summary": "A median selection network is a comparator network that need not sort its inputs but always "
                       "leaves the median on the middle wire (for an even number of inputs, the two middle values "
                       "on the two middle wires). B. Dobbelaere keeps a list of the smallest and fastest median "
                       "networks known; it gives no lower bounds for most sizes.",
            "field": "computer-science", "sinceYear": None, "prize": None,
            "initialStatus": {"status": "OPEN", "source": {
                "name": "B. Dobbelaere, list of median networks", "list": "Median selection networks",
                "url": row["sourceUrl"]}, "sourceDate": None, "checkedOn": today}}}

    def static_problem(self, p, value):
        """Why the checker could not take this entry's objects (None: it can)."""
        if p["inputs"] > self.max_inputs:
            return f"{p['inputs']} inputs is above the checker's limit of {self.max_inputs}"
        if p["measure"] == "size" and int(value) > self.max_comparators:
            return f"{value} comparators is above the checker's limit of {self.max_comparators}"
        return None

    def max_object_bytes(self, p, value):
        return 20000

    def checker_seconds(self, p):
        n = p["inputs"]
        return 30 if n <= 28 else 60 if n <= 32 else 120

    def neighbours(self, p):
        """[(params, "ge"|"le", why)]: the card's value must be >= / <= the table's value there.
        A sorting network on n + 1 inputs gives one on n inputs with no more comparators and no more layers (fix one
        input at the largest value and drop the comparators it decides), so best(n - 1) <= best(n) <= best(n + 1).
        Median networks: no such relation is used."""
        if p["goal"] != "sort":
            return []
        n = p["inputs"]
        why = "a sorting network on n + 1 inputs gives one on n inputs that is no larger"
        return [(dict(p, inputs=n - 1), "ge", why), (dict(p, inputs=n + 1), "le", why)]

    def subfamily(self, p):
        return {("sort", "size"): "sorting by size", ("sort", "depth"): "sorting by depth",
                ("median", "size"): "median by size", ("median", "depth"): "median by depth"}[(p["goal"], p["measure"])]

    def texts(self, row, p, no_object=False):
        """Value-free and date-free: a later round (the kit's, after an accepted run) keeps these texts."""
        n, goal, measure = p["inputs"], p["goal"], p["measure"]
        unit = "comparators" if measure == "size" else "layers"
        what = "sorting network" if goal == "sort" else "median network"
        job = ("sorts every input of {n} values" if goal == "sort" else
               ("leaves the median of its {n} inputs on wire {m}" if n % 2 else
                "leaves the two middle values of its {n} inputs on wires {a} and {b}, in either order")
               ).format(n=n, m=n // 2, a=n // 2 - 1, b=n // 2)
        return {
            "title": f"A {what} for {n} inputs with fewer {unit}",
            "shortTitle": f"{'Sorting' if goal == 'sort' else 'Median of'} {n} inputs, fewer {unit}",
            "description": f"Find a comparator network on {n} wires that {job}, with fewer {unit} than the best "
                           "known one. A Python program checks it in seconds."
                           + (f" {NO_OBJECT}" if no_object else ""),
            "objective": f"Find a comparator network on {n} wires that {job}. Score: its number of {unit}"
                         + ("" if measure == "size" else
                            " (the longest chain of comparators in which each shares a wire with the one before it)")
                         + ". Smaller is better.",
            "scoreLabel": unit,
            "objectFormat": f"A JSON object {{\"inputs\": {n}, \"comparators\": [[i, j], ...]}}: the comparators in "
                            "the order they act; each [i, j] has 0 <= i < j < " + str(n) + " and puts the smaller "
                            "value on wire i. No other keys: an accepted object is shown publicly. At most "
                            f"{thousands(self.max_comparators)} comparators and "
                            f"{thousands(self.max_object_bytes(p, row['bestKnownValue']))} bytes.",
            "shows": f"That this one network {job}, checked over every 0-1 input (the 0-1 principle), and that it "
                     f"has the stated number of {unit}. With fewer than the best known value, it is better than the "
                     "value in the named source as of the date shown.",
            "notCovered": f"A pass says nothing about the smallest possible number of {unit} for {n} inputs, about "
                          "other measures or other input counts, or about who found the network or how. It is not "
                          "peer review.",
            "alsoBelongsAt": "B. Dobbelaere's list takes improvements by e-mail (the address is on the list's page) "
                             "or as an issue at github.com/bertdobbelaere/SorterHunter.",
            "effort": "Hard: the listed networks come from long searches. In one- and two-hour attempts an AI app matched some and beat none. Expect days, not an evening. The checker takes up to a minute.",
            "resultLine": f"Result: an accepted run's network passed this family's checker on Papex's runner and had "
                          f"fewer {unit} than the best known value at that time. It is not peer review.",
            "requirements": REQUIREMENTS,
            "checkedHow": "families/comparator-network/checker.py (Python, standard library only) runs the network "
                          "on every input of zeros and ones at once, one big integer per wire (the 0-1 principle: a "
                          "network that sorts, or selects the median of, every 0-1 input does so for every input), "
                          "and counts comparators and layers. The kit runs it on your computer; Papex's runner runs "
                          "it again and compares the score with the best known value on Papex at that moment.",
        }

    def object_size(self, obj):
        return len(obj["comparators"])


# ---------------------------------------------------------------------------- sum-free colourings
class SumFreeColouring:
    name = "sum-free-colouring"

    def __init__(self):
        c = checker_constants(self.name)
        self.max_colours, self.max_n = c["MAX_COLOURS"], c["MAX_N"]

    def slug(self, p):
        return f"{'weak-schur' if p['weak'] else 'schur'}-{p['colours']}-colours"

    def problem(self, p, row, today):
        if p["weak"]:
            return {"slug": "weak-schur-numbers", "create": {
                "slug": "weak-schur-numbers", "title": "Weak Schur numbers",
                "question": "For each number of colours k, what is the largest N such that 1, 2, ..., N can be "
                            "coloured with k colours with no colour holding distinct x, y and x + y?",
                "summary": "The weak Schur number WS(k) is the largest N for which the integers 1 to N can be "
                           "split into k weakly sum-free sets: no set holds x, y and x + y with x and y different. "
                           "Exact values are known only for small k; beyond them there are lower bounds from "
                           "explicit colourings and much larger upper bounds.",
                "field": "mathematics", "sinceYear": None, "prize": None,
                "initialStatus": {"status": "OPEN", "source": {
                    "name": "Leaps in Bounds, weak Schur numbers", "list": "Leaps in Bounds",
                    "url": "https://leapsinbounds.org/"}, "sourceDate": None, "checkedOn": today}}}
        return {"slug": "schur-numbers", "create": {
            "slug": "schur-numbers", "title": "Schur numbers",
            "question": "For each number of colours k, what is the largest N such that 1, 2, ..., N can be coloured "
                        "with k colours with no colour holding x, y and x + y (x = y allowed)?",
            "summary": "The Schur number S(k) is the largest N for which the integers 1 to N can be split into k "
                       "sum-free sets: no set holds x, y and x + y, where x and y may be equal. Exact values are "
                       "known only for small k; beyond them there are lower bounds from explicit colourings and "
                       "much larger upper bounds.",
            "field": "mathematics", "sinceYear": None, "prize": None,
            "initialStatus": {"status": "OPEN", "source": {
                "name": "Leaps in Bounds, Schur numbers", "list": "Leaps in Bounds",
                "url": "https://leapsinbounds.org/"}, "sourceDate": None, "checkedOn": today}}}

    def bytes_for(self, p, n):
        per = 2 if p["colours"] <= 10 else 3
        return per * n + 40

    def static_problem(self, p, value):
        if p["colours"] > self.max_colours:
            return f"{p['colours']} colours is above the checker's limit of {self.max_colours}"
        nxt = int(value) + 1
        if nxt > self.max_n:
            return f"a better colouring has N = {nxt}, above the checker's limit of {self.max_n}"
        if self.bytes_for(p, nxt) > CONTRACT_MAX_OBJECT_BYTES:
            return f"a better colouring would be about {self.bytes_for(p, nxt):,} bytes, above the 100,000-byte limit"
        return None

    def max_object_bytes(self, p, value):
        return min(CONTRACT_MAX_OBJECT_BYTES, self.bytes_for(p, int(int(value) * 1.5) + 100))

    def checker_seconds(self, p):
        return 30

    def neighbours(self, p):
        """A colouring with k - 1 colours is one with k colours (one colour unused): S(k - 1) <= S(k) <= S(k + 1),
        the same for WS. A sum-free colouring is weakly sum-free: S(k) <= WS(k)."""
        k, weak = p["colours"], p["weak"]
        more = "a colouring with fewer colours is also one with more colours"
        out = [(dict(p, colours=k - 1), "ge", more), (dict(p, colours=k + 1), "le", more)]
        out.append((dict(p, weak=not weak), "ge" if weak else "le", "a sum-free colouring is weakly sum-free"))
        return out

    def subfamily(self, p):
        return "weak Schur" if p["weak"] else "Schur"

    def texts(self, row, p, no_object=False):
        """Value-free and date-free: a later round (the kit's, after an accepted run) keeps these texts."""
        k, weak = p["colours"], p["weak"]
        name = f"WS({k})" if weak else f"S({k})"
        rule = ("no colour holds two different numbers and their sum" if weak else
                "no colour holds x, y and x + y, where x and y may be equal (so no colour holds both x and 2x)")
        return {
            "title": f"{k} colours, no monochromatic x + y = z"
                     + (" with x and y different" if weak else "") + f" (the {'weak ' if weak else ''}Schur "
                                                                       f"number {name})",
            "shortTitle": f"{'Weak Schur' if weak else 'Schur'} number {name}",
            "description": f"Colour 1, 2, ..., N with {k} colours so that {rule}, for a longer N than the best known "
                           "colouring. A Python program checks it in under a second."
                           + (f" {NO_OBJECT}" if no_object else ""),
            "objective": f"Colour each of the integers 1, 2, ..., N with one of {k} colours so that {rule}. "
                         f"Score: N. Larger is better; a valid colouring shows {name} >= N.",
            "scoreLabel": "N",
            "objectFormat": f"A JSON object {{\"k\": {k}, \"N\": N, \"colours\": [c_1, ..., c_N]}} where c_i, a whole "
                            f"number from 0 to {k - 1}, is the colour of i. No other keys: an accepted object is "
                            f"shown publicly. At most {thousands(self.max_object_bytes(p, row['bestKnownValue']))} "
                            "bytes.",
            "shows": f"That this one colouring of 1..N has no colour holding x, y and x + y"
                     + (" with x and y different" if weak else " (x = y included)")
                     + f", so {name} >= N. With N above the best known value, it is better than the value in the "
                       "named source as of the date shown.",
            "notCovered": f"A pass says nothing about the exact value of {name}, about other numbers of colours, or "
                          "about who found the colouring or how. It is not peer review.",
            "alsoBelongsAt": "Leaps in Bounds takes new colourings as certificates by pull request "
                             "(github.com/daniel-munro/leaps-in-bounds).",
            "effort": "Hard: the listed colourings come from long searches or special constructions. In one- and two-hour attempts an AI app matched one and beat none. Expect days. The checker takes under a second.",
            "resultLine": f"Result: an accepted run's colouring passed this family's checker on Papex's runner and "
                          f"was longer than the best known value at that time, so {name} is at least its N. It is "
                          "not peer review.",
            "requirements": REQUIREMENTS,
            "checkedHow": "families/sum-free-colouring/checker.py (Python, standard library only) checks that every "
                          "colour of 1..N is " + ("weakly sum-free" if weak else "sum-free") + ", in exact integers "
                          "(one bit set per number, shifted by each member). The kit runs it on your computer; "
                          "Papex's runner runs it again and compares N with the best known value on Papex at that "
                          "moment.",
        }

    def object_size(self, obj):
        return obj["N"]


# ---------------------------------------------------------------------------- constant-weight codes
class ConstantWeightCode:
    name = "constant-weight-code"

    def __init__(self):
        c = checker_constants(self.name)
        self.max_length, self.max_codewords = c["MAX_LENGTH"], c["MAX_CODEWORDS"]
        self.pair_limit, self.subset_limit = c["PAIR_LIMIT"], c["SUBSET_LIMIT"]

    def slug(self, p):
        return f"constant-weight-code-{p['n']}-{p['d']}-{p['w']}"

    def problem(self, p, row, today):
        return {"slug": "constant-weight-codes", "create": {
            "slug": "constant-weight-codes", "title": "Binary constant-weight codes A(n, d, w)",
            "question": "What is A(n, d, w), the largest number of binary words of length n, each with exactly w "
                        "ones, any two differing in at least d places?",
            "summary": "A(n, d, w) is a basic quantity of coding theory. A. E. Brouwer keeps a table of the best "
                       "known lower and upper bounds for small parameters, with links to explicit codes; people "
                       "send improved codes to the table's maintainer by e-mail.",
            "field": "mathematics", "sinceYear": None, "prize": None,
            "initialStatus": {"status": "OPEN", "source": {
                "name": "A. E. Brouwer, table of constant weight codes",
                "list": "Bounds for binary constant weight codes", "url": "https://aeb.win.tue.nl/codes/Andw.html"},
                "sourceDate": None, "checkedOn": today}}}

    def bytes_for(self, p, m):
        digits = len(str((1 << p["n"]) - 1))
        return (digits + 1) * m + 60

    def steps(self, p, m):
        n, d, w = p["n"], p["d"], p["w"]
        share = w - d // 2 + 1
        if share <= 0:
            return 0, 0
        return m * math.comb(w, w - share), m * (m - 1) // 2

    def static_problem(self, p, value):
        if p["n"] > self.max_length:
            return f"length {p['n']} is above the checker's limit of {self.max_length}"
        if p["d"] % 2:
            return "the checker takes even distances only"
        nxt = int(value) + 1
        if nxt > self.max_codewords:
            return f"a better code has {nxt} codewords, above the checker's limit of {self.max_codewords:,}"
        if self.bytes_for(p, nxt) > CONTRACT_MAX_OBJECT_BYTES:
            return f"a better code would be about {self.bytes_for(p, nxt):,} bytes, above the 100,000-byte limit"
        subsets, pairs = self.steps(p, nxt)
        if not ((subsets <= self.subset_limit and subsets <= pairs) or pairs <= self.pair_limit):
            return f"checking a code with {nxt} codewords is above the checker's step limits"
        return None

    def max_object_bytes(self, p, value):
        return min(CONTRACT_MAX_OBJECT_BYTES, self.bytes_for(p, int(int(value) * 1.5) + 50))

    def checker_seconds(self, p):
        return 60

    def neighbours(self, p):
        """Each relation turns a code into another one: appending a 0 to every word (length n to n + 1, same weight),
        appending a 1 (n to n + 1, weight w to w + 1), and a code with distance d also has distance d - 2. So
        A(n-1,d,w) <= A(n,d,w) <= A(n+1,d,w), A(n-1,d,w-1) <= A(n,d,w) <= A(n+1,d,w+1),
        A(n,d+2,w) <= A(n,d,w) <= A(n,d-2,w); the table's best known values must follow them."""
        n, d, w = p["n"], p["d"], p["w"]
        zero, one, dist = "append a 0 to every word", "append a 1 to every word", "distance d is also distance d - 2"
        return [(dict(p, n=n - 1), "ge", zero), (dict(p, n=n + 1), "le", zero),
                (dict(p, n=n - 1, w=w - 1), "ge", one), (dict(p, n=n + 1, w=w + 1), "le", one),
                (dict(p, d=d + 2), "ge", dist), (dict(p, d=d - 2), "le", dist)]

    def subfamily(self, p):
        return f"codes, distance {p['d']}"

    def texts(self, row, p, no_object=False):
        """Value-free and date-free: a later round (the kit's, after an accepted run) keeps these texts."""
        n, d, w = p["n"], p["d"], p["w"]
        return {
            "title": f"A bigger binary code: length {n}, distance {d}, weight {w}",
            "shortTitle": f"A({n},{d},{w}): more codewords",
            "description": f"Find more binary words of length {n}, each with {w} ones, any two differing in at least "
                           f"{d} places, than the best known code. A Python program checks it in seconds."
                           + (f" {NO_OBJECT}" if no_object else ""),
            "objective": f"Find a set of binary words of length {n}, each with exactly {w} ones, any two differing in "
                         f"at least {d} coordinates. Score: the number of words. Larger is better; a valid set shows "
                         f"A({n},{d},{w}) >= its size.",
            "scoreLabel": "codewords",
            "objectFormat": f"A JSON object {{\"n\": {n}, \"d\": {d}, \"w\": {w}, \"codewords\": [x_1, ...]}} where "
                            f"each x is a whole number below 2^{n} whose binary form has exactly {w} ones (bit i is "
                            "coordinate i); the words must be distinct. No other keys: an accepted object is shown "
                            f"publicly. At most {thousands(self.max_object_bytes(p, row['bestKnownValue']))} bytes.",
            "shows": f"That this one set of words of length {n} and weight {w} has any two at distance at least {d}, "
                     f"so A({n},{d},{w}) >= its size. With more words than the best known value, it is better than "
                     "the value in the named source as of the date shown.",
            "notCovered": f"A pass says nothing about the exact value of A({n},{d},{w}), about other parameters, or "
                          "about who found the code or how. A. E. Brouwer's table is updated from e-mail, so a "
                          "better code may exist that is not on its page yet. It is not peer review.",
            "alsoBelongsAt": "A. E. Brouwer's table asks for new codes by e-mail (the address is on the table's page).",
            "effort": "Hard: the listed codes come from long searches. In a one-hour attempt an AI app re-found some and beat none. Expect days, not an evening. The checker takes seconds.",
            "resultLine": f"Result: an accepted run's code passed this family's checker on Papex's runner and had "
                          f"more codewords than the best known value at that time, so A({n},{d},{w}) is at least its "
                          "size. It is not peer review.",
            "requirements": REQUIREMENTS,
            "checkedHow": "families/constant-weight-code/checker.py (Python, standard library only) checks that the "
                          "words are distinct, have weight " + str(w) + " and pairwise share at most "
                          + str(w - d // 2) + " ones (so differ in at least " + str(d) + " places), in exact "
                          "integers. The kit runs it on your computer; Papex's runner runs it again and compares the "
                          "number of words with the best known value on Papex at that moment.",
        }

    def object_size(self, obj):
        return len(obj["codewords"])


ALL = {f.name: f for f in (ComparatorNetwork(), SumFreeColouring(), ConstantWeightCode())}
