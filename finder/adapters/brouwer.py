"""A. E. Brouwer's table of bounds for binary constant weight codes A(n, d, w) (aeb.win.tue.nl/codes/Andw.html).

The page states no licence, so its codes are read to check them and LINKED (bestKnown.objectUrl); only their
sha256 is kept. robots.txt: "crawl-delay: 5".

Read per run (all through the cache):
  aeb.win.tue.nl   robots.txt, Andw.html                                                                     2
                   one code file per entry whose card is made or moved today (5 s apart; kept 30 days);
                   at most REQUESTS - 2 in a run, the rest wait for the next run                       <= 30

Cell grammar (the page's own legend): "lower-upper" with labels in <sup>; a link on the lower bound is the code.
d = 4: "For now, lower bounds only. Optimum values are indicated by a dot." d >= 6: a single number is the exact
value; "lower-upper" is open; "lower-..." is open with no upper bound shown.
"""

import re

from common import Unavailable, as_listed, blocks, make_row, safe_name, safe_path, squash, strip_tags

FAMILY = "constant-weight-code"
PAGE = "https://aeb.win.tue.nl/codes/Andw.html"
BASE = "https://aeb.win.tue.nl/codes/"
SOURCE_NAME = "A. E. Brouwer, table of constant weight codes"
REQUESTS = {"aeb.win.tue.nl": 32}
NO_OBJECT = "the table links no code for this entry (the value comes from a construction it names only by a label)"
MAX_CODEWORDS = 20000
MAX_LENGTH = 64  # the table's longest words; a code file is read only for n up to this
PAGE_BYTES = 2 * 1024 * 1024
CODE_BYTES = 1024 * 1024
MAX_CELL = 2000
MAX_CELLS = 5000

TABLE_START_RE = re.compile(r'<a name="d(\d{1,2})">')
LABEL_RE = re.compile(r"^[A-Za-z\u00c0-\u017f]{1,8}$")


def parse_cell(inner):
    """{lower, dot, upper, upperShown, href, lowerLabels, upperLabels, newHere} or None for an empty cell.
    Raises Unavailable for a cell this reader does not understand."""
    if len(inner) > MAX_CELL:
        raise Unavailable("cell not understood: longer than a table cell")
    s = re.sub(r"<!--.*?-->", "", inner, flags=re.S)
    new_here = 'class="nw"' in s
    s = re.sub(r"</?span[^>]*>", "", s).replace("&nbsp;", " ").strip()
    if not s:
        return None
    depth, cut = 0, None
    for i, ch in enumerate(s):
        if ch == "<":
            depth += 1
        elif ch == ">":
            depth -= 1
        elif ch == "-" and depth == 0:
            cut = i
            break
    low, up = (s[:cut], s[cut + 1:]) if cut is not None else (s, None)
    href = re.search(r'<a href="([^"<>]{1,200})"', low)
    low_labels = [squash(strip_tags(x)) for x in re.findall(r"<sup>(.*?)</sup>", low, re.S)]
    low_text = squash(strip_tags(re.sub(r"<sup>.*?</sup>", "", low, flags=re.S)))
    m = re.fullmatch(r"(\d{1,9}) ?(\.?)", low_text)
    if not m:
        raise Unavailable(f"cell not understood: {squash(strip_tags(inner))[:40]}")
    cell = {"lower": int(m.group(1)), "dot": bool(m.group(2)), "upper": None, "upperShown": up is not None,
            "href": href.group(1) if href else None, "lowerLabels": [x for x in low_labels if x],
            "upperLabels": [], "newHere": new_here}
    if up is not None:
        up_labels = [squash(strip_tags(x)) for x in re.findall(r"<sup>(.*?)</sup>", up, re.S)]
        up_text = squash(strip_tags(re.sub(r"<sup>.*?</sup>", "", up, flags=re.S)))
        if re.fullmatch(r"\d{1,9}", up_text):
            cell["upper"] = int(up_text)
        elif up_text not in ("...", "\u2026"):
            raise Unavailable(f"cell not understood: {squash(strip_tags(inner))[:40]}")
        cell["upperLabels"] = [x for x in up_labels if x]
    return cell


