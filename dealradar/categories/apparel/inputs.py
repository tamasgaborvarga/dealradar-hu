"""CLOTHING_SHOES_SPORT evaluation inputs."""

from __future__ import annotations

from dealradar.categories.apparel.attributes import (
    ApparelListingAttrs,
    ApparelProductAttrs,
    ApparelVariantAttrs,
    AuthenticityRisk,
    Gender,
)
from dealradar.categories.base import common_input_fields
from dealradar.core.enums import SizeSystem
from dealradar.evaluation.inputs import CategoryEvaluationInputs
from dealradar.normalize.types import NormalizedListing


class ApparelEvaluationInputs(CategoryEvaluationInputs):
    size: str | None
    size_system: SizeSystem | None
    color: str | None
    gender: Gender | None
    authenticity_risk: AuthenticityRisk
    authenticity_reasons: tuple[str, ...]


def build(listing: NormalizedListing) -> ApparelEvaluationInputs:
    p, v, la = listing.product_attrs, listing.variant_attrs, listing.listing_attrs
    assert isinstance(p, ApparelProductAttrs) and isinstance(v, ApparelVariantAttrs)
    assert isinstance(la, ApparelListingAttrs)
    missing, flags = common_input_fields(listing)
    if v.size is None:
        missing.append("size")
    if not listing.brand:
        missing.append("brand")
    if la.authenticity_risk is AuthenticityRisk.UNKNOWN:
        flags.append("authenticity_unknown")
    if v.size_inferred:
        flags.append("size_system_inferred")
    return ApparelEvaluationInputs(
        category=listing.category,
        price_huf=listing.price_huf,
        shipping_huf=listing.shipping_huf,
        condition=listing.condition,
        seller_kind=listing.seller_kind,
        resale_applicable=True,
        missing_inputs=tuple(missing),
        review_flags=tuple(sorted(set(flags))),
        size=v.size,
        size_system=v.size_system,
        color=p.color,
        gender=p.gender,
        authenticity_risk=la.authenticity_risk,
        authenticity_reasons=la.authenticity_reasons,
    )
