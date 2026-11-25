"""Builders for category tests. All data is synthetic: no real shops, prices or people."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from dealradar.core.enums import Category, ListingKind, SellerKind
from dealradar.matching.types import ProductCandidate, VariantCandidate
from dealradar.normalize.types import NormalizedListing, RawListing
from dealradar.services.catalog import normalize

OBSERVED = datetime(2026, 11, 24, 10, 0, tzinfo=UTC)


def gtin(body: str) -> str:
    """Append the GS1 check digit to a 7/11/12/13-digit body."""
    total = sum(int(d) * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(body)))
    return body + str((10 - total % 10) % 10)


def raw(title: str, **overrides: Any) -> RawListing:
    data: dict[str, Any] = {
        "source_key": "manual",
        "external_id": "manual:1",
        "title": title,
        "listing_kind": ListingKind.RETAIL,
        "observed_at": OBSERVED,
        "price_text": "10 000 Ft",
        "shipping_text": "ingyenes szállítás",
        "condition_text": "új",
        "seller_kind": SellerKind.RETAILER,
    }
    data.update(overrides)
    return RawListing(**data)


def norm(category: Category, title: str, **overrides: Any) -> NormalizedListing:
    return normalize(raw(title, **overrides), category)


def codes(listing: NormalizedListing) -> set[str]:
    return {i.code for i in listing.issues}


def error_codes(listing: NormalizedListing) -> set[str]:
    return {i.code for i in listing.issues if i.severity == "ERROR"}


def candidate(
    listing: NormalizedListing, product_id: int = 1, variant_id: int = 10, **overrides: Any
) -> ProductCandidate:
    """A stored product as it would look if created from ``listing``."""
    attrs = listing.product_attrs.model_dump(mode="json") if listing.product_attrs else {}
    data: dict[str, Any] = {
        "product_id": product_id,
        "category": listing.category,
        "brand_key": listing.brand_key,
        "model_key": listing.model_key,
        "title_key": listing.title_key,
        "product_attrs": attrs,
        "variants": (
            VariantCandidate(
                variant_id=variant_id,
                variant_key=listing.variant_key or "default",
                identifiers=frozenset((i.id_type, i.value) for i in listing.identifiers),
            ),
        ),
    }
    data.update(overrides)
    return ProductCandidate(**data)
