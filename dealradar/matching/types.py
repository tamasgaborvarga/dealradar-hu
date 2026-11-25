"""Matching data shapes. ``ProductCandidate`` is a read-only view built from the database."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol

from dealradar.core.enums import Category, IdType, MatchMethod
from dealradar.normalize.types import NormalizedListing


@dataclass(frozen=True)
class VariantCandidate:
    variant_id: int
    variant_key: str
    identifiers: frozenset[tuple[IdType, str]] = frozenset()
    attrs: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProductCandidate:
    product_id: int
    category: Category
    brand_key: str | None
    model_key: str | None
    title_key: str
    product_attrs: dict[str, Any]
    variants: tuple[VariantCandidate, ...] = ()

    def identifiers(self) -> dict[tuple[IdType, str], int]:
        """(id_type, value) -> variant_id, over all variants."""
        return {ident: v.variant_id for v in self.variants for ident in v.identifiers}

    def variant_by_key(self, key: str) -> VariantCandidate | None:
        return next((v for v in self.variants if v.variant_key == key), None)


class OutcomeKind(StrEnum):
    AUTO_MATCH = "AUTO_MATCH"  # safe to link without review
    REVIEW = "REVIEW"  # candidates exist, user decides
    CONFLICT = "CONFLICT"  # evidence contradicts itself -> user must resolve
    NO_MATCH = "NO_MATCH"


@dataclass(frozen=True)
class ScoredCandidate:
    product_id: int
    method: MatchMethod
    confidence: int  # 0..100
    reason: str


@dataclass(frozen=True)
class MatchOutcome:
    kind: OutcomeKind
    product_id: int | None = None
    variant_id: int | None = None
    method: MatchMethod | None = None
    confidence: int = 0
    reasons: tuple[str, ...] = ()
    candidates: tuple[ScoredCandidate, ...] = ()


class MatchingRules(Protocol):
    """Category-specific matching knowledge consumed by the generic cascade."""

    fuzzy_threshold: int  # 0..100; fuzzy results are never auto-accepted
    rule_key_decisive: bool

    def identifier_requires_brand(self, id_type: IdType) -> bool: ...

    def identifier_pins_variant(self, id_type: IdType) -> bool:
        """True if the identifier denotes one variant (EAN of one size), False if it denotes
        the whole product (a sneaker style code covers every size)."""
        ...

    def rule_key(self, listing: NormalizedListing) -> str | None: ...

    def product_rule_key(self, product: ProductCandidate) -> str | None: ...

    def contradictions(
        self, listing: NormalizedListing, product: ProductCandidate
    ) -> list[str]: ...
