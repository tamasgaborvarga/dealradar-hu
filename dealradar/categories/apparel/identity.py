"""CLOTHING_SHOES_SPORT matching rules.

- GTIN identifies one size of one colourway: decisive, and also pins the variant.
- Style code (e.g. sneaker SKU) is decisive together with the brand (stored brand-scoped).
- Rule key brand + model + colour: candidate only (colour names are too coarse for colourways).
- Contradictions: brand, colour, or incompatible gender (UNISEX is compatible with MEN/WOMEN).
"""

from __future__ import annotations

from dealradar.categories.apparel.attributes import ApparelProductAttrs, Gender
from dealradar.categories.base import differs
from dealradar.core.enums import IdType
from dealradar.matching.types import ProductCandidate
from dealradar.normalize.types import NormalizedListing

FUZZY_THRESHOLD = 88
RULE_KEY_DECISIVE = False


def identifier_pins_variant(id_type: IdType) -> bool:
    """Style codes cover all sizes of a colourway; GTINs denote one size."""
    return id_type is not IdType.STYLE_CODE


def identifier_requires_brand(id_type: IdType) -> bool:
    return id_type in (IdType.MPN, IdType.STYLE_CODE)


def rule_key(listing: NormalizedListing) -> str | None:
    if not (listing.brand_key and listing.model_key and listing.color):
        return None
    return f"{listing.brand_key}|{listing.model_key}|{listing.color}"


def product_rule_key(product: ProductCandidate) -> str | None:
    color = product.product_attrs.get("color")
    if not (product.brand_key and product.model_key and color):
        return None
    return f"{product.brand_key}|{product.model_key}|{color}"


def _gender_compatible(a: str | None, b: str | None) -> bool:
    if a is None or b is None or a == b:
        return True
    return Gender.UNISEX in (a, b) and Gender.KIDS not in (a, b)


def contradictions(listing: NormalizedListing, product: ProductCandidate) -> list[str]:
    out = []
    if differs(listing.brand_key, product.brand_key):
        out.append(f"brand {listing.brand_key} != {product.brand_key}")
    attrs = listing.product_attrs
    if isinstance(attrs, ApparelProductAttrs):
        other = product.product_attrs
        if differs(attrs.color, other.get("color")):
            out.append(f"colour {attrs.color} != {other.get('color')}")
        if not _gender_compatible(attrs.gender, other.get("gender")):
            out.append(f"gender {attrs.gender} != {other.get('gender')}")
    return out
