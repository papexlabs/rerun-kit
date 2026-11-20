"""Test helpers: an offline Fetcher whose cache holds saved or hand-written copies of the sources, small networks,
and the rows and published lists the planner tests use. No test sends a request."""

import itertools
import json
import os
import sys
import tempfile

TESTS = os.path.dirname(os.path.abspath(__file__))
FINDER = os.path.dirname(TESTS)
FIXTURES = os.path.join(TESTS, "fixtures")
sys.dont_write_bytecode = True
if FINDER not in sys.path:
    sys.path.insert(0, FINDER)

import fetch  # noqa: E402
from common import git_blob_sha1, make_row  # noqa: E402


def batcher(n):
    """Batcher's merge-exchange sorting network (Knuth 5.2.2 M), in layers."""
    out, t = [], (n - 1).bit_length()
    p = 1 << (t - 1)
    while p > 0:
        q, r, d = 1 << (t - 1), 0, p
        while d > 0:
            for i in range(n - d):
                if i & p == r:
                    out.append([i, i + d])
            d, q, r = q - p, q >> 1, p
        p >>= 1
    level, tagged = [0] * n, []
    for i, j in out:
        lv = max(level[i], level[j]) + 1
        level[i] = level[j] = lv
        tagged.append((lv, i, j))
    tagged.sort(key=lambda x: x[0])
    return [[i, j] for _, i, j in tagged]


def depth(net, n):
    level, best = [0] * n, 0
    for i, j in net:
        lv = max(level[i], level[j]) + 1
        level[i] = level[j] = lv
        best = max(best, lv)
    return best


def schur_colouring(k):
    col, m = [0], 1
    for c in range(1, k):
        col, m = col + [c] * (m + 1) + col, 3 * m + 1
    return col


def offline_fetcher(pages):
    """A Fetcher that only reads `pages` ({url: bytes or str}), stored in a fresh temporary cache."""
    cache = tempfile.mkdtemp(prefix="finder-test-")
    f = fetch.Fetcher(cache, offline=True)
    for url, body in pages.items():
        f._store(url, 200, body.encode("utf-8") if isinstance(body, str) else body, "text/plain")
    return f


# ---------------------------------------------------------------------------- B. Dobbelaere (hand-written copies)
NETS = {"Networks/Sorters/Sort_4_5_3.json": (4, [[0, 1], [2, 3], [0, 2], [1, 3], [1, 2]]),
        "Networks/Sorters/Sort_13_%d_%d.json": (13, batcher(13)),
        "Networks/Sorters/Sort_20_%d_%d.json": (20, batcher(20)),
        "Networks/Median/Median_11_%d_%d.json": (11, batcher(11)),
        "Networks/Median/Median_3_3_3.json": (3, [[0, 1], [1, 2], [0, 1]])}


