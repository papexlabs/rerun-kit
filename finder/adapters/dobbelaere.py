"""Bert Dobbelaere's lists of sorting networks and median selection networks, and the MIT-licensed SorterHunter
repository that holds every listed network as a JSON file.

Read per run (all through the cache):
  bertdobbelaere.github.io   robots.txt, sorting_networks_extended.html (n = 2..64), median_networks.html      3
  api.github.com             robots.txt, the master commit, the repository tree                                3
  raw.githubusercontent.com  robots.txt, one file per network whose card is made or moved today; a file is read
                             again only when its git blob hash in the tree changes                       1 + few

Values and proofs of optimality come from the summary tables of the two pages (the "table"); objects come from the
repository (`Networks/Sorters/Sort_<N>_<L>_<D>.json`, `Networks/Median/Median_<N>_<L>_<D>.json`). A row's value is
the table's; its best known object is the repository file that reaches it.
"""

import datetime
import json
import re

from common import Unavailable, as_listed, blocks, git_blob_sha1, make_row, safe_name, safe_path, squash, strip_tags

FAMILY = "comparator-network"
PAGES = {"sort": "https://bertdobbelaere.github.io/sorting_networks_extended.html",
         "median": "https://bertdobbelaere.github.io/median_networks.html"}
PAGE_NAMES = {"sort": "B. Dobbelaere, list of sorting networks", "median": "B. Dobbelaere, list of median networks"}
REPO = "bertdobbelaere/SorterHunter"
API = "https://api.github.com/repos/" + REPO
RAW = "https://raw.githubusercontent.com/" + REPO + "/"
BLOB = "https://github.com/" + REPO + "/blob/"
FOLDERS = {"sort": ("Networks/Sorters/", "Sort"), "median": ("Networks/Median/", "Median")}
LICENCE = "MIT (SorterHunter repository, Copyright (c) 2017 bertdobbelaere)"
REQUESTS = {"bertdobbelaere.github.io": 4, "api.github.com": 4, "raw.githubusercontent.com": 60}
NO_OBJECT = "the repository holds no network file for this entry"
RECENT_DAYS = 730

PAIR_RE = re.compile(r"\((\d{1,6}), ?(\d{1,6})\)")
FILE_RE = re.compile(r"^(Sort|Median)_(\d{1,3})_(\d{1,6})_(\d{1,4})\.json$")
MAX_INPUTS = 64  # the largest input count the lists have; history ranges are cut to 2..MAX_INPUTS
MAX_ROWS = 500
MAX_CELL = 4000  # characters of one table cell that are read
PAGE_BYTES = 2 * 1024 * 1024
TREE_BYTES = 4 * 1024 * 1024
NETWORK_BYTES = 256 * 1024


def cells(row):
    """The cells of a table row, without their <td …> tags, each cut to MAX_CELL characters (linear)."""
    out = []
    for inner in blocks(row, "<td", "</td>", limit=20):
        gt = inner.find(">")
        out.append(inner[gt + 1:gt + 1 + MAX_CELL] if gt >= 0 else "")
    return out


def summary_table(page):
    """{n: {"pairs": [(size, depth)], "size": (lo, hi, exact) | None, "depth": … | None, "comment": text}}."""
    start = page.find("<h3>Summary table</h3>")
    if start < 0:
        raise Unavailable("the page has no summary table")
    end = page.find("</table>", start)
    table = {}
    for row in blocks(page[start:end], "<tr>", "</tr>", limit=MAX_ROWS):
        tds = cells(row)
        if not tds:
            continue
        n_text = squash(strip_tags(tds[0]))
        if not re.fullmatch(r"\d{1,3}", n_text) or not 2 <= int(n_text) <= MAX_INPUTS:
            raise Unavailable(f"a summary row does not start with a number of inputs: {n_text[:40]}")
        n = int(n_text)
        pairs = [(int(a), int(b)) for a, b in PAIR_RE.findall(strip_tags(tds[1]))[:20]]
        if not pairs:
            raise Unavailable(f"the summary row for {n} inputs names no (size, depth) pair")
        entry = {"pairs": pairs, "size": None, "depth": None, "comment": squash(strip_tags(tds[-1]))[:600]}
        if len(tds) == 5:  # sorting: n, pairs, size bounds, depth bounds, comments
            entry["size"] = bounds(tds[2])
            entry["depth"] = bounds(tds[3])
        elif len(tds) != 3:
            raise Unavailable(f"the summary row for {n} inputs has {len(tds)} cells")
        table[n] = entry
    if not table:
        raise Unavailable("the summary table is empty")
    return table


