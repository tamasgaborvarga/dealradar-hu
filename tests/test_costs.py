"""Money formulas (evaluation/costs.py) with hand-computed expectations and edge cases."""

from __future__ import annotations

import random

import pytest

from dealradar.core.money import Bp
from dealradar.evaluation.costs import (
    capital_exposure,
    commission,
    discount_bp,
    effective_price,
    expected_cost,
    holding_cost,
    payment_fee,
    resale_scenario,
    roi_bp,
    tax_cost,
)
from dealradar.evaluation.params import FeeProfile, TaxKind, TaxProfile

FEE = FeeProfile(
    platform="synthetic",
    commission_bp=Bp(1_000),
    commission_min_huf=200,
    payment_fee_bp=Bp(150),
    payment_fixed_huf=50,
    outbound_shipping_cost_huf=1_990,
    packaging_huf=500,
    verified=True,
)
TAX_15_PROFIT = TaxProfile(TaxKind.PERCENT_OF_PROFIT, Bp(1_500), verified=True)


def reference(**overrides: object):  # type: ignore[no-untyped-def]
    args: dict[str, object] = {
        "sale_price": 60_000,
        "buyer_shipping_charge": 1_500,
        "acquisition_cost": 40_000,
        "days_to_sell": 10,
        "fee": FEE,
        "tax": TAX_15_PROFIT,
        "return_rate_bp": 300,
        "return_cost_huf": 3_000,
        "defect_rate_bp": 200,
        "defect_loss_bp": 5_000,
        "capital_cost_bp_per_year": 800,
        "storage_cost_huf_per_day": 0,
    }
    args.update(overrides)
    return resale_scenario(**args)  # type: ignore[arg-type]


def test_reference_scenario_by_hand() -> None:
    """gross 61 500; commission 10 % x 60 000 = 6 000; payment 1.5 % x 61 500 = 922.5 -> 923 + 50
    = 973; return 3 % x 3 000 = 90; defect 2 % x (50 % x 60 000) = 600; holding 40 000 x 8 % x
    10 / 365 = 87.67 -> 88; pre-tax 61 500 - 40 000 - 6 000 - 973 - 1 990 - 500 - 90 - 600 - 88
    = 11 259; tax 15 % = 1 688.85 -> 1 689; net 9 570; ROI 9 570 / 40 000 = 23.925 % -> 2 393 bp."""
    s = reference()
    assert (s.commission, s.payment_fee, s.fixed_fees) == (6_000, 973, 0)
    assert (s.outbound_shipping, s.packaging) == (1_990, 500)
    assert (s.expected_return_cost, s.expected_defect_cost, s.holding_cost) == (90, 600, 88)
    assert s.tax == 1_689
    assert s.net_profit == 9_570
    assert s.roi_bp == 2_393
    assert s.income - s.total_costs == s.net_profit  # the breakdown adds up exactly


def test_commission_minimum_cap_and_shipping_base() -> None:
    assert commission(1_000, 0, FEE) == 200  # 10 % = 100 < minimum 200
    capped = FeeProfile("x", Bp(1_000), commission_cap_huf=5_000)
    assert commission(100_000, 0, capped) == 5_000
    with_ship = FeeProfile("x", Bp(1_000), commission_includes_shipping=True)
    assert commission(60_000, 1_500, with_ship) == 6_150
    assert commission(0, 0, FeeProfile("x", Bp(0))) == 0


def test_payment_fee_rounding() -> None:
    assert payment_fee(61_500, FEE) == 973  # 922.5 rounds half up, + 50 fixed
    assert payment_fee(0, FEE) == 50


@pytest.mark.parametrize(
    ("profile", "revenue", "pre_tax", "expected"),
    [
        (TAX_15_PROFIT, 60_000, 11_259, 1_689),
        (TAX_15_PROFIT, 60_000, -5_000, 0),  # no tax on a loss, and no tax credit either
        (
            TaxProfile(TaxKind.PERCENT_OF_REVENUE, Bp(200)),
            60_000,
            -5_000,
            1_200,
        ),  # due even on a loss
        (TaxProfile(TaxKind.NO_TAX_DECLARED), 60_000, 11_259, 0),
    ],
)
def test_tax_cost(profile: TaxProfile, revenue: int, pre_tax: int, expected: int) -> None:
    assert tax_cost(profile, revenue, pre_tax) == expected