def dobbelaere_pages():
    from adapters import dobbelaere as D
    files, blobs = {}, {}
    for name, (n, net) in NETS.items():
        path = name % (len(net), depth(net, n)) if "%d" in name else name
        body = json.dumps({"N": n, "L": len(net), "D": depth(net, n), "symmetric": False, "nw": net}).encode()
        files[path] = body
        blobs[path] = git_blob_sha1(body)
    s13, s20, m11 = batcher(13), batcher(20), batcher(11)
    sort_page = f"""<html><body><h3>Summary table</h3>
<table><tr><th>Number of inputs</th><th>(Size,Depth) combinations</th><th>Min. size bounds</th><th>Min. depth bounds</th><th>Comments</th></tr>
<tr><td class="idx">4</td><td class="idx"><a href="#N4L5D3">(5, 3)</a>&nbsp;</td><td class="idx"><b>5</b></td><td class="idx"><b>3</b></td><td class="idx">[<a href="#TAOCPv3">TAOCPv3</a>]</td></tr>
<tr><td class="idx">13</td><td class="idx"><a href="#x">({len(s13)}, {depth(s13, 13)})</a>&nbsp;</td><td class="idx">44&hellip;{len(s13)}</td><td class="idx"><b>{depth(s13, 13)}</b></td><td class="idx">Optimal depth proven in [<a href="#BZ14">BZ14</a>]</td></tr>
<tr><td class="idx">20</td><td class="idx"><a href="#x">({len(s20)}, {depth(s20, 20)})</a>&nbsp;</td><td class="idx">78&hellip;{len(s20)}</td><td class="idx">10&hellip;{depth(s20, 20)}</td><td class="idx">Size ubound: <a href="https://github.com/bertdobbelaere/SorterHunter">SorterHunter</a>, depth ubound: [<a href="#EM14">EM14</a>].</td></tr>
<tr><td class="idx">40</td><td class="idx"><a href="#x">(300, 20)</a>&nbsp;</td><td class="idx">200&hellip;300</td><td class="idx">10&hellip;20</td><td class="idx"></td></tr>
</table>
<h3>History</h3>
<table><tr><td>2026-10-29</td><td>Improved size for 20 inputs, contributed by someone.</td></tr>
<tr><td>2019-01-01</td><td>Minor improvements for 13 and 40 inputs.</td></tr></table></body></html>"""
    median_page = f"""<html><body><h3>Summary table</h3>
<table><tr><th>Number of inputs</th><th>(Size,Depth) combinations</th><th>Comments</th></tr>
<tr><td class="idx">3</td><td class="idx"><a href="#N3L3D3">(3, 3)</a>&nbsp;</td><td class="idx">For 3 inputs, the optimal median selection network is just the optimal sorting network.</td></tr>
<tr><td class="idx">11</td><td class="idx"><a href="#x">({len(m11)}, {depth(m11, 11)})</a>&nbsp;</td><td class="idx"></td></tr>
</table><h3>History</h3><table><tr><td>2026-11-08</td><td>Minor improvements for various sizes between 10 and 12.</td></tr></table></body></html>"""
    commit = {"sha": "c" * 40, "commit": {"tree": {"sha": "e" * 40}}}
    tree = {"sha": "e" * 40, "truncated": False,
            "tree": [{"path": p, "type": "blob", "sha": b} for p, b in blobs.items()]}
    pages = {D.PAGES["sort"]: sort_page, D.PAGES["median"]: median_page,
             D.API + "/commits/master": json.dumps(commit),
             f"{D.API}/git/trees/{'e' * 40}?recursive=1": json.dumps(tree)}
    for path, body in files.items():
        pages[D.RAW + "c" * 40 + "/" + path] = body
    return pages


# ---------------------------------------------------------------------------- Leaps in Bounds (trimmed, MIT) and OEIS
def leaps_pages():
    from adapters import leaps as L
    def read(name):
        with open(os.path.join(FIXTURES, name), "rb") as fh:
            return fh.read()

    pages = {L.DATA + "constants.json": read("leaps-constants.json"),
             L.DATA + "sources.json": read("leaps-sources.json"),
             L.RAW + "certificates/weak-schur/weak-schur-6-lower-650.yml": read("leaps-weak-schur-6-lower-650.yml"),
             L.RAW + "certificates/weak-schur/weak-schur-6-lower-650.txt": read("leaps-weak-schur-6-lower-650.txt"),
             L.OEIS["schur"][1]: "%I A045652 #1\n%S A045652 1,4,13,44,160\n%N A045652 Schur's numbers.\n"
                                 "%C A045652 The best known: a(6) >= 536 and a(7) >= 1680.\n"
                                 "%C A045652 Refined: a(6) >= 537, a(8) >= 5372.\n%O A045652 1,2\n",
             L.OEIS["weak-schur"][1]: "%I A072842 #1\n%S A072842 2,8,23,66\n%N A072842 Weak.\n"
                                      "%C A072842 a(6) >= 646, a(7) >= 2146, a(9) >= 22536.\n%O A072842 1,1\n"}
    return pages


# ---------------------------------------------------------------------------- A. E. Brouwer (hand-written copy)
def hamming8_weight4():
    words = set()
    for m in range(16):
        g = [0b11110000, 0b11001100, 0b10101010, 0b11111111]
        c = 0
        for i in range(4):
            if m >> i & 1:
                c ^= g[i]
        if bin(c).count("1") == 4:
            words.add(c)
    return sorted(words)


