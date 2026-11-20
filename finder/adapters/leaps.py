"""Leaps in Bounds (leapsinbounds.org; data and certificates MIT-licensed) for Schur and weak Schur numbers, with
OEIS (read from the oeis/oeisdata GitHub repository) as the second source.

Read per run (all through the cache):
  leapsinbounds.org          robots.txt, /data/constants.json (bounds, exactness, certificates, history),
                             /data/sources.json (who and when)                                               3
  raw.githubusercontent.com  the certificate file and its witness file, for each Schur or weak Schur entry whose
                             card is made or moved today; kept by URL for 30 days                        2 per row
                             OEIS: seq/A045/A045652.seq (S(k)), seq/A072/A072842.seq (WS(k)); kept 7 days      2

The same constants.json also gives Leaps in Bounds' values for sorting networks, used as a second source for
B. Dobbelaere's table (`sorting_secondary`).
"""

import lzma
import re
import zlib

from common import Unavailable, as_listed, make_row, safe_name, safe_path

FAMILY = "sum-free-colouring"
DATA = "https://leapsinbounds.org/data/"
SITE = "https://leapsinbounds.org/constants/"
RAW = "https://raw.githubusercontent.com/daniel-munro/leaps-in-bounds/main/"
BLOB = "https://github.com/daniel-munro/leaps-in-bounds/blob/main/"
LICENCE = "MIT (Leaps in Bounds repository, Copyright (c) 2025 Daniel Munro)"
OEIS = {"schur": ("A045652", "https://raw.githubusercontent.com/oeis/oeisdata/main/seq/A045/A045652.seq"),
        "weak-schur": ("A072842", "https://raw.githubusercontent.com/oeis/oeisdata/main/seq/A072/A072842.seq")}
REQUESTS = {"leapsinbounds.org": 4, "raw.githubusercontent.com": 60}
NO_OBJECT = "Leaps in Bounds holds no verified witness for this value (literature only)"
CONSTANT_RE = re.compile(r"^(schur|weak-schur)-(\d+)$")
MAX_WITNESS_BYTES = 4 * 1024 * 1024  # a witness, after decompression
MAX_DOWNLOAD = 2 * 1024 * 1024
CONSTANTS_BYTES = 12 * 1024 * 1024  # constants.json was 6.8 MB on 20 Nov 2026
RECENT_DAYS = 730
# One author as Leaps in Bounds writes them: initials, then a surname of one to three words. No nested repetition.
AUTHOR_RE = re.compile(r"^[A-Z][a-z]?\.(?:[ -]?[A-Z][a-z]?\.){0,3} ?[A-Z][\w'’-]{0,40}(?: [A-Z][\w'’-]{0,40}){0,2}$")


def load(fetcher):
    """(constants, sources) of Leaps in Bounds, read once per run."""
    memo = getattr(fetcher, "_leaps", None)
    if memo is None:
        import json
        constants = json.loads(fetcher.text(DATA + "constants.json", max_bytes=CONSTANTS_BYTES)[0])
        sources = json.loads(fetcher.text(DATA + "sources.json", max_bytes=4 * 1024 * 1024)[0])
        if not isinstance(constants, dict) or not isinstance(sources, dict):
            raise Unavailable("Leaps in Bounds data is not in the expected shape")
        memo = fetcher._leaps = (constants, sources)
    return memo


def integer(bound):
    """The whole number in a Leaps bound object ({"latex": "538", ...}), or None for anything else."""
    if not isinstance(bound, dict) or not isinstance(bound.get("latex"), str):
        return None
    latex = bound["latex"].replace("{,}", "").replace(",", "").strip()
    return int(latex) if re.fullmatch(r"[1-9]\d{0,11}|0", latex) else None


def exact_reading(constant, lower, upper):
    """True only on a strict positive reading: exact_value is a whole number equal to both bounds."""
    exact = integer(constant.get("exact_value"))
    return exact is not None and exact == lower == upper


