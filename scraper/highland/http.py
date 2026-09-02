"""Polite HTTP client: browser TLS impersonation (curl_cffi), per-domain throttling,
robots.txt enforcement, retries with backoff, and structured errors that the pipeline
records as source failures instead of crashing the run."""
from __future__ import annotations

import json
import logging
import random
import time
from typing import Any, Optional
from urllib.parse import urlsplit

from curl_cffi import requests as cr

from .config import DEFAULT_MIN_INTERVAL_S
from .robots import Robots

log = logging.getLogger("highland.http")


class HttpError(Exception):
    def __init__(self, msg: str, status: Optional[int] = None, body: str = ""):
        super().__init__(msg)
        self.status = status
        self.body = body[:500]


class RobotsDisallowed(HttpError):
    pass


class Http:
    def __init__(
        self,
        impersonate: str = "chrome",
        min_interval: float = DEFAULT_MIN_INTERVAL_S,
        timeout: float = 30.0,
        max_retries: int = 3,
        respect_robots: bool = True,
        robots_agent: str = "*",
    ):
        self.impersonate = impersonate
        self.session = cr.Session(impersonate=impersonate)
        self.min_interval = min_interval
        self.timeout = timeout
        self.max_retries = max_retries
        self.respect_robots = respect_robots
        self.robots_agent = robots_agent
        self._last_hit: dict[str, float] = {}
        self._robots: dict[str, Robots] = {}
        self.requests_made = 0

    # ---- robots ----
    def robots_for(self, url: str) -> Robots:
        parts = urlsplit(url)
        key = parts.netloc.lower()
        if key not in self._robots:
            robots_url = f"{parts.scheme}://{parts.netloc}/robots.txt"
            try:
                self._throttle(key, None)
                r = self.session.get(robots_url, timeout=self.timeout)
                self.requests_made += 1
                if r.status_code == 200:
                    self._robots[key] = Robots.parse(r.text)
                elif 400 <= r.status_code < 500:
                    self._robots[key] = Robots.allow_all()
                else:
                    log.warning("robots.txt for %s returned %s; assuming allow", key, r.status_code)
                    self._robots[key] = Robots.allow_all()
            except Exception as e:  # network failure: don't block the run, but say so
                log.warning("robots.txt fetch failed for %s: %s; assuming allow", key, e)
                self._robots[key] = Robots.allow_all()
        return self._robots[key]

    def allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        pq = parts.path or "/"
        if parts.query:
            pq += "?" + parts.query
        return self.robots_for(url).can_fetch(pq, self.robots_agent)

    # ---- throttling ----
    def _throttle(self, domain: str, crawl_delay: Optional[float]) -> None:
        gap = max(self.min_interval, crawl_delay or 0.0)
        last = self._last_hit.get(domain)
        if last is not None:
            wait = gap - (time.monotonic() - last)
            if wait > 0:
                time.sleep(wait + random.uniform(0, 0.25))
        self._last_hit[domain] = time.monotonic()

    # ---- requests ----
    def get(
        self,
        url: str,
        params: Optional[dict[str, Any]] = None,
        headers: Optional[dict[str, str]] = None,
        ok_statuses: tuple[int, ...] = (200,),
    ) -> cr.Response:
        if self.respect_robots and not self.allowed(url):
            raise RobotsDisallowed(f"robots.txt disallows {url}")
        parts = urlsplit(url)
        domain = parts.netloc.lower()
        delay = self.robots_for(url).crawl_delay(self.robots_agent) if self.respect_robots else None
        last_err: Optional[Exception] = None
        for attempt in range(1, self.max_retries + 1):
            self._throttle(domain, delay)
            try:
                r = self.session.get(url, params=params, headers=headers, timeout=self.timeout)
                self.requests_made += 1
            except Exception as e:  # DNS / TLS / timeout
                last_err = e
                log.warning("GET %s attempt %d failed: %s", url, attempt, e)
                time.sleep(2 ** attempt)
                continue
            if r.status_code in ok_statuses:
                return r
            if r.status_code in (429, 500, 502, 503, 504) or (r.status_code == 403 and attempt < self.max_retries):
                last_err = HttpError(f"HTTP {r.status_code} for {url}", r.status_code, r.text)
                log.warning("GET %s -> %s (attempt %d)", url, r.status_code, attempt)
                time.sleep(2 ** attempt + random.uniform(0, 1))
                continue
            raise HttpError(f"HTTP {r.status_code} for {url}", r.status_code, r.text)
        raise HttpError(f"giving up on {url}: {last_err}", getattr(last_err, "status", None), getattr(last_err, "body", ""))

    def get_json(self, url: str, **kw) -> Any:
        r = self.get(url, **kw)
        try:
            return r.json()
        except (json.JSONDecodeError, ValueError) as e:
            # Typical "markup changed" / bot-wall symptom: HTML where JSON was expected.
            raise HttpError(f"non-JSON response from {url}: {e}", r.status_code, r.text)

    def get_text(self, url: str, **kw) -> str:
        return self.get(url, **kw).text
