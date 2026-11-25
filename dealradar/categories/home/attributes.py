"""HOME attribute schemas. Product = manufacturer + model number; variant = colour or default."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class DeliveryMethod(StrEnum):
    PARCEL = "PARCEL"
    FREIGHT = "FREIGHT"  # bulky / heavy: courier with 2 people, pallet, own truck
    PICKUP_ONLY = "PICKUP_ONLY"
    UNKNOWN = "UNKNOWN"


class HomeProductAttrs(BaseModel):
    """Stored in ``product_attrs_home``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: str | None = Field(default=None, max_length=64)
    width_mm: int | None = Field(default=None, gt=0)
    height_mm: int | None = Field(default=None, gt=0)
    depth_mm: int | None = Field(default=None, gt=0)
    weight_g: int | None = Field(default=None, gt=0)
    energy_class: str | None = Field(default=None, pattern=r"^[A-G](\+{1,3})?$")
    power_w: int | None = Field(default=None, gt=0)
    noise_db: int | None = Field(default=None, gt=0, lt=200)
    tech_specs: dict[str, str] = Field(default_factory=dict)  # remaining sanitized spec table
    bulky: bool | None = None
    assembly_required: bool | None = None
    installation_required: bool | None = None


class HomeVariantAttrs(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    color: str | None = None


class HomeListingAttrs(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    delivery_method: DeliveryMethod
    dimension_order_assumed: bool = False
