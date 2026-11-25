"""HOME evaluation inputs."""

from __future__ import annotations

from dealradar.categories.base import common_input_fields
from dealradar.categories.home.attributes import DeliveryMethod, HomeListingAttrs, HomeProductAttrs
from dealradar.core.enums import WarrantyType
from dealradar.evaluation.inputs import CategoryEvaluationInputs
from dealradar.normalize.types import NormalizedListing


class HomeEvaluationInputs(CategoryEvaluationInputs):
    warranty_months: int | None
    warranty_type: WarrantyType | None
    delivery_method: DeliveryMethod
    bulky: bool | None
    assembly_required: bool | None
    installation_required: bool | None
    energy_class: str | None
    dimensions_known: bool


def build(listing: NormalizedListing) -> HomeEvaluationInputs:
    p, la = listing.product_attrs, listing.listing_attrs
    assert isinstance(p, HomeProductAttrs) and isinstance(la, HomeListingAttrs)
    missing, flags = common_input_fields(listing)
    if listing.warranty_months is None:
        missing.append("warranty")
    if la.delivery_method is DeliveryMethod.UNKNOWN:
        missing.append("delivery_requirements")
    return HomeEvaluationInputs(
        category=listing.category,
        price_huf=listing.price_huf,
        shipping_huf=listing.shipping_huf,
        condition=listing.condition,
        seller_kind=listing.seller_kind,
        resale_applicable=True,
        missing_inputs=tuple(missing),
        review_flags=tuple(flags),
        warranty_months=listing.warranty_months,
        warranty_type=listing.warranty_type,
        delivery_method=la.delivery_method,
        bulky=p.bulky,
        assembly_required=p.assembly_required,
        installation_required=p.installation_required,
        energy_class=p.energy_class,
        dimensions_known=bool(p.width_mm and p.height_mm and p.depth_mm),
    )
