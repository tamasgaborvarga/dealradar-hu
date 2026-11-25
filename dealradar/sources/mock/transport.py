"""In-process fake transport serving the synthetic catalog over ``mock://`` URLs.

``script`` lets tests make a URL misbehave (429, timeouts, 5xx, 403, challenge pages) a given
number of times before it serves normally.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any
from urllib.parse import parse_qs, urlsplit

from dealradar.core.clock import utcnow
from dealradar.sources.mock.catalog import MARKET, SHOP, huf_text, price_on
from dealradar.sources.requester import TransportResponse, TransportTimeout

PAGE_SIZE = 3
ROBOTS = b"User-agent: *\nDisallow: /private/\nAllow: /\n"
SITES: dict[str, dict[str, list[dict[str, Any]]]] = {
    "mock-shop": SHOP,
    "mock-shop-2": SHOP,
    "mock-market": MARKET,
}
# Second shop prices the same synthetic catalog a few percent differently.
PRICE_FACTOR: dict[str, int] = {"mock-shop": 100, "mock-shop-2": 104, "mock-market": 100}

Scripted = TransportResponse | type[TransportTimeout]


class MockTransport:
    def __init__(self, clock: Callable[[], datetime] = utcnow) -> None:
        self.clock = clock
        self.calls: list[str] = []
        self.script: dict[str, list[Scripted]] = defaultdict(list)

    def fail(self, url_contains: str, *responses: Scripted) -> None:
        self.script[url_contains].extend(responses)

    def get(self, url: str, headers: Mapping[str, str], timeout_s: float) -> TransportResponse:
        self.calls.append(url)
        for marker, queue in self.script.items():
            if marker in url and queue:
                scripted = queue.pop(0)
                if scripted is TransportTimeout:
                    raise TransportTimeout(url)
                assert isinstance(scripted, TransportResponse)
                return scripted
        parts = urlsplit(url)
        site = SITES.get(parts.netloc)
        if site is None:
            return TransportResponse(404, {}, b"unknown host")
        if parts.path == "/robots.txt":
            return TransportResponse(200, {}, ROBOTS)
        if parts.path != "/api/offers":
            return TransportResponse(404, {}, b"not found")
        query = parse_qs(parts.query)
        category = query.get("category", [""])[0]
        page = int(query.get("page", ["1"])[0])
        items = site.get(category, [])
        chunk = items[(page - 1) * PAGE_SIZE : page * PAGE_SIZE]
        day = self.clock().date()
        payload = {
            "items": [
                _render(item, day, i + (page - 1) * PAGE_SIZE, PRICE_FACTOR[parts.netloc])
                for i, item in enumerate(chunk)
            ],
            "next_page": page + 1 if page * PAGE_SIZE < len(items) else None,
        }
        return TransportResponse(
            200, {"Content-Type": "application/json"}, json.dumps(payload).encode()
        )


def _render(item: dict[str, Any], day: Any, index: int, factor: int = 100) -> dict[str, Any]:
    out = {k: v for k, v in item.items() if k not in ("base", "flash")}
    if item.get("base") is not None:
        base = item["base"] * factor // 100
        if item.get("flash") and factor != 100 and day == utcnow().date():
            base = base * 75 // 100  # synthetic flash sale, today only
        out["price"] = huf_text(price_on(base, day, index))
    else:
        out["price"] = item.get("price_text")
    return out


def challenge_page() -> TransportResponse:
    return TransportResponse(200, {}, b"<html>Please complete the CAPTCHA to continue</html>")