def inner_cells(row, tag):
    """The contents of each <tag …>…</tag> of a row, without the opening tag (linear)."""
    out = []
    for inner in blocks(row, "<" + tag, "</" + tag + ">", limit=64):
        gt = inner.find(">")
        out.append(inner[gt + 1:] if gt >= 0 else "")
    return out


def tables(page):
    """{d: [(n, w, cell)]} for every table on the page."""
    out, total = {}, 0
    starts = [(int(m.group(1)), m.start()) for m in TABLE_START_RE.finditer(page)][:20]
    for k, (d, at) in enumerate(starts):
        end = starts[k + 1][1] if k + 1 < len(starts) else len(page)
        seg = page[at:end]
        t0 = seg.find("<table")
        t1 = seg.find("</table>", t0)
        if t0 < 0 or t1 < 0:
            raise Unavailable(f"the d={d} table was not found")
        rows = blocks(seg[t0:t1], "<tr>", "</tr>", limit=200)
        if not rows:
            raise Unavailable(f"the d={d} table has no rows")
        header = [squash(strip_tags(x)) for x in inner_cells(rows[0], "th")]
        if not header or not header[0].startswith("n") or not all(re.fullmatch(r"\d{1,2}", x) for x in header[1:]):
            raise Unavailable(f"the d={d} table has no n\\w header")
        ws = [int(x) for x in header[1:]]
        cells = []
        for row in rows[1:]:
            th = inner_cells(row, "th")
            if not th:
                continue
            first = squash(strip_tags(th[0]))
            if not re.fullmatch(r"\d{1,2}", first):
                if first.startswith("n") and len(th) > 1 and all(re.fullmatch(r"\d{1,2}", squash(strip_tags(x)))
                                                                 for x in th[1:]):
                    ws = [int(squash(strip_tags(x))) for x in th[1:]]  # the header repeated further down
                    continue
                raise Unavailable(f"the d={d} table has a row headed {first[:20]!r}")
            n = int(first)
            for col, inner in enumerate(inner_cells(row, "td")):
                if col >= len(ws):
                    raise Unavailable(f"the d={d} table row n={n} has more cells than columns")
                cells.append((n, ws[col], inner))
                total += 1
                if total > MAX_CELLS:
                    raise Unavailable("the page has more table cells than this reader takes")
        out[d] = cells
    if not out:
        raise Unavailable("no tables found on the page")
    return out


def legend_entries(section):
    """[(label, text)] of a legend section: paragraphs that start "Label: …" (split with str.split: linear)."""
    out = []
    for part in section.replace("<br>", "<p>").split("<p>")[:400]:
        m = re.match(r"\s*([A-Za-z\u00c0-\u017f]{1,8}):\s*", part)
        if m:
            out.append((m.group(1), part[m.end():m.end() + 3000]))
    return out


def legend(page):
    """({label: reference text}, {label: construction text}) from the page's legend sections."""
    refs, cons = {}, {}
    a = page.find("<h3>Constructions</h3>")
    b = page.find("<h3>Upper bounds</h3>")
    if 0 <= a < b and b - a < 200000:
        for label, text in legend_entries(page[a:b]):
            cons[label] = squash(strip_tags(text.split("<h3>")[0]))
    c = page.find("<h3>References for labels</h3>")
    if c >= 0:
        e = page.find("Jump to", c)
        section = page[c:e if e > 0 else len(page)][:400000]
        section = re.sub(r"<!--.*?-->", "", section, flags=re.S)
        for label, text in legend_entries(section):
            refs[label] = text
    return refs, cons


