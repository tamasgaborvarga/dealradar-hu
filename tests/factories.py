"""Minimal object builders for tests (synthetic data only, no real shops or people)."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy.orm import Session

from dealradar.core.clock import utcnow
from dealradar.core.enums import (
    AccessMethod,
    Availability,
    Category,
    ListingKind,
    PlatformKind,
    ProductOrigin,
)
from dealradar.db.models import (
    Listing,
    Offer,
    Platform,
    PriceObservation,
    Product,
    ProductVariant,
    Source,
)


def source(s: Session, key: str = "manual") -> Source:
    platform = Platform(key=f"p-{key}", name=f"Platform {key}", kind=PlatformKind.OTHER)
    src = Source(
        key=key, name=f"Source {key}", platform=platform, access_method=AccessMethod.MANUAL
    )
    s.add(src)
    s.flush()
    return src


def product(
    s: Session, category: Category = Category.TECH, variant_key: str = "default"
) -> tuple[Product, ProductVariant]:
    prod = Product(category=category, title=f"Test {category}", created_by=ProductOrigin.USER)
    variant = ProductVariant(product=prod, variant_key=variant_key)
    s.add_all([prod, variant])
    s.flush()
    return prod, variant


def offer(s: Session, src: Source, external_id: str = "manual:1") -> Offer:
    listing = Listing(
        source_id=src.id, external_id=external_id, title="t", listing_kind=ListingKind.RETAIL
    )
    off = Offer(listing=listing)
    s.add_all([listing, off])
    s.flush()
    return off


def observe(
    s: Session,
    off: Offer,
    price: int | None = 10_000,
    *,
    hours_ago: float = 1,
    shipping: int | None = None,
    availability: Availability = Availability.IN_STOCK,
) -> PriceObservation:
    obs = PriceObservation(
        offer_id=off.id,
        source_id=off.listing.source_id,
        observed_at=utcnow() - timedelta(hours=hours_ago),
        price_huf=price,
        shipping_huf=shipping,
        availability=availability,
        condition=off.listing.condition,
        listing_kind=off.listing.listing_kind,
        loyalty_only=off.loyalty_only,
        min_quantity=off.min_quantity,
    )
    s.add(obs)
    s.flush()
    return obs
