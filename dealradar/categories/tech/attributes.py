"""TECH attribute schemas. Product = model line; variant = configuration / capacity."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class TechKind(StrEnum):
    CPU = "CPU"
    GPU = "GPU"
    RAM = "RAM"
    SSD = "SSD"
    LAPTOP = "LAPTOP"
    MONITOR = "MONITOR"
    OTHER = "OTHER"


class SsdInterface(StrEnum):
    NVME_PCIE3 = "NVME_PCIE3"
    NVME_PCIE4 = "NVME_PCIE4"
    NVME_PCIE5 = "NVME_PCIE5"
    NVME = "NVME"  # PCIe generation not stated
    SATA = "SATA"


class TechProductAttrs(BaseModel):
    """Stored in ``product_attrs_tech`` (one column per field)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: TechKind | None = None
    cpu_socket: str | None = Field(
        default=None, pattern=r"^(AM[2-5]\+?|LGA\d{3,4}|FM2\+?|STRX4|SP[35]|TR5)$"
    )
    gpu_chipset: str | None = Field(default=None, max_length=40)
    ram_type: str | None = Field(default=None, pattern=r"^(LP)?DDR[2-5]X?$")
    ssd_interface: SsdInterface | None = None
    ssd_form_factor: str | None = Field(default=None, max_length=20)
    screen_diag_tenth_in: int | None = Field(default=None, ge=50, le=1000)
    resolution: str | None = Field(default=None, pattern=r"^\d{3,4}x\d{3,4}$")
    panel: str | None = Field(default=None, max_length=16)
    refresh_hz: int | None = Field(default=None, ge=24, le=1000)
    cpu_model: str | None = Field(default=None, max_length=100)
    gpu_model: str | None = Field(default=None, max_length=100)


class TechVariantAttrs(BaseModel):
    """Stored in ``product_variants.variant_attrs`` (JSON)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    capacity_gb: int | None = Field(default=None, gt=0)  # SSD capacity / RAM kit total
    modules: int | None = Field(default=None, ge=1, le=16)  # RAM kit module count
    memory_gb: int | None = Field(default=None, gt=0)  # GPU VRAM / laptop RAM
    storage_gb: int | None = Field(default=None, gt=0)  # laptop storage
    speed_mts: int | None = Field(default=None, ge=400, le=20_000)  # RAM speed


class TechListingAttrs(BaseModel):
    """Stored in ``listings.category_attrs`` (JSON)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    sealed: bool | None = None
    invoice_available: bool | None = None
