from __future__ import annotations

import pytest

from dealradar.core.enums import Condition, MatchMethod, MatchStatus, WarrantyType
from dealradar.engines.personal import WatchlistRelevance, evaluate
from dealradar.evaluation.params import PersonalParams
from dealradar.evaluation.types import Level, MatchInfo, PersonalVerdict, ValueKind, WatchlistTarget
from tests.engine_fixtures import advertised, personal_inputs

V = PersonalVerdict


@pytest.mark.parametrize(
    ("price", "verdict", "discount"),
    [
        (80_000, V.STRONG_DEAL, 2_000),  # exactly 20 % below the median
        (80_010, V.GOOD_DEAL, 1_999),
        (90_000, V.GOOD_DEAL, 1_000),  # exactly 10 %
        (90_010, V.FAIR_PRICE, 999),
        (103_000, V.FAIR_PRICE, -300),  # exactly 3 % above the median
        (103_010, V.NOT_A_DEAL, -301),
    ],
)
def test_threshold_boundaries(price: int, verdict: PersonalVerdict, discount: int) -> None:
    r = evaluate(personal_inputs(price, benchmark=advertised(item_min=70_000)))
    assert (r.verdict, r.discount_vs_median_bp) == (verdict, discount)
    assert r.comparison_basis == "ITEM" and r.benchmark_median_huf == 100_000


def test_strong_needs_high_confidence_benchmark() -> None:
    r = evaluate(personal_inputs(80_000, benchmark=advertised(confidence=Level.MEDIUM)))
    assert r.verdict is V.GOOD_DEAL
    assert any("nem elég megbízható" in x for x in r.reasons)


def test_historical_minimum_upgrades_good_to_strong() -> None:
    r = evaluate(personal_inputs(85_000))  # 15 % below median, equal to historical min
    assert r.at_or_below_historical_min and r.discount_vs_min_bp == 0
    assert r.verdict is V.STRONG_DEAL


def test_too_good_to_be_true_needs_review() -> None:
    r = evaluate(personal_inputs(50_000))
    assert r.verdict is V.MANUAL_REVIEW and "too_good_to_be_true" in r.review_flags


@pytest.mark.parametrize(
    ("kw", "field", "code"),
    [
        ({"benchmark": None}, "missing", "price_benchmark"),
        (
            {"benchmark": advertised(status="INSUFFICIENT_DATA", item_median=None)},
            "missing",
            "price_benchmark",
        ),
        ({"benchmark": advertised(status="STALE")}, "flags", "benchmark_stale"),
        ({"benchmark": advertised(confidence=Level.LOW)}, "flags", "benchmark_confidence_low"),
        (
            {"benchmark": advertised(condition_group="USED")},
            "flags",
            "benchmark_condition_mismatch",
        ),
        ({"match": MatchInfo(MatchStatus.UNMATCHED)}, "missing", "product_match"),
        (
            {"match": MatchInfo(MatchStatus.MATCHED, MatchMethod.FUZZY, 95)},
            "flags",
            "match_not_confirmed",
        ),
        (
            {"match": MatchInfo(MatchStatus.MATCHED, MatchMethod.RULE, 85)},
            "flags",
            "match_confidence_low",
        ),
        ({"category_kw": {"shipping_huf": None}}, "missing", "shipping"),  # engine checks itself
        ({"category_kw": {"price_huf": None}}, "missing", "price"),
        ({"category_kw": {"missing_inputs": ("warranty",)}}, "missing", "warranty"),
        ({"category_kw": {"review_flags": ("authenticity_high",)}}, "flags", "authenticity_high"),
        ({"warranty_type": WarrantyType.NONE}, "flags", "new_without_warranty"),
    ],
)
def test_uncertainty_means_manual_review(kw: dict[str, object], field: str, code: str) -> None:
    r = evaluate(personal_inputs(80_000, **kw))
    assert r.verdict is V.MANUAL_REVIEW
    assert code in (r.missing_inputs if field == "missing" else r.review_flags)


def test_user_confirmed_fuzzy_match_is_accepted() -> None:
    m = MatchInfo(MatchStatus.MATCHED, MatchMethod.FUZZY, 70, confirmed_by_user=True)
    assert evaluate(personal_inputs(80_000, match=m)).verdict is V.STRONG_DEAL


def test_landed_comparison_includes_delivery() -> None:
    r = evaluate(
        personal_inputs(
            80_000,
            category_kw={"shipping_huf": 4_990},
            benchmark=advertised(landed_median=101_990, item_min=70_000),
        )
    )
    assert r.comparison_basis == "LANDED"
    assert (r.effective_price_huf, r.compared_price_huf) == (84_990, 84_990)
    assert r.discount_vs_median_bp == 1_667  # (101 990 - 84 990) / 101 990
    assert r.verdict is V.GOOD_DEAL


def test_bulky_goods_require_landed_comparison() -> None:
    p = PersonalParams(require_landed_comparison=True)
    r = evaluate(personal_inputs(80_000, params=p))
    assert r.verdict is V.MANUAL_REVIEW and "landed_benchmark_missing" in r.review_flags


def test_item_comparison_is_labelled() -> None:
    r = evaluate(personal_inputs(80_000, category_kw={"shipping_huf": 2_990}))
    assert r.effective_price_huf == 82_990
    assert any("szállítási díj nélkül" in x for x in r.reasons)


def test_watchlist_target_and_limits() -> None:
    w = WatchlistTarget(target_price_huf=82_000, max_price_huf=95_000)
    met = evaluate(personal_inputs(80_000, watchlist=w))
    assert met.watchlist is WatchlistRelevance.TARGET_MET and met.verdict is V.STRONG_DEAL
    above = evaluate(personal_inputs(96_000, watchlist=w))
    assert above.watchlist is WatchlistRelevance.ABOVE_MAX_PRICE and above.verdict is V.NOT_A_DEAL
    used_only = WatchlistTarget(acceptable_conditions=frozenset({Condition.USED_A}))
    blocked = evaluate(personal_inputs(80_000, watchlist=used_only))
    assert blocked.watchlist is WatchlistRelevance.CONDITION_NOT_ACCEPTED
    assert blocked.verdict is V.NOT_A_DEAL
    assert evaluate(personal_inputs(80_000)).watchlist is WatchlistRelevance.NOT_WATCHED


def test_target_met_is_visible_even_without_benchmark() -> None:
    r = evaluate(
        personal_inputs(80_000, benchmark=None, watchlist=WatchlistTarget(target_price_huf=90_000))
    )
    assert r.verdict is V.MANUAL_REVIEW and r.watchlist is WatchlistRelevance.TARGET_MET


def test_minimum_warranty_is_a_user_limit() -> None:
    p = PersonalParams(min_warranty_months_new=36)
    r = evaluate(personal_inputs(80_000, params=p))
    assert r.verdict is V.NOT_A_DEAL and any("garancia" in x for x in r.reasons)


def test_pickup_is_noted() -> None:
    r = evaluate(personal_inputs(80_000, pickup_only=True, category_kw={"shipping_huf": None}))
    assert r.verdict is V.STRONG_DEAL and r.effective_price_huf == 80_000
    assert any("személyes átvétel" in x for x in r.reasons)


def test_result_is_labelled_and_never_authorizes() -> None:
    r = evaluate(personal_inputs(80_000))
    assert r.engine == "PERSONAL" and r.decision_required is True
    kinds = {a.kind for a in r.assumptions}
    assert {ValueKind.ASSUMPTION, ValueKind.ESTIMATE} <= kinds
    assert not hasattr(r, "net_profit_huf")  # no resale numbers in a personal result