def test_tax_requires_a_selected_profile() -> None:
    with pytest.raises(ValueError):
        tax_cost(TaxProfile(TaxKind.NONE_SELECTED), 1, 1)


def test_holding_and_expected_costs() -> None:
    assert holding_cost(40_000, 10, 800, 0) == 88
    assert holding_cost(40_000, 0, 800, 100) == 0
    assert holding_cost(40_000, 30, 0, 100) == 3_000  # storage only
    assert holding_cost(365_000, 365, 1_000, 0) == 36_500  # 10 % of a year
    assert expected_cost(300, 3_000) == 90
    assert expected_cost(0, 3_000) == 0


def test_roi_edge_cases() -> None:
    assert roi_bp(9_570, 40_000) == 2_393
    assert roi_bp(-10_000, 40_000) == -2_500
    assert roi_bp(0, 40_000) == 0
    assert roi_bp(5_000, 0) is None  # free item: ROI undefined, not infinite


def test_effective_price_never_assumes_free_delivery() -> None:
    assert effective_price(10_000, 1_990, False) == 11_990
    assert effective_price(10_000, None, False) is None
    assert effective_price(10_000, None, True) == 10_000  # pickup: travel cost handled elsewhere
    assert effective_price(None, 0, False) is None


def test_discount_bp_sign() -> None:
    assert discount_bp(100_000, 80_000) == 2_000
    assert discount_bp(100_000, 103_000) == -300
    assert discount_bp(100_000, 100_000) == 0
    with pytest.raises(ValueError):
        discount_bp(0, 1)


def test_scenario_rejects_incomplete_profile_and_negative_input() -> None:
    with pytest.raises(ValueError):
        reference(fee=FeeProfile("x", Bp(1_000)))  # no shipping / packaging cost
    with pytest.raises(ValueError):
        reference(sale_price=-1)


def test_loss_scenario() -> None:
    s = reference(sale_price=38_000)
    assert s.net_profit < 0 and s.tax == 0
    assert s.roi_bp is not None and s.roi_bp < 0


def test_free_acquisition() -> None:
    s = reference(acquisition_cost=0)
    assert s.roi_bp is None and s.holding_cost == 0 and s.net_profit > 0


def test_capital_exposure() -> None:
    fee = FeeProfile(
        "x", Bp(0), listing_fee_huf=290, outbound_shipping_cost_huf=0, packaging_huf=500
    )
    assert capital_exposure(40_000, fee) == 40_790


@pytest.mark.parametrize("seed", range(30))
def test_breakdown_always_adds_up(seed: int) -> None:
    rng = random.Random(seed)
    fee = FeeProfile(
        "x",
        Bp(rng.randint(0, 2_000)),
        commission_min_huf=rng.randint(0, 500),
        commission_cap_huf=rng.choice([None, rng.randint(500, 20_000)]),
        commission_includes_shipping=rng.random() < 0.5,
        fixed_fee_huf=rng.randint(0, 300),
        listing_fee_huf=rng.randint(0, 300),
        payment_fee_bp=Bp(rng.randint(0, 400)),
        payment_fixed_huf=rng.randint(0, 100),
        outbound_shipping_cost_huf=rng.randint(0, 5_000),
        packaging_huf=rng.randint(0, 1_000),
    )
    tax = rng.choice(
        [
            TaxProfile(TaxKind.NO_TAX_DECLARED),
            TaxProfile(TaxKind.PERCENT_OF_PROFIT, Bp(rng.randint(0, 3_000))),
            TaxProfile(TaxKind.PERCENT_OF_REVENUE, Bp(rng.randint(0, 1_000))),
        ]
    )
    s = reference(
        sale_price=rng.randint(0, 900_000),
        buyer_shipping_charge=rng.randint(0, 5_000),
        acquisition_cost=rng.randint(0, 900_000),
        days_to_sell=rng.randint(0, 200),
        fee=fee,
        tax=tax,
        return_rate_bp=rng.randint(0, 3_000),
        return_cost_huf=rng.randint(0, 20_000),
        defect_rate_bp=rng.randint(0, 2_000),
        defect_loss_bp=rng.randint(0, 10_000),
        capital_cost_bp_per_year=rng.randint(0, 2_000),
        storage_cost_huf_per_day=rng.randint(0, 200),
    )
    assert s.income - s.total_costs == s.net_profit
    assert min(s.commission, s.payment_fee, s.tax, s.holding_cost) >= 0
