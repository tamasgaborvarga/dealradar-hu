"""Listings, offers and match candidates (DATABASE_DESIGN.md §5, ADR-014/021)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, ClassVar

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from dealradar.core.clock import utcnow
from dealradar.core.enums import (
    Actor,
    CandidateStatus,
    Category,
    Condition,
    ListingKind,
    MatchMethod,
    MatchStatus,
    SellerKind,
    WarrantyType,
)
from dealradar.db.base import Base, Mutability, UTCDateTime, enum_type


class Listing(Base):
    """One page / ad / flyer item at one source. STATE.

    Matched product is ``product_id``; method and confidence live on the ACCEPTED
    match candidate (no duplicated state). ``delisted_at`` is NOT evidence of a sale.
    """

    __tablename__ = "listings"
    __table_args__ = (
        Index("uq_listings_source_external", "source_id", "external_id", unique=True),
        CheckConstraint(
            "(match_status = 'MATCHED') = (product_id IS NOT NULL)", "matched_iff_product"
        ),
        CheckConstraint("warranty_months IS NULL OR warranty_months >= 0", "warranty_non_negative"),
        CheckConstraint("duplicate_of_id IS NULL OR duplicate_of_id != id", "no_self_duplicate"),
        CheckConstraint("last_seen_at >= first_seen_at", "seen_order"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"))
    external_id: Mapped[str] = mapped_column(String(512))
    url: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    listing_kind: Mapped[ListingKind] = mapped_column(enum_type(ListingKind, "listing_kind"))
    category_hint: Mapped[Category | None] = mapped_column(enum_type(Category, "category_hint"))
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"), index=True)
    match_status: Mapped[MatchStatus] = mapped_column(
        enum_type(MatchStatus, "match_status"), default=MatchStatus.UNMATCHED
    )
    seller_kind: Mapped[SellerKind | None] = mapped_column(enum_type(SellerKind, "seller_kind"))
    seller_ref: Mapped[str | None] = mapped_column(String(200))  # private sellers: salted hash only
    condition: Mapped[Condition | None] = mapped_column(enum_type(Condition, "condition"))
    warranty_months: Mapped[int | None] = mapped_column(Integer)
    warranty_type: Mapped[WarrantyType | None] = mapped_column(
        enum_type(WarrantyType, "warranty_type")
    )
    price_is_net: Mapped[bool | None] = mapped_column(Boolean)
    location_text: Mapped[str | None] = mapped_column(String(200))
    category_attrs: Mapped[dict[str, Any] | None] = mapped_column(JSON)  # category ListingAttrs
    # Snapshot of the NormalizedListing used for the latest evaluation (re-evaluation without
    # re-fetching). Untrusted text inside stays untrusted.
    normalized: Mapped[dict[str, Any] | None] = mapped_column(JSON(none_as_null=True))
    first_seen_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    delisted_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    duplicate_of_id: Mapped[int | None] = mapped_column(ForeignKey("listings.id"))

    offers: Mapped[list[Offer]] = relationship(back_populates="listing")


class Offer(Base):
    """The priced, buyable unit: one listing x one variant. Prices: price_observations. STATE."""

    __tablename__ = "offers"
    __table_args__ = (
        Index("uq_offers_listing_variant_raw", "listing_id", "variant_key_raw", unique=True),
        Index("ix_offers_variant_active", "variant_id", "is_active"),
        CheckConstraint("min_quantity >= 1", "min_quantity_positive"),
        CheckConstraint(
            "valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from", "validity_order"
        ),
        CheckConstraint("length(currency) = 3", "currency_code"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    listing_id: Mapped[int] = mapped_column(ForeignKey("listings.id"))
    variant_id: Mapped[int | None] = mapped_column(ForeignKey("product_variants.id"))
    variant_key_raw: Mapped[str] = mapped_column(String(128), default="default")
    currency: Mapped[str] = mapped_column(String(3), default="HUF")
    loyalty_only: Mapped[bool] = mapped_column(Boolean, default=False)
    min_quantity: Mapped[int] = mapped_column(Integer, default=1)
    valid_from: Mapped[datetime | None] = mapped_column(UTCDateTime)
    valid_to: Mapped[datetime | None] = mapped_column(UTCDateTime)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    listing: Mapped[Listing] = relationship(back_populates="offers")


class MatchCandidate(Base):
    """A proposed listing -> product link. IMMUTABLE except the decision columns.

    At most one ACCEPTED candidate per listing (partial unique index).
    """

    __tablename__ = "match_candidates"
    __mutability__: ClassVar[Mutability] = Mutability.IMMUTABLE
    __mutable_columns__: ClassVar[frozenset[str]] = frozenset(
        {"status", "decided_at", "decided_by"}
    )
    __table_args__ = (
        Index(
            "uq_match_candidates_one_accepted",
            "listing_id",
            unique=True,
            sqlite_where=text("status = 'ACCEPTED'"),
        ),
        CheckConstraint("confidence BETWEEN 0 AND 100", "confidence_range"),
        CheckConstraint("(status = 'OPEN') = (decided_at IS NULL)", "decided_iff_not_open"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    listing_id: Mapped[int] = mapped_column(ForeignKey("listings.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    method: Mapped[MatchMethod] = mapped_column(enum_type(MatchMethod, "method"))
    confidence: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str | None] = mapped_column(Text)
    status: Mapped[CandidateStatus] = mapped_column(
        enum_type(CandidateStatus, "status"), default=CandidateStatus.OPEN
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    decided_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    decided_by: Mapped[Actor | None] = mapped_column(enum_type(Actor, "decided_by"))