def credit(cell, n, d, refs, cons):
    """(by, year, recent) for the cell's lower bound, from the page's own legend. Names and labels are used only
    when they are plainly names (common.safe_name); otherwise "as listed in" the table."""
    labels = [x for lab in cell["lowerLabels"] for x in lab.split() if LABEL_RE.match(x)]
    people = [lab for lab in labels if lab in refs]
    if people:
        names, years, recent = [], set(), False
        for lab in people:
            text = refs[lab]
            head = text.split("<i>")[0]
            if re.search(r"<(?!br\s*/?>)[^>]{0,200}>", head):  # markup where a name should be: not a name
                return as_listed(SOURCE_NAME), None, False
            name = squash(strip_tags(head))
            name = re.split(r",\s*(?:emails?\b|arXiv|preprint|with\b)", name)[0].strip().rstrip(",").strip()
            name = safe_name(name) if not re.search(r"\d", name) else None
            if not name:
                return as_listed(SOURCE_NAME), None, False
            names.append(name)
            plain = squash(strip_tags(text))
            years.update(int(y) for y in re.findall(r"\b(19\d\d|20\d\d)\b", plain))
            recent = recent or bool(re.search(r"\b202[56]\b", plain))
        joined = "; ".join(names)
        if len(joined) > 150:
            return as_listed(SOURCE_NAME), None, recent
        return joined + " (as given on Brouwer's table)", (years.pop() if len(years) == 1 else None), recent
    constructions = [lab for lab in labels if lab in cons]
    if constructions:
        what = safe_name(cons[constructions[0]].split("(")[0].strip().rstrip("."), limit=60)
        return (f"Brouwer's table (construction {', '.join(constructions)}" + (f": {what})" if what else ")")), \
            None, False
    if cell["newHere"]:
        return "A. E. Brouwer's table (new on the table)", None, False
    if labels:
        return f"Brouwer's table (label {' '.join(labels)})", None, False
    # The page says unmarked lower bounds (n <= 28) come from [BSSS] 1990 (d = 4: Brouwer and Etzion 2011), but
    # some unmarked cells hold later values, so no name is given for them.
    return "A. E. Brouwer's table (no source label on the entry)", None, False


def exact_reading(d, cell):
    """(proved, upper, unclear). Proved only on the table's own marks: for d = 4 the dot ("Optimum values are
    indicated by a dot"), elsewhere a lower and an upper bound that are equal. A lone number in a d >= 6 table is
    not marked either way: it is neither proved nor open (no card, and never a close)."""
    if d == 4:
        return cell["dot"], None, False
    if not cell["upperShown"]:
        return False, None, True
    upper = cell["upper"]
    return upper is not None and upper == cell["lower"], upper, False


def read_rows(fetcher, today):
    try:
        page, _ = fetcher.text(PAGE, max_bytes=PAGE_BYTES)
        all_tables = tables(page)
        refs, cons = legend(page)
    except Exception as e:
        return [], [{"source": "brouwer", "reason": f"page not read: {str(e)[:200]}"}]
    rows, problems = [], []
    for d, cells in sorted(all_tables.items()):
        for n, w, inner in cells:
            try:
                cell = parse_cell(inner)
                if cell is None:
                    continue
                proved, upper, unclear = exact_reading(d, cell)
                if upper is not None and upper < cell["lower"]:
                    raise Unavailable(f"the upper bound {upper} is below the lower bound {cell['lower']}")
                by, year, recent = credit(cell, n, d, refs, cons)
                href = safe_path(cell["href"], "cwc/", max_segments=4) if cell["href"] else None
                params = {"n": n, "d": d, "w": w}
                rows.append(make_row(FAMILY, params, cell["lower"], "max", by=by, year=year,
                                     sourceName=SOURCE_NAME, sourceUrl=f"{PAGE}#d{d}",
                                     objectUrl=BASE + href if href else None,
                                     objectLicence=None, provedOptimal=proved, exactUnclear=unclear,
                                     upperOrLowerLimit=upper, readOn=today, source="brouwer", recent=recent,
                                     instanceSize=cell["lower"],
                                     labels=[x for x in cell["lowerLabels"] if safe_name(x, limit=20)],
                                     objectRef={"href": href} if href else None, secondary=[]))
            except Exception as e:  # one bad cell is dropped with its reason; the table still runs
                problems.append({"source": "brouwer", "row": f"A({n},{d},{w})", "reason": str(e)[:200]})
    return rows, problems


