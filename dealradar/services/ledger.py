"""Recording what the USER bought and sold (actual money). The app never buys anything itself.

Every write is a ledger transaction (positive amount + direction); corrections are reversals.
Summaries are computed by ``ledger.calc`` from recorded transactions only.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from dealradar.core import hu
from dealradar.core.clock import utcnow
from dealradar.core.enums import (
    INCOME_TYPES,
    Actor,
    Category,
    Condition,
    Decision,
    Direction,
    ItemIntent,
    ItemStatus,
    SaleEvidence,
    TxType,
)
from dealradar.db.models import (
    Acquisition,
    InventoryItem,
    LedgerTransaction,
    OfferDecision,
    ResaleEvaluation,
)
from dealradar.db.repositories import AuditLogRepository
from dealradar.db.session import Database
from dealradar.ledger.calc import (
    ItemResult,
    ItemView,
    PortfolioSummary,
    Tx,
    effective,
    item_results,
    summarize,
)
from dealradar.pricing.types import SalePoint

# Status changes allowed by hand. SOLD is set only by record_sale (it needs a SALE transaction).
_MANUAL_STATUS = {
    ItemStatus.IN_STOCK,
    ItemStatus.LISTED,
    ItemStatus.RETURNED_TO_SELLER,
    ItemStatus.WRITTEN_OFF,
    ItemStatus.PERSONAL_USE,
}
OWN_SALES_PLATFORM_ID = 0  # SalePoint platform for the user's own sales


def _direction(t: TxType) -> Direction:
    return Direction.IN if t in INCOME_TYPES else Direction.OUT


def _check_amount(amount: int, what: str) -> None:
    if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
        raise ValueError(f"{what}: pozitív, egész forintösszeg kell")


def _tx(
    s: Session,
    type_: TxType,
    amount: int,
    at: datetime,
    *,
    acquisition_id: int | None = None,
    item_id: int | None = None,
    platform: str | None = None,
    note: str | None = None,
) -> None:
    _check_amount(amount, type_.value)
    s.add(
        LedgerTransaction(
            occurred_at=at,
            type=type_,
            direction=_direction(type_),
            amount_huf=amount,
            acquisition_id=acquisition_id,
            inventory_item_id=item_id,
            platform=platform,
            note=note,
        )
    )


def record_purchase(
    db: Database,
    *,
    title: str,
    category: Category,
    seller: str,
    total_price_huf: int,
    shipping_huf: int = 0,
    unit_count: int = 1,
    intent: ItemIntent = ItemIntent.RESALE,
    condition: Condition | None = None,
    variant_id: int | None = None,
    offer_id: int | None = None,
    acquired_at: datetime | None = None,
    note: str | None = None,
) -> list[int]:
    """Record a purchase the user made. Creates one inventory item per unit. Returns item ids."""
    at = acquired_at or utcnow()
    if at > utcnow():
        raise ValueError("a vásárlás dátuma a jövőben van")
    if unit_count < 1:
        raise ValueError("legalább 1 darab kell")
    if not title.strip() or not seller.strip():
        raise ValueError("a megnevezés és az eladó kötelező")
    with db.write_session() as s:
        acq = Acquisition(
            acquired_at=at,
            seller=seller.strip()[:200],
            offer_id=offer_id,
            unit_count=unit_count,
            note=note,
        )
        s.add(acq)
        s.flush()
        _tx(s, TxType.PURCHASE, total_price_huf, at, acquisition_id=acq.id, platform=seller)
        if shipping_huf:
            _tx(s, TxType.INBOUND_SHIPPING, shipping_huf, at, acquisition_id=acq.id)
        status = ItemStatus.PERSONAL_USE if intent is ItemIntent.PERSONAL else ItemStatus.IN_STOCK
        items = [
            InventoryItem(
                acquisition_id=acq.id,
                title=title.strip()[:300],
                category=category,
                variant_id=variant_id,
                intent=intent,
                condition=condition,
                status=status,
                status_changed_at=at,
            )
            for _ in range(unit_count)
        ]
        s.add_all(items)
        if offer_id is not None:
            s.add(OfferDecision(offer_id=offer_id, decision=Decision.BOUGHT, decided_at=at))
        s.flush()
        AuditLogRepository(s).record(
            actor=Actor.USER,
            entity="acquisitions",
            entity_id=str(acq.id),
            action="purchase_recorded",
            after={"total": total_price_huf, "units": unit_count},
        )
        return [i.id for i in items]


def record_item_transaction(
    db: Database,
    item_id: int,
    type_: TxType,
    amount_huf: int,
    *,
    occurred_at: datetime | None = None,
    platform: str | None = None,
    note: str | None = None,
) -> None:
    """A cost or income booked on one item (fee, shipping, packaging, refund, tax...)."""
    if type_ in (TxType.PURCHASE, TxType.SALE):
        raise ValueError("vásárlást és eladást a saját űrlapján rögzíts")
    if occurred_at is not None and occurred_at > utcnow():
        raise ValueError("a tétel dátuma a jövőben van")
    with db.write_session() as s:
        if s.get(InventoryItem, item_id) is None:
            raise ValueError(f"nincs ilyen tétel: {item_id}")
        _tx(
            s,
            type_,
            amount_huf,
            occurred_at or utcnow(),
            item_id=item_id,
            platform=platform,
            note=note,
        )


def record_sale(
    db: Database,
    item_id: int,
    *,
    sale_price_huf: int,
    platform: str,
    sold_at: datetime | None = None,
    buyer_shipping_charged_huf: int = 0,
    platform_fee_huf: int = 0,
    payment_fee_huf: int = 0,
    outbound_shipping_huf: int = 0,
    packaging_huf: int = 0,
    tax_huf: int = 0,
) -> None:
    """Record a completed sale with its actual costs, and close the item as SOLD."""
    at = sold_at or utcnow()
    if at > utcnow():
        raise ValueError("az eladás dátuma a jövőben van")
    with db.write_session() as s:
        item = s.get(InventoryItem, item_id)
        if item is None:
            raise ValueError(f"nincs ilyen tétel: {item_id}")
        if item.status is ItemStatus.SOLD:
            raise ValueError("a tétel már el van adva; előbb stornózd az eladást")
        if item.intent is not ItemIntent.RESALE:
            raise ValueError("saját használatú tételt nem lehet itt eladni")
        acquisition = s.get(Acquisition, item.acquisition_id)
        if acquisition is not None and at < acquisition.acquired_at:
            raise ValueError("az eladás dátuma korábbi, mint a vásárlásé")
        _tx(s, TxType.SALE, sale_price_huf, at, item_id=item_id, platform=platform)
        for type_, amount in (
            (TxType.OTHER_INCOME, buyer_shipping_charged_huf),
            (TxType.PLATFORM_FEE, platform_fee_huf),
            (TxType.PAYMENT_FEE, payment_fee_huf),
            (TxType.OUTBOUND_SHIPPING, outbound_shipping_huf),
            (TxType.PACKAGING, packaging_huf),
            (TxType.TAX, tax_huf),
        ):
            if amount < 0:
                raise ValueError(f"{hu.label('tx_type', type_)}: nem lehet negatív")
            if amount:
                note = "a vevő által fizetett szállítás" if type_ is TxType.OTHER_INCOME else None
                _tx(s, type_, amount, at, item_id=item_id, platform=platform, note=note)
        before = item.status
        item.status = ItemStatus.SOLD
        item.status_changed_at = at
        AuditLogRepository(s).record(
            actor=Actor.USER,
            entity="inventory_items",
            entity_id=str(item_id),
            action="sold",
            before=before.value,
            after="SOLD",
        )


def set_status(db: Database, item_id: int, status: ItemStatus) -> None:
    if status not in _MANUAL_STATUS:
        raise ValueError(
            f"{hu.label('item_status', status)} állapot csak eladás rögzítésével állítható be"
        )
    with db.write_session() as s:
        item = s.get(InventoryItem, item_id)
        if item is None:
            raise ValueError(f"nincs ilyen tétel: {item_id}")
        if item.status is ItemStatus.SOLD:
            raise ValueError("eladott tétel állapota nem változtatható; előbb stornózd az eladást")
        if status is ItemStatus.PERSONAL_USE and item.intent is not ItemIntent.PERSONAL:
            raise ValueError(
                "a „Saját használatban” állapot csak saját használatú tételnél választható"
            )
        if item.intent is ItemIntent.PERSONAL and status in (
            ItemStatus.IN_STOCK,
            ItemStatus.LISTED,
        ):
            raise ValueError("saját használatú tételt nem lehet meghirdetni")
        before = item.status
        item.status = status
        item.status_changed_at = utcnow()
        AuditLogRepository(s).record(
            actor=Actor.USER,
            entity="inventory_items",
            entity_id=str(item_id),
            action="status",
            before=before.value,
            after=status.value,
        )


def reverse_transaction(db: Database, tx_id: int, note: str) -> None:
    """Cancel a wrong transaction by adding its reversal. A reversed SALE re-opens the item."""
    with db.write_session() as s:
        t = s.get(LedgerTransaction, tx_id)
        if t is None:
            raise ValueError(f"nincs ilyen tranzakció: {tx_id}")
        if t.reverses_id is not None:
            raise ValueError("stornó tételt nem lehet stornózni; rögzíts helyette új tételt")
        if s.scalar(select(LedgerTransaction).where(LedgerTransaction.reverses_id == tx_id)):
            raise ValueError("ez a tranzakció már stornózva van")
        s.add(
            LedgerTransaction(
                occurred_at=utcnow(),
                type=t.type,
                direction=t.direction,
                amount_huf=t.amount_huf,
                acquisition_id=t.acquisition_id,
                inventory_item_id=t.inventory_item_id,
                platform=t.platform,
                note=f"stornó: {note}"[:500],
                reverses_id=t.id,
            )
        )
        if t.type is TxType.SALE and t.inventory_item_id is not None:
            item = s.get(InventoryItem, t.inventory_item_id)
            if item is not None and item.status is ItemStatus.SOLD:
                item.status = ItemStatus.IN_STOCK
                item.status_changed_at = utcnow()


# --- reading ---


@dataclass(frozen=True)
class ItemRow:
    id: int
    title: str
    category: Category
    intent: ItemIntent
    status: ItemStatus
    acquired_at: datetime
    seller: str
    result: ItemResult


@dataclass(frozen=True)
class TxRow:
    id: int
    occurred_at: datetime
    type: TxType
    direction: Direction
    amount_huf: int
    item_id: int | None
    acquisition_id: int | None
    platform: str | None
    note: str | None
    reversed: bool
    is_reversal: bool


@dataclass(frozen=True)
class EstimatedOpportunities:
    """ESTIMATES from the Resale engine (not money). Shown apart from actual results."""

    offers: int
    expected_net_profit_huf: int
    capital_needed_huf: int


def _load(s: Session) -> tuple[list[ItemView], list[Tx]]:
    items = s.scalars(select(InventoryItem)).all()
    views = [ItemView(i.id, i.acquisition_id, i.status, i.intent) for i in items]
    txs = [
        Tx(
            t.id,
            t.type,
            t.direction,
            t.amount_huf,
            t.acquisition_id,
            t.inventory_item_id,
            t.reverses_id,
        )
        for t in s.scalars(select(LedgerTransaction)).all()
    ]
    return views, txs


def portfolio(db: Database) -> PortfolioSummary:
    with db.read_session() as s:
        views, txs = _load(s)
    return summarize(views, txs)


def items(db: Database) -> list[ItemRow]:
    with db.read_session() as s:
        views, txs = _load(s)
        results = item_results(views, txs)
        rows = s.execute(
            select(InventoryItem, Acquisition).join(Acquisition).order_by(InventoryItem.id.desc())
        ).all()
        return [
            ItemRow(
                i.id,
                i.title,
                i.category,
                i.intent,
                i.status,
                a.acquired_at,
                a.seller,
                results[i.id],
            )
            for i, a in rows
        ]


def transactions(db: Database, limit: int = 500) -> list[TxRow]:
    with db.read_session() as s:
        rows = s.scalars(
            select(LedgerTransaction).order_by(LedgerTransaction.id.desc()).limit(limit)
        ).all()
        reversed_ids = {t.reverses_id for t in rows if t.reverses_id is not None}
        return [
            TxRow(
                t.id,
                t.occurred_at,
                t.type,
                t.direction,
                t.amount_huf,
                t.inventory_item_id,
                t.acquisition_id,
                t.platform,
                t.note,
                t.id in reversed_ids,
                t.reverses_id is not None,
            )
            for t in rows
        ]


def estimated_opportunities(db: Database) -> EstimatedOpportunities:
    """Latest resale evaluation per offer with verdict PROFITABLE (ESTIMATE, not money)."""
    with db.read_session() as s:
        latest: dict[int, tuple[str, int, int]] = {}
        for e in s.scalars(select(ResaleEvaluation).order_by(ResaleEvaluation.id)).all():
            latest[e.offer_id] = (
                e.verdict.value,
                e.net_profit_huf or 0,
                e.acquisition_cost_huf or 0,
            )
        decided = {
            d.offer_id: d.decision
            for d in s.scalars(select(OfferDecision).order_by(OfferDecision.id)).all()
        }
    picks = [
        v
        for oid, v in latest.items()
        if v[0] == "PROFITABLE" and decided.get(oid) not in (Decision.REJECT, Decision.BOUGHT)
    ]
    return EstimatedOpportunities(
        offers=len(picks),
        expected_net_profit_huf=sum(v[1] for v in picks),
        capital_needed_huf=sum(v[2] for v in picks),
    )


def own_sale_points(
    s: Session, variant_ids: Sequence[int], since: datetime, until: datetime, report_as_variant: int
) -> list[SalePoint]:
    """The user's own completed sales as evidence for the sold benchmark (ADR-006, ADR-050)."""
    if not variant_ids:
        return []
    _, txs = _load(s)
    sale_txs = {t.item_id: t for t in effective(txs) if t.type is TxType.SALE and t.item_id}
    items_ = s.scalars(
        select(InventoryItem).where(
            InventoryItem.variant_id.in_(list(variant_ids)),
            InventoryItem.status == ItemStatus.SOLD,
            InventoryItem.condition.is_not(None),
        )
    ).all()
    acq_dates = {a.id: a.acquired_at for a in s.scalars(select(Acquisition)).all()}
    out: list[SalePoint] = []
    for item in items_:
        sale = sale_txs.get(item.id)
        if sale is None or item.condition is None:
            continue
        row = s.get(LedgerTransaction, sale.id)
        if row is None or not since <= row.occurred_at <= until:
            continue
        days = (row.occurred_at - acq_dates[item.acquisition_id]).days
        out.append(
            SalePoint(
                sale_id=-sale.id,
                variant_id=report_as_variant,
                platform_id=OWN_SALES_PLATFORM_ID,
                evidence=SaleEvidence.OWN_SALE,
                condition=item.condition,
                sale_price_huf=sale.amount_huf,
                buyer_shipping_huf=None,
                sold_at=row.occurred_at,
                days_listed=max(0, days),
            )
        )
    return out
