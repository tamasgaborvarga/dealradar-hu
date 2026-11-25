from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest

from dealradar.core.enums import Condition, MatchMethod, MatchStatus
from dealradar.engines.resale import evaluate
from dealradar.engines.resale.liquidity import LiquidityClass, assess
from dealradar.evaluation.params import ResaleParams, TaxKind, TaxProfile
from dealradar.evaluation.types import Level, MatchInfo, ResaleVerdict, ValueKind
from tests.engine_fixtures import FEE, TAX, resale_inputs, sold

V = ResaleVerdict


def test_reference_case_is_profitable_with_exact_numbers() -> None:
    """Same numbers as tests/test_costs.py::test_reference_scenario_by_hand."""
    r = evaluate(resale_inputs())
    assert r.verdict is V.PROFITABLE
    assert (r.acquisition_cost_huf, r.expected_sale_huf) == (40_000, 60_000)
    assert r.net_profit_huf == 9_570 and r.roi_bp == 2_393
    assert r.capital_exposure_huf == 40_500  # acquisition + packaging (no listing fee)
    assert r.liquidity.liquidity is LiquidityClass.MEDIUM and r.liquidity.est_days_to_sell == 10
    assert r.price_source == "COMPLETED_SALES" and r.decision_required is True
    assert r.scenarios is not None and set(r.scenarios) == {"low", "expected", "high"}
    kinds = {a.kind for a in r.assumptions}
    assert {ValueKind.ESTIMATE, ValueKind.ASSUMPTION, ValueKind.USER_INPUT} <= kinds


def test_price_range_from_completed_sales() -> None:
    r = evaluate(resale_inputs(completed_sales=sold(p25=50_000, median=60_000, p75=70_000)))
    assert r.net_profit_low_huf is not None and r.net_profit_high_huf is not None
    assert r.net_profit_low_huf < r.net_profit_huf < r.net_profit_high_huf  # type: ignore[operator]
    assert (r.expected_sale_low_huf, r.expected_sale_high_huf) == (50_000, 70_000)


def test_not_profitable() -> None:
    # gross 46 500 - 40 000 - 4 500 - 748 - 1 990 - 500 - 90 - 450 - 88 = -1 866, no tax on a loss
    r = evaluate(resale_inputs(completed_sales=sold(p25=45_000, median=45_000, p75=45_000)))
    assert r.verdict is V.NOT_PROFITABLE and r.net_profit_huf == -1_866


def test_marginal_when_below_thresholds() -> None:
    # pre-tax 4 259, tax 639 -> net 3 620 < 5 000; ROI 905 bp < 1 500
    r = evaluate(resale_inputs(completed_sales=sold(p25=52_000, median=52_000, p75=52_000)))
    assert r.verdict is V.MARGINAL and r.net_profit_huf == 3_620 and r.roi_bp == 905
    assert any("nettó haszon" in x for x in r.reasons) and any("megtérülés" in x for x in r.reasons)


def test_marginal_when_low_price_would_lose_money() -> None:
    r = evaluate(resale_inputs(completed_sales=sold(p25=42_000, median=60_000, p75=62_000)))
    assert r.verdict is V.MARGINAL and r.net_profit_low_huf is not None and r.net_profit_low_huf < 0
    assert any("alacsony (p25)" in x for x in r.reasons)


def test_marginal_when_illiquid_or_slow() -> None:
    slow = evaluate(resale_inputs(completed_sales=sold(n_sales=3)))  # 0.5 sales / 30 days
    assert slow.verdict is V.MARGINAL and slow.liquidity.liquidity is LiquidityClass.LOW
    long_listing = evaluate(resale_inputs(completed_sales=sold(median_days_listed=70)))
    assert long_listing.verdict is V.MARGINAL
    assert any("nap alatt adható el" in x for x in long_listing.reasons)


@pytest.mark.parametrize(
    ("kw", "code"),
    [
        ({"completed_sales": None}, "completed_sales"),
        ({"completed_sales": sold(status="INSUFFICIENT_DATA", median=None)}, "completed_sales"),
        ({"completed_sales": sold(n_sales=2)}, "completed_sales"),
        ({"fee_profile": None}, "fee_profile"),
        ({"fee_profile": replace(FEE, outbound_shipping_cost_huf=None)}, "outbound_shipping_cost"),
        ({"fee_profile": replace(FEE, packaging_huf=None)}, "packaging_cost"),
        ({"tax_profile": None}, "tax_profile"),
        ({"tax_profile": TaxProfile(TaxKind.NONE_SELECTED)}, "tax_profile"),
        ({"category_kw": {"shipping_huf": None}}, "shipping"),
        ({"category_kw": {"price_huf": None}}, "price"),
        ({"category_kw": {"condition": None}}, "condition"),
        ({"pickup_only": True, "category_kw": {"shipping_huf": None}}, "pickup_travel_cost"),
        ({"match": MatchInfo(MatchStatus.UNMATCHED)}, "product_match"),
        ({"category_kw": {"missing_inputs": ("warranty",)}}, "warranty"),
    ],
)
def test_missing_critical_input_means_no_profit_numbers(kw: dict[str, object], code: str) -> None:
    r = evaluate(resale_inputs(**kw))
    assert r.verdict is V.MANUAL_REVIEW
    assert code in r.missing_inputs
    assert r.net_profit_huf is None and r.scenarios is None and r.roi_bp is None
    assert "nyereség nincs kiszámolva" in r.reasons[0]


