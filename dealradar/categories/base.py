"""Category module contract (ARCHITECTURE.md §4) and small helpers shared by the four modules.

A category module owns: product/variant/listing attribute schemas, normalization, validation,
matching rules (identifier scope, rule key, contradictions, variant key) and evaluation inputs.
Modules never import each other; shared code reaches them only through ``registry``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol

from pydantic import BaseModel

from dealradar.core.enums import Category, IdType
from dealradar.core.hu_parse import ParseError
from dealradar.core.identifiers import code_key, is_restricted_gtin, normalize_gtin, text_key
from dealradar.evaluation.inputs import CategoryEvaluationInputs
from dealradar.evaluation.params import PersonalParams, ResaleParams
from dealradar.matching.types import ProductCandidate
from dealradar.normalize.types import Identifier, Issue, NormalizedListing, Severity, issue
from dealradar.pricing.types import BenchmarkPolicy


class ComparisonBasis(StrEnum):
    ITEM = "ITEM"
    ITEM_PER_SIZE = "ITEM_PER_SIZE"
    UNIT_PRICE = "UNIT_PRICE"


@dataclass(frozen=True)
class CategoryInfo:
    key: Category
    label: str
    scope: str
    variant_means: str
    comparison_basis: ComparisonBasis
    resale_enabled_by_default: bool


class CategoryModule(Protocol):
    info: CategoryInfo
    product_attrs_model: type[BaseModel]
    variant_attrs_model: type[BaseModel]
    listing_attrs_model: type[BaseModel]
    fuzzy_threshold: int
    rule_key_decisive: bool
    benchmark_policy: BenchmarkPolicy  # category-aware benchmark parameters
    personal_params: PersonalParams  # Personal engine defaults
    resale_params: ResaleParams  # Resale engine defaults

    # normalization + validation
    def normalize(self, listing: NormalizedListing) -> NormalizedListing: ...

    def validate(self, listing: NormalizedListing) -> list[Issue]: ...

    # matching rules
    def identifier_requires_brand(self, id_type: IdType) -> bool: ...

    def identifier_pins_variant(self, id_type: IdType) -> bool: ...

    def rule_key(self, listing: NormalizedListing) -> str | None: ...

    def product_rule_key(self, product: ProductCandidate) -> str | None: ...

    def contradictions(
        self, listing: NormalizedListing, product: ProductCandidate
    ) -> list[str]: ...

    # evaluation inputs
    def evaluation_inputs(self, listing: NormalizedListing) -> CategoryEvaluationInputs: ...


# --- helpers ------------------------------------------------------------------------------------


def first_attr(listing: NormalizedListing, *names: str) -> str | None:
    return listing.attr(*names)


def search_text(listing: NormalizedListing) -> str:
    """Title + spec values (not the description: it is long, untrusted and often off-topic)."""
    return " ".join([listing.title, *listing.attributes.values()])


def brand_from(listing: NormalizedListing, *attr_names: str) -> dict[str, Any]:
    """Brand from the explicit field, else from the spec table. Returns model_copy updates."""
    if listing.brand:
        return {}
    value = listing.attr(*attr_names)
    return {"brand": value, "brand_key": text_key(value)} if value else {}


def add_identifier(
    listing: NormalizedListing, id_type: IdType, text: str | None
) -> tuple[tuple[Identifier, ...], list[Issue]]:
    """Add an identifier found in the spec table, unless one of that type already exists."""
    ids = listing.identifiers
    if not text or listing.identifier(id_type) is not None:
        return ids, []
    try:
        if id_type is IdType.GTIN:
            if is_restricted_gtin(text):
                return ids, [
                    issue(
                        "gtin_restricted",
                        "gtin",
                        "store-internal barcode ignored",
                        Severity.WARNING,
                    )
                ]
            value = normalize_gtin(text)
        else:
            value = code_key(text)
    except ParseError as exc:
        return ids, [
            issue(f"{id_type.lower()}_invalid", id_type.lower(), str(exc), Severity.WARNING)
        ]
    return (*ids, Identifier(id_type=id_type, value=value, raw=text)), []


def scope_identifiers(
    ids: tuple[Identifier, ...], brand_key: str | None, scoped: frozenset[IdType]
) -> tuple[Identifier, ...]:
    """Prefix manufacturer-scoped codes (MPN, style code) with the brand key.

    The same part number can exist at two manufacturers; 'samsung|MZV9P2T0BW' cannot.
    Without a brand the code stays unscoped and cannot auto-match (identifier_requires_brand).
    """
    out = []
    for ident in ids:
        if ident.id_type in scoped and brand_key and "|" not in ident.value:
            ident = ident.model_copy(update={"value": f"{brand_key}|{ident.value}"})
        out.append(ident)
    return tuple(out)


def differs(a: Any, b: Any) -> bool:
    """Both known and different."""
    return a is not None and b is not None and a != b


def common_input_fields(listing: NormalizedListing) -> tuple[list[str], list[str]]:
    """Missing inputs and review flags every category shares."""
    missing: list[str] = []
    if listing.price_huf is None:
        missing.append("price")
    if listing.shipping_huf is None and not listing.pickup_only:
        missing.append("shipping")
    if listing.condition is None:
        missing.append("condition")
    flags = sorted({i.code for i in listing.issues if i.severity is Severity.ERROR})
    return missing, flags


def int_or_none(text: str | None) -> int | None:
    if text is None:
        return None
    m = re.search(r"\d+", text)
    return int(m.group()) if m else None
