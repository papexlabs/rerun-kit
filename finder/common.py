"""Shared helpers: rows, hashes, canonical bytes, small HTML helpers."""

import datetime
import hashlib
import html
import json
import os
import re
import unicodedata

FINDER = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.dirname(FINDER)  # the kit this folder is part of
FAMILIES = os.path.join(KIT, "families")  # the kit's families: one copy of each checker in the repository
# Downloads are kept out of the repository: $PAPEX_FINDER_CACHE, else ~/.cache/papex-finder.
CACHE = os.environ.get("PAPEX_FINDER_CACHE") or os.path.join(os.path.expanduser("~"), ".cache", "papex-finder")

ROW_KEYS = ("family", "params", "bestKnownValue", "direction", "by", "year", "sourceName", "sourceUrl", "objectUrl",
            "objectLicence", "provedOptimal", "upperOrLowerLimit", "readOn")


class Unavailable(Exception):
    """A row's object (or a value) that cannot be had today, and why, in plain words."""


def today():
    return datetime.date.today().isoformat()


def sha256_hex(data):
    return hashlib.sha256(data).hexdigest()


def canonical_bytes(obj):
    """The contract's canonical bytes of an object."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii")


def params_key(params):
    return json.dumps(params, sort_keys=True, separators=(",", ":"))


def row_id(family, params):
    return family + " " + params_key(params)


def make_row(family, params, value, direction, **more):
    """A normalized row (the contract of this finder): every field named, extra fields after them."""
    row = {"family": family, "params": params, "bestKnownValue": str(value), "direction": direction,
           "by": None, "year": None, "sourceName": None, "sourceUrl": None, "objectUrl": None,
           "objectLicence": None, "provedOptimal": False, "upperOrLowerLimit": None, "readOn": today()}
    row.update(more)
    row["id"] = row_id(family, params)
    return row


def checker_path(family):
    return os.path.join(FAMILIES, family, "checker.py")


def checker_sha256(family):
    with open(checker_path(family), "rb") as fh:
        return "0x" + sha256_hex(fh.read())


TAG_RE = re.compile(r"<[^>]*>")


def strip_tags(text):
    return html.unescape(TAG_RE.sub("", text))


def squash(text):
    return re.sub(r"\s+", " ", text).strip()


def git_blob_sha1(data):
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def utf16_length(text):
    return len(text.encode("utf-16-le")) // 2


# ---------------------------------------------------------------------------- third-party text and paths
NAME_MAX = 100


def safe_name(text, limit=NAME_MAX):
    """A third-party name (an author list, a contributor's handle, a table's label text) when it is plainly a name:
    letters of any script, digits, spaces, dots, hyphens, apostrophes, commas and parentheses only, at most `limit`
    characters, no URL; otherwise None. " & " is read as " and ". Nothing else from a source reaches a card's text."""
    if not isinstance(text, str) or any(unicodedata.category(ch)[0] == "C" for ch in text):
        return None  # control and format characters (line breaks, tabs, zero-width and direction marks)
    text = squash(text.replace(" & ", " and "))
    if not text or len(text) > limit or "://" in text or "www." in text.lower():
        return None
    if not all(ch.isalnum() and ch != "_" or ch in " .-'\u2019,()" for ch in text):
        return None
    if not any(ch.isalpha() for ch in text):
        return None
    return text


def as_listed(source_name):
    return f"as listed in {source_name}"


SEGMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def safe_path(path, prefix, max_segments=6):
    """`path` when it is a relative path under `prefix` made of plain segments (letters, digits, dot, underscore,
    hyphen; never "." or ".."); otherwise None. Links are built only from such paths."""
    if not isinstance(path, str) or not path.startswith(prefix) or "\\" in path or "%" in path:
        return None
    parts = path.split("/")
    if len(parts) > max_segments or any(p in (".", "..") or not SEGMENT_RE.match(p) for p in parts):
        return None
    return path


def blocks(text, start, end, limit=20000):
    """The texts between each `start` and the next `end`, in order, found with str.find (linear in the text), at
    most `limit` of them: no regular expression scans the whole page for these."""
    out, at = [], 0
    while len(out) < limit:
        i = text.find(start, at)
        if i < 0:
            break
        j = text.find(end, i + len(start))
        if j < 0:
            break
        out.append(text[i + len(start):j])
        at = j + len(end)
    return out
