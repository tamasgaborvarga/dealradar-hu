"""Polite, safe fetching (docs/SOURCES.md §3). Every adapter request goes through PoliteRequester.

Order per request: fresh cache hit -> robots.txt -> daily cap -> throttle -> transport ->
classify status. Only GET is offered (idempotent, safe to retry). Retried: timeouts, 5xx, and 429
when Retry-After is acceptable. Never retried, never worked around: 401/403/407 and challenge
pages (-> SourceBlocked), robots disallow, other 4xx.
"""

from __future__ import annotations

import base64
import hashlib
import json
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Protocol
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

from dealradar.core.clock import utcnow
from dealradar.sources.errors import (
    ClientError,
    DailyCapReached,
    RateLimited,
    RobotsDisallowed,
    SourceBlocked,
    SourceTimeout,
    SourceUnavailable,
)

USER_AGENT = "DealRadarHU/0.1 (personal, local price tracker; low request rate)"
BLOCK_STATUSES = frozenset({401, 403, 407})
RETRY_STATUSES = frozenset({500, 502, 503, 504})
# A 200 page that is really an anti-bot challenge must be treated as a block, not parsed.
CHALLENGE_MARKERS = (b"captcha", b"cf-challenge", b"are you a robot", b"robotellenorzes")
MAX_BODY_BYTES = 5_000_000


@dataclass(frozen=True)
class TransportResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes


class TransportTimeout(Exception):
    pass


class Transport(Protocol):
    def get(self, url: str, headers: Mapping[str, str], timeout_s: float) -> TransportResponse: ...


@dataclass(frozen=True)
class Response:
    url: str
    status: int
    body: bytes
    fetched_at: datetime
    from_cache: bool = False

    def json(self) -> object:
        return json.loads(self.body.decode("utf-8"))


