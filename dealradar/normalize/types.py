"""Data shapes of the normalization pipeline (pure, no I/O)."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator

from dealradar.core.enums import (
    Category,
    Condition,
    IdType,
    ListingKind,
    SellerKind,
    WarrantyType,
)

MAX_TITLE = 500
MAX_DESCRIPTION = 5_000
MAX_ATTRIBUTES = 200
MAX_ATTR_KEY = 100
MAX_ATTR_VALUE = 500


class Severity(StrEnum):
    ERROR = "ERROR"  # blocks automatic decisions -> MANUAL_REVIEW
    WARNING = "WARNING"  # recorded, shown to the user, does not block on its own


class Issue(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: str
    field: str
    severity: Severity
    message: str


class RawListing(BaseModel):
    """What a collector or manual import hands over. Every text field is untrusted."""

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    source_key: str
    external_id: str
    title: str = Field(min_length=1)
    listing_kind: ListingKind
    observed_at: datetime
    category_hint: Category | None = None
    url: str | None = None
    brand: str | None = None
    model: str | None = None
    price_text: str | None = None
    price_is_net: bool | None = None
    shipping_text: str | None = None
    condition_text: str | None = None
    warranty_text: str | None = None
    seller_kind: SellerKind | None = None
    gtin: str | None = None
    mpn: str | None = None
    style_code: str | None = None
    variant_text: str | None = None
    color_text: str | None = None
    description: str | None = None
    attributes: dict[str, str] = Field(default_factory=dict)

    @field_validator("observed_at")
    @classmethod
    def _aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("observed_at must be timezone-aware")
        return value

    @field_validator("attributes")
    @classmethod
    def _bounded_attributes(cls, value: dict[str, str]) -> dict[str, str]:
        if len(value) > MAX_ATTRIBUTES:
            raise ValueError(f"at most {MAX_ATTRIBUTES} attributes")
        return value


class Identifier(BaseModel):
    model_config = ConfigDict(frozen=True)

    id_type: IdType
    value: str  # normalized comparison key (GTIN-14, code key)
    raw: str


class NormalizedListing(BaseModel):
    """Generic fields + category-specific attribute models (set by the category module)."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    source_key: str
    external_id: str
    category: Category
    listing_kind: ListingKind
    observed_at: datetime
    title: str
    title_key: str
    description: str | None
    brand: str | None
    brand_key: str | None
    model: str | None
    model_key: str | None
    price_huf: int | None
    shipping_huf: int | None
    pickup_only: bool
    condition: Condition | None
    warranty_months: int | None
    warranty_type: WarrantyType | None
    seller_kind: SellerKind | None
    color: str | None
    variant_text: str | None  # size / pack / configuration as written
    identifiers: tuple[Identifier, ...]
    attributes: dict[str, str]  # sanitized raw spec table, keys case-folded
    product_attrs: BaseModel | None = None
    variant_attrs: BaseModel | None = None
    listing_attrs: BaseModel | None = None
    variant_key: str | None = None
    issues: tuple[Issue, ...] = ()

    def identifier(self, id_type: IdType) -> Identifier | None:
        return next((i for i in self.identifiers if i.id_type is id_type), None)

    def attr(self, *names: str) -> str | None:
        """First present spec-table value among several (HU/EN) key spellings."""
        for name in names:
            value = self.attributes.get(name.casefold())
            if value:
                return value
        return None

    def with_issues(self, *issues: Issue) -> NormalizedListing:
        return self.model_copy(update={"issues": (*self.issues, *issues)})

    @property
    def has_errors(self) -> bool:
        return any(i.severity is Severity.ERROR for i in self.issues)


class CategoryNormalizer(Protocol):
    """The part of a category module that the normalization pipeline needs."""

    def normalize(self, listing: NormalizedListing) -> NormalizedListing: ...

    def validate(self, listing: NormalizedListing) -> list[Issue]: ...


def issue(code: str, field: str, message: str, severity: Severity = Severity.ERROR) -> Issue:
    return Issue(code=code, field=field, severity=severity, message=message)