def parse_code(text, n, w):
    """The codewords (as integers, bit i = coordinate i) of a code file in one of the formats seen on the page:
    '$BASE=16' (or '$BASE=2') then one word per line; one 0/1 word of length n per line with no header; or
    '$EXEC orbit' then permutation generators in cycle notation, '..', and orbit representatives as 0/1 strings.
    A 0/1 string is read as a binary number, so its last character is coordinate 0: with that reading the orbits of
    the page's files have exactly the sizes the table gives (checked on A(12,4,6) = 132 and A(19,6,6) >= 172; the
    other reading gives 110 words, and 576 words at distance 2)."""
    if not 1 <= n <= MAX_LENGTH:
        raise Unavailable(f"length {n} is outside what this reader takes")
    lines = [ln.strip() for ln in text.splitlines()[:MAX_CODEWORDS + 200] if ln.strip()]
    if not lines:
        raise Unavailable("the code file is empty")
    top = 1 << n
    head = lines[0]
    if head in ("$BASE=16", "$BASE=2"):
        base = 16 if head.endswith("16") else 2
        width = (n + 3) // 4 if base == 16 else n  # the most digits a word of length n can need
        if len(lines) - 1 > MAX_CODEWORDS:
            raise Unavailable("the code file has more words than the checker takes")
        words = []
        for ln in lines[1:]:
            if len(ln) > width or not re.fullmatch(r"[0-9A-Fa-f]+" if base == 16 else r"[01]+", ln):
                raise Unavailable(f"the code file has a line that is not a base-{base} word of length {n}")
            x = int(ln, base)
            if x >= top:
                raise Unavailable(f"the code file has a word longer than {n} coordinates")
            words.append(x)
        return words
    if all(re.fullmatch(r"[01]+", ln) and len(ln) == n for ln in lines):  # one 0/1 word per line, no header
        if len(lines) > MAX_CODEWORDS:
            raise Unavailable("the code file has more words than the checker takes")
        return [int(ln, 2) for ln in lines]
    if head == "$EXEC orbit":
        try:
            sep = lines.index("..")
        except ValueError:
            raise Unavailable("the orbit file has no '..' line")
        if sep > 101 or len(lines) - sep - 1 > MAX_CODEWORDS:
            raise Unavailable("the orbit file has more generators or representatives than this reader takes")
        gens = []
        for ln in lines[1:sep]:
            if len(ln) > 4000 or not re.fullmatch(r"(\(\d{1,2}(,\d{1,2})+\))+", ln):
                raise Unavailable("the orbit file has a generator that is not in cycle notation")
            perm = list(range(n))
            for cyc in re.findall(r"\(([\d,]+)\)", ln):
                pts = [int(x) for x in cyc.split(",")]
                if any(p >= n for p in pts) or len(set(pts)) != len(pts):
                    raise Unavailable("the orbit file has a generator that moves a point outside the code length")
                for a, b in zip(pts, pts[1:] + pts[:1]):
                    perm[a] = b
            gens.append(perm)
        seen = set()
        for ln in lines[sep + 1:]:
            if not re.fullmatch(r"[01]+", ln) or len(ln) != n:
                raise Unavailable("the orbit file has a representative that is not a 0/1 word of length n")
            start = int(ln, 2)  # read as a binary number: the last character is coordinate 0 (as the generators)
            todo = [start]
            if start in seen:
                continue
            seen.add(start)
            while todo:
                x = todo.pop()
                ones = [i for i in range(n) if (x >> i) & 1]
                for perm in gens:
                    y = 0
                    for i in ones:
                        y |= 1 << perm[i]
                    if y not in seen:
                        seen.add(y)
                        todo.append(y)
                        if len(seen) > MAX_CODEWORDS:
                            raise Unavailable("the orbits give more codewords than the checker takes")
        return sorted(seen)
    raise Unavailable("the code file's format is not one this reader takes")


def fetch_object(fetcher, row):
    ref = row.get("objectRef")
    if not ref:
        raise Unavailable(NO_OBJECT)
    href = safe_path(ref.get("href"), "cwc/", max_segments=4)
    if not href:
        raise Unavailable("the code's link is not a plain path under the table's codes folder")
    url = BASE + href
    status, body, _ = fetcher.get(url, max_age_hours=24 * 30, max_bytes=CODE_BYTES)
    if status != 200:
        raise Unavailable(f"the code file answered {status}")
    p = row["params"]
    words = parse_code(body.decode("latin-1"), p["n"], p["w"])
    if len(words) > MAX_CODEWORDS:
        raise Unavailable("the code has more codewords than the checker takes")
    return ({"n": p["n"], "d": p["d"], "w": p["w"], "codewords": sorted(words)},
            {"url": url, "licence": None, "copyable": False})