def bounds(cell):
    """(lower, upper, exact): a bold number is the exact value; 'a…b' is a range."""
    text = squash(strip_tags(cell))[:40]
    m = re.fullmatch(r"(\d{1,6})", text)
    if m and re.fullmatch(r"\s*<b>\s*\d{1,6}\s*</b>\s*", cell):  # the page's mark of an exact value: bold
        v = int(m.group(1))
        return v, v, True
    m = re.fullmatch(r"(\d{1,6}) ?… ?(\d{1,6})", text)
    if m and int(m.group(1)) <= int(m.group(2)):
        return int(m.group(1)), int(m.group(2)), False
    raise Unavailable(f"a bounds cell is not understood: {text[:40]}")


def history_inputs(page, today):
    """Input counts that the page's dated History names within RECENT_DAYS of today."""
    start = page.find("<h3>History</h3>")
    if start < 0:
        return set()
    recent = set()
    cutoff = datetime.date.fromisoformat(today) - datetime.timedelta(days=RECENT_DAYS)
    for row in blocks(page[start:], "<tr>", "</tr>", limit=MAX_ROWS):
        tds = cells(row)
        if len(tds) < 2:
            continue
        try:
            when = datetime.date.fromisoformat(squash(strip_tags(tds[0]))[:10])
        except ValueError:
            continue
        if when < cutoff:
            continue
        text = squash(strip_tags(tds[1]))[:600]
        found = set(int(x) for x in re.findall(r"N(\d{1,3})D\d{1,3}", text))
        for a, b in re.findall(r"between (\d{1,9}) and (\d{1,9})", text) + \
                re.findall(r"(\d{1,9}) ?\.\.\. ?(\d{1,9})", text):
            lo, hi = max(2, int(a)), min(MAX_INPUTS, int(b))  # a range is cut to the input counts the lists have
            found.update(range(lo, hi + 1))
        for group in re.findall(r"((?:\d{1,3}, ?){0,30}\d{1,3}(?:,? and \d{1,3})?) inputs", text):
            found.update(int(x) for x in re.findall(r"\d+", group))
        recent |= {n for n in found if 2 <= n <= MAX_INPUTS}
    return recent


def repository(fetcher):
    """(commit sha, {path: blob sha}) of the repository's master branch."""
    text, _ = fetcher.text(API + "/commits/master", max_age_hours=20)
    commit = json.loads(text)
    sha = commit.get("sha")
    tree_sha = ((commit.get("commit") or {}).get("tree") or {}).get("sha")
    if not (isinstance(sha, str) and re.fullmatch(r"[0-9a-f]{40}", sha) and isinstance(tree_sha, str)):
        raise Unavailable("the repository's master commit could not be read")
    if not re.fullmatch(r"[0-9a-f]{40}", tree_sha):
        raise Unavailable("the repository's tree could not be read")
    text, _ = fetcher.text(f"{API}/git/trees/{tree_sha}?recursive=1", max_age_hours=None, max_bytes=TREE_BYTES)
    tree = json.loads(text)
    if not isinstance(tree, dict) or tree.get("truncated") or not isinstance(tree.get("tree"), list):
        raise Unavailable("the repository tree came back truncated or not as a list")
    blobs = {}
    for t in tree["tree"]:
        if isinstance(t, dict) and t.get("type") == "blob" and isinstance(t.get("sha"), str) \
                and re.fullmatch(r"[0-9a-f]{40}", t["sha"]) and safe_path(t.get("path"), "Networks/"):
            blobs[t["path"]] = t["sha"]
    return sha, blobs


def read_rows(fetcher, today):
    """(rows, problems). One row per (inputs, goal, measure) the tables list. A bad row is dropped with its reason."""
    rows, problems = [], []
    try:
        commit, blobs = repository(fetcher)
    except Exception as e:  # the whole source is skipped today
        return [], [{"source": "dobbelaere", "reason": f"repository not read: {str(e)[:200]}"}]
    for goal in ("sort", "median"):
        try:
            page, _ = fetcher.text(PAGES[goal], max_bytes=PAGE_BYTES)
            table = summary_table(page)
            recent = history_inputs(page, today)
        except Exception as e:
            problems.append({"source": "dobbelaere", "reason": f"{goal} page not read: {str(e)[:200]}"})
            continue
        folder, prefix = FOLDERS[goal]
        files = {}
        for path, blob in blobs.items():
            if not path.startswith(folder):
                continue
            m = FILE_RE.match(path[len(folder):])
            if m and m.group(1) == prefix:
                n, size, depth = int(m.group(2)), int(m.group(3)), int(m.group(4))
                files.setdefault(n, []).append((size, depth, path, blob))
        for n, entry in sorted(table.items()):
            for measure in ("size", "depth"):
                try:
                    rows.append(table_row(goal, measure, n, entry, files, commit, recent, today, problems))
                except Exception as e:
                    problems.append({"source": "dobbelaere", "row": f"{goal} {n} {measure}",
                                     "reason": f"entry not read ({type(e).__name__}: {str(e)[:120]})"})
    return rows, problems