@pytest.mark.parametrize(
    ("kw", "flag"),
    [
        ({"fee_profile": replace(FEE, verified=False)}, "fee_profile_unverified"),
        ({"tax_profile": replace(TAX, verified=False)}, "tax_profile_unverified"),
        ({"completed_sales": sold(confidence=Level.LOW)}, "completed_sales_confidence_low"),
        ({"completed_sales": sold(status="STALE")}, "completed_sales_stale"),
        ({"completed_sales": sold(condition_group="NEW")}, "sales_condition_mismatch"),
        ({"match": MatchInfo(MatchStatus.MATCHED, MatchMethod.FUZZY, 92)}, "match_not_confirmed"),
        ({"category_kw": {"review_flags": ("authenticity_high",)}}, "authenticity_high"),
    ],
)
def test_review_flags_give_provisional_numbers(kw: dict[str, object], flag: str) -> None:
    r = evaluate(resale_inputs(**kw))
    assert r.verdict is V.MANUAL_REVIEW and flag in r.review_flags
    assert r.provisional and r.net_profit_huf is not None


def test_not_applicable_category() -> None:
    r = evaluate(resale_inputs(category_kw={"resale_applicable": False}))
    assert r.verdict is V.NOT_APPLICABLE and r.net_profit_huf is None


def test_pickup_with_travel_cost() -> None:
    r = evaluate(
        resale_inputs(
            pickup_only=True,
            category_kw={"shipping_huf": None},
            params_kw={"pickup_travel_cost_huf": 2_000},
        )
    )
    assert r.acquisition_cost_huf == 42_000
    assert any(
        a.name == "pickup travel cost" and a.kind is ValueKind.ASSUMPTION for a in r.assumptions
    )


def test_asking_prices_never_change_the_result() -> None:
    base = evaluate(resale_inputs())
    tempting = evaluate(resale_inputs(context_asking_median=250_000))
    assert (tempting.verdict, tempting.net_profit_huf, tempting.expected_sale_huf) == (
        base.verdict,
        base.net_profit_huf,
        base.expected_sale_huf,
    )
    nothing_sold = evaluate(resale_inputs(completed_sales=None, context_asking_median=250_000))
    assert nothing_sold.verdict is V.MANUAL_REVIEW and nothing_sold.expected_sale_huf is None


def test_unknown_buyer_shipping_is_a_labelled_conservative_assumption() -> None:
    r = evaluate(resale_inputs(completed_sales=sold(buyer_shipping_median=None)))
    a = next(x for x in r.assumptions if x.name == "buyer shipping charge")
    assert a.kind is ValueKind.ASSUMPTION and a.value.startswith("0 HUF")
    assert r.net_profit_huf is not None and r.net_profit_huf < 9_570


def test_revenue_tax_assumption() -> None:
    r = evaluate(
        resale_inputs(tax_profile=TaxProfile(TaxKind.PERCENT_OF_REVENUE, 200, verified=True))
    )
    assert r.scenarios is not None and r.scenarios["expected"].tax == 1_200


def test_user_reported_sales_are_mentioned() -> None:
    r = evaluate(
        resale_inputs(completed_sales=sold(user_reported_only=True, confidence=Level.MEDIUM))
    )
    assert any("saját rögzítésű" in x for x in r.reasons)


def test_category_parameters_change_the_result() -> None:
    risky = evaluate(resale_inputs(params_kw={"return_rate_bp": 2_000, "return_cost_huf": 15_000}))
    assert risky.net_profit_huf is not None and risky.net_profit_huf < 9_570
    assert any("2000 bp" in a.value for a in risky.assumptions if a.name == "returns / defects")


# --- liquidity ---


def test_liquidity_classes() -> None:
    p = ResaleParams()
    high = assess(sold(n_sales=30, median_days_listed=7), p)
    assert high.liquidity is LiquidityClass.HIGH and high.sales_per_30d == Decimal(5)
    assert assess(sold(), p).liquidity is LiquidityClass.MEDIUM
    assert assess(sold(n_sales=3), p).liquidity is LiquidityClass.LOW
    assert assess(None, p).liquidity is LiquidityClass.UNKNOWN


def test_time_to_sell_fallback_from_sale_frequency() -> None:
    liq = assess(sold(n_sales=12, n_with_days_listed=1, median_days_listed=3), ResaleParams())
    assert liq.est_days_to_sell == 15  # 12 sales / 180 days = 2 per 30 days -> one every 15 days
    assert liq.confidence is Level.LOW and "gyakoriságából" in liq.basis


def test_engine_rejects_nothing_silently_for_used_condition() -> None:
    r = evaluate(resale_inputs(category_kw={"condition": Condition.USED}))
    assert r.verdict is V.PROFITABLE  # USED (grade unknown) is still the USED group
