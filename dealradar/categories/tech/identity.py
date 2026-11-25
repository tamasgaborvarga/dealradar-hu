"""TECH matching rules.

- GTIN: decisive on its own.
- MPN: decisive only together with the manufacturer (stored brand-scoped).
- Rule key manufacturer + model name: candidate only (board-partner GPU and laptop names are
  too similar across variants to auto-accept).
- Contradictions: different kind, socket, GPU chipset, RAM type or SSD interface.
"""

from __future__ import annotations

from dealradar.categories.base import differs
from dealradar.categories.tech.attributes import TechProductAttrs
from dealradar.core.enums import IdType
from dealradar.matching.types import ProductCandidate
from dealradar.normalize.types import NormalizedListing

FUZZY_THRESHOLD = 85
RULE_KEY_DECISIVE = False
_COMPARED = ("kind", "cpu_socket", "gpu_chipset", "ram_type", "ssd_interface")


def identifier_pins_variant(id_type: IdType) -> bool:
    """EAN and MPN denote one configuration / capacity."""
    return True


def identifier_requires_brand(id_type: IdType) -> bool:
    return id_type in (IdType.MPN, IdType.STYLE_CODE)


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
        out.append(f"manufacturer {listing.brand_key} != {product.brand_key}")
    attrs = listing.product_attrs
    if isinstance(attrs, TechProductAttrs):
        mine = attrs.model_dump()
        for field in _COMPARED:
            if differs(mine.get(field), product.product_attrs.get(field)):
                out.append(f"{field} {mine[field]} != {product.product_attrs[field]}")
    return out
