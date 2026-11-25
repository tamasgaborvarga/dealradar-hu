"""Transaction calculations: realized profit from recorded money only (with edge cases)."""

from __future__ import annotations

import random

import pytest

from dealradar.core.enums import Direction, ItemIntent, ItemStatus, TxType
from dealradar.ledger.calc import ItemView, Tx, allocate, effective, item_results, summarize

IN, OUT = Direction.IN, Direction.OUT
R, P = ItemIntent.RESALE, ItemIntent.PERSONAL
_ids = iter(range(1, 10_000))


def tx(
    type_: TxType,
    amount: int,
    *,
    acq: int | None = None,
    item: int | None = None,
    reverses: int | None = None,
    tid: int | None = None,
) -> Tx:
    direction = IN if type_ in (TxType.SALE, TxType.REFUND_RECEIVED, TxType.OTHER_INCOME) else OUT
    return Tx(tid or next(_ids), type_, direction, amount, acq, item, reverses)


def test_single_item_sold_with_costs() -> None:
    """Bought 40 000 + 1 490 delivery; sold 60 000; fees 6 000 + 973; shipping 1 990; packaging 500.
    Realized = 60 000 - (41 490 + 6 000 + 973 + 1 990 + 500) = 9 047."""
    items = [ItemView(1, 10, ItemStatus.SOLD, R)]
    txs = [
        tx(TxType.PURCHASE, 40_000, acq=10),
        tx(TxType.INBOUND_SHIPPING, 1_490, acq=10),
        tx(TxType.SALE, 60_000, item=1),
        tx(TxType.PLATFORM_FEE, 6_000, item=1),
        tx(TxType.PAYMENT_FEE, 973, item=1),
        tx(TxType.OUTBOUND_SHIPPING, 1_990, item=1),
        tx(TxType.PACKAGING, 500, item=1),
    ]
    r = item_results(items, txs)[1]
    assert (r.allocated_acquisition_cost, r.item_costs, r.income) == (41_490, 9_463, 60_000)
    assert r.cost_basis == 50_953 and r.realized_profit == 9_047
    s = summarize(items, txs)
    assert s.realized_profit_huf == 9_047 and s.closed_items == 1
    assert s.realized_roi_bp == 1_776  # 9 047 / 50 953 = 17.755 %
    assert s.net_cash_flow_huf == 9_047 and s.unallocated_huf == 0


def test_open_item_has_no_realized_profit() -> None:
    items = [ItemView(1, 10, ItemStatus.LISTED, R)]
    s = summarize(items, [tx(TxType.PURCHASE, 40_000, acq=10)])
    assert s.realized_profit_huf == 0 and s.closed_items == 0 and s.realized_roi_bp is None
    assert s.capital_in_stock_huf == 40_000 and s.open_items == 1
    assert item_results(items, [])[1].realized_profit is None


def test_multi_unit_order_split_exactly() -> None:
    items = [ItemView(i, 10, ItemStatus.IN_STOCK, R) for i in (3, 1, 2)]
    r = item_results(
        items, [tx(TxType.PURCHASE, 10_000, acq=10), tx(TxType.INBOUND_SHIPPING, 1, acq=10)]
    )
    shares = {i: r[i].allocated_acquisition_cost for i in (1, 2, 3)}
    assert shares == {1: 3_334, 2: 3_334, 3: 3_333}  # 10 001 / 3, remainder to lowest ids
    assert sum(shares.values()) == 10_001


@pytest.mark.parametrize(("total", "n"), [(10, 3), (-10, 3), (0, 4), (7, 7), (1, 5), (999_999, 13)])
def test_allocate_always_sums_exactly(total: int, n: int) -> None:
    shares = allocate(total, list(range(1, n + 1)))
    assert sum(shares.values()) == total
    assert max(shares.values()) - min(shares.values()) <= 1


def test_allocate_needs_items() -> None:
    with pytest.raises(ValueError):
        allocate(100, [])


def test_reversal_cancels_the_original() -> None:
    items = [ItemView(1, 10, ItemStatus.SOLD, R)]
    wrong = tx(TxType.SALE, 600_000, item=1, tid=500)  # typo: one zero too many
    txs = [
        tx(TxType.PURCHASE, 40_000, acq=10),
        wrong,
        tx(TxType.SALE, 600_000, item=1, reverses=500),
        tx(TxType.SALE, 60_000, item=1),
    ]
    assert summarize(items, txs).realized_profit_huf == 20_000
    assert [t.id for t in effective(txs)] == [txs[0].id, txs[3].id]


