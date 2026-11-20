"""Reading public pages politely: robots.txt first, its crawl delay, a plain generic User-Agent, a cache on disk,
never the same URL twice in one run, and a request budget per host.

Everything read here is data: it is parsed, never executed.
"""

import datetime
import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser

USER_AGENT = "Mozilla/5.0 (compatible; table-reader/1.0)"
ROBOTS_TOKEN = "table-reader"
TIMEOUT = 40
MAX_BYTES = 2 * 1024 * 1024  # a body is refused above this unless the caller allows more (max_bytes)
HARD_MAX_BYTES = 16 * 1024 * 1024  # never more than this, for any body
MIN_DELAY = 1.0  # seconds between two requests to one host, when robots.txt asks for none
MAX_REDIRECTS = 3
# Hosts a program of Papex never reads (owner's rules, 20 Nov).
BLOCKED_HOSTS = ("erdosproblems.com", "coveringrepository.com", "codetables.de")
# arXiv: only /abs/ and /html/ pages.
ARXIV_HOSTS = ("arxiv.org", "export.arxiv.org")


class FetchError(Exception):
    """A URL that was not read, and why (refused by a rule, robots.txt, the budget, or the network)."""


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def _host(url):
    return (urllib.parse.urlsplit(url).hostname or "").lower()


def _blocked(host):
    return any(host == h or host.endswith("." + h) for h in BLOCKED_HOSTS)


