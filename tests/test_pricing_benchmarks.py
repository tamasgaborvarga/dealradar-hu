"""Benchmark behaviour on synthetic data. One test (or more) per requirement."""

from __future__ import annotations

import random
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest

from dealradar.categories.registry import module_for
from dealradar.core.enums import Availability, Category, Condition, ListingKind, SaleEvidence
from dealradar.pricing.benchmarks import (
    advertised_benchmark,
    sold_benchmark,
    unit_price_across_packs,
)
from dealradar.pricing.types import (
    BenchmarkKey,
    BenchmarkPolicy,
    BenchmarkStatus,
    Channel,
    ConditionGroup,
    Confidence,
    PriceKind,
)
from tests.pricing_fixtures import KEY_NEW_RETAIL, NOW, daily, market, point, sale

POLICY = BenchmarkPolicy()
TECH = module_for(Category.TECH).benchmark_policy
FOOD = module_for(Category.FOOD).benchmark_policy
HOME = module_for(Category.HOME).benchmark_policy


def bench(points, policy=POLICY, key=KEY_NEW_RETAIL, **kw):  # type: ignore[no-untyped-def]
    return advertised_benchmark(points, key, policy, NOW, **kw)


# --- insufficient data: explicit status, no invented numbers ---


def test_no_data() -> None:
    b = bench([])
    assert b.status is BenchmarkStatus.NO_DATA and b.confidence is Confidence.NONE
    assert b.item is None and b.lowest_current is None


def test_insufficient_data_returns_no_statistics() -> None:
    b = bench([*daily(1, [10_000, 10_100]), point(2, 9_900)])
    assert b.status is BenchmarkStatus.INSUFFICIENT_DATA
    assert b.confidence is Confidence.NONE
    assert b.item is None and b.landed is None and b.delivery is None
    assert any("need 5" in r for r in b.reasons)
    assert b.lowest_current is not None and b.lowest_current.price_huf == 9_900  # a fact, kept


def test_single_offer_is_never_a_market_price() -> None:
    b = bench(daily(1, [10_000] * 30))
    assert b.status is BenchmarkStatus.INSUFFICIENT_DATA
    assert any("distinct offer" in r for r in b.reasons)


# --- observations, also unchanged ones; offer-day sampling ---


def test_unchanged_hourly_checks_count_once_per_day() -> None:
    hourly = [point(1, 10_000, hours_ago=h) for h in range(10)]  # 10 checks today
    others = [*daily(2, [10_200] * 3), *daily(3, [9_800] * 3)]
    b = bench([*hourly, *daily(1, [10_000] * 3, start_days_ago=1), *others])
    assert b.n_observations == 19
    assert b.n_samples == 10  # offer 1: 4 days, offers 2-3: 3 days each
    assert b.status is BenchmarkStatus.OK


def test_latest_observation_of_the_day_wins() -> None:
    pts = [point(1, 12_000, hours_ago=5), point(1, 10_000, hours_ago=1)]
    pts += [point(o, 10_000) for o in (2, 3, 4, 5)]
    b = bench(pts)
    assert b.item is not None and b.item.max == 10_000


def test_days_without_checks_are_not_filled_in() -> None:
    pts = [*daily(1, [10_000], start_days_ago=0), *daily(1, [10_000], start_days_ago=9)]
    pts += [*daily(2, [10_000] * 2), *daily(3, [10_000])]
    b = bench(pts)
    assert b.n_samples == 5  # 2 + 2 + 1 offer-days; days 1-8 of offer 1 are unknown


# --- statistics and outliers ---


def test_ok_benchmark_statistics() -> None:
    b = bench(market(5, 6, 100_000, sources=5))
    assert b.status is BenchmarkStatus.OK
    s = b.item
    assert s is not None and s.n == 30
    assert s.min <= s.p10 <= s.p25 <= s.trimmed_median <= s.p75 <= s.p90 <= s.max
    assert 97_000 <= s.trimmed_median <= 103_000
    assert b.n_offers == 5 and b.n_sources == 5
    assert b.price_kind is PriceKind.ADVERTISED


