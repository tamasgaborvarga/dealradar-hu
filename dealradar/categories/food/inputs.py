"""FOOD evaluation inputs. Resale is NOT_APPLICABLE by default (OPEN-5)."""

from __future__ import annotations

from datetime import date

from dealradar.categories.base import common_input_fields
from dealradar.categories.food.attributes import (
    DateKind,
    FoodListingAttrs,
    FoodProductAttrs,
    FoodVariantAttrs,
)
from dealradar.core.enums import CanonicalUnit
from dealradar.evaluation.inputs import CategoryEvaluationInputs
from dealradar.normalize.types import NormalizedListing


class FoodEvaluationInputs(CategoryEvaluationInputs):
    unit_price_chuf: int | None
    canonical_unit: CanonicalUnit | None
    pack_key: str | None
    total_canonical: str | None
    best_before: date | None
    date_kind: DateKind | None
    days_to_date: int | None


def build(listing: NormalizedListing) -> FoodEvaluationInputs:
    p, v, la = listing.product_attrs, listing.variant_attrs, listing.listing_attrs
    assert isinstance(p, FoodProductAttrs) and isinstance(v, FoodVariantAttrs)
    assert isinstance(la, FoodListingAttrs)
    missing, flags = common_input_fields(listing)
    # Food is sold new by shops; condition is not a meaningful input here.
    missing = [m for m in missing if m != "condition"]
    if listing.variant_key is None:
        missing.append("package_size")
    if la.unit_price_chuf is None:
        missing.append("unit_price")
    days = (la.best_before - listing.observed_at.date()).days if la.best_before else None
    return FoodEvaluationInputs(
        category=listing.category,
        price_huf=listing.price_huf,
        shipping_huf=listing.shipping_huf,
        condition=listing.condition,
        seller_kind=listing.seller_kind,
        resale_applicable=False,
        missing_inputs=tuple(dict.fromkeys(missing)),
        review_flags=tuple(flags),
        unit_price_chuf=la.unit_price_chuf,
        canonical_unit=p.canonical_unit,
        pack_key=listing.variant_key,
        total_canonical=v.total_canonical,
        best_before=la.best_before,
        date_kind=la.date_kind,
        days_to_date=days,
    )
