"""Ledger service on the database: actual recorded money, kept apart from estimates."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select

from dealradar.core.clock import utcnow
from dealradar.core.enums import (
    Category,
    Condition,
    Decision,
    ItemIntent,
    ItemStatus,
    SaleEvidence,
    TxType,
)
from dealradar.db.models import LedgerTransaction, OfferDecision
from dealradar.db.session import Database
from dealradar.services import ledger


def _buy(db: Database, **kw: object) -> list[int]:
    args: dict[str, object] = {
        "title": "Demotron DX900 1TB",
        "category": Category.TECH,
        "seller": "private seller",
        "total_price_huf": 40_000,
        "shipping_huf": 1_490,
        "acquired_at": utcnow() - timedelta(days=10),
    }
    args.update(kw)
    return ledger.record_purchase(db, **args)  # type: ignore[arg-type]


def test_purchase_then_sale_gives_realized_profit(db: Database) -> None:
    [item] = _buy(db)
    assert ledger.portfolio(db).realized_profit_huf == 0  # open item: nothing realized yet
    assert ledger.portfolio(db).capital_in_stock_huf == 41_490
    ledger.record_sale(
        db,
        item,
        sale_price_huf=60_000,
        platform="demo marketplace",
        sold_at=utcnow() - timedelta(days=1),
        platform_fee_huf=6_000,
        payment_fee_huf=973,
        outbound_shipping_huf=1_990,
        packaging_huf=500,
    )
    p = ledger.portfolio(db)
    assert p.realized_profit_huf == 9_047 and p.closed_items == 1 and p.realized_roi_bp == 1_776
    [row] = ledger.items(db)
    assert row.status is ItemStatus.SOLD and row.result.realized_profit == 9_047
    with pytest.raises(ValueError, match="már el van adva"):
        ledger.record_sale(db, item, sale_price_huf=1, platform="x")


def test_multi_unit_purchase_and_buyer_paid_shipping(db: Database) -> None:
    items = _buy(db, total_price_huf=10_000, shipping_huf=1, unit_count=3)
    assert len(items) == 3
    ledger.record_sale(
        db,
        items[0],
        sale_price_huf=5_000,
        platform="p",
        buyer_shipping_charged_huf=1_990,
        outbound_shipping_huf=1_990,
    )
    results = {r.id: r.result for r in ledger.items(db)}
    assert results[items[0]].allocated_acquisition_cost == 3_334
    assert results[items[0]].realized_profit == 5_000 + 1_990 - 3_334 - 1_990


def test_reversing_a_wrong_sale_reopens_the_item(db: Database) -> None:
    [item] = _buy(db)
    ledger.record_sale(db, item, sale_price_huf=600_000, platform="p")  # typo
    with db.read_session() as s:
        sale = s.scalar(select(LedgerTransaction).where(LedgerTransaction.type == TxType.SALE))
        assert sale is not None
        sale_id = sale.id
    ledger.reverse_transaction(db, sale_id, "typo, one zero too many")
    assert ledger.items(db)[0].status is ItemStatus.IN_STOCK
    assert ledger.portfolio(db).realized_profit_huf == 0
    with pytest.raises(ValueError, match="már stornózva"):
        ledger.reverse_transaction(db, sale_id, "again")
    ledger.record_sale(db, item, sale_price_huf=60_000, platform="p")
    assert ledger.portfolio(db).realized_profit_huf == 60_000 - 41_490
    rows = ledger.transactions(db)
    assert any(r.reversed for r in rows) and any(r.is_reversal for r in rows)


def test_statuses_and_personal_items(db: Database) -> None:
    [resale_item] = _buy(db)
    ledger.set_status(db, resale_item, ItemStatus.WRITTEN_OFF)
    assert ledger.portfolio(db).realized_profit_huf == -41_490  # a write-off is a realized loss
    with pytest.raises(ValueError):
        ledger.set_status(db, resale_item, ItemStatus.SOLD)
    [personal] = _buy(db, intent=ItemIntent.PERSONAL, total_price_huf=80_000, shipping_huf=0)
    with pytest.raises(ValueError):
        ledger.record_sale(db, personal, sale_price_huf=1, platform="p")
    with pytest.raises(ValueError):
        ledger.set_status(db, personal, ItemStatus.LISTED)
    p = ledger.portfolio(db)
    assert p.personal_spend_huf == 80_000 and p.realized_profit_huf == -41_490


@pytest.mark.parametrize(
    "kwargs",
    [
        {"total_price_huf": 0},
        {"total_price_huf": -5},
        {"unit_count": 0},
        {"seller": " "},
        {"acquired_at": utcnow() + timedelta(days=2)},
    ],
)
def test_invalid_purchases_are_rejected(db: Database, kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        _buy(db, **kwargs)
    assert ledger.transactions(db) == []


def test_item_costs_and_refunds(db: Database) -> None:
    [item] = _buy(db)
    with pytest.raises(ValueError):
        ledger.record_item_transaction(db, item, TxType.SALE, 100)
    ledger.record_item_transaction(db, item, TxType.OTHER_COST, 2_000, note="repair")
    ledger.record_sale(db, item, sale_price_huf=60_000, platform="p")
    ledger.record_item_transaction(db, item, TxType.REFUND_GIVEN, 5_000)
    assert ledger.portfolio(db).realized_profit_huf == 60_000 - 41_490 - 2_000 - 5_000


def test_purchase_from_an_offer_records_bought(db: Database) -> None:
    from dealradar.core.enums import RefreshScope
    from dealradar.services import sources
    from dealradar.services.refresh import refresh

    sources.register_mock_sources(db)
    refresh(db, RefreshScope.SOURCE, "mock_market", evaluate=False)
    _buy(db, offer_id=1)
    with db.read_session() as s:
        d = s.scalar(select(OfferDecision).where(OfferDecision.offer_id == 1))
        assert d is not None and d.decision is Decision.BOUGHT


def test_own_sales_become_sold_evidence(db: Database) -> None:
    from dealradar.core.enums import RefreshScope
    from dealradar.db.models import Offer
    from dealradar.services import sources
    from dealradar.services.refresh import refresh

    sources.register_mock_sources(db)
    refresh(db, RefreshScope.SOURCE, "mock_market", evaluate=False)
    with db.read_session() as s:
        variant_id = s.scalar(select(Offer.variant_id).where(Offer.variant_id.is_not(None)))
    assert variant_id is not None
    [item] = _buy(db, variant_id=variant_id, condition=Condition.USED_B)
    sold_at = utcnow() - timedelta(days=2)
    ledger.record_sale(db, item, sale_price_huf=25_000, platform="p", sold_at=sold_at)
    with db.read_session() as s:
        points = ledger.own_sale_points(
            s, [variant_id], sold_at - timedelta(days=1), utcnow(), variant_id
        )
    assert len(points) == 1
    assert points[0].evidence is SaleEvidence.OWN_SALE and points[0].sale_price_huf == 25_000
    assert points[0].days_listed == 8  # purchase (10 days ago) -> sale (2 days ago)


def test_estimates_are_separate_from_actual_money(db: Database) -> None:
    est = ledger.estimated_opportunities(db)
    assert (est.offers, est.expected_net_profit_huf) == (0, 0)
    _buy(db)
    assert ledger.estimated_opportunities(db).offers == 0  # a purchase is not an opportunity


def test_sale_dates_must_be_plausible(db: Database) -> None:
    """QA: a sale before the purchase (or a future cost) is invalid input, not data."""
    [item] = _buy(db)
    with pytest.raises(ValueError, match="korábbi, mint a vásárlásé"):
        ledger.record_sale(
            db, item, sale_price_huf=1_000, platform="p", sold_at=utcnow() - timedelta(days=30)
        )
    with pytest.raises(ValueError, match="jövőben"):
        ledger.record_item_transaction(
            db, item, TxType.PACKAGING, 100, occurred_at=utcnow() + timedelta(days=1)
        )
    assert [t.type for t in ledger.transactions(db)] == [TxType.INBOUND_SHIPPING, TxType.PURCHASE]


def test_failed_sale_leaves_no_partial_rows(db: Database) -> None:
    [item] = _buy(db)
    with pytest.raises(ValueError):
        ledger.record_sale(db, item, sale_price_huf=60_000, platform="p", platform_fee_huf=-1)
    assert ledger.items(db)[0].status is ItemStatus.IN_STOCK
    assert TxType.SALE not in {t.type for t in ledger.transactions(db)}
