"""Product identity: products, variants, identifiers (DATABASE_DESIGN.md §3, ADR-014/015)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, CheckConstraint, ForeignKey, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from dealradar.core.clock import utcnow
from dealradar.core.enums import Category, IdType, ProductOrigin
from dealradar.db.base import Base, UTCDateTime, enum_type


class Product(Base):
    """A model / style / product line. Category here is authoritative. STATE."""

    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint("merged_into_id IS NULL OR merged_into_id != id", "no_self_merge"),
        Index("ix_products_category_brand_key", "category", "brand_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    category: Mapped[Category] = mapped_column(enum_type(Category, "category"), index=True)
    subcategory: Mapped[str | None] = mapped_column(String(64))
    brand: Mapped[str | None] = mapped_column(String(200))
    brand_key: Mapped[str | None] = mapped_column(String(200))  # core.identifiers.text_key(brand)
    model_name: Mapped[str | None] = mapped_column(String(300))
    model_key: Mapped[str | None] = mapped_column(String(300))
    title: Mapped[str] = mapped_column(Text)
    created_by: Mapped[ProductOrigin] = mapped_column(enum_type(ProductOrigin, "created_by"))
    merged_into_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)

    variants: Mapped[list[ProductVariant]] = relationship(
        back_populates="product", foreign_keys="ProductVariant.product_id"
    )


class ProductVariant(Base):
    """The 1:1 comparable unit (configuration, size, pack size or 'default'). STATE."""

    __tablename__ = "product_variants"
    __table_args__ = (
        Index("uq_product_variants_product_key", "product_id", "variant_key", unique=True),
        CheckConstraint("merged_into_id IS NULL OR merged_into_id != id", "no_self_merge"),
        CheckConstraint("length(variant_key) > 0", "variant_key_not_empty"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    variant_key: Mapped[str] = mapped_column(String(128), default="default")
    title_suffix: Mapped[str | None] = mapped_column(String(200))
    variant_attrs: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    merged_into_id: Mapped[int | None] = mapped_column(ForeignKey("product_variants.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    product: Mapped[Product] = relationship(back_populates="variants", foreign_keys=[product_id])
    identifiers: Mapped[list[VariantIdentifier]] = relationship(back_populates="variant")


class VariantIdentifier(Base):
    """GTIN / MPN / style code / shop SKU of a variant. STATE.

    Uniqueness: a global identifier (no source) maps to exactly one variant; a SHOP_SKU is unique
    per source. Two partial indexes are needed because SQLite treats NULLs as distinct in UNIQUE.
    """

    __tablename__ = "variant_identifiers"
    __table_args__ = (
        Index(
            "uq_variant_identifiers_global",
            "id_type",
            "value",
            unique=True,
            sqlite_where=text("source_id IS NULL"),
        ),
        Index(
            "uq_variant_identifiers_per_source",
            "id_type",
            "value",
            "source_id",
            unique=True,
            sqlite_where=text("source_id IS NOT NULL"),
        ),
        CheckConstraint(
            "(id_type = 'SHOP_SKU') = (source_id IS NOT NULL)", "shop_sku_needs_source"
        ),
        CheckConstraint("length(value) > 0", "value_not_empty"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    variant_id: Mapped[int] = mapped_column(ForeignKey("product_variants.id"), index=True)
    id_type: Mapped[IdType] = mapped_column(enum_type(IdType, "id_type"))
    value: Mapped[str] = mapped_column(String(128))
    source_id: Mapped[int | None] = mapped_column(ForeignKey("sources.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    variant: Mapped[ProductVariant] = relationship(back_populates="identifiers")