def authors(text):
    """The leading author list of a source line ("Z. Chen, L. Zhu and F. Long, A new lower bound ..."), or None."""
    if not isinstance(text, str):
        return None
    names = []
    for part in re.split(r", and |, | and ", text[:400]):
        if AUTHOR_RE.match(part):
            names.append(part)
        else:
            break
    if not names:
        return None
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def dicts(value):
    return [x for x in value if isinstance(x, dict)] if isinstance(value, list) else []


def credit(constant, value, sources, source_name):
    """(by, year, date) of the earliest record of `value` as the lower bound. A name from the source is used only
    when it is plainly a name (common.safe_name); otherwise "as listed in <source>"."""
    for cert in dicts(constant.get("certificates")):
        if cert.get("bound") == "lower" and cert.get("value") == value and cert.get("role") == "discovery":
            date = cert.get("date") if isinstance(cert.get("date"), str) else ""
            who = safe_name(cert.get("submitted_by"), limit=60)
            return (f"{who} (certificate on Leaps in Bounds)" if who else as_listed(source_name)), year_of(date), date
    events = [u for u in dicts(constant.get("updates"))
              if u.get("type") == "lower_bound" and integer(u.get("value")) == value]
    events.sort(key=lambda u: str(u.get("date") or "9999"))
    if events:
        e = events[0]
        key = e.get("source") if isinstance(e.get("source"), str) else ""
        src = sources.get(key) if isinstance(sources.get(key), dict) else {}
        who = safe_name(authors(src.get("string")))
        date = e.get("date") if isinstance(e.get("date"), str) else (src.get("date") if isinstance(src.get("date"),
                                                                                                    str) else "")
        return (who or as_listed(source_name)), year_of(date), date or ""
    return as_listed(source_name), None, ""


def year_of(date):
    m = re.match(r"(\d{4})", date if isinstance(date, str) else "")
    return int(m.group(1)) if m and 1000 <= int(m.group(1)) <= 9999 else None


def recent(date, today):
    import datetime
    try:
        when = datetime.date.fromisoformat(date[:10]) if len(date) >= 10 else datetime.date(int(date[:4]), 12, 31)
    except (ValueError, TypeError):
        return False
    return (datetime.date.fromisoformat(today) - when).days <= RECENT_DAYS


def read_rows(fetcher, today):
    try:
        constants, sources = load(fetcher)
    except Exception as e:
        return [], [{"source": "leaps", "reason": f"Leaps in Bounds data not read: {e}"}]
    try:
        oeis = {fam: oeis_values(fetcher, fam) for fam in OEIS}
    except Exception as e:
        oeis = {}
        oeis_problem = {"source": "oeis", "reason": f"OEIS not read: {e}"}
    else:
        oeis_problem = None
    rows, problems = [], ([oeis_problem] if oeis_problem else [])
    for key, c in sorted(constants.items()):
        if not isinstance(key, str) or not CONSTANT_RE.match(key):
            continue
        try:
            row = constant_row(key, c, sources, oeis, today)
        except Exception as e:  # one malformed entry is dropped with its reason; the others still run
            problems.append({"source": "leaps", "row": key, "reason": f"entry not read ({type(e).__name__}: "
                                                                      f"{str(e)[:120]})"})
            continue
        if isinstance(row, str):
            problems.append({"source": "leaps", "row": key, "reason": row})
            continue
        rows.append(row)
    return rows, problems