def table_row(goal, measure, n, entry, files, commit, recent, today, problems):
    folder = FOLDERS[goal][0]
    k = 0 if measure == "size" else 1
    table_best = min(p[k] for p in entry["pairs"])
    comment = entry["comment"]
    soft = False
    if goal == "sort":
        lo, hi, exact = entry[measure]
        if hi != table_best:
            problems.append({"source": "dobbelaere", "row": f"{goal} {n} {measure}",
                             "reason": f"the bounds column says {hi} but the pairs say {table_best}"})
        proved, limit = exact and lo == hi == table_best, lo
    else:
        # The median page states no bounds. A comment that mentions optimality keeps the entry from getting a
        # card, but is never read as a proof (it never closes a card).
        proved, limit, soft = False, None, "optimal" in comment.lower()
    candidates = sorted(files.get(n, []), key=lambda f: (f[k], f[1 - k]))
    best_file = candidates[0] if candidates else None
    params = {"inputs": n, "goal": goal, "measure": measure}
    row = make_row(FAMILY, params, table_best, "min",
                   by=by_line(goal, measure, comment),
                   year=None,
                   sourceName=PAGE_NAMES[goal],
                   sourceUrl=PAGES[goal],
                   objectUrl=(BLOB + "master/" + best_file[2]) if best_file else None,
                   objectLicence=LICENCE if best_file else None,
                   provedOptimal=bool(proved),
                   softExact=soft,
                   upperOrLowerLimit=limit,
                   readOn=today,
                   source="dobbelaere",
                   recent=n in recent,
                   instanceSize=n,
                   labels=[],
                   objectRef={"path": best_file[2], "blob": best_file[3], "commit": commit,
                              "fileValue": best_file[k]} if best_file else None,
                   secondary=[])
    if best_file and best_file[k] != table_best:
        row["secondary"].append({"name": "SorterHunter repository files", "value": str(best_file[k]),
                                 "url": BLOB + "master/" + folder.rstrip("/")})
    return row


def by_line(goal, measure, comment):
    """Who the page credits for this measure's bound, from its comments cell: used only when it is plainly a name
    (a reference key such as [Baddar09] loses its brackets); otherwise the list itself."""
    named = None
    for m in re.finditer(r"(Size and depth|Size/depth|Size|Depth) ubounds?: ?([^,]{1,120})", comment[:600], re.I):
        which = m.group(1).lower()
        if which.startswith("size and") or which.startswith("size/") or which == measure:
            named = re.split(r"\.\s", m.group(2))[0].strip().rstrip(".")
            break
    lists = "B. Dobbelaere's list of " + ("sorting networks" if goal == "sort" else "median networks")
    if named is None:
        return lists
    named = safe_name(re.sub(r"^\[([^\[\]]{1,40})\]$", r"\1", named), limit=60)
    return f"{named} (as given on {lists})" if named else as_listed(lists)


def fetch_object(fetcher, row):
    """The repository's network for the row, as this family's object {"inputs", "comparators"}."""
    ref = row.get("objectRef")
    if not ref:
        raise Unavailable(NO_OBJECT)
    path = safe_path(ref.get("path"), "Networks/")
    if not path or not re.fullmatch(r"[0-9a-f]{40}", str(ref.get("commit"))):
        raise Unavailable("the network's path is not a plain path inside the repository's Networks folder")
    url = RAW + ref["commit"] + "/" + path
    body = fetcher.blob(url, ref["blob"], git_blob_sha1, max_bytes=NETWORK_BYTES)
    try:
        data = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise Unavailable("the network file is not JSON")
    if not isinstance(data, dict) or not isinstance(data.get("nw"), list) or not isinstance(data.get("N"), int):
        raise Unavailable("the network file is not {N, L, D, nw}")
    n = row["params"]["inputs"]
    if data["N"] != n:
        raise Unavailable(f"the network file is for {str(data['N'])[:10]} inputs, not {n}")
    if len(data["nw"]) > 5000:
        raise Unavailable("the network file holds more comparators than the family's checker takes")
    comps = []
    for c in data["nw"]:
        if not (isinstance(c, list) and len(c) == 2 and all(isinstance(x, int) and not isinstance(x, bool) for x in c)):
            raise Unavailable("a comparator in the file is not a pair of whole numbers")
        i, j = c
        if not 0 <= i < j < n:
            raise Unavailable(f"the file has a comparator that is not in the form i < j < {n}")
        comps.append([i, j])
    if data.get("L") != len(comps):
        raise Unavailable(f"the file's L is not the number of comparators it holds ({len(comps)})")
    return {"inputs": n, "comparators": comps}, {"url": url, "sha256Source": None, "licence": LICENCE,
                                                 "copyable": True}
