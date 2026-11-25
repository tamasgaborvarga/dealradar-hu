"""FOOD matching rules.

- GTIN (barcode) is decisive and pins the pack-size variant. Store-internal codes are ignored.
- Rule key brand + product name: candidate only (flavours/variants often share a name).
- Pack size never makes a different *product* - it selects the variant.
- Contradictions: brand, or measurement unit (kg vs l vs piece).
"""

from __future__ import annotations

from dealradar.categories.base import differs
from dealradar.categories.food.attributes import FoodProductAttrs
from dealradar.core.enums import IdType
from dealradar.matching.types import ProductCandidate
from dealradar.normalize.types import NormalizedListing

FUZZY_THRESHOLD = 90
RULE_KEY_DECISIVE = False


def identifier_pins_variant(id_type: IdType) -> bool:
    """A barcode denotes one pack size."""
    return True


def identifier_requires_brand(id_type: IdType) -> bool:
    return id_type is not IdType.GTIN


def rule_key(listing: NormalizedListing) -> str | None:
    if not (listing.brand_key and listing.model_key):
        return None
    return f"{listing.brand_key}|{listing.model_key}"


def product_rule_key(product: ProductCandidate) -> str | None:
    if not (product.brand_key and product.model_key):
        return None
    return f"{product.brand_key}|{product.model_key}"


def contradictions(listing: NormalizedListing, product: ProductCandidate) -> list[str]:
    out = []
    if differs(listing.brand_key, product.brand_key):
        out.append(f"brand {listing.brand_key} != {product.brand_key}")
    attrs = listing.product_attrs
    if isinstance(attrs, FoodProductAttrs) and differs(
        attrs.canonical_unit, product.product_attrs.get("canonical_unit")
    ):
        out.append(f"unit {attrs.canonical_unit} != {product.product_attrs.get('canonical_unit')}")
    return out
