"""Inventory and money ledger (DATABASE_DESIGN.md §11, ADR-019). Actual recorded money only."""

from __future__ import annotations

from datetime import datetime
from typing import ClassVar

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from dealradar.core.clock import utcnow
from dealradar.core.enums import Category, Condition, Direction, ItemIntent, ItemStatus, TxType
from dealradar.db.base import Base, Mutability, UTCDateTime, enum_type

_INCOME = "('SALE', 'REFUND_RECEIVED', 'OTHER_INCOME')"


class Acquisition(Base):
    """One purchase the USER made (an order; may contain several units). IMMUTABLE except note."""

    __tablename__ = "acquisitions"
    __mutability__: ClassVar[Mutability] = Mutability.IMMUTABLE
    __mutable_columns__: ClassVar[frozenset[str]] = frozenset({"note"})
    __table_args__ = (CheckConstraint("unit_count >= 1", "unit_count_positive"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    acquired_at: Mapped[datetime] = mapped_column(UTCDateTime)
    seller: Mapped[str] = mapped_column(String(200))
    offer_id: Mapped[int | None] = mapped_column(ForeignKey("offers.id"))
    unit_count: Mapped[int] = mapped_column(Integer)
    note: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class InventoryItem(Base):
    """One physical unit. STATE: status changes are audited by the service."""

    __tablename__ = "inventory_items"
    __table_args__ = (
        Index("ix_inventory_items_acquisition", "acquisition_id"),
        CheckConstraint(
            "listed_price_huf IS NULL OR listed_price_huf > 0", "listed_price_positive"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    acquisition_id: Mapped[int] = mapped_column(ForeignKey("acquisitions.id"))
    title: Mapped[str] = mapped_column(String(300))
    category: Mapped[Category] = mapped_column(enum_type(Category, "category"))
    variant_id: Mapped[int | None] = mapped_column(ForeignKey("product_variants.id"))
    intent: Mapped[ItemIntent] = mapped_column(enum_type(ItemIntent, "intent"))
    condition: Mapped[Condition | None] = mapped_column(enum_type(Condition, "condition"))
    status: Mapped[ItemStatus] = mapped_column(enum_type(ItemStatus, "status"))
    listed_price_huf: Mapped[int | None] = mapped_column(Integer)
    listed_platform: Mapped[str | None] = mapped_column(String(120))
    status_changed_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class LedgerTransaction(Base):
    """A real money movement. LEDGER: never updated; corrections are reversal rows.

    ``amount_huf`` is always positive; ``direction`` says which way it went. A reversal row has
    ``reverses_id`` set and cancels the referenced row in every calculation.
    """

    __tablename__ = "transactions"
    __mutability__: ClassVar[Mutability] = Mutability.LEDGER
    __table_args__ = (
        Index("ix_transactions_acquisition", "acquisition_id"),
        Index("ix_transactions_item", "inventory_item_id"),
        Index("uq_transactions_one_reversal", "reverses_id", unique=True),
        CheckConstraint("amount_huf > 0", "amount_positive"),
        CheckConstraint(f"(direction = 'IN') = (type IN {_INCOME})", "direction_matches_type"),
        CheckConstraint(
            "(acquisition_id IS NULL) != (inventory_item_id IS NULL)", "belongs_to_exactly_one"
        ),
        CheckConstraint("reverses_id IS NULL OR reverses_id != id", "no_self_reversal"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime)
    type: Mapped[TxType] = mapped_column(enum_type(TxType, "type"))
    direction: Mapped[Direction] = mapped_column(enum_type(Direction, "direction"))
    amount_huf: Mapped[int] = mapped_column(Integer)
    acquisition_id: Mapped[int | None] = mapped_column(ForeignKey("acquisitions.id"))
    inventory_item_id: Mapped[int | None] = mapped_column(ForeignKey("inventory_items.id"))
    platform: Mapped[str | None] = mapped_column(String(120))
    note: Mapped[str | None] = mapped_column(String(500))
    reverses_id: Mapped[int | None] = mapped_column(ForeignKey("transactions.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
