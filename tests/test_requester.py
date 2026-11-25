"""PoliteRequester: robots.txt, throttling, timeouts, retries, Retry-After, blocking, caching."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from dealradar.sources.errors import (
    ClientError,
    DailyCapReached,
    RateLimited,
    RobotsDisallowed,
    SourceBlocked,
    SourceTimeout,
    SourceUnavailable,
)
from dealradar.sources.mock.transport import MockTransport, challenge_page
from dealradar.sources.requester import (
    PoliteRequester,
    ResponseCache,
    TransportResponse,
    TransportTimeout,
)

URL = "mock://mock-shop/api/offers?category=TECH&page=1"


class FakeClock:
    def __init__(self) -> None:
        self.now = datetime(2026, 11, 24, 12, tzinfo=UTC)
        self.slept: list[float] = []

    def __call__(self) -> datetime:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += timedelta(seconds=seconds)


def requester(transport: MockTransport, clock: FakeClock, **kw: object) -> PoliteRequester:
    args: dict[str, object] = {
        "transport": transport,
        "min_interval_s": 5,
        "clock": clock,
        "sleep": clock.sleep,
        "backoff_base_s": 2,
    }
    args.update(kw)
    return PoliteRequester(**args)  # type: ignore[arg-type]


def test_fetches_robots_once_then_throttles() -> None:
    clock, t = FakeClock(), MockTransport()
    r = requester(t, clock)
    r.get(URL)
    r.get(URL.replace("page=1", "page=2"))
    assert t.calls[0].endswith("/robots.txt") and len([c for c in t.calls if "robots" in c]) == 1
    assert clock.slept == [5, 5]  # after robots.txt and after page 1: min interval respected
    assert r.stats.requests == 3


def test_robots_disallow_is_respected() -> None:
    with pytest.raises(RobotsDisallowed):
        requester(MockTransport(), FakeClock()).get("mock://mock-shop/private/data")


def test_timeouts_and_5xx_are_retried_with_backoff() -> None:
    clock, t = FakeClock(), MockTransport()
    t.fail("api/offers", TransportTimeout, TransportResponse(503, {}, b""))
    r = requester(t, clock)
    assert r.get(URL).status == 200
    assert r.stats.retries == 2 and 2 in clock.slept and 4 in clock.slept  # backoff 2 s, then 4 s


def test_retries_are_bounded() -> None:
    t = MockTransport()
    t.fail("api/offers", TransportTimeout, TransportTimeout, TransportTimeout)
    with pytest.raises(SourceTimeout):
        requester(t, FakeClock()).get(URL)
    t2 = MockTransport()
    t2.fail("api/offers", *[TransportResponse(502, {}, b"")] * 3)
    with pytest.raises(SourceUnavailable):
        requester(t2, FakeClock()).get(URL)


def test_rate_limit_honours_retry_after() -> None:
    clock, t = FakeClock(), MockTransport()
    t.fail("api/offers", TransportResponse(429, {"Retry-After": "30"}, b""))
    assert requester(t, clock).get(URL).status == 200
    assert 30 in clock.slept


def test_rate_limit_with_long_wait_stops() -> None:
    t = MockTransport()
    t.fail("api/offers", TransportResponse(429, {"Retry-After": "3600"}, b""))
    with pytest.raises(RateLimited) as exc:
        requester(t, FakeClock()).get(URL)
    assert exc.value.retry_after_s == 3600


@pytest.mark.parametrize("status", [401, 403, 407])
def test_blocks_are_never_retried(status: int) -> None:
    t = MockTransport()
    t.fail("api/offers", TransportResponse(status, {}, b""))
    r = requester(t, FakeClock())
    with pytest.raises(SourceBlocked):
        r.get(URL)
    assert r.stats.retries == 0


def test_challenge_page_is_a_block_not_data() -> None:
    t = MockTransport()
    t.fail("api/offers", challenge_page())
    with pytest.raises(SourceBlocked, match="nem kerüljük ki"):
        requester(t, FakeClock()).get(URL)


def test_other_client_errors_and_daily_cap() -> None:
    t = MockTransport()
    t.fail("api/offers", TransportResponse(404, {}, b""))
    with pytest.raises(ClientError):
        requester(t, FakeClock()).get(URL)
    with pytest.raises(DailyCapReached):
        requester(MockTransport(), FakeClock(), daily_cap=5, requests_today=5).get(URL)


def test_cache_returns_original_fetch_time(tmp_path: Path) -> None:
    clock, t = FakeClock(), MockTransport()
    cache = ResponseCache(tmp_path)
    first = requester(t, clock, cache=cache, cache_ttl_s=3600).get(URL)
    clock.now += timedelta(minutes=10)
    again = requester(t, clock, cache=cache, cache_ttl_s=3600).get(URL)
    assert again.from_cache and again.fetched_at == first.fetched_at and again.body == first.body
    clock.now += timedelta(hours=2)
    fresh = requester(t, clock, cache=cache, cache_ttl_s=3600).get(URL)
    assert not fresh.from_cache and fresh.fetched_at > first.fetched_at
