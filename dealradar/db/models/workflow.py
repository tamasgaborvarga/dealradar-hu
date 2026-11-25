"""User workflow: evaluations, watchlists, decisions, notifications, fee profiles."""

from __future__ import annotations

from datetime import datetime
from typing import Any, ClassVar

from sqlalchemy import JSON, Boolean, CheckConstraint, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from dealradar.core.clock import utcnow
from dealradar.core.enums import (
    Category,
    Decision,
    PersonalVerdict,
    RejectReason,
    ResaleVerdict,
    TelegramStatus,
)
from dealradar.db.base import Base, Mutability, UTCDateTime, enum_type

_REVIEW_IFF = (
    "(verdict = 'MANUAL_REVIEW') = "
    "(json_array_length(missing_json) + json_array_length(flags_json) > 0)"
)


class PersonalEvaluation(Base):
    """One Personal engine result. IMMUTABLE; the latest row per offer is current (ADR-017)."""

    __tablename__ = "personal_evaluations"
    __mutability__: ClassVar[Mutability] = Mutability.IMMUTABLE
    __table_args__ = (
        Index("ix_personal_evaluations_offer", "offer_id", "id"),
        CheckConstraint(_REVIEW_IFF, "review_iff_missing_or_flags"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    offer_id: Mapped[int] = mapped_column(ForeignKey("offers.id"))
    evaluated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    verdict: Mapped[PersonalVerdict] = mapped_column(enum_type(PersonalVerdict, "verdict"))
    effective_price_huf: Mapped[int | None] = mapped_column(Integer)
    benchmark_median_huf: Mapped[int | None] = mapped_column(Integer)
    discount_vs_median_bp: Mapped[int | None] = mapped_column(Integer)
    watchlist_relevance: Mapped[str] = mapped_column(String(32))
    missing_json: Mapped[list[str]] = mapped_column(JSON)
    flags_json: Mapped[list[str]] = mapped_column(JSON)
    result_json: Mapped[dict[str, Any]] = mapped_column(JSON)


class ResaleEvaluation(Base):
    """One Resale engine result (ESTIMATE, never an actual result). IMMUTABLE."""

    __tablename__ = "resale_evaluations"
    __mutability__: ClassVar[Mutability] = Mutability.IMMUTABLE
    __table_args__ = (
        Index("ix_resale_evaluations_offer", "offer_id", "id"),
        CheckConstraint(_REVIEW_IFF, "review_iff_missing_or_flags"),
        CheckConstraint(
            "verdict NOT IN ('PROFITABLE', 'MARGINAL', 'NOT_PROFITABLE') "
            "OR net_profit_huf IS NOT NULL",
            "numbers_for_decided_verdicts",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    offer_id: Mapped[int] = mapped_column(ForeignKey("offers.id"))
    evaluated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    verdict: Mapped[ResaleVerdict] = mapped_column(enum_type(ResaleVerdict, "verdict"))
    fee_profile_id: Mapped[int | None] = mapped_column(ForeignKey("fee_profiles.id"))
    acquisition_cost_huf: Mapped[int | None] = mapped_column(Integer)
    expected_sale_huf: Mapped[int | None] = mapped_column(Integer)
    net_profit_huf: Mapped[int | None] = mapped_column(Integer)
    net_profit_low_huf: Mapped[int | None] = mapped_column(Integer)
    roi_bp: Mapped[int | None] = mapped_column(Integer)
    provisional: Mapped[bool] = mapped_column(Boolean, default=False)
    liquidity: Mapped[str] = mapped_column(String(16))
    est_days_to_sell: Mapped[int | None] = mapped_column(Integer)
    missing_json: Mapped[list[str]] = mapped_column(JSON)
    flags_json: Mapped[list[str]] = mapped_column(JSON)
    result_json: Mapped[dict[str, Any]] = mapped_column(JSON)


class Watchlist(Base):
    """What the user wants to buy for themselves. STATE (changes audited by the service)."""

    __tablename__ = "watchlists"
    __table_args__ = (
        CheckConstraint(
            "variant_id IS NOT NULL OR product_id IS NOT NULL OR query_text IS NOT NULL",
            "has_target",
        ),
        CheckConstraint(
            "target_price_huf IS NULL OR max_price_huf IS NULL "
            "OR target_price_huf <= max_price_huf",
            "target_not_above_max",
        ),
        CheckConstraint(
            "(target_price_huf IS NULL OR target_price_huf > 0) AND "
            "(max_price_huf IS NULL OR max_price_huf > 0)",
            "positive_prices",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    category: Mapped[Category] = mapped_column(enum_type(Category, "category"))
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"))
    variant_id: Mapped[int | None] = mapped_column(ForeignKey("product_variants.id"))
    query_text: Mapped[str | None] = mapped_column(String(200))
    target_price_huf: Mapped[int | None] = mapped_column(Integer)
    max_price_huf: Mapped[int | None] = mapped_column(Integer)
    acceptable_conditions: Mapped[list[str] | None] = mapped_column(JSON(none_as_null=True))
    notify: Mapped[bool] = mapped_column(Boolean, default=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class OfferDecision(Base):
    """A user decision on an offer (incl. rejection feedback). IMMUTABLE; latest is current."""

    __tablename__ = "offer_decisions"
    __mutability__: ClassVar[Mutability] = Mutability.IMMUTABLE
    __table_args__ = (
        Index("ix_offer_decisions_offer", "offer_id", "id"),
        CheckConstraint("decision != 'REJECT' OR reason IS NOT NULL", "reject_needs_reason"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    offer_id: Mapped[int] = mapped_column(ForeignKey("offers.id"))
    decided_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    decision: Mapped[Decision] = mapped_column(enum_type(Decision, "decision"))
    reason: Mapped[RejectReason | None] = mapped_column(enum_type(RejectReason, "reason"))
    note: Mapped[str | None] = mapped_column(String(500))


class Notification(Base):
    """In-app inbox entry; optionally mirrored to Telegram. STATE (read / delivery fields)."""

    __tablename__ = "notifications"
    __mutability__: ClassVar[Mutability] = Mutability.IMMUTABLE
    __mutable_columns__: ClassVar[frozenset[str]] = frozenset(
        {"read_at", "telegram_status", "telegram_error"}
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    kind: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    offer_id: Mapped[int | None] = mapped_column(ForeignKey("offers.id"))
    dedupe_key: Mapped[str] = mapped_column(String(200), unique=True)
    read_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    telegram_status: Mapped[TelegramStatus] = mapped_column(
        enum_type(TelegramStatus, "telegram_status")
    )
    telegram_error: Mapped[str | None] = mapped_column(String(300))


class FeeProfileRecord(Base):
    """User-entered selling costs on one platform (docs/ENGINE_FORMULAS.md §2.9). STATE, audited."""

    __tablename__ = "fee_profiles"
    __table_args__ = (
        CheckConstraint(
            "commission_bp >= 0 AND commission_min_huf >= 0 AND fixed_fee_huf >= 0 AND "
            "listing_fee_huf >= 0 AND payment_fee_bp >= 0 AND payment_fixed_huf >= 0",
            "non_negative",
        ),
        CheckConstraint(
            "(outbound_shipping_cost_huf IS NULL OR outbound_shipping_cost_huf >= 0) AND "
            "(packaging_huf IS NULL OR packaging_huf >= 0) AND "
            "(commission_cap_huf IS NULL OR commission_cap_huf >= commission_min_huf)",
            "optional_non_negative",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    platform: Mapped[str] = mapped_column(String(120))
    commission_bp: Mapped[int] = mapped_column(Integer)
    commission_min_huf: Mapped[int] = mapped_column(Integer, default=0)
    commission_cap_huf: Mapped[int | None] = mapped_column(Integer)
    commission_includes_shipping: Mapped[bool] = mapped_column(Boolean, default=False)
    fixed_fee_huf: Mapped[int] = mapped_column(Integer, default=0)
    listing_fee_huf: Mapped[int] = mapped_column(Integer, default=0)
    payment_fee_bp: Mapped[int] = mapped_column(Integer, default=0)
    payment_fixed_huf: Mapped[int] = mapped_column(Integer, default=0)
    outbound_shipping_cost_huf: Mapped[int | None] = mapped_column(Integer)
    packaging_huf: Mapped[int | None] = mapped_column(Integer)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    note: Mapped[str | None] = mapped_column(String(500))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)
