"""CLOTHING_SHOES_SPORT attribute schemas. Product = brand + model + colourway; variant = size."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from dealradar.core.enums import SizeSystem


class Gender(StrEnum):
    MEN = "MEN"
    WOMEN = "WOMEN"
    UNISEX = "UNISEX"
    KIDS = "KIDS"


class Season(StrEnum):
    SPRING_SUMMER = "SPRING_SUMMER"
    AUTUMN_WINTER = "AUTUMN_WINTER"
    ALL_SEASON = "ALL_SEASON"


class AuthenticityRisk(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    UNKNOWN = "UNKNOWN"


class ApparelProductAttrs(BaseModel):
    """Stored in ``product_attrs_apparel``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    gender: Gender | None = None
    fit: str | None = Field(default=None, max_length=32)
    color: str | None = Field(default=None, max_length=40)
    season: Season | None = None
    material: str | None = Field(default=None, max_length=200)
    size_system: SizeSystem | None = None
    counterfeit_prone: bool = False  # set by the user for models often faked


class ApparelVariantAttrs(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    size: str | None = Field(default=None, max_length=16)
    size_system: SizeSystem | None = None
    size_inferred: bool = False  # size system was inferred (e.g. bare "42" -> EU)


class ApparelListingAttrs(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    authenticity_risk: AuthenticityRisk
    authenticity_reasons: tuple[str, ...] = ()