def test_suspicious_outliers_are_excluded_and_reported() -> None:
    pts = [*market(5, 4, 100_000), point(9, 9_900), point(10, 990_000)]
    b = bench(pts)
    assert {o.ref_id for o in b.outliers} == {9, 10}
    assert b.item is not None and b.item.min > 90_000 and b.item.max < 110_000
    assert b.item.median_all != 0
    assert b.lowest_current is not None and b.lowest_current.offer_id == 9
    assert b.lowest_current.flagged_outlier  # kept as a fact, flagged for review


# --- separation: condition, channel, variant ---


def test_conditions_are_never_mixed() -> None:
    new = market(5, 3, 100_000)
    used = [
        replace(p, offer_id=p.offer_id + 100, price_huf=60_000, condition=Condition.USED_B)
        for p in new
    ]
    refurb = [replace(p, offer_id=p.offer_id + 200, condition=Condition.REFURBISHED) for p in new]
    unknown = [replace(p, offer_id=p.offer_id + 300, condition=None) for p in new]
    b = bench([*new, *used, *refurb, *unknown])
    assert b.item is not None and b.item.min > 90_000
    assert b.excluded == {"other_condition": 30, "condition_unknown": 15}
    used_b = bench([*new, *used], key=BenchmarkKey(1, ConditionGroup.USED, Channel.RETAIL))
    assert used_b.item is not None and used_b.item.trimmed_median == 60_000


def test_open_box_is_its_own_group() -> None:
    pts = [replace(p, condition=Condition.OPEN_BOX) for p in market(5, 2, 90_000)]
    assert bench(pts).status is BenchmarkStatus.NO_DATA
    ob = bench(pts, key=BenchmarkKey(1, ConditionGroup.OPEN_BOX, Channel.RETAIL))
    assert ob.status is BenchmarkStatus.OK


def test_secondhand_asks_are_not_retail_prices() -> None:
    asks = [replace(p, listing_kind=ListingKind.CLASSIFIED) for p in market(5, 3, 70_000)]
    b = bench([*market(5, 3, 100_000), *asks])
    assert b.excluded["other_channel"] == 15
    assert b.item is not None and b.item.min > 90_000


def test_other_and_unresolved_variants_are_never_compared() -> None:
    other = [replace(p, variant_id=2, price_huf=50_000) for p in market(5, 3, 100_000)]
    unresolved = [replace(p, variant_id=None) for p in market(5, 3, 100_000)]
    b = bench([*market(5, 3, 100_000), *other, *unresolved])
    assert b.excluded["other_variant"] == 30
    assert b.item is not None and b.item.min > 90_000


def test_merged_variants_count_as_the_surviving_variant() -> None:
    merged = [replace(p, variant_id=7) for p in market(5, 3, 100_000)]
    assert bench(merged).status is BenchmarkStatus.NO_DATA
    assert bench(merged, variant_ids=frozenset({1, 7})).status is BenchmarkStatus.OK


# --- delivery costs are separate ---


def test_delivery_tracked_separately_and_unknown_is_not_free() -> None:
    known = market(5, 2, 100_000, shipping=1_990)
    unknown = [
        replace(p, offer_id=p.offer_id + 10, shipping_huf=None) for p in market(5, 2, 100_000)
    ]
    free = [replace(p, offer_id=p.offer_id + 20, shipping_huf=0) for p in market(5, 1, 100_000)]
    b = bench([*known, *unknown, *free])
    d = b.delivery
    assert d is not None and (d.n_known, d.n_unknown, d.n_free) == (15, 10, 5)
    assert d.median_huf == 1_990
    assert b.landed is not None and b.landed.n == 15  # only samples with a known delivery cost
    assert b.item is not None and b.item.n == 25


def test_landed_price_needs_known_delivery_and_matters_for_home() -> None:
    pts = market(5, 3, 200_000, shipping=None)
    tech = bench(pts, policy=TECH)
    assert tech.landed is None and tech.status is BenchmarkStatus.OK
    home = bench(pts, policy=HOME)
    assert home.landed is None
    assert any("landed price unavailable" in r for r in home.reasons)
    assert home.confidence is not Confidence.HIGH


# --- availability, loyalty, multi-buy ---