def brouwer_pages():
    from adapters import brouwer as B
    page = """<html><body>
<h3>Constructions</h3>
<p>
s: shortened code (from code of length n+1 and weight w or w+1).
<p>
g: code with specified group of automorphisms.
<p>
<h3>Upper bounds</h3>
<h3>References for labels</h3>
<p>
Ab: Ann Body, email 2026-10-01 with 3 new codes.
<p>
Old: Olga Lder,
<i>A paper</i>, J. Codes 1 (1999) 1-2.
<p>
Jump to <a href="#d4">d=4</a>.
<h1><a name="d4">Bounds on A(n,4,w)</a></h1>
<table border="1">
<tr><th>n\\w</th> <th>3</th> <th>4</th></tr>
<tr><th>7</th> <td>7.</td></tr>
<tr><th>8</th> <td>8.</td> <td><a href="cwc/d4/h8">14</a><sup>Ab</sup></td></tr>
</table>
<h1><a name="d6">Bounds on A(n,6,w)</a></h1>
<table border="1">
<tr><th>n\\w</th><th>4</th><th>5</th></tr>
<tr><th>13</th><td><span class="nw"><a href="cwc/d6/pg13">13</a><sup>Old</sup></span>-15</td><td>20<sup>s</sup>-30</td></tr>
<tr><th>14</th><td>14</td><td>28<sup>s</sup>-...</td></tr>
<tr><th>15</th><td>??</td></tr>
</table>
</body></html>"""
    h8 = "$BASE=16\n" + "\n".join("%02X" % x for x in hamming8_weight4()) + "\n"
    pg13 = "$EXEC orbit\n(0,1,2,3,4,5,6,7,8,9,10,11,12)\n..\n" + format(1 + 2 + 8 + 512, "013b") + "\n"
    return {B.PAGE: page, B.BASE + "cwc/d4/h8": h8, B.BASE + "cwc/d6/pg13": pg13}


# ---------------------------------------------------------------------------- planner inputs
def row(family="sum-free-colouring", params=None, value="650", direction="max", proved=False, **more):
    params = params or {"colours": 6, "weak": True}
    base = dict(by="Someone", year=2026, sourceName="A table", sourceUrl="https://example.org/t", objectUrl=None,
                objectLicence="MIT", provedOptimal=proved, upperOrLowerLimit=None, readOn="2026-11-20",
                source="leaps", recent=False, instanceSize=int(value), labels=[], objectRef={"path": "x"},
                secondary=[])
    base.update(more)
    return make_row(family, params, value, direction, **base)


def published_list(slug, key, state="OPEN", value="650", round_=1, family="sum-free-colouring", params=None,
                   checker_sha=None, task_result=None, direction="max", papex_from=None):
    """A task list as GET /api/shared-work/publisher/tasks shows it. papex_from: the list key whose accepted run
    this round's best known value is (sourceName Papex, sourceUrl that list's page), as the kit's runner writes it."""
    from common import checker_sha256
    best = {"value": value, "by": "x", "year": 2026, "sourceName": "A table", "sourceUrl": "https://example.org/t",
            "asOf": "2026-11-19"}
    if papex_from:
        page = f"https://papex.org/problems/weak-schur-numbers/shared-work/{papex_from}"
        best = {"value": value, "by": "an accepted run on Papex", "year": 2026, "sourceName": "Papex",
                "sourceUrl": page, "asOf": "2026-11-19", "objectUrl": page}
    return {"problemSlug": "weak-schur-numbers", "listKey": key, "state": state, "replacedByListKey": None,
            "taskResult": task_result,
            "task": {"slug": slug, "kind": "record", "direction": direction, "round": round_,
                     "bestKnown": best, "previousListKey": None if round_ == 1 else f"{slug}-r{round_ - 1}",
                     "checkerSha256": checker_sha or checker_sha256(family), "family": family,
                     "params": params or {"colours": 6, "weak": True}}}


def run_result(score, at="2026-11-19T10:00:00Z"):
    return {"score": score, "acceptedAt": at, "objectSha256": "0x" + "ab" * 32}


# ---------------------------------------------------------------------------- a stand-in Papex (publisher routes)
PUBLISHER_TOKEN = "made-up-publisher-token-for-the-finder-tests"