def test_buyer_refund_and_return_to_seller() -> None:
    sold_then_refunded = [ItemView(1, 10, ItemStatus.SOLD, R)]
    txs = [
        tx(TxType.PURCHASE, 40_000, acq=10),
        tx(TxType.SALE, 60_000, item=1),
        tx(TxType.REFUND_GIVEN, 10_000, item=1),
    ]
    assert summarize(sold_then_refunded, txs).realized_profit_huf == 10_000
    returned = [ItemView(1, 11, ItemStatus.RETURNED_TO_SELLER, R)]
    txs2 = [
        tx(TxType.PURCHASE, 40_000, acq=11),
        tx(TxType.INBOUND_SHIPPING, 1_490, acq=11),
        tx(TxType.REFUND_RECEIVED, 40_000, acq=11),
    ]
    assert summarize(returned, txs2).realized_profit_huf == -1_490  # lost the delivery cost


def test_written_off_is_a_realized_loss() -> None:
    items = [ItemView(1, 10, ItemStatus.WRITTEN_OFF, R)]
    assert summarize(items, [tx(TxType.PURCHASE, 25_000, acq=10)]).realized_profit_huf == -25_000


def test_personal_items_are_spending_not_profit() -> None:
    items = [ItemView(1, 10, ItemStatus.PERSONAL_USE, P), ItemView(2, 11, ItemStatus.SOLD, R)]
    txs = [
        tx(TxType.PURCHASE, 80_000, acq=10),
        tx(TxType.PURCHASE, 10_000, acq=11),
        tx(TxType.SALE, 15_000, item=2),
    ]
    s = summarize(items, txs)
    assert s.personal_spend_huf == 80_000 and s.realized_profit_huf == 5_000
    assert item_results(items, txs)[1].realized_profit is None


def test_tax_and_other_costs_reduce_profit() -> None:
    items = [ItemView(1, 10, ItemStatus.SOLD, R)]
    txs = [
        tx(TxType.PURCHASE, 40_000, acq=10),
        tx(TxType.SALE, 60_000, item=1),
        tx(TxType.TAX, 3_000, item=1),
        tx(TxType.OTHER_COST, 200, item=1),
        tx(TxType.OTHER_INCOME, 1_500, item=1),
    ]
    assert summarize(items, txs).realized_profit_huf == 60_000 + 1_500 - 40_000 - 3_000 - 200


def test_acquisition_without_items_is_reported_unallocated() -> None:
    s = summarize([], [tx(TxType.PURCHASE, 5_000, acq=99)])
    assert s.unallocated_huf == 5_000 and s.cash_out_huf == 5_000


def test_empty_ledger() -> None:
    s = summarize([], [])
    assert (s.realized_profit_huf, s.cash_in_huf, s.cash_out_huf, s.realized_roi_bp) == (
        0,
        0,
        0,
        None,
    )


@pytest.mark.parametrize("seed", range(25))
def test_cash_flow_identity_on_random_ledgers(seed: int) -> None:
    """When every resale item is closed, realized profit equals net cash flow exactly."""
    rng = random.Random(seed)
    items, txs, next_item = [], [], 1
    for acq in range(1, rng.randint(1, 6) + 1):
        n = rng.randint(1, 4)
        txs.append(tx(TxType.PURCHASE, rng.randint(1, 500_000), acq=acq))
        if rng.random() < 0.5:
            txs.append(tx(TxType.INBOUND_SHIPPING, rng.randint(1, 5_000), acq=acq))
        for _ in range(n):
            status = rng.choice(
                [ItemStatus.SOLD, ItemStatus.WRITTEN_OFF, ItemStatus.RETURNED_TO_SELLER]
            )
            items.append(ItemView(next_item, acq, status, R))
            if status is ItemStatus.SOLD:
                txs.append(tx(TxType.SALE, rng.randint(1, 600_000), item=next_item))
                txs.append(tx(TxType.PLATFORM_FEE, rng.randint(1, 30_000), item=next_item))
            next_item += 1
    s = summarize(items, txs)
    assert s.realized_profit_huf == s.net_cash_flow_huf
    assert s.unallocated_huf == 0 and s.open_items == 0