def test_out_of_stock_loyalty_and_multibuy_excluded_by_default() -> None:
    base = market(5, 2, 100_000)
    oos = [
        replace(p, offer_id=p.offer_id + 10, availability=Availability.OUT_OF_STOCK) for p in base
    ]
    loyal = [
        replace(p, offer_id=p.offer_id + 20, price_huf=80_000, loyalty_only=True) for p in base
    ]
    multi = [replace(p, offer_id=p.offer_id + 30, min_quantity=3) for p in base]
    b = bench([*base, *oos, *loyal, *multi])
    assert b.excluded == {"out_of_stock": 10, "loyalty_only": 10, "multi_buy": 10}
    with_loyalty = bench([*base, *loyal], policy=replace(POLICY, include_loyalty_only=True))
    assert with_loyalty.n_samples == 20


# --- staleness, windows, confidence ---


def test_stale_benchmark_is_labelled_and_capped() -> None:
    pts = [
        replace(p, observed_at=p.observed_at - timedelta(days=20)) for p in market(5, 5, 100_000)
    ]
    b = bench(pts)
    assert b.status is BenchmarkStatus.STALE
    assert b.confidence in (Confidence.LOW, Confidence.NONE)
    assert any("days old" in r for r in b.reasons)


def test_observations_outside_window_are_ignored() -> None:
    old = [
        replace(p, observed_at=p.observed_at - timedelta(days=100)) for p in market(5, 5, 100_000)
    ]
    b = bench(old)
    assert b.status is BenchmarkStatus.NO_DATA and b.excluded == {"outside_window": 25}


def test_high_confidence_requires_volume_sources_and_tight_prices() -> None:
    assert bench(market(6, 5, 100_000, sources=3)).confidence is Confidence.HIGH
    single = bench(market(6, 5, 100_000, sources=1))
    assert single.confidence is not Confidence.HIGH
    assert any("1 source" in r for r in single.reasons)
    wide = bench(market(6, 5, 100_000, spread=0.4, sources=3))
    assert wide.confidence is not Confidence.HIGH
    assert any("spread" in r for r in wide.reasons)
    few = bench(market(5, 1, 100_000, sources=3))
    assert few.confidence is Confidence.LOW


# --- lowest current price is a fact with freshness ---


def test_lowest_current_requires_fresh_buyable_observation() -> None:
    pts = market(5, 3, 100_000)
    pts.append(point(8, 80_000, days_ago=3))  # cheap, but 3 days old
    pts.append(point(9, 85_000, availability=Availability.OUT_OF_STOCK))
    b = bench(pts)
    assert b.lowest_current is not None and b.lowest_current.price_huf >= 97_000
    stale_only = bench([replace(p, observed_at=p.observed_at - timedelta(days=3)) for p in pts])
    assert stale_only.lowest_current is None


def test_naive_now_rejected() -> None:
    with pytest.raises(ValueError):
        advertised_benchmark([], KEY_NEW_RETAIL, POLICY, NOW.replace(tzinfo=None))


# --- category awareness ---


def test_food_ignores_condition_and_reports_unit_price() -> None:
    pts = [replace(p, condition=None) for p in market(5, 3, 899)]
    b = bench(pts, policy=FOOD, unit_total=Decimal("0.5"))
    assert b.key.condition_group is ConditionGroup.NOT_APPLICABLE
    assert b.status is BenchmarkStatus.OK
    assert b.unit_price is not None and b.unit_price.unit == "CHUF"
    assert b.unit_price.trimmed_median == b.item.trimmed_median * 200  # per kg, in centi-HUF
    no_pack = bench(pts, policy=FOOD)
    assert no_pack.unit_price is None and any("pack size" in r for r in no_pack.reasons)


def test_food_window_is_shorter_than_tech() -> None:
    pts = [replace(p, observed_at=p.observed_at - timedelta(days=40)) for p in market(5, 5, 899)]
    assert bench(pts, policy=TECH).status is not BenchmarkStatus.NO_DATA
    assert (
        bench([replace(p, condition=None) for p in pts], policy=FOOD).status
        is BenchmarkStatus.NO_DATA
    )


def test_every_category_has_a_policy() -> None:
    for category in Category:
        assert isinstance(module_for(category).benchmark_policy, BenchmarkPolicy)
    assert FOOD.cross_variant_unit_price and not TECH.cross_variant_unit_price


# --- completed sales are a separate benchmark ---


