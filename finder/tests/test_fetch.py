"""The polite reader: robots.txt, crawl delay, the cache, one request per URL per run, budgets, blocked hosts."""

import io
import tempfile
import unittest
import urllib.error

import helpers  # noqa: F401
import fetch
from common import git_blob_sha1


class Response:
    def __init__(self, status, body, headers=None):
        self.status, self._body, self.headers = status, body, headers or {}

    def read(self, n=-1):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeOpener:
    """Answers from a dict {url: (status, body, headers)}; records every request."""

    def __init__(self, answers):
        self.answers, self.calls = answers, []

    def open(self, request, timeout=None):
        url = request.full_url
        self.calls.append((url, request.get_header("User-agent")))
        status, body, headers = self.answers.get(url, (404, b"", {}))
        if status >= 300:
            raise urllib.error.HTTPError(url, status, "x", headers, io.BytesIO(body))
        return Response(status, body, headers)


def fetcher(answers, **kw):
    sleeps = []
    f = fetch.Fetcher(tempfile.mkdtemp(prefix="finder-fetch-"), opener=FakeOpener(answers), sleep=sleeps.append, **kw)
    return f, sleeps


class Robots(unittest.TestCase):
    def test_disallowed_path_is_not_read(self):
        f, _ = fetcher({"https://a.org/robots.txt": (200, b"User-agent: *\nDisallow: /private\n", {}),
                        "https://a.org/ok": (200, b"fine", {})})
        self.assertEqual(f.text("https://a.org/ok")[0], "fine")
        with self.assertRaises(fetch.FetchError):
            f.get("https://a.org/private/x")
        self.assertNotIn("https://a.org/private/x", [u for u, _ in f.opener.calls])

    def test_crawl_delay_is_kept_and_the_agent_is_generic(self):
        f, sleeps = fetcher({"https://b.org/robots.txt": (200, b"User-agent: *\nDisallow:\nCrawl-delay: 5\n", {}),
                             "https://b.org/1": (200, b"1", {}), "https://b.org/2": (200, b"2", {})})
        f.get("https://b.org/1")
        f.get("https://b.org/2")
        self.assertTrue(sleeps and max(sleeps) > 4.0)
        for _, agent in f.opener.calls:
            self.assertEqual(agent, fetch.USER_AGENT)
            self.assertNotIn("@", agent)

    def test_no_robots_file_allows_and_an_error_forbids(self):
        f, _ = fetcher({"https://c.org/x": (200, b"x", {})})  # robots.txt answers 404
        self.assertEqual(f.text("https://c.org/x")[0], "x")
        f, _ = fetcher({"https://d.org/robots.txt": (503, b"", {}), "https://d.org/x": (200, b"x", {})})
        with self.assertRaises(fetch.FetchError):
            f.get("https://d.org/x")

    def test_a_redirect_to_another_host_obeys_that_hosts_robots(self):
        f, _ = fetcher({"https://e.org/x": (301, b"", {"Location": "https://f.org/y"}),
                        "https://f.org/robots.txt": (200, b"User-agent: *\nDisallow: /\n", {}),
                        "https://f.org/y": (200, b"y", {})})
        with self.assertRaises(fetch.FetchError):
            f.get("https://e.org/x")
        self.assertNotIn("https://f.org/y", [u for u, _ in f.opener.calls])


class Rules(unittest.TestCase):
    def test_hosts_never_read_and_arxiv_paths(self):
        f, _ = fetcher({})
        for url in ("https://www.erdosproblems.com/1", "https://coveringrepository.com/", "https://codetables.de/x",
                    "https://arxiv.org/pdf/2511.02864"):
            with self.assertRaises(fetch.FetchError):
                f.get(url)
        self.assertEqual(f.opener.calls, [])
        self.assertIsNone(fetch.rule_problem("https://arxiv.org/abs/2511.02864"))
        self.assertIsNone(fetch.rule_problem("https://arxiv.org/html/2511.02864v1"))


class Cache(unittest.TestCase):
    def test_one_request_per_url_and_the_cache_is_used(self):
        answers = {"https://g.org/x": (200, b"x", {})}
        f, _ = fetcher(answers)
        f.get("https://g.org/x")
        f.get("https://g.org/x", max_age_hours=0)
        self.assertEqual([u for u, _ in f.opener.calls].count("https://g.org/x"), 1)
        again = fetch.Fetcher(f.cache_dir, opener=FakeOpener(answers), sleep=lambda s: None)
        again.get("https://g.org/x", max_age_hours=20)  # fresh in the cache: no request
        self.assertEqual(again.opener.calls, [])
        offline = fetch.Fetcher(f.cache_dir, offline=True)
        self.assertEqual(offline.text("https://g.org/x")[0], "x")
        with self.assertRaises(fetch.FetchError):
            offline.get("https://g.org/never-read")

    def test_budget_per_host(self):
        f, _ = fetcher({"https://h.org/1": (200, b"1", {}), "https://h.org/2": (200, b"2", {})},
                       budgets={"h.org": 2})
        f.get("https://h.org/1")  # robots.txt + this = 2
        with self.assertRaises(fetch.FetchError) as e:
            f.get("https://h.org/2")
        self.assertIn("budget", str(e.exception))

    def test_content_addressed_blobs(self):
        body = b'{"N": 2}'
        digest = git_blob_sha1(body)
        f, _ = fetcher({"https://i.org/a": (200, body, {}), "https://i.org/b": (200, body, {})})
        self.assertEqual(f.blob("https://i.org/a", digest, git_blob_sha1), body)
        self.assertEqual(f.blob("https://i.org/b", digest, git_blob_sha1), body)  # same content: no request
        self.assertNotIn("https://i.org/b", [u for u, _ in f.opener.calls])
        with self.assertRaises(fetch.FetchError):
            f.blob("https://i.org/a", "0" * 40, git_blob_sha1)


if __name__ == "__main__":
    unittest.main()
