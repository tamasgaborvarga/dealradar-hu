"""Typed per-category product attribute tables (ADR-012).

The schemas are owned by the category modules (``categories/<cat>/attributes.py``); these tables
persist them column by column. ``tests/test_category_persistence.py`` asserts that every Pydantic
field has a column. Variant-level attributes live in ``product_variants.variant_attrs`` and
listing-level ones in ``listings.category_attrs``. No floats: sizes are integers in small units.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, Boolean, CheckConstraint, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from dealradar.core.enums import CanonicalUnit, SizeSystem
from dealradar.db.base import Base, enum_type


class TechAttributes(Base):
    __tablename__ = "product_attrs_tech"

    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), primary_key=True)
    kind: Mapped[str | None] = mapped_column(String(32))  # categories.tech.attributes.TechKind
    cpu_socket: Mapped[str | None] = mapped_column(String(16))
    gpu_chipset: Mapped[str | None] = mapped_column(String(40))
    ram_type: Mapped[str | None] = mapped_column(String(8))
    ssd_interface: Mapped[str | None] = mapped_column(String(16))
    ssd_form_factor: Mapped[str | None] = mapped_column(String(20))
    screen_diag_tenth_in: Mapped[int | None] = mapped_column(Integer)  # 15.6" -> 156
    resolution: Mapped[str | None] = mapped_column(String(32))
    panel: Mapped[str | None] = mapped_column(String(32))
    refresh_hz: Mapped[int | None] = mapped_column(Integer)
    cpu_model: Mapped[str | None] = mapped_column(String(100))
    gpu_model: Mapped[str | None] = mapped_column(String(100))
    extra: Mapped[dict[str, Any] | None] = mapped_column(JSON)


class ApparelAttributes(Base):
    __tablename__ = "product_attrs_apparel"

    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), primary_key=True)
    gender: Mapped[str | None] = mapped_column(String(16))
    fit: Mapped[str | None] = mapped_column(String(32))
    color: Mapped[str | None] = mapped_column(String(40))
    size_system: Mapped[SizeSystem | None] = mapped_column(enum_type(SizeSystem, "size_system"))
    material: Mapped[str | None] = mapped_column(String(200))
    season: Mapped[str | None] = mapped_column(String(32))
    counterfeit_prone: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    extra: Mapped[dict[str, Any] | None] = mapped_column(JSON)


class FoodAttributes(Base):
    __tablename__ = "product_attrs_food"

    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), primary_key=True)
    canonical_unit: Mapped[CanonicalUnit | None] = mapped_column(
        enum_type(CanonicalUnit, "canonical_unit")
    )
    extra: Mapped[dict[str, Any] | None] = mapped_column(JSON)


class HomeAttributes(Base):
    __tablename__ = "product_attrs_home"
    __table_args__ = (CheckConstraint("weight_g IS NULL OR weight_g > 0", "positive_weight"),)

    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), primary_key=True)
    kind: Mapped[str | None] = mapped_column(String(64))
    energy_class: Mapped[str | None] = mapped_column(String(8))
    width_mm: Mapped[int | None] = mapped_column(Integer)
    height_mm: Mapped[int | None] = mapped_column(Integer)
    depth_mm: Mapped[int | None] = mapped_column(Integer)
    weight_g: Mapped[int | None] = mapped_column(Integer)
    power_w: Mapped[int | None] = mapped_column(Integer)
    noise_db: Mapped[int | None] = mapped_column(Integer)
    tech_specs: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    bulky: Mapped[bool | None] = mapped_column(Boolean)
    assembly_required: Mapped[bool | None] = mapped_column(Boolean)
    installation_required: Mapped[bool | None] = mapped_column(Boolean)
    canonical_unit: Mapped[CanonicalUnit | None] = mapped_column(
        enum_type(CanonicalUnit, "canonical_unit")
    )
    extra: Mapped[dict[str, Any] | None] = mapped_column(JSON)