def test_sold_benchmark_uses_completed_sales_only() -> None:
    sales = [
        sale(p, days_ago=i, platform=1 + i % 2)
        for i, p in enumerate([60_000, 62_000, 61_000, 59_000, 63_000])
    ]
    b = sold_benchmark(sales, 1, ConditionGroup.USED, POLICY, NOW)
    assert b.price_kind is PriceKind.SOLD and b.status is BenchmarkStatus.OK
    assert b.sale_price is not None and b.sale_price.trimmed_median == 61_000
    assert b.buyer_delivery is not None and b.buyer_delivery.median_huf == 1_500
    assert b.median_days_listed == 5 and b.n_platforms == 2


def test_sold_benchmark_insufficient_and_condition_separated() -> None:
    b = sold_benchmark([sale(60_000), sale(61_000)], 1, ConditionGroup.USED, POLICY, NOW)
    assert b.status is BenchmarkStatus.INSUFFICIENT_DATA and b.sale_price is None
    new = sold_benchmark(
        [sale(90_000, condition=Condition.NEW)] * 5, 1, ConditionGroup.USED, POLICY, NOW
    )
    assert new.status is BenchmarkStatus.NO_DATA


def test_user_reported_sales_cap_confidence() -> None:
    sales = [
        sale(60_000 + i * 100, days_ago=i, platform=i % 3, evidence=SaleEvidence.USER_REPORTED)
        for i in range(12)
    ]
    b = sold_benchmark(sales, 1, ConditionGroup.USED, POLICY, NOW)
    assert b.confidence is not Confidence.HIGH
    assert any("user-reported" in r for r in b.reasons)
    assert b.evidence == {"USER_REPORTED": 12}


def test_outlier_sale_excluded() -> None:
    sales = [
        sale(p, days_ago=i) for i, p in enumerate([60_000, 61_000, 59_500, 60_500, 61_500, 5_000])
    ]
    b = sold_benchmark(sales, 1, ConditionGroup.USED, POLICY, NOW)
    assert [o.value for o in b.outliers] == [5_000]
    assert b.sale_price is not None and b.sale_price.min >= 59_500


# --- unit price across pack sizes (food only) ---


def test_unit_price_across_pack_sizes_for_food() -> None:
    small = [replace(p, variant_id=11, condition=None) for p in market(3, 3, 899)]  # 500 g
    big = [
        replace(p, offer_id=p.offer_id + 10, variant_id=12, condition=None)
        for p in market(3, 3, 1_599)
    ]  # 1 kg
    b = unit_price_across_packs([*small, *big], 5, {11: Decimal("0.5"), 12: Decimal("1")}, "KG",
                                Channel.RETAIL, FOOD, NOW)  # fmt: skip
    assert b.status is BenchmarkStatus.OK and b.basis == "UNIT_PRICE_ACROSS_PACK_SIZES"
    assert b.samples_per_variant == {11: 9, 12: 9}
    assert b.unit_price is not None and b.unit_price.min < 170_000 < b.unit_price.max


def test_cross_variant_comparison_refused_outside_food() -> None:
    with pytest.raises(ValueError):
        unit_price_across_packs([], 5, {}, "KG", Channel.RETAIL, TECH, NOW)


# --- invariants on random synthetic markets ---


@pytest.mark.parametrize("seed", range(25))
def test_invariants_on_random_markets(seed: int) -> None:
    rng = random.Random(seed)
    pts = market(
        rng.randint(1, 8),
        rng.randint(1, 10),
        rng.randint(1_000, 900_000),
        spread=rng.choice([0.01, 0.1, 0.5]),
        seed=seed,
        sources=rng.randint(1, 4),
    )
    pts += [point(99, rng.choice([1, 10_000_000]))] if rng.random() < 0.5 else []
    b = bench(pts)
    assert b.n_samples <= b.n_observations
    if b.status in (BenchmarkStatus.NO_DATA, BenchmarkStatus.INSUFFICIENT_DATA):
        assert b.item is None and b.confidence is Confidence.NONE
    else:
        s = b.item
        assert s is not None
        assert s.min <= s.p10 <= s.p25 <= s.trimmed_median <= s.p75 <= s.p90 <= s.max
        assert s.n == b.n_samples
    offer_days = len({(p.offer_id, p.observed_at.date()) for p in pts})
    if b.status is not BenchmarkStatus.NO_DATA:
        assert b.n_samples + len(b.outliers) == offer_days  # every offer-day used or reported
