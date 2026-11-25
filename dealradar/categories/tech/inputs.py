"""TECH evaluation inputs (consumed by the Personal/Resale engines in Phases 3-4)."""

from __future__ import annotations

from dealradar.categories.base import common_input_fields
from dealradar.categories.tech.attributes import (
    TechKind,
    TechListingAttrs,
    TechProductAttrs,
    TechVariantAttrs,
)
from dealradar.core.enums import WarrantyType
from dealradar.evaluation.inputs import CategoryEvaluationInputs
from dealradar.normalize.types import NormalizedListing


class TechEvaluationInputs(CategoryEvaluationInputs):
    kind: TechKind | None
    variant_key: str | None
    warranty_months: int | None
    warranty_type: WarrantyType | None
    has_global_identifier: bool
    sealed: bool | None
    invoice_available: bool | None


def build(listing: NormalizedListing) -> TechEvaluationInputs:
    p, v, la = listing.product_attrs, listing.variant_attrs, listing.listing_attrs
    assert isinstance(p, TechProductAttrs) and isinstance(v, TechVariantAttrs)
    assert isinstance(la, TechListingAttrs)
    missing, flags = common_input_fields(listing)
    if listing.warranty_months is None:
        missing.append("warranty")
    if listing.variant_key is None:
        missing.append("variant")
    if p.kind is None:
        flags.append("kind_unknown")
    return TechEvaluationInputs(
        category=listing.category,
        price_huf=listing.price_huf,
        shipping_huf=listing.shipping_huf,
        condition=listing.condition,
        seller_kind=listing.seller_kind,
        resale_applicable=True,
        missing_inputs=tuple(missing),
        review_flags=tuple(flags),
        kind=p.kind,
        variant_key=listing.variant_key,
        warranty_months=listing.warranty_months,
        warranty_type=listing.warranty_type,
        has_global_identifier=bool(listing.identifiers),
        sealed=la.sealed,
        invoice_available=la.invoice_available,
    )