def constant_row(key, c, sources, oeis, today):
    """The row of one constant, or a text saying why it cannot be read."""
    m = CONSTANT_RE.match(key)
    if not isinstance(c, dict):
        return "the entry is not an object"
    fam, k = m.group(1), int(m.group(2))
    if not 1 <= k <= 16:
        return "the number of colours is outside 1 to 16"
    lower, upper = integer(c.get("lower_bound")), integer(c.get("upper_bound"))
    if lower is None:
        return "lower bound is not a whole number"
    if upper is not None and upper < lower:
        return f"the upper bound {upper} is below the lower bound {lower}"
    source_name = "Leaps in Bounds, " + ("weak Schur numbers" if fam == "weak-schur" else "Schur numbers")
    by, year, date = credit(c, lower, sources, source_name)
    witness = None
    for cert in dicts(c.get("certificates")):
        if cert.get("bound") == "lower" and cert.get("value") == lower and cert.get("kind") == "witness" \
                and cert.get("status") == "verified":
            path = safe_path(cert.get("path"), f"certificates/{fam}/")
            if path and path.endswith(".yml"):
                witness = path
                break
    params = {"colours": k, "weak": fam == "weak-schur"}
    row = make_row(FAMILY, params, lower, "max", by=by, year=year, sourceName=source_name,
                   sourceUrl=SITE + key + "/",
                   objectUrl=BLOB + witness if witness else None,
                   objectLicence=LICENCE if witness else None,
                   provedOptimal=exact_reading(c, lower, upper), upperOrLowerLimit=upper, readOn=today,
                   source="leaps", recent=recent(date, today), instanceSize=lower, labels=[],
                   objectRef={"path": witness} if witness else None, secondary=[],
                   constant=key, discoveredOn=date or None)
    seq = oeis.get(fam)
    if seq:
        name, url, terms, stated = seq
        if k in terms:
            row["secondary"].append({"name": f"OEIS {name} (data)", "value": str(terms[k]), "url": url,
                                     "exact": True})
        elif k in stated:
            row["secondary"].append({"name": f"OEIS {name} (comments, largest a({k}) >= v)",
                                     "value": str(stated[k]), "url": url, "exact": False})
    return row


def oeis_values(fetcher, fam):
    """(name, url, {k: proved term}, {k: largest lower bound stated as 'a(k) >= v'}) of the family's sequence."""
    name, url = OEIS[fam]
    text, _ = fetcher.text(url, max_age_hours=24 * 7)
    offset, data, stated = None, [], {}
    for line in text.splitlines()[:2000]:
        line = line[:2000]
        if line.startswith("%O " + name):
            offset = int(line.split()[2].split(",")[0])
        elif line[:2] in ("%S", "%T", "%U") and line[3:3 + len(name)] == name:
            data.append(line.split(None, 2)[2].strip() if len(line.split(None, 2)) > 2 else "")
        elif line.startswith("%C " + name):
            for a, v in re.findall(r"a\((\d{1,3})\) ?>= ?(\d{1,12})", line):
                stated[int(a)] = max(stated.get(int(a), 0), int(v))
    if offset is None:
        raise Unavailable(f"{name} has no offset line")
    terms = [int(t) for t in ",".join(data).split(",")[:200] if re.fullmatch(r" ?\d{1,15}", t)]
    return name, url, {offset + i: t for i, t in enumerate(terms)}, stated


def sorting_secondary(fetcher):
    """{(n, measure): (upper bound, exact)} from Leaps in Bounds' sorting network constants."""
    try:
        constants, _ = load(fetcher)
    except Exception:
        return {}
    out = {}
    for key, c in constants.items():
        m = re.match(r"^sorting-network-(size|depth)-(\d{1,3})$", key) if isinstance(key, str) else None
        if m and isinstance(c, dict):
            upper = integer(c.get("upper_bound"))
            out[(int(m.group(2)), m.group(1))] = (upper, exact_reading(c, integer(c.get("lower_bound")), upper))
    return out


