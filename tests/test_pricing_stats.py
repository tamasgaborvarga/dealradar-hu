from __future__ import annotations

import random
import statistics
from decimal import Decimal

import pytest

from dealradar.pricing.stats import find_outliers, median, quantile, summarize, trimmed_mean

D = Decimal


def ds(*values: int) -> list[Decimal]:
    return [D(v) for v in values]


def test_median_odd_even() -> None:
    assert median(ds(3, 1, 2)) == 2
    assert median(ds(4, 1, 3, 2)) == D("2.5")
    with pytest.raises(ValueError):
        median([])


@pytest.mark.parametrize("seed", range(20))
def test_quantile_matches_type7_oracle(seed: int) -> None:
    rng = random.Random(seed)
    values = [rng.randint(1_000, 500_000) for _ in range(rng.randint(2, 60))]
    oracle = statistics.quantiles(values, n=20, method="inclusive")  # type 7, every 5 %
    for i, expected in enumerate(oracle, start=1):
        got = quantile(ds(*values), D(i) / 20)
        assert abs(float(got) - expected) < 1e-6  # test-side float only


def test_quantile_edges() -> None:
    assert quantile(ds(10, 20, 30), D(0)) == 10
    assert quantile(ds(10, 20, 30), D(1)) == 30
    assert quantile(ds(10, 20, 30, 40), D("0.25")) == D("17.5")
    assert quantile(ds(7), D("0.9")) == 7
    with pytest.raises(ValueError):
        quantile(ds(1, 2), D("1.5"))


def test_trimmed_mean() -> None:
    values = ds(1, 100, 101, 102, 103, 104, 105, 106, 107, 10_000)
    assert trimmed_mean(values, D("0.1")) == D("103.5")  # drops 1 and 10 000
    assert trimmed_mean(ds(1, 2, 3), D(0)) == 2
    assert trimmed_mean(ds(5), D("0.4")) == 5
    with pytest.raises(ValueError):
        trimmed_mean(ds(1, 2), D("0.5"))


def test_outliers_mad() -> None:
    values = ds(100, 101, 99, 102, 98, 100, 101, 10, 400)
    found = find_outliers(values, z_limit=D("3.5"), rel_limit_when_mad_zero=D("0.5"), min_samples=5)
    assert found.method == "mad"
    assert found.indices == {7, 8}
    assert "low" in found.reasons[7] and "high" in found.reasons[8]


def test_outliers_when_most_values_identical() -> None:
    values = ds(100, 100, 100, 100, 100, 140, 40)
    found = find_outliers(values, z_limit=D("3.5"), rel_limit_when_mad_zero=D("0.5"), min_samples=5)
    assert found.method == "relative"
    assert found.indices == {6}  # 40 is 60 % below; 140 is only 40 % above


def test_outlier_check_skipped_for_small_samples_but_zero_flagged() -> None:
    found = find_outliers(
        ds(100, 0, 5_000), z_limit=D("3.5"), rel_limit_when_mad_zero=D("0.5"), min_samples=5
    )
    assert found.method == "skipped"
    assert found.indices == {1}  # a zero price is always suspicious


def test_summarize_separates_robust_and_raw_median() -> None:
    clean = [100, 102, 104, 106, 108]
    stats = summarize(clean, [*clean, 1, 2], D("0.1"))
    assert stats.trimmed_median == 104
    assert stats.median_all == 102
    assert (stats.min, stats.max, stats.n) == (100, 108, 5)
    assert stats.p10 <= stats.p25 <= stats.trimmed_median <= stats.p75 <= stats.p90
    assert stats.dispersion == D(4) / D(104)
    with pytest.raises(ValueError):
        summarize([], [1], D("0.1"))


def test_summarize_rounds_half_up_to_whole_huf() -> None:
    assert summarize([1, 2], [1, 2], D(0)).trimmed_median == 2  # 1.5 -> 2