def rule_problem(url):
    """Why a URL may not be read at all (None: it may, subject to robots.txt)."""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https":
        return "not an https address"
    host = (parts.hostname or "").lower()
    if not host:
        return "no host"
    if _blocked(host):
        return f"{host} is never read by this program"
    if any(host == h or host.endswith("." + h) for h in ARXIV_HOSTS):
        if not (parts.path.startswith("/abs/") or parts.path.startswith("/html/")):
            return "arXiv is read only at /abs/ and /html/"
    return None


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Fetcher:
    """One run's reader. `budgets` maps a host to the most requests this run may send it (robots.txt included);
    hosts not named get `default_budget`. Ages are in hours: a cached copy younger than `max_age_hours` is used
    without a request; `None` means a cached copy never goes stale (content-addressed URLs)."""

    def __init__(self, cache_dir, budgets=None, default_budget=10, offline=False, log=None, sleep=time.sleep,
                 opener=None):
        self.cache_dir = os.path.abspath(cache_dir)
        self.budgets = dict(budgets or {})
        self.default_budget = default_budget
        self.offline = offline
        self.sleep = sleep
        self.log = log if log is not None else []
        self.memo = {}  # url -> (status, body) for this run
        self.requests = {}  # host -> requests sent this run
        self.hits = {}  # host -> URLs served from the cache this run (no request)
        self.robots = {}  # host -> RobotFileParser, or a refusal text
        self.last = {}  # host -> time of the last request
        self.opener = opener or urllib.request.build_opener(_NoRedirect())

    # -------------------------------------------------------------------- cache
    def _paths(self, url):
        key = hashlib.sha256(url.encode("utf-8")).hexdigest()[:32]
        folder = os.path.join(self.cache_dir, _host(url) or "_")
        return os.path.join(folder, key + ".body"), os.path.join(folder, key + ".meta.json")

    def cached(self, url):
        """(meta, body) of the cached copy, or (None, None)."""
        body_path, meta_path = self._paths(url)
        try:
            with open(meta_path, encoding="utf-8") as fh:
                meta = json.load(fh)
            with open(body_path, "rb") as fh:
                body = fh.read()
        except (OSError, ValueError):
            return None, None
        if meta.get("url") != url or hashlib.sha256(body).hexdigest() != meta.get("sha256"):
            return None, None
        return meta, body

    def _store(self, url, status, body, content_type):
        body_path, meta_path = self._paths(url)
        os.makedirs(os.path.dirname(body_path), exist_ok=True)
        meta = {"url": url, "status": status, "fetchedAt": _now().isoformat(timespec="seconds"),
                "sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body), "contentType": content_type}
        tmp = body_path + ".part"
        with open(tmp, "wb") as fh:
            fh.write(body)
        os.replace(tmp, body_path)
        tmp = meta_path + ".part"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(meta, fh, sort_keys=True)
        os.replace(tmp, meta_path)
        return meta

    # -------------------------------------------------------------------- robots
    def _robots(self, url):
        parts = urllib.parse.urlsplit(url)
        host = (parts.hostname or "").lower()
        if host in self.robots:
            return self.robots[host]
        robots_url = f"{parts.scheme}://{parts.netloc}/robots.txt"
        parser = urllib.robotparser.RobotFileParser()
        try:
            for _ in range(MAX_REDIRECTS + 1):
                status, body, meta = self._get(robots_url, max_age_hours=24, robots=False)
                target = urllib.parse.urljoin(robots_url, meta.get("location") or "")
                if status in (301, 302, 303, 307, 308) and meta.get("location") \
                        and urllib.parse.urlsplit(target).path == "/robots.txt" \
                        and not self.redirect_problem(robots_url, target):
                    robots_url = target
                    continue
                break
        except FetchError as e:
            self.robots[host] = f"robots.txt of {host} could not be read ({e}), so nothing is read from it"
            return self.robots[host]
        if 200 <= status < 300:
            parser.parse(body.decode("utf-8", "replace").splitlines())
        elif status in (404, 410):
            parser.allow_all = True
        else:
            self.robots[host] = f"robots.txt of {host} answered {status}, so nothing is read from it"
            return self.robots[host]
        self.robots[host] = parser
        return parser

    def delay(self, host):
        parser = self.robots.get(host)
        wanted = None
        if isinstance(parser, urllib.robotparser.RobotFileParser):
            wanted = parser.crawl_delay(ROBOTS_TOKEN)
        try:
            wanted = float(wanted) if wanted is not None else MIN_DELAY
        except (TypeError, ValueError):
            wanted = MIN_DELAY
        return max(MIN_DELAY, wanted)

    def allowed(self, url):
        """None when robots.txt lets this program read the URL; else the reason it may not."""
        why = rule_problem(url)
        if why:
            return why
        parser = self._robots(url)
        if isinstance(parser, str):
            return parser
        if not parser.can_fetch(ROBOTS_TOKEN, url):
            return f"robots.txt of {_host(url)} does not allow it"
        return None

    # -------------------------------------------------------------------- reading
    def get(self, url, max_age_hours=20, max_bytes=MAX_BYTES):
        """(status, body bytes, meta) for a URL; FetchError when it may not or cannot be read.
        Redirects are followed by hand (at most three), only to https and only to the same host or a host this run
        has a budget for, each hop checked against the rules and robots.txt."""
        for _ in range(MAX_REDIRECTS + 1):
            status, body, meta = self._get(url, max_age_hours=max_age_hours, robots=True, max_bytes=max_bytes)
            if status in (301, 302, 303, 307, 308) and meta.get("location"):
                target = urllib.parse.urljoin(url, meta["location"])
                why = self.redirect_problem(url, target)
                if why:
                    raise FetchError(why)
                url = target
                continue
            return status, body, meta
        raise FetchError("too many redirects")

    def redirect_problem(self, url, target):
        parts = urllib.parse.urlsplit(target)
        if parts.scheme != "https":
            return f"{url} redirects to an address that is not https"
        host = (parts.hostname or "").lower()
        if host != _host(url) and host not in self.budgets:
            return f"{url} redirects to another host ({host[:60]}), which this program does not read"
        return None

    def text(self, url, max_age_hours=20, encoding="utf-8", max_bytes=MAX_BYTES):
        status, body, meta = self.get(url, max_age_hours=max_age_hours, max_bytes=max_bytes)
        if status != 200:
            raise FetchError(f"{url} answered {status}")
        return body.decode(encoding, "replace"), meta

    def _get(self, url, max_age_hours, robots, max_bytes=MAX_BYTES):
        why = rule_problem(url)
        if why:
            raise FetchError(why)
        if url in self.memo:
            return self.memo[url]
        meta, body = self.cached(url)
        if meta is not None:
            fresh = max_age_hours is None
            if not fresh:
                try:
                    age = _now() - datetime.datetime.fromisoformat(meta["fetchedAt"])
                    fresh = age.total_seconds() <= max_age_hours * 3600
                except (KeyError, ValueError):
                    fresh = False
            if (fresh or self.offline) and len(body) > min(max_bytes, HARD_MAX_BYTES):
                raise FetchError(f"{url} is larger than {min(max_bytes, HARD_MAX_BYTES):,} bytes, the most this "
                                 "program reads from it")
            if fresh or self.offline:
                host = _host(url)
                self.hits[host] = self.hits.get(host, 0) + 1
                result = (meta["status"], body, dict(meta, fromCache=True))
                self.memo[url] = result
                return result
        if self.offline:
            raise FetchError(f"not in the cache and this run is offline: {url}")
        if robots:
            refusal = self.allowed(url)
            if refusal:
                self.log.append({"url": url, "refused": refusal})
                raise FetchError(refusal)
        host = _host(url)
        budget = self.budgets.get(host, self.default_budget)
        if self.requests.get(host, 0) >= budget:
            raise FetchError(f"this run's request budget for {host} ({budget}) is used up")
        wait = self.delay(host) - (time.monotonic() - self.last.get(host, -1e9))
        if wait > 0:
            self.sleep(wait)
        self.requests[host] = self.requests.get(host, 0) + 1
        # a plain GET: no body, no cookie, no credential; two headers only
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "identity"},
                                         method="GET")
        cap = min(max_bytes, HARD_MAX_BYTES)
        location = None
        try:
            with self.opener.open(request, timeout=TIMEOUT) as response:
                status = response.status
                body = response.read(cap + 1)
                content_type = response.headers.get("Content-Type", "")
        except urllib.error.HTTPError as e:
            status = e.code
            location = e.headers.get("Location") if e.headers else None
            body = e.read(cap + 1) if hasattr(e, "read") else b""
            content_type = e.headers.get("Content-Type", "") if e.headers else ""
        except (urllib.error.URLError, OSError, ValueError) as e:
            self.last[host] = time.monotonic()
            self.log.append({"url": url, "error": str(e)[:200]})
            raise FetchError(f"{url} could not be read ({str(e)[:120]})")
        self.last[host] = time.monotonic()
        if len(body) > cap:
            raise FetchError(f"{url} is larger than {cap:,} bytes, the most this program reads from it")
        self.log.append({"url": url, "status": status, "bytes": len(body)})
        if status == 200 or status in (404, 410):
            meta = self._store(url, status, body, content_type)
        else:
            meta = {"url": url, "status": status, "fetchedAt": _now().isoformat(timespec="seconds"),
                    "sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body), "contentType": content_type}
        if location:
            meta["location"] = location
        result = (status, body, dict(meta, fromCache=False))
        self.memo[url] = result
        return result

    def blob(self, url, digest, hash_fn, max_bytes=MAX_BYTES):
        """Bytes whose hash_fn(bytes) is `digest`: from the content-addressed store when held, else read once from
        `url`, checked, and kept. A file is read again only when its digest changes."""
        path = os.path.join(self.cache_dir, "_blobs", digest)
        try:
            with open(path, "rb") as fh:
                body = fh.read()
            if hash_fn(body) == digest:
                host = _host(url)
                self.hits[host] = self.hits.get(host, 0) + 1
                return body
        except OSError:
            pass
        status, body, _ = self.get(url, max_age_hours=None, max_bytes=max_bytes)
        if status != 200:
            raise FetchError(f"{url} answered {status}")
        if hash_fn(body) != digest:
            raise FetchError(f"{url} does not have the expected hash {digest[:12]}")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path + ".part", "wb") as fh:
            fh.write(body)
        os.replace(path + ".part", path)
        return body

    def summary(self):
        return {"requests": dict(sorted(self.requests.items())), "fromCache": dict(sorted(self.hits.items())),
                "robots": {h: (p if isinstance(p, str) else "read") for h, p in sorted(self.robots.items())}}
