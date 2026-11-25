"""Price history and benchmarks on the shared database (category-aware via the registry)."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.orm import Session

from dealradar.categories.registry import module_for
from dealradar.core.clock import utcnow
from dealradar.core.enums import Actor, Availability, Condition, SaleEvidence
from dealradar.db.models import ObservedSale, Offer, PriceObservation, Product, ProductVariant
from dealradar.db.repositories import ObservedSaleRepository, PriceObservationRepository
from dealradar.db.session import Database
from dealradar.pricing.benchmarks import (
    advertised_benchmark as _advertised,
)
from dealradar.pricing.benchmarks import (
    sold_benchmark as _sold,
)
from dealradar.pricing.benchmarks import (
    unit_price_across_packs as _unit_across,
)
from dealradar.pricing.types import (
    AdvertisedBenchmark,
    BenchmarkKey,
    BenchmarkPolicy,
    Channel,
    ConditionGroup,
    ObservationPoint,
    SalePoint,
    SoldBenchmark,
    UnitPriceBenchmark,
)
from dealradar.services.catalog import ATTRIBUTE_TABLES
from dealradar.services.ledger import own_sale_points

MAX_CLOCK_SKEW = timedelta(minutes=5)


def _check_time(value: datetime, now: datetime, what: str) -> None:
    if value.tzinfo is None:
        raise ValueError(f"{what} must be timezone-aware")
    if value > now + MAX_CLOCK_SKEW:
        raise ValueError(f"{what} is in the future")


# --- writing ---


def record_observation(
    session: Session,
    offer_id: int,
    *,
    observed_at: datetime,
    price_huf: int | None,
    shipping_huf: int | None,
    availability: Availability,
    raw_record_id: int | None = None,
) -> PriceObservation:
    """Append one check of an offer - also when nothing changed since the previous check.

    Source, condition, listing kind and loyalty / multi-buy terms are snapshotted from the
    listing and offer as they are at this moment. Non-HUF offers are refused (no FX data yet).
    """
    _check_time(observed_at, utcnow(), "observed_at")
    offer = session.get(Offer, offer_id)
    if offer is None:
        raise ValueError(f"unknown offer {offer_id}")
    if offer.currency != "HUF":
        raise ValueError("non-HUF prices need an FX rate source, which does not exist yet")
    listing = offer.listing
    obs = PriceObservation(
        offer_id=offer.id,
        source_id=listing.source_id,
        observed_at=observed_at,
        price_huf=price_huf,
        shipping_huf=shipping_huf,
        availability=availability,
        condition=listing.condition,
        listing_kind=listing.listing_kind,
        loyalty_only=offer.loyalty_only,
        min_quantity=offer.min_quantity,
        raw_record_id=raw_record_id,
    )
    session.add(obs)
    session.flush()
    return obs


def record_completed_sale(
    session: Session,
    *,
    variant_id: int,
    platform_id: int,
    evidence: SaleEvidence,
    condition: Condition,
    sale_price_huf: int,
    buyer_shipping_huf: int | None,
    sold_at: datetime,
    source_ref: str,
    entered_by: Actor,
    days_listed: int | None = None,
    listing_id: int | None = None,
    note: str | None = None,
) -> ObservedSale:
    """A completed sale with a known final price. An asking price must never be recorded here."""
    _check_time(sold_at, utcnow(), "sold_at")
    sale = ObservedSale(
        variant_id=variant_id,
        platform_id=platform_id,
        evidence=evidence,
        condition=condition,
        sale_price_huf=sale_price_huf,
        buyer_shipping_huf=buyer_shipping_huf,
        sold_at=sold_at,
        days_listed=days_listed,
        listing_id=listing_id,
        source_ref=source_ref,
        entered_by=entered_by,
        note=note,
    )
    session.add(sale)
    session.flush()
    return sale


# --- reading ---


def _variant_family(session: Session, variant_id: int) -> tuple[ProductVariant, frozenset[int]]:
    variant = session.get(ProductVariant, variant_id)
    if variant is None:
        raise ValueError(f"unknown variant {variant_id}")
    merged = session.scalars(
        select(ProductVariant.id).where(ProductVariant.merged_into_id == variant_id)
    ).all()
    return variant, frozenset({variant_id, *merged})


def policy_for_product(product: Product) -> BenchmarkPolicy:
    return module_for(product.category).benchmark_policy


def _unit_total(variant: ProductVariant) -> Decimal | None:
    raw = (variant.variant_attrs or {}).get("total_canonical")
    if raw is None:
        return None
    try:
        value = Decimal(str(raw))
    except InvalidOperation:
        return None
    return value if value > 0 else None


def _point(obs: PriceObservation, variant_id: int) -> ObservationPoint:
    return ObservationPoint(
        observation_id=obs.id,
        offer_id=obs.offer_id,
        variant_id=variant_id,
        source_id=obs.source_id,
        observed_at=obs.observed_at,
        price_huf=obs.price_huf,
        shipping_huf=obs.shipping_huf,
        availability=obs.availability,
        condition=obs.condition,
        listing_kind=obs.listing_kind,
        loyalty_only=obs.loyalty_only,
        min_quantity=obs.min_quantity,
    )


def advertised_benchmark(
    db: Database,
    variant_id: int,
    condition_group: ConditionGroup,
    channel: Channel,
    now: datetime | None = None,
) -> AdvertisedBenchmark:
    now = now or utcnow()
    with db.read_session() as s:
        variant, family = _variant_family(s, variant_id)
        policy = policy_for_product(variant.product)
        since = now - timedelta(days=policy.window_days)
        rows = PriceObservationRepository(s).for_variants(family, since, now)
        points = [_point(obs, vid) for obs, vid in rows]
        unit_total = _unit_total(variant) if policy.unit_price_basis else None
    return _advertised(
        points,
        BenchmarkKey(variant_id, condition_group, channel),
        policy,
        now,
        variant_ids=family,
        unit_total=unit_total,
    )


def sold_benchmark(
    db: Database, variant_id: int, condition_group: ConditionGroup, now: datetime | None = None
) -> SoldBenchmark:
    now = now or utcnow()
    with db.read_session() as s:
        variant, family = _variant_family(s, variant_id)
        policy = policy_for_product(variant.product)
        since = now - timedelta(days=policy.sold_window_days)
        sales = [
            SalePoint(
                sale_id=x.id,
                variant_id=variant_id,  # merged variants count as the surviving variant
                platform_id=x.platform_id,
                evidence=x.evidence,
                condition=x.condition,
                sale_price_huf=x.sale_price_huf,
                buyer_shipping_huf=x.buyer_shipping_huf,
                sold_at=x.sold_at,
                days_listed=x.days_listed,
            )
            for x in ObservedSaleRepository(s).for_variants(family, since, now)
        ]
        sales += own_sale_points(s, sorted(family), since, now, variant_id)
    return _sold(sales, variant_id, condition_group, policy, now)


def unit_price_across_packs(
    db: Database, product_id: int, channel: Channel, now: datetime | None = None
) -> UnitPriceBenchmark:
    now = now or utcnow()
    with db.read_session() as s:
        product = s.get(Product, product_id)
        if product is None:
            raise ValueError(f"unknown product {product_id}")
        policy = policy_for_product(product)
        if not policy.cross_variant_unit_price:
            raise ValueError(f"{product.category} does not allow comparing different variants")
        totals = {
            v.id: t
            for v in product.variants
            if v.merged_into_id is None and (t := _unit_total(v)) is not None
        }
        attrs = s.get(ATTRIBUTE_TABLES[product.category], product_id)
        unit = getattr(attrs, "canonical_unit", None)
        if unit is None:
            raise ValueError("canonical unit of the product is unknown; pack sizes not comparable")
        since = now - timedelta(days=policy.window_days)
        rows = PriceObservationRepository(s).for_variants(totals, since, now)
        points = [_point(obs, vid) for obs, vid in rows]
    return _unit_across(points, product_id, totals, str(unit), channel, policy, now)