# ---------------------------------------------------------------------------- certificates
def yaml_fields(text):
    """The few fields of a certificate file, read from its simple YAML. Refuses what it does not understand."""
    out, section = {}, None
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        i += 1
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        m = re.match(r"^\s*([A-Za-z_][\w-]*):\s?(.*)$", line)
        if not m:
            raise Unavailable("the certificate file has a line that is not 'key: value'")
        key, value = m.group(1), m.group(2).strip()
        if indent == 0:
            section = key if value == "" else None
            name = key
        elif indent == 2 and section:
            name = section + "." + key
        else:
            raise Unavailable("the certificate file is nested deeper than this reader takes")
        if value in ("|", "|-", ">", ">-", "|+", ">+"):
            block = []
            while i < len(lines) and (not lines[i].strip() or len(lines[i]) - len(lines[i].lstrip(" ")) > indent):
                block.append(lines[i].strip())
                i += 1
            value = "\n".join(block)
        elif value.startswith("'") and value.endswith("'") and len(value) >= 2:
            value = value[1:-1].replace("''", "'")
        elif value.startswith('"') and value.endswith('"') and len(value) >= 2:
            value = value[1:-1]
        elif value.startswith(("'", '"')):
            raise Unavailable("the certificate file has a quoted value over several lines")
        out[name] = value
    return out


def bounded_decompress(body, name, limit=MAX_WITNESS_BYTES):
    """A .gz or .xz witness decompressed to at most `limit` bytes; Unavailable when it would grow past it."""
    if name.endswith(".gz"):
        d = zlib.decompressobj(16 + zlib.MAX_WBITS)
        out = d.decompress(body, limit + 1)
        if len(out) > limit or d.unconsumed_tail:
            raise Unavailable(f"the witness grows past {limit:,} bytes when unpacked")
        return out
    if name.endswith(".xz"):
        d = lzma.LZMADecompressor(memlimit=64 * 1024 * 1024)
        out = d.decompress(body, max_length=limit + 1)
        if len(out) > limit:
            raise Unavailable(f"the witness grows past {limit:,} bytes when unpacked")
        return out
    return body


def fetch_object(fetcher, row):
    ref = row.get("objectRef")
    if not ref:
        raise Unavailable(NO_OBJECT)
    fam = "weak-schur" if row["params"]["weak"] else "schur"
    path = safe_path(ref.get("path"), f"certificates/{fam}/")
    if not path:
        raise Unavailable("the certificate's path is not a plain path inside the repository's certificates")
    text, _ = fetcher.text(RAW + path, max_age_hours=24 * 30, max_bytes=MAX_DOWNLOAD)
    fields = yaml_fields(text)
    k = row["params"]["colours"]
    if fields.get("kind") != "witness" or fields.get("witness.format") != "coloring":
        raise Unavailable(f"the certificate is not a colouring witness (format {str(fields.get('witness.format'))[:30]})")
    if fields.get("bound") != "lower" or fields.get("value") != row["bestKnownValue"]:
        raise Unavailable("the certificate's bound or value is not the table's")
    if "witness.data" in fields:
        data = fields["witness.data"]
        url = RAW + path
    elif "witness.file" in fields:
        name = fields["witness.file"]
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,120}", name) or ".." in name:
            raise Unavailable("the witness file name is not a plain file name")
        url = RAW + path.rsplit("/", 1)[0] + "/" + name
        status, body, _ = fetcher.get(url, max_age_hours=24 * 30, max_bytes=MAX_DOWNLOAD)
        if status != 200:
            raise Unavailable(f"the witness file answered {status}")
        body = bounded_decompress(body, name)
        if len(body) > MAX_WITNESS_BYTES:
            raise Unavailable("the witness is larger than this finder takes")
        data = body.decode("ascii", "replace")
    else:
        raise Unavailable("the certificate holds neither data nor a file (a generator or a link: not used)")
    if len(data) > MAX_WITNESS_BYTES:
        raise Unavailable("the witness is larger than this finder takes")
    colours = []
    for ch in data:
        if ch.isspace():
            continue
        v = int(ch, 36) if ch.isalnum() and ch.isascii() else None
        if v is None or v >= k:
            raise Unavailable(f"the witness has the character {ch!r}, not a colour from 0 to {k - 1}")
        colours.append(v)
        if len(colours) > 60000:
            raise Unavailable("the witness is longer than the family's checker takes")
    return {"k": k, "N": len(colours), "colours": colours}, {"url": url, "licence": LICENCE, "copyable": True}
