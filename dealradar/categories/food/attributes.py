"""FOOD attribute schemas. Product = brand + product; variant = pack size."""

from __future__ import annotations

from datetime import date
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from dealradar.core.enums import CanonicalUnit


class DateKind(StrEnum):
    BEST_BEFORE = "BEST_BEFORE"  # "Minőségét megőrzi" - quality, may still be safe after
    USE_BY = "USE_BY"  # "Fogyasztható" - safety limit


class FoodProductAttrs(BaseModel):
    """Stored in ``product_attrs_food``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    canonical_unit: CanonicalUnit | None = None


class FoodVariantAttrs(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    pack_count: int | None = Field(default=None, ge=1)
    each_amount: str | None = None  # decimal as text, e.g. "330"
    each_unit: str | None = None  # Unit value: G, KG, ML, CL, DL, L, PIECE, M2
    total_canonical: str | None = None  # decimal text in canonical unit, e.g. "1.98" (L)


class FoodListingAttrs(BaseModel):
    """Stored in ``listings.category_attrs``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    unit_price_chuf: int | None = Field(default=None, ge=0)  # computed from price and pack
    shelf_unit_price_chuf: int | None = Field(default=None, ge=0)  # as printed by the shop
    best_before: date | None = None
    date_kind: DateKind | None = None
