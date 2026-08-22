"""Fetcher behavior: block/challenge detection, 404/403/429/5xx handling, retries.
Uses httpx's MockTransport so these run offline against canned responses instead of
the live site.
"""
from __future__ import annotations

from urllib.robotparser import RobotFileParser

import httpx
import pytest

from scraper.fetcher import Fetcher, FetcherConfig, _looks_blocked, _parse_retry_after


def _fetcher(handler, **config_kwargs) -> Fetcher:
    f = Fetcher(FetcherConfig(delay_seconds=0, backoff_base_seconds=0.01, **config_kwargs))
    f._client = httpx.Client(transport=httpx.MockTransport(handler), headers=f._client.headers)
    # These tests exercise fetch()/retry logic against a mock handler that responds
    # to every request identically (or by call count) — a real robots.txt fetch
    # would consume one of those calls and desync the handlers' call-count
    # assertions. Pre-seed a permissive robots state so fetch() skips straight to
    # the page request; robots.txt behavior itself is covered by dedicated tests.
    permissive = RobotFileParser()
    permissive.parse([])
    f._robots = permissive
    f._robots_checked_host = "propsearch.ae"
    return f


def test_normal_page_is_not_flagged_as_blocked():
    # A real reCAPTCHA widget's script text is present on every ordinary Propsearch
    # page (see PROPSEARCH_STRUCTURE.md) — a bare "captcha" substring must not trip
    # the block heuristic, or every single page would be misclassified as blocked
    # (this happened during development; see IMPLEMENTATION_STATUS.md bug #1).
    html = "<html><body>Real content <script>grecaptcha.execute()</script></body></html>"
    assert _looks_blocked(html) is False


def test_cloudflare_challenge_page_is_flagged_as_blocked():
    html = "<html><body>Checking your browser before accessing propsearch.ae...</body></html>"
    assert _looks_blocked(html) is True


def test_fetch_returns_html_on_200():
    def handler(request):
        return httpx.Response(200, text="<html>ok</html>")
    f = _fetcher(handler)
    result = f.fetch("https://propsearch.ae/dubai/jvc")
    assert result.status_code == 200
    assert result.html == "<html>ok</html>"
    assert result.error is None
    assert result.blocked is False


def test_fetch_404_is_not_an_error_state_but_not_found():
    def handler(request):
        return httpx.Response(404, text="not found")
    f = _fetcher(handler)
    result = f.fetch("https://propsearch.ae/dubai/does-not-exist")
    assert result.status_code == 404
    assert result.html is None
    assert result.error == "not_found"
    assert result.blocked is False


def test_fetch_403_is_flagged_blocked():
    def handler(request):
        return httpx.Response(403, text="forbidden")
    f = _fetcher(handler)
    result = f.fetch("https://propsearch.ae/dubai/jvc")
    assert result.blocked is True
    assert f.consecutive_blocks == 1


def test_fetch_challenge_page_on_200_is_flagged_blocked():
    def handler(request):
        return httpx.Response(200, text="Please verify you are a human before continuing.")
    f = _fetcher(handler)
    result = f.fetch("https://propsearch.ae/dubai/jvc")
    assert result.status_code == 200
    assert result.blocked is True
    assert result.error == "challenge_detected"


def test_fetch_retries_on_500_then_succeeds():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] < 2:
            return httpx.Response(500, text="server error")
        return httpx.Response(200, text="<html>recovered</html>")
    f = _fetcher(handler, max_retries=3)
    result = f.fetch("https://propsearch.ae/dubai/jvc")
    assert result.html == "<html>recovered</html>"
    assert calls["n"] == 2


def test_fetch_gives_up_after_max_retries_on_persistent_500():
    def handler(request):
        return httpx.Response(500, text="server error")
    f = _fetcher(handler, max_retries=2)
    result = f.fetch("https://propsearch.ae/dubai/jvc")
    assert result.html is None
    assert result.error is not None


def test_consecutive_blocks_resets_on_success():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(403, text="forbidden")
        return httpx.Response(200, text="<html>ok</html>")
    f = _fetcher(handler)
    f.fetch("https://propsearch.ae/dubai/a")
    assert f.consecutive_blocks == 1
    f.fetch("https://propsearch.ae/dubai/b")
    assert f.consecutive_blocks == 0


