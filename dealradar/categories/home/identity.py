"""HOME matching rules.

- GTIN decisive. MPN / appliance model number decisive together with the manufacturer.
- Rule key manufacturer + model number: decisive, but only produced when the model looks like a
  model number (letters and digits, e.g. 'WW80T534DAW'); descriptive names ('Kanapé Oslo')
  give no rule key and fall through to fuzzy review.
- Contradictions: manufacturer, energy class, or any dimension differing by more than 2 %.
"""

from __future__ import annotations

import re

from dealradar.categories.base import differs
from dealradar.categories.home.attributes import HomeProductAttrs
from dealradar.core.enums import IdType
from dealradar.matching.types import ProductCandidate
from dealradar.normalize.types import NormalizedListing

FUZZY_THRESHOLD = 85
RULE_KEY_DECISIVE = True
DIMENSION_TOLERANCE_BP = 200
_CODE = re.compile(r"^(?=.*\d)(?=.*[a-z])[a-z0-9 ]{5,}$")


def identifier_pins_variant(id_type: IdType) -> bool:
    """EAN and model numbers denote one variant."""
    return True


def identifier_requires_brand(id_type: IdType) -> bool:
    return id_type in (IdType.MPN, IdType.STYLE_CODE)


def _key(brand_key: str | None, model_key: str | None) -> str | None:
    if not (brand_key and model_key and _CODE.fullmatch(model_key)):
        return None
    return f"{brand_key}|{model_key.replace(' ', '')}"


def rule_key(listing: NormalizedListing) -> str | None:
    return _key(listing.brand_key, listing.model_key)


def product_rule_key(product: ProductCandidate) -> str | None:
    return _key(product.brand_key, product.model_key)


def contradictions(listing: NormalizedListing, product: ProductCandidate) -> list[str]:
    out = []
    if differs(listing.brand_key, product.brand_key):
        out.append(f"manufacturer {listing.brand_key} != {product.brand_key}")
    attrs = listing.product_attrs
    if not isinstance(attrs, HomeProductAttrs):
        return out
    other = product.product_attrs
    if differs(attrs.energy_class, other.get("energy_class")):
        out.append(f"energy class {attrs.energy_class} != {other.get('energy_class')}")
    for field in ("width_mm", "height_mm", "depth_mm"):
        a, b = getattr(attrs, field), other.get(field)
        if a and b and abs(a - b) * 10_000 > DIMENSION_TOLERANCE_BP * max(a, b):
            out.append(f"{field} {a} != {b}")
    return out
