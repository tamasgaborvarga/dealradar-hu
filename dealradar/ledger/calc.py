"""Realized results from recorded transactions only (docs/ENGINE_FORMULAS.md §4).

Rules:
- Every transaction has a positive amount and a direction; IN adds, OUT subtracts.
- A reversal row (``reverses_id`` set) cancels the referenced row; both are ignored.
- Acquisition-level money (the order price, inbound shipping, order refunds) is split equally over
  the acquisition's items; the remainder HUF goes 1 HUF at a time to the lowest item ids, so the
  shares always sum exactly to the total.
- Realized profit exists only for closed items (SOLD, RETURNED_TO_SELLER, WRITTEN_OFF).
  Open items show their cost basis (capital in stock). PERSONAL items are spending, not profit.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal

from dealradar.core.enums import (
    CLOSED_ITEM_STATUSES,
    Direction,
    ItemIntent,
    ItemStatus,
    TxType,
)
from dealradar.core.money import BP_PER_UNIT, round_huf


@dataclass(frozen=True)
class Tx:
    id: int
    type: TxType
    direction: Direction
    amount_huf: int
    acquisition_id: int | None = None
    item_id: int | None = None
    reverses_id: int | None = None

    @property
    def signed(self) -> int:
        return self.amount_huf if self.direction is Direction.IN else -self.amount_huf


@dataclass(frozen=True)
class ItemView:
    id: int
    acquisition_id: int
    status: ItemStatus
    intent: ItemIntent


@dataclass(frozen=True)
class ItemResult:
    item_id: int
    status: ItemStatus
    intent: ItemIntent
    allocated_acquisition_cost: int  # share of the order (price, inbound shipping, net of refunds)
    item_costs: int  # fees, shipping, packaging, tax, refunds given... booked on the item
    income: int  # sale price, refunds received, other income booked on the item
    cost_basis: int  # allocated_acquisition_cost + item_costs
    realized_profit: int | None  # income - cost_basis, only for closed resale items

    @property
    def closed(self) -> bool:
        return self.status in CLOSED_ITEM_STATUSES


@dataclass(frozen=True)
class PortfolioSummary:
    """ACTUAL results from recorded transactions. Never mixed with estimates."""

    realized_profit_huf: int
    realized_income_huf: int
    realized_cost_basis_huf: int
    realized_roi_bp: int | None
    closed_items: int
    open_items: int
    capital_in_stock_huf: int  # cost basis of open resale items
    personal_spend_huf: int  # cost basis of personal items
    cash_in_huf: int
    cash_out_huf: int
    unallocated_huf: int  # acquisition money with no items to carry it (should be 0)

    @property
    def net_cash_flow_huf(self) -> int:
        return self.cash_in_huf - self.cash_out_huf


def effective(transactions: Iterable[Tx]) -> list[Tx]:
    """Drop reversal rows and the rows they reverse."""
    txs = list(transactions)
    reversed_ids = {t.reverses_id for t in txs if t.reverses_id is not None}
    return [t for t in txs if t.reverses_id is None and t.id not in reversed_ids]


def allocate(total: int, item_ids: Sequence[int]) -> dict[int, int]:
    """Split ``total`` over items exactly: equal shares, remainder to the lowest ids."""
    if not item_ids:
        raise ValueError("nothing to allocate to")
    ids = sorted(item_ids)
    base, remainder = divmod(total, len(ids))
    return {item_id: base + (1 if i < remainder else 0) for i, item_id in enumerate(ids)}


def item_results(items: Sequence[ItemView], transactions: Iterable[Tx]) -> dict[int, ItemResult]:
    txs = effective(transactions)
    by_acq: dict[int, list[int]] = defaultdict(list)
    for item in items:
        by_acq[item.acquisition_id].append(item.id)
    acq_cost: dict[int, int] = defaultdict(int)  # positive = money spent on the order
    item_out: dict[int, int] = defaultdict(int)
    item_in: dict[int, int] = defaultdict(int)
    for t in txs:
        if t.acquisition_id is not None:
            acq_cost[t.acquisition_id] -= t.signed
        elif t.item_id is not None:
            if t.direction is Direction.IN:
                item_in[t.item_id] += t.amount_huf
            else:
                item_out[t.item_id] += t.amount_huf
    shares: dict[int, int] = {}
    for acq_id, ids in by_acq.items():
        shares.update(allocate(acq_cost.get(acq_id, 0), ids))
    out: dict[int, ItemResult] = {}
    for item in items:
        basis = shares[item.id] + item_out[item.id]
        realized = (
            item_in[item.id] - basis
            if item.status in CLOSED_ITEM_STATUSES and item.intent is ItemIntent.RESALE
            else None
        )
        out[item.id] = ItemResult(
            item_id=item.id,
            status=item.status,
            intent=item.intent,
            allocated_acquisition_cost=shares[item.id],
            item_costs=item_out[item.id],
            income=item_in[item.id],
            cost_basis=basis,
            realized_profit=realized,
        )
    return out


def summarize(items: Sequence[ItemView], transactions: Iterable[Tx]) -> PortfolioSummary:
    txs = effective(transactions)
    results = item_results(items, txs)
    acq_with_items = {i.acquisition_id for i in items}
    unallocated = sum(
        -t.signed
        for t in txs
        if t.acquisition_id is not None and t.acquisition_id not in acq_with_items
    )
    closed = [r for r in results.values() if r.realized_profit is not None]
    open_resale = [r for r in results.values() if r.intent is ItemIntent.RESALE and not r.closed]
    personal = [r for r in results.values() if r.intent is ItemIntent.PERSONAL]
    realized_profit = sum(r.realized_profit or 0 for r in closed)
    realized_basis = sum(r.cost_basis for r in closed)
    roi = (
        int(round_huf(Decimal(realized_profit) * BP_PER_UNIT / Decimal(realized_basis)))
        if realized_basis > 0
        else None
    )
    return PortfolioSummary(
        realized_profit_huf=realized_profit,
        realized_income_huf=sum(r.income for r in closed),
        realized_cost_basis_huf=realized_basis,
        realized_roi_bp=roi,
        closed_items=len(closed),
        open_items=len(open_resale),
        capital_in_stock_huf=sum(r.cost_basis for r in open_resale),
        personal_spend_huf=sum(r.cost_basis for r in personal),
        cash_in_huf=sum(t.amount_huf for t in txs if t.direction is Direction.IN),
        cash_out_huf=sum(t.amount_huf for t in txs if t.direction is Direction.OUT),
        unallocated_huf=unallocated,
    )
