"""Price history (ADR-039) and completed-sale evidence (ADR-006).

Two tables, never mixed:
- ``price_observations``: what a source *advertised* at one moment. One row per check, also when
  nothing changed - unchecked time is unknown, never filled in.
- ``observed_sales``: completed sales the user did not make (own sales will come from the ledger).
"""

from __future__ import annotations

from datetime import datetime
from typing import ClassVar

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from dealradar.core.clock import utcnow
from dealradar.core.enums import Actor, Availability, Condition, ListingKind, SaleEvidence
from dealradar.db.base import Base, Mutability, UTCDateTime, enum_type


class PriceObservation(Base):
    """One check of one offer. IMMUTABLE.

    Identity: ``offer_id`` (source + listing external id + raw variant text); the offer's link to
    a product variant is the current, audited match. Source, condition, listing kind and the
    offer's loyalty / multi-buy terms are snapshotted because they can change between checks.
    """

    __tablename__ = "price_observations"
    __mutability__: ClassVar[Mutability] = Mutability.IMMUTABLE
    __table_args__ = (
        Index("uq_price_observations_offer_time", "offer_id", "observed_at", unique=True),
        Index("ix_price_observations_observed_at", "observed_at"),
        CheckConstraint("price_huf IS NULL OR price_huf >= 0", "price_non_negative"),
        CheckConstraint("shipping_huf IS NULL OR shipping_huf >= 0", "shipping_non_negative"),
        CheckConstraint(
            "price_huf IS NOT NULL OR availability IN ('OUT_OF_STOCK', 'UNKNOWN')",
            "price_or_not_buyable",
        ),
        CheckConstraint("min_quantity >= 1", "min_quantity_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    offer_id: Mapped[int] = mapped_column(ForeignKey("offers.id"))
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"))
    observed_at: Mapped[datetime] = mapped_column(UTCDateTime)
    price_huf: Mapped[int | None] = mapped_column(Integer)  # gross item price
    shipping_huf: Mapped[int | None] = mapped_column(Integer)  # NULL = unknown, 0 = free
    availability: Mapped[Availability] = mapped_column(enum_type(Availability, "availability"))
    condition: Mapped[Condition | None] = mapped_column(enum_type(Condition, "condition"))
    listing_kind: Mapped[ListingKind] = mapped_column(enum_type(ListingKind, "listing_kind"))
    loyalty_only: Mapped[bool] = mapped_column(Boolean)
    min_quantity: Mapped[int] = mapped_column(Integer)
    raw_record_id: Mapped[int | None] = mapped_column(ForeignKey("raw_records.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class ObservedSale(Base):
    """A completed sale with a final price. IMMUTABLE. Never an asking price (ADR-006)."""

    __tablename__ = "observed_sales"
    __mutability__: ClassVar[Mutability] = Mutability.IMMUTABLE
    __table_args__ = (
        Index("ix_observed_sales_variant_sold", "variant_id", "sold_at"),
        CheckConstraint("sale_price_huf > 0", "sale_price_positive"),
        CheckConstraint(
            "buyer_shipping_huf IS NULL OR buyer_shipping_huf >= 0", "shipping_non_negative"
        ),
        CheckConstraint("days_listed IS NULL OR days_listed >= 0", "days_listed_non_negative"),
        CheckConstraint("length(source_ref) > 0", "source_ref_required"),
        # Own sales are read from the ledger, never copied here (ADR-006 / ADR-019).
        CheckConstraint("evidence != 'OWN_SALE'", "no_own_sales"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    variant_id: Mapped[int] = mapped_column(ForeignKey("product_variants.id"))
    platform_id: Mapped[int] = mapped_column(ForeignKey("platforms.id"))
    evidence: Mapped[SaleEvidence] = mapped_column(enum_type(SaleEvidence, "evidence"))
    condition: Mapped[Condition] = mapped_column(enum_type(Condition, "condition"))
    sale_price_huf: Mapped[int] = mapped_column(Integer)  # final item price
    buyer_shipping_huf: Mapped[int | None] = mapped_column(Integer)  # paid by buyer, separate
    sold_at: Mapped[datetime] = mapped_column(UTCDateTime)
    days_listed: Mapped[int | None] = mapped_column(Integer)
    listing_id: Mapped[int | None] = mapped_column(ForeignKey("listings.id"))
    source_ref: Mapped[str] = mapped_column(Text)  # URL, note: where the evidence comes from
    entered_by: Mapped[Actor] = mapped_column(enum_type(Actor, "entered_by"))
    note: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