class ResponseCache:
    """Successful responses on disk, keyed by URL. Expired entries are ignored, not deleted."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def _path(self, url: str) -> Path:
        return self.directory / f"{hashlib.sha256(url.encode('utf-8')).hexdigest()}.json"

    def get(self, url: str, ttl_s: int, now: datetime) -> Response | None:
        path = self._path(url)
        if ttl_s <= 0 or not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        fetched_at = datetime.fromisoformat(data["fetched_at"])
        if now - fetched_at > timedelta(seconds=ttl_s) or data["url"] != url:
            return None
        body = base64.b64decode(data["body"])
        return Response(url, int(data["status"]), body, fetched_at, from_cache=True)

    def put(self, response: Response) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        data = {
            "url": response.url,
            "status": response.status,
            "fetched_at": response.fetched_at.isoformat(),
            "body": base64.b64encode(response.body).decode("ascii"),
        }
        self._path(response.url).write_text(json.dumps(data), encoding="utf-8")


@dataclass
class RequestStats:
    requests: int = 0
    retries: int = 0
    cache_hits: int = 0
    waited_s: float = 0.0


@dataclass
class PoliteRequester:
    transport: Transport
    min_interval_s: float
    timeout_s: float = 20.0
    max_attempts: int = 3
    backoff_base_s: float = 2.0
    max_retry_wait_s: float = 60.0
    daily_cap: int | None = None
    requests_today: int = 0
    cache: ResponseCache | None = None
    cache_ttl_s: int = 0
    check_robots: bool = True
    user_agent: str = USER_AGENT
    clock: Callable[[], datetime] = utcnow
    sleep: Callable[[float], None] = time.sleep
    stats: RequestStats = field(default_factory=RequestStats)
    _last_request_at: datetime | None = None
    _robots: dict[str, RobotFileParser] = field(default_factory=dict)

    # --- public ---

    def get(self, url: str) -> Response:
        now = self.clock()
        if self.cache is not None:
            hit = self.cache.get(url, self.cache_ttl_s, now)
            if hit is not None:
                self.stats.cache_hits += 1
                return hit
        if self.check_robots and not self._robots_allows(url):
            raise RobotsDisallowed(f"a robots.txt tiltja: {url}")
        response = self._get_with_retries(url)
        if self.cache is not None and self.cache_ttl_s > 0:
            self.cache.put(response)
        return response

    # --- internals ---

    def _wait(self, seconds: float) -> None:
        if seconds > 0:
            self.stats.waited_s += seconds
            self.sleep(seconds)

    def _throttle(self) -> None:
        if self._last_request_at is not None:
            elapsed = (self.clock() - self._last_request_at).total_seconds()
            self._wait(self.min_interval_s - elapsed)

    def _send(self, url: str) -> TransportResponse:
        if self.daily_cap is not None and self.requests_today >= self.daily_cap:
            raise DailyCapReached(f"elérte a napi {self.daily_cap} kéréses limitet")
        self._throttle()
        self.requests_today += 1
        self.stats.requests += 1
        try:
            return self.transport.get(url, {"User-Agent": self.user_agent}, self.timeout_s)
        finally:
            self._last_request_at = self.clock()

    def _get_with_retries(self, url: str) -> Response:
        last_error: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            if attempt > 1:
                self.stats.retries += 1
            try:
                raw = self._send(url)
            except TransportTimeout:
                last_error = SourceTimeout(f"időtúllépés {self.timeout_s} mp után: {url}")
                self._backoff(attempt)
                continue
            status = raw.status
            if status in BLOCK_STATUSES:
                raise SourceBlocked(f"HTTP {status}, a hozzáférés megtagadva: {url}")
            if status == 429:
                wait = _retry_after_seconds(raw.headers, self.clock())
                wait = self.backoff_base_s * attempt if wait is None else wait
                if wait > self.max_retry_wait_s or attempt == self.max_attempts:
                    raise RateLimited(
                        f"túl sok kérés, {wait:.0f} mp várakozást kér a forrás: {url}", wait
                    )
                self._wait(wait)
                continue
            if status in RETRY_STATUSES:
                last_error = SourceUnavailable(f"HTTP {status} for {url}")
                self._backoff(attempt)
                continue
            if 400 <= status < 500:
                raise ClientError(f"HTTP {status} for {url}")
            if len(raw.body) > MAX_BODY_BYTES:
                raise ClientError(f"a válasz nagyobb {MAX_BODY_BYTES} bájtnál: {url}")
            if any(marker in raw.body[:20_000].lower() for marker in CHALLENGE_MARKERS):
                raise SourceBlocked(
                    f"robotellenőrző oldal ({url}); nem kerüljük ki, a forrás leáll"
                )
            return Response(url, status, raw.body, self.clock())
        assert last_error is not None
        raise last_error

    def _backoff(self, attempt: int) -> None:
        if attempt < self.max_attempts:
            self._wait(self.backoff_base_s * (2 ** (attempt - 1)))

    def _robots_allows(self, url: str) -> bool:
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https", "mock"):
            return True
        origin = f"{parts.scheme}://{parts.netloc}"
        parser = self._robots.get(origin)
        if parser is None:
            parser = RobotFileParser()
            raw = self._send(f"{origin}/robots.txt")
            if raw.status in BLOCK_STATUSES:
                raise SourceBlocked(f"a robots.txt nem elérhető (HTTP {raw.status})")
            if raw.status >= 400:
                parser.parse([])  # no robots.txt: nothing disallowed by robots (ToS still applies)
            else:
                parser.parse(raw.body.decode("utf-8", errors="replace").splitlines())
            self._robots[origin] = parser
        return parser.can_fetch(self.user_agent, url)


def _retry_after_seconds(headers: Mapping[str, str], now: datetime) -> float | None:
    value = next((v for k, v in headers.items() if k.lower() == "retry-after"), None)
    if value is None:
        return None
    value = value.strip()
    if value.isdigit():
        return float(value)
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return max(0.0, (when - now).total_seconds())