class StandInPapex:
    """The publisher routes with the server's rules for publishing (CONTRACT.md, Deviations, server items 1-4 and
    17), as the kit's own tests model them. Replaces urllib.request.urlopen while in use; nothing leaves the
    computer."""

    def __init__(self, lists=()):
        import io  # noqa: F401
        self.lists = {x["listKey"]: dict(x, body=None) for x in lists}
        self.requests = []
        self.lose_answer = False
        self.refuse_replacing = None  # a code: answer 409 with it to any publish that replaces a list

    def tasks(self):
        return [{k: v for k, v in x.items() if k != "body"} for x in self.lists.values()]

    def fail(self, request, status, body):
        import io
        import urllib.error
        raise urllib.error.HTTPError(request.full_url, status, "error", {}, io.BytesIO(json.dumps(body).encode()))

    @staticmethod
    def ok(value):
        import io
        return io.BytesIO(json.dumps(value).encode())

    def urlopen(self, request, timeout=None):
        import urllib.parse
        parts = urllib.parse.urlsplit(request.full_url)
        path, method = parts.path, request.get_method()
        body = json.loads(request.data) if request.data else None
        self.requests.append({"method": method, "path": path, "body": body,
                              "auth": request.get_header("Authorization")})
        if not path.startswith("/api/shared-work/publisher/tasks"):
            self.fail(request, 404, {"code": "NOT_FOUND"})
        if request.get_header("Authorization") != "Bearer " + PUBLISHER_TOKEN:
            self.fail(request, 401, {"code": "SHARED_WORK_PUBLISHER_TOKEN_INVALID", "message": "no"})
        if method == "GET":
            return self.ok({"tasks": self.tasks()})
        if path.endswith("/close"):
            key = path.strip("/").split("/")[-2]
            x = self.lists[key]
            if x["state"] == "OPEN":
                x["state"] = "CLOSED"
            return self.ok({"problemSlug": x["problemSlug"], "listKey": key, "state": x["state"]})
        return self.publish(request, body)

    def publish(self, request, body):
        lst, task = body["list"], body["list"]["howTo"]["task"]
        previous = None if task["round"] == 1 else f"{task['slug']}-r{task['round'] - 1}"
        if lst["key"] != f"{task['slug']}-r{task['round']}" or task["previousListKey"] != previous \
                or body["replaces"] not in (None, previous) \
                or (task["round"] == 1) != (body["problem"]["create"] is not None):
            self.fail(request, 422, {"code": "SHARED_WORK_PUBLISH_INVALID", "message": "shape"})
        if self.refuse_replacing and body["replaces"]:
            self.fail(request, 409, {"code": self.refuse_replacing, "message": "the accepted score is better"})
        if lst["key"] in self.lists:
            if self.lists[lst["key"]]["body"] == body:
                return self.ok({"problemSlug": body["problem"]["slug"], "listKey": lst["key"], "already": True})
            self.fail(request, 409, {"code": "SHARED_WORK_TASK_KEY_TAKEN", "message": "taken"})
        rounds = [x for x in self.lists.values() if x["task"]["slug"] == task["slug"]]
        if task["round"] != max([x["task"]["round"] for x in rounds] or [0]) + 1:
            self.fail(request, 409, {"code": "SHARED_WORK_TASK_ROUND_INVALID", "message": "round"})
        if any(x["state"] == "OPEN" and x["listKey"] != body["replaces"] for x in rounds):
            self.fail(request, 409, {"code": "SHARED_WORK_TASK_ROUND_OPEN", "message": "another round is open"})
        if task["round"] > 1 and body["replaces"] is None and self.lists[previous]["state"] != "CLOSED":
            self.fail(request, 409, {"code": "SHARED_WORK_TASK_ROUND_INVALID", "message": "replaces"})
        self.lists[lst["key"]] = {"problemSlug": body["problem"]["slug"], "listKey": lst["key"], "state": "OPEN",
                                  "task": task, "taskResult": None, "replacedByListKey": None, "body": body}
        if body["replaces"]:
            old = self.lists[body["replaces"]]
            old["state"], old["replacedByListKey"] = "REPLACED", lst["key"]
        if self.lose_answer:
            self.fail(request, 502, {"code": "BAD_GATEWAY", "message": "lost"})
        return self.ok({"problemSlug": body["problem"]["slug"], "listKey": lst["key"], "already": False})


def all_01(n):
    return itertools.product((0, 1), repeat=n)
