"""Synthetic price data for pricing tests. Deterministic; no real shops, products or prices."""

from __future__ import annotations

import itertools
import random
from datetime import UTC, datetime, timedelta

from dealradar.core.enums import Availability, Condition, ListingKind, SaleEvidence
from dealradar.pricing.types import (
    BenchmarkKey,
    Channel,
    ConditionGroup,
    ObservationPoint,
    SalePoint,
)

NOW = datetime(2026, 11, 24, 12, 0, tzinfo=UTC)
VARIANT = 1
KEY_NEW_RETAIL = BenchmarkKey(VARIANT, ConditionGroup.NEW, Channel.RETAIL)
_ids = itertools.count(1)


def point(
    offer: int,
    price: int | None,
    *,
    days_ago: float = 0,
    hours_ago: float = 0,
    source: int | None = None,
    variant: int | None = VARIANT,
    shipping: int | None = 0,
    availability: Availability = Availability.IN_STOCK,
    condition: Condition | None = Condition.NEW,
    kind: ListingKind = ListingKind.RETAIL,
    loyalty_only: bool = False,
    min_quantity: int = 1,
) -> ObservationPoint:
    return ObservationPoint(
        observation_id=next(_ids),
        offer_id=offer,
        variant_id=variant,
        source_id=source if source is not None else offer,
        observed_at=NOW - timedelta(days=days_ago, hours=hours_ago),
        price_huf=price,
        shipping_huf=shipping,
        availability=availability,
        condition=condition,
        listing_kind=kind,
        loyalty_only=loyalty_only,
        min_quantity=min_quantity,
    )


def daily(
    offer: int, prices: list[int], *, start_days_ago: int = 0, **kw: object
) -> list[ObservationPoint]:
    """One observation per day, newest first: prices[0] is today (or start_days_ago)."""
    return [point(offer, p, days_ago=start_days_ago + i, **kw) for i, p in enumerate(prices)]  # type: ignore[arg-type]


def market(
    offers: int,
    days: int,
    base: int,
    *,
    spread: float = 0.03,
    seed: int = 7,
    sources: int | None = None,
    **kw: object,
) -> list[ObservationPoint]:
    """A plausible synthetic market: each offer re-priced daily within +-spread of base."""
    rng = random.Random(seed)
    out: list[ObservationPoint] = []
    for o in range(1, offers + 1):
        src = (o % sources) + 1 if sources else o
        for d in range(days):
            price = round(base * (1 + rng.uniform(-spread, spread)))
            out.append(point(o, price, days_ago=d, source=src, **kw))  # type: ignore[arg-type]
    return out


def sale(
    price: int,
    *,
    days_ago: float = 1,
    platform: int = 1,
    evidence: SaleEvidence = SaleEvidence.PLATFORM_FINAL_PRICE,
    condition: Condition = Condition.USED_B,
    buyer_shipping: int | None = 1_500,
    days_listed: int | None = 5,
    variant: int = VARIANT,
) -> SalePoint:
    return SalePoint(
        sale_id=next(_ids),
        variant_id=variant,
        platform_id=platform,
        evidence=evidence,
        condition=condition,
        sale_price_huf=price,
        buyer_shipping_huf=buyer_shipping,
        sold_at=NOW - timedelta(days=days_ago),
        days_listed=days_listed,
    )
