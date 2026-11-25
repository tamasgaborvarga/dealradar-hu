"""Robust statistics on integer prices with Decimal arithmetic (no floats, ADR-007)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_FLOOR, Decimal

from dealradar.core.money import round_huf
from dealradar.pricing.types import PriceStats

MAD_SCALE = Decimal("0.6745")  # makes the MAD consistent with a normal standard deviation


def median(values: Sequence[Decimal]) -> Decimal:
    if not values:
        raise ValueError("median of empty sample")
    s = sorted(values)
    mid = len(s) // 2
    return s[mid] if len(s) % 2 else (s[mid - 1] + s[mid]) / 2


def quantile(values: Sequence[Decimal], p: Decimal) -> Decimal:
    """Linear interpolation between order statistics (Hyndman-Fan type 7, as R / numpy default)."""
    if not values:
        raise ValueError("quantile of empty sample")
    if not Decimal(0) <= p <= Decimal(1):
        raise ValueError("p must be within 0..1")
    s = sorted(values)
    h = (len(s) - 1) * p
    lo = int(h.to_integral_value(rounding=ROUND_FLOOR))
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (h - lo) * (s[hi] - s[lo])


def trimmed_mean(values: Sequence[Decimal], fraction: Decimal) -> Decimal | None:
    """Mean after dropping floor(n * fraction) values at each end. None if nothing would remain."""
    if not Decimal(0) <= fraction < Decimal("0.5"):
        raise ValueError("fraction must be within 0..0.5")
    s = sorted(values)
    k = int((len(s) * fraction).to_integral_value(rounding=ROUND_FLOOR))
    kept = s[k : len(s) - k]
    if not kept:
        return None
    return sum(kept, Decimal(0)) / len(kept)


@dataclass(frozen=True)
class OutlierResult:
    indices: frozenset[int]
    method: str  # "mad", "relative" (MAD was 0) or "skipped"
    reasons: dict[int, str]


def find_outliers(
    values: Sequence[Decimal],
    *,
    z_limit: Decimal,
    rel_limit_when_mad_zero: Decimal,
    min_samples: int,
) -> OutlierResult:
    """Modified z-score on the median absolute deviation (robust to the outliers themselves).

    If more than half the values are identical (MAD = 0), values further than
    ``rel_limit_when_mad_zero`` from the median (relative) are flagged instead. Zero prices are
    always flagged. Samples smaller than ``min_samples`` are not checked (reported as "skipped").
    """
    reasons: dict[int, str] = {i: "zero price" for i, v in enumerate(values) if v == 0}
    if len(values) < min_samples:
        return OutlierResult(frozenset(reasons), "skipped", reasons)
    m = median(values)
    mad = median([abs(v - m) for v in values])
    if mad > 0:
        for i, v in enumerate(values):
            z = MAD_SCALE * (v - m) / mad
            if abs(z) > z_limit:
                side = "low" if v < m else "high"
                reasons.setdefault(i, f"{side} outlier (modified z {z:.1f})")
        return OutlierResult(frozenset(reasons), "mad", reasons)
    if m == 0:
        return OutlierResult(frozenset(reasons), "relative", reasons)
    for i, v in enumerate(values):
        rel = abs(v - m) / m
        if rel > rel_limit_when_mad_zero:
            side = "low" if v < m else "high"
            reasons.setdefault(i, f"{side} outlier ({rel:.0%} from the typical price)")
    return OutlierResult(frozenset(reasons), "relative", reasons)


def summarize(
    clean: Sequence[int], all_values: Sequence[int], trim_fraction: Decimal, unit: str = "HUF"
) -> PriceStats:
    """PriceStats from outlier-free values (``clean``) plus the median of everything."""
    if not clean:
        raise ValueError("cannot summarize an empty sample")
    c = [Decimal(v) for v in clean]
    tm = trimmed_mean(c, trim_fraction)

    def r(x: Decimal) -> int:
        return int(round_huf(x))

    return PriceStats(
        unit=unit,
        n=len(c),
        min=min(clean),
        p10=r(quantile(c, Decimal("0.10"))),
        p25=r(quantile(c, Decimal("0.25"))),
        trimmed_median=r(median(c)),
        p75=r(quantile(c, Decimal("0.75"))),
        p90=r(quantile(c, Decimal("0.90"))),
        max=max(clean),
        median_all=r(median([Decimal(v) for v in all_values])),
        trimmed_mean=None if tm is None else r(tm),
    )
