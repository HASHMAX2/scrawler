"""Polite HTTP fetching: configurable delay, low concurrency, retries with exponential
backoff, and detection of blocking (403/429/CAPTCHA/Cloudflare challenge) so the crawler
can stop/slow down rather than hammer the site (brief §12).
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx

from scraper.models import FetchResult

logger = logging.getLogger("propsearch.fetcher")

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 PropsearchLocalResearchBot"
)

_BLOCK_MARKERS = (
    "checking your browser",
    "cf-browser-verification",
    "attention required! | cloudflare",
    "please verify you are a human",
    "complete the captcha",
    "solve the captcha",
    "captcha to continue",
    "access denied",
    "sorry, you have been blocked",
    "ray id",  # Cloudflare block-page footer ("Ray ID: ...")
)
# Note: a bare "captcha" substring is deliberately NOT used as a marker — Propsearch
# embeds a normal Google reCAPTCHA Enterprise widget on every ordinary page (see
# PROPSEARCH_STRUCTURE.md), so that alone is not a signal of being blocked.


@dataclass
class FetcherConfig:
    delay_seconds: float = 1.5
    max_concurrency: int = 2
    timeout_seconds: float = 20.0
    max_retries: int = 3
    backoff_base_seconds: float = 2.0
    user_agent: str = USER_AGENT


class BlockedError(Exception):
    """Raised (and caught internally) when the site appears to be actively blocking us."""


class Fetcher:
    """Thin synchronous wrapper around httpx with the brief's politeness rules.

    Synchronous + a single shared client keeps this simple to reason about for a local,
    low-concurrency prototype crawler; a small thread pool provides the "low concurrency"
    knob without pulling in an async framework.
    """

    def __init__(self, config: FetcherConfig | None = None):
        self.config = config or FetcherConfig()
        self._client = httpx.Client(
            headers={
                "User-Agent": self.config.user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            },
            follow_redirects=True,
            timeout=self.config.timeout_seconds,
            http2=True,
        )
        self._last_request_at = 0.0
        self.consecutive_blocks = 0
        self._robots: RobotFileParser | None = None
        self._robots_checked_host: str | None = None

    def close(self):
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def _respect_rate_limit_headers(self, headers, url: str):
        """Propsearch publishes `x-ratelimit-limit` / `x-ratelimit-remaining` response
        headers (observed live — see PROPSEARCH_STRUCTURE.md). When we're close to
        exhausting the budget, proactively slow down rather than waiting to get a 429.
        """
        try:
            remaining = int(headers.get("x-ratelimit-remaining", ""))
            limit = int(headers.get("x-ratelimit-limit", ""))
        except ValueError:
            return
        if limit <= 0:
            return
        if remaining <= max(2, limit * 0.1):
            wait = self.config.backoff_base_seconds
            logger.info("[THROTTLE] %s: %d/%d requests remaining, pausing %.1fs", url, remaining, limit, wait)
            time.sleep(wait)

    def _throttle(self):
        elapsed = time.monotonic() - self._last_request_at
        wait = self.config.delay_seconds - elapsed
        if wait > 0:
            time.sleep(wait)
        self._last_request_at = time.monotonic()

    def _ensure_robots_loaded(self, url: str) -> None:
        """Fetch and parse /robots.txt for `url`'s host, once per host per Fetcher
        lifetime. If the fetch itself fails, defaults to allowing everything (the
        documented state at the time of writing — PROPSEARCH_STRUCTURE.md — but this
        check makes that a live fact rather than a stale assumption if the policy
        ever changes) rather than bricking the crawler on a transient robots.txt
        fetch failure.
        """
        parts = urlsplit(url)
        host = parts.netloc.lower()
        if self._robots_checked_host == host:
            return
        self._robots_checked_host = host
        robots_url = f"{parts.scheme}://{host}/robots.txt"
        parser = RobotFileParser()
        parser.set_url(robots_url)
        try:
            resp = self._client.get(robots_url, timeout=self.config.timeout_seconds)
            if resp.status_code == 200:
                parser.parse(resp.text.splitlines())
                logger.info("[ROBOTS] Loaded %s", robots_url)
            else:
                # No robots.txt (404) or a server error fetching it — RobotFileParser's
                # own convention is "no rules found" == allow everything, which is the
                # correct conservative-but-not-paranoid default here.
                parser.parse([])
                logger.info("[ROBOTS] %s returned %d; treating as no restrictions", robots_url, resp.status_code)
        except httpx.HTTPError as exc:
            parser.parse([])
            logger.warning("[ROBOTS] Failed to fetch %s (%s); treating as no restrictions", robots_url, exc)
        self._robots = parser

    def _robots_allows(self, url: str) -> bool:
        self._ensure_robots_loaded(url)
        if self._robots is None:
            return True
        return self._robots.can_fetch(self.config.user_agent, url)

    def fetch(self, url: str) -> FetchResult:
        if not self._robots_allows(url):
            logger.warning("[ROBOTS] %s disallowed by robots.txt — skipping", url)
            return FetchResult(url=url, final_url=url, status_code=None, html=None, error="robots_disallowed")

        last_error = None
        for attempt in range(1, self.config.max_retries + 1):
            self._throttle()
            try:
                resp = self._client.get(url)
            except httpx.TimeoutException as exc:
                last_error = f"timeout: {exc}"
                logger.warning("[FAILED] %s (attempt %d/%d) timeout", url, attempt, self.config.max_retries)
            except httpx.ConnectError as exc:
                last_error = f"connection error: {exc}"
                logger.warning("[FAILED] %s (attempt %d/%d) connection error", url, attempt, self.config.max_retries)
            except httpx.HTTPError as exc:
                last_error = f"http error: {exc}"
                logger.warning("[FAILED] %s (attempt %d/%d) %s", url, attempt, self.config.max_retries, exc)
            else:
                if resp.status_code == 404:
                    self.consecutive_blocks = 0
                    return FetchResult(url=url, final_url=str(resp.url), status_code=404,
                                        html=None, error="not_found")
                if resp.status_code == 429:
                    last_error = "rate_limited (429)"
                    wait = _parse_retry_after(resp.headers.get("Retry-After"))
                    if wait is None:
                        wait = self.config.backoff_base_seconds * (2 ** (attempt - 1))
                        logger.warning("[BLOCKED] %s rate-limited (429), no Retry-After header, backing off %.1fs", url, wait)
                    else:
                        logger.warning("[BLOCKED] %s rate-limited (429), honoring Retry-After: %.1fs", url, wait)
                    time.sleep(wait)
                    continue
                if resp.status_code == 403:
                    self.consecutive_blocks += 1
                    logger.warning("[BLOCKED] %s returned 403", url)
                    return FetchResult(url=url, final_url=str(resp.url), status_code=403,
                                        html=resp.text if resp.text else None, error="forbidden", blocked=True)
                if resp.status_code >= 500:
                    last_error = f"server error {resp.status_code}"
                    wait = self.config.backoff_base_seconds * (2 ** (attempt - 1))
                    logger.warning("[FAILED] %s server error %d, retrying in %.1fs", url, resp.status_code, wait)
                    time.sleep(wait)
                    continue
                if resp.status_code >= 400:
                    self.consecutive_blocks = 0
                    return FetchResult(url=url, final_url=str(resp.url), status_code=resp.status_code,
                                        html=resp.text if resp.text else None, error=f"http_{resp.status_code}")

                html = resp.text
                if _looks_blocked(html):
                    self.consecutive_blocks += 1
                    logger.warning("[BLOCKED] %s served a challenge/block page", url)
                    return FetchResult(url=url, final_url=str(resp.url), status_code=resp.status_code,
                                        html=html, error="challenge_detected", blocked=True)

                self.consecutive_blocks = 0
                self._respect_rate_limit_headers(resp.headers, url)
                return FetchResult(url=url, final_url=str(resp.url), status_code=resp.status_code,
                                    html=html, error=None)

            wait = self.config.backoff_base_seconds * (2 ** (attempt - 1))
            time.sleep(wait)

        return FetchResult(url=url, final_url=url, status_code=None, html=None, error=last_error)


def _looks_blocked(html: str) -> bool:
    lowered = html[:5000].lower()
    return any(marker in lowered for marker in _BLOCK_MARKERS)


def _parse_retry_after(value: str | None) -> float | None:
    """Retry-After is either a plain integer seconds count or an HTTP-date
    (RFC 7231 §7.1.3). Returns None (caller falls back to exponential backoff) if
    absent or unparseable — never raises.
    """
    if not value:
        return None
    value = value.strip()
    try:
        seconds = float(value)
        return max(0.0, seconds)
    except ValueError:
        pass
    try:
        dt = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if dt is None:
        return None
    now = dt.__class__.now(dt.tzinfo) if dt.tzinfo else dt.__class__.now()
    delta = (dt - now).total_seconds()
    return max(0.0, delta)