# -- robots.txt -----------------------------------------------------------------

def _fetcher_with_real_robots(handler, **config_kwargs) -> Fetcher:
    """Unlike _fetcher(), does NOT pre-seed a permissive robots state — used
    specifically to test the robots.txt-loading path itself.
    """
    f = Fetcher(FetcherConfig(delay_seconds=0, backoff_base_seconds=0.01, **config_kwargs))
    f._client = httpx.Client(transport=httpx.MockTransport(handler), headers=f._client.headers)
    return f


def test_robots_txt_disallow_blocks_fetch_without_hitting_the_page():
    calls = []

    def handler(request):
        calls.append(str(request.url))
        if str(request.url).endswith("/robots.txt"):
            return httpx.Response(200, text="User-agent: *\nDisallow: /dubai/blocked-path\n")
        return httpx.Response(200, text="<html>should not be reached</html>")

    f = _fetcher_with_real_robots(handler)
    result = f.fetch("https://propsearch.ae/dubai/blocked-path")
    assert result.error == "robots_disallowed"
    assert result.html is None
    # Only the robots.txt fetch happened — the disallowed page itself was never requested.
    assert calls == ["https://propsearch.ae/robots.txt"]


def test_robots_txt_allow_permits_fetch():
    def handler(request):
        if str(request.url).endswith("/robots.txt"):
            return httpx.Response(200, text="User-agent: *\nDisallow: /dubai/blocked-path\n")
        return httpx.Response(200, text="<html>ok</html>")

    f = _fetcher_with_real_robots(handler)
    result = f.fetch("https://propsearch.ae/dubai/allowed-path")
    assert result.html == "<html>ok</html>"


def test_robots_txt_missing_defaults_to_allow():
    def handler(request):
        if str(request.url).endswith("/robots.txt"):
            return httpx.Response(404, text="not found")
        return httpx.Response(200, text="<html>ok</html>")

    f = _fetcher_with_real_robots(handler)
    result = f.fetch("https://propsearch.ae/dubai/anything")
    assert result.html == "<html>ok</html>"


def test_robots_txt_is_only_fetched_once_per_host():
    calls = {"robots": 0}

    def handler(request):
        if str(request.url).endswith("/robots.txt"):
            calls["robots"] += 1
            return httpx.Response(200, text="User-agent: *\nDisallow:\n")
        return httpx.Response(200, text="<html>ok</html>")

    f = _fetcher_with_real_robots(handler)
    f.fetch("https://propsearch.ae/dubai/a")
    f.fetch("https://propsearch.ae/dubai/b")
    f.fetch("https://propsearch.ae/dubai/c")
    assert calls["robots"] == 1


# -- Retry-After ------------------------------------------------------------------

def test_parse_retry_after_seconds():
    assert _parse_retry_after("120") == 120.0


def test_parse_retry_after_missing_is_none():
    assert _parse_retry_after(None) is None
    assert _parse_retry_after("") is None


def test_parse_retry_after_garbage_is_none():
    assert _parse_retry_after("not-a-date-or-number") is None


def test_parse_retry_after_http_date_is_parsed_as_seconds_from_now():
    from datetime import datetime, timedelta, timezone
    future = datetime.now(timezone.utc) + timedelta(seconds=90)
    header_value = future.strftime("%a, %d %b %Y %H:%M:%S GMT")
    result = _parse_retry_after(header_value)
    assert result is not None
    # Allow a little slack for test execution time.
    assert 85 <= result <= 95


def test_fetch_honors_retry_after_header_on_429(monkeypatch):
    sleeps = []
    monkeypatch.setattr("scraper.fetcher.time.sleep", lambda s: sleeps.append(s))

    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "7"}, text="slow down")
        return httpx.Response(200, text="<html>ok</html>")

    f = _fetcher(handler, max_retries=2)
    result = f.fetch("https://propsearch.ae/dubai/jvc")
    assert result.html == "<html>ok</html>"
    assert 7.0 in sleeps
