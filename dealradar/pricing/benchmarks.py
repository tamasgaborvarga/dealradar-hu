"""Benchmark computation (pure). Inputs are observation/sale points; output never invents prices.

Sampling unit for advertised prices: one **offer-day** = the last eligible observation of an offer
on a UTC calendar day. Hourly re-checks of an unchanged price are stored (history), but count once
per day here, so a frequently polled shop cannot dominate the median, and days without any check
contribute nothing (no extrapolation over gaps).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from dealradar.core.enums import Availability, SaleEvidence
from dealradar.pricing.stats import OutlierResult, find_outliers, summarize
from dealradar.pricing.types import (
    AdvertisedBenchmark,
    BenchmarkKey,
    BenchmarkPolicy,
    BenchmarkStatus,
    Channel,
    Confidence,
    CurrentPrice,
    DeliveryStats,
    ObservationPoint,
    Outlier,
    PriceStats,
    SalePoint,
    SoldBenchmark,
    UnitPriceBenchmark,
    channel_of,
    condition_group,
)
from dealradar.pricing.types import ConditionGroup as CG

BUYABLE = frozenset({Availability.IN_STOCK, Availability.LIMITED})
_CONFIDENCE_ORDER = (Confidence.NONE, Confidence.LOW, Confidence.MEDIUM, Confidence.HIGH)


# --- helpers ---


def _exclusion(
    p: ObservationPoint,
    group: CG,
    channel: Channel,
    policy: BenchmarkPolicy,
    variant_ids: frozenset[int],
) -> str | None:
    if p.variant_id is None or p.variant_id not in variant_ids:
        return "other_variant"
    if channel_of(p.listing_kind) is not channel:
        return "other_channel"
    if policy.condition_relevant:
        observed_group = condition_group(p.condition)
        if observed_group is None:
            return "condition_unknown"
        if observed_group is not group:
            return "other_condition"
    if p.availability is Availability.OUT_OF_STOCK:
        return "out_of_stock"
    if p.price_huf is None:
        return "price_missing"
    if p.loyalty_only and not policy.include_loyalty_only:
        return "loyalty_only"
    if p.min_quantity > 1 and not policy.include_multibuy:
        return "multi_buy"
    return None


@dataclass(frozen=True)
class _Sample:
    point: ObservationPoint
    day: date
    price: int


def _offer_days(points: Iterable[ObservationPoint]) -> list[_Sample]:
    latest: dict[tuple[int, date], ObservationPoint] = {}
    for p in points:
        k = (p.offer_id, p.observed_at.date())
        if k not in latest or p.observed_at > latest[k].observed_at:
            latest[k] = p
    ordered = sorted(latest.items(), key=lambda kv: kv[1].observed_at)
    return [_Sample(p, d, p.price_huf or 0) for (_, d), p in ordered]


def _median_int(values: Sequence[int]) -> int | None:
    if not values:
        return None
    s = sorted(values)
    mid = len(s) // 2
    if len(s) % 2:
        return s[mid]
    return int(((Decimal(s[mid - 1]) + s[mid]) / 2).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _delivery(costs: Sequence[int | None]) -> DeliveryStats:
    known = [c for c in costs if c is not None]
    return DeliveryStats(
        n_known=len(known),
        n_unknown=len(costs) - len(known),
        n_free=sum(1 for c in known if c == 0),
        median_huf=_median_int(known),
        min_huf=min(known) if known else None,
        max_huf=max(known) if known else None,
    )


def _outliers(values: Sequence[int], policy: BenchmarkPolicy) -> OutlierResult:
    return find_outliers(
        [Decimal(v) for v in values],
        z_limit=policy.outlier_mad_z,
        rel_limit_when_mad_zero=policy.outlier_rel_when_mad_zero,
        min_samples=policy.outlier_min_samples,
    )


def _confidence(
    stats: PriceStats,
    n_sources: int,
    outlier_share: Decimal,
    policy: BenchmarkPolicy,
    high_samples: int,
    min_samples: int,
) -> tuple[Confidence, list[str]]:
    limits: list[str] = []
    if stats.n < high_samples:
        limits.append(f"confidence limited: {stats.n} samples (< {high_samples})")
    if n_sources < policy.min_sources_for_high:
        limits.append(f"confidence limited: {n_sources} source(s)")
    if stats.dispersion > policy.max_dispersion_for_high:
        limits.append(f"confidence limited: wide price spread ({stats.dispersion:.0%} IQR/median)")
    if outlier_share > policy.max_outlier_share_for_high:
        limits.append(f"confidence limited: {outlier_share:.0%} outliers")
    if not limits:
        return Confidence.HIGH, []
    if stats.n >= 2 * min_samples and stats.dispersion <= 2 * policy.max_dispersion_for_high:
        return Confidence.MEDIUM, limits
    return Confidence.LOW, limits


def _cap(confidence: Confidence, cap: Confidence) -> Confidence:
    idx = min(_CONFIDENCE_ORDER.index(confidence), _CONFIDENCE_ORDER.index(cap))
    return _CONFIDENCE_ORDER[idx]


def _chuf(price: int, total: Decimal) -> int:
    return int((Decimal(price) * 100 / total).quantize(Decimal(1), rounding=ROUND_HALF_UP))


# --- advertised prices ---


def advertised_benchmark(
    points: Sequence[ObservationPoint],
    key: BenchmarkKey,
    policy: BenchmarkPolicy,
    now: datetime,
    *,
    variant_ids: frozenset[int] | None = None,
    unit_total: Decimal | None = None,
) -> AdvertisedBenchmark:
    """Benchmark for one variant x condition group x channel.

    ``variant_ids``: the variant plus variants merged into it (default: just ``key.variant_id``).
    ``unit_total``: the variant's pack size in canonical units, for unit-price statistics.
    """
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    ids = variant_ids or frozenset({key.variant_id})
    group = key.condition_group if policy.condition_relevant else CG.NOT_APPLICABLE
    key = BenchmarkKey(key.variant_id, group, key.channel)
    window_start = now - timedelta(days=policy.window_days)

    excluded: Counter[str] = Counter()
    eligible: list[ObservationPoint] = []
    for p in points:
        if not window_start <= p.observed_at <= now:
            excluded["outside_window"] += 1
            continue
        reason = _exclusion(p, group, key.channel, policy, ids)
        if reason:
            excluded[reason] += 1
        else:
            eligible.append(p)

    if not eligible:
        return AdvertisedBenchmark(
            key=key,
            status=BenchmarkStatus.NO_DATA,
            confidence=Confidence.NONE,
            reasons=("no eligible observations in the window",),
            computed_at=now,
            window_start=window_start,
            n_observations=0,
            n_samples=0,
            n_offers=0,
            n_sources=0,
            newest_sample_at=None,
            excluded=dict(excluded),
        )

    samples = _offer_days(eligible)
    found = _outliers([s.price for s in samples], policy)
    outliers = tuple(
        Outlier(s.point.offer_id, s.price, found.reasons[i], s.point.observed_at)
        for i, s in enumerate(samples)
        if i in found.indices
    )
    clean = [s for i, s in enumerate(samples) if i not in found.indices]

    reasons: list[str] = []
    if found.method == "skipped":
        reasons.append(
            f"outlier check skipped: {len(samples)} samples (< {policy.outlier_min_samples})"
        )
    unknown_av = sum(1 for s in clean if s.point.availability is Availability.UNKNOWN)
    if clean and unknown_av * 2 > len(clean):
        reasons.append(f"availability unknown for {unknown_av} of {len(clean)} samples")

    n_offers = len({s.point.offer_id for s in clean})
    n_sources = len({s.point.source_id for s in clean})
    newest = max((s.point.observed_at for s in clean), default=None)
    lowest = _lowest_current(eligible, outliers, policy, now)

    missing: list[str] = []
    if len(clean) < policy.min_samples:
        missing.append(f"only {len(clean)} usable offer-day samples (need {policy.min_samples})")
    if n_offers < policy.min_distinct_offers:
        missing.append(f"only {n_offers} distinct offer(s) (need {policy.min_distinct_offers})")
    if missing or newest is None:
        return AdvertisedBenchmark(
            key=key,
            status=BenchmarkStatus.INSUFFICIENT_DATA,
            confidence=Confidence.NONE,
            reasons=(*missing, *reasons),
            computed_at=now,
            window_start=window_start,
            n_observations=len(eligible),
            n_samples=len(clean),
            n_offers=n_offers,
            n_sources=n_sources,
            newest_sample_at=newest,
            excluded=dict(excluded),
            outliers=outliers,
            lowest_current=lowest,
        )

    item = summarize([s.price for s in clean], [s.price for s in samples], policy.trim_fraction)
    share = Decimal(len(outliers)) / Decimal(len(samples))
    confidence, limits = _confidence(
        item, n_sources, share, policy, policy.high_confidence_samples, policy.min_samples
    )
    reasons += limits

    status = BenchmarkStatus.OK
    if now - newest > timedelta(days=policy.stale_after_days):
        status = BenchmarkStatus.STALE
        confidence = _cap(confidence, Confidence.LOW)
        reasons.append(f"newest sample is {(now - newest).days} days old")

    with_delivery = [s for s in clean if s.point.shipping_huf is not None]
    landed: PriceStats | None = None
    if len(with_delivery) >= policy.min_samples:
        totals = [s.price + (s.point.shipping_huf or 0) for s in with_delivery]
        landed = summarize(totals, totals, policy.trim_fraction)
    elif policy.landed_price_relevant:
        reasons.append(
            f"delivery cost known for only {len(with_delivery)} samples; landed price unavailable"
        )
        confidence = _cap(confidence, Confidence.MEDIUM)

    unit_stats: PriceStats | None = None
    if policy.unit_price_basis:
        if unit_total is None or unit_total <= 0:
            reasons.append("unit price unavailable: pack size of the variant unknown")
        else:
            unit_stats = summarize(
                [_chuf(s.price, unit_total) for s in clean],
                [_chuf(s.price, unit_total) for s in samples],
                policy.trim_fraction,
                unit="CHUF",
            )

    return AdvertisedBenchmark(
        key=key,
        status=status,
        confidence=confidence,
        reasons=tuple(reasons),
        computed_at=now,
        window_start=window_start,
        n_observations=len(eligible),
        n_samples=len(clean),
        n_offers=n_offers,
        n_sources=n_sources,
        newest_sample_at=newest,
        excluded=dict(excluded),
        outliers=outliers,
        item=item,
        landed=landed,
        delivery=_delivery([s.point.shipping_huf for s in clean]),
        unit_price=unit_stats,
        lowest_current=lowest,
    )


def _lowest_current(
    eligible: Sequence[ObservationPoint],
    outliers: Sequence[Outlier],
    policy: BenchmarkPolicy,
    now: datetime,
) -> CurrentPrice | None:
    """Latest observation per offer, if recent and buyable; cheapest wins. Outliers are kept but
    flagged - an implausibly low price may be the deal or an error, the engine decides."""
    flagged = {(o.ref_id, o.at.date()) for o in outliers}
    latest: dict[int, ObservationPoint] = {}
    for p in eligible:
        if p.offer_id not in latest or p.observed_at > latest[p.offer_id].observed_at:
            latest[p.offer_id] = p
    fresh = [
        p
        for p in latest.values()
        if p.availability in BUYABLE
        and p.price_huf is not None
        and now - p.observed_at <= timedelta(hours=policy.current_max_age_hours)
    ]
    if not fresh:
        return None
    best = min(fresh, key=lambda p: (p.price_huf or 0, p.observed_at))
    return CurrentPrice(
        offer_id=best.offer_id,
        source_id=best.source_id,
        price_huf=best.price_huf or 0,
        shipping_huf=best.shipping_huf,
        observed_at=best.observed_at,
        flagged_outlier=(best.offer_id, best.observed_at.date()) in flagged,
    )


# --- completed sales ---


def sold_benchmark(
    sales: Sequence[SalePoint],
    variant_id: int,
    group: CG,
    policy: BenchmarkPolicy,
    now: datetime,
) -> SoldBenchmark:
    """Completed sales only. Advertised prices cannot enter this function (different type)."""
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    window_start = now - timedelta(days=policy.sold_window_days)
    usable = [
        s
        for s in sales
        if s.variant_id == variant_id
        and condition_group(s.condition) is group
        and window_start <= s.sold_at <= now
    ]
    evidence = dict(Counter(s.evidence.value for s in usable))
    if not usable:
        return SoldBenchmark(
            variant_id=variant_id,
            condition_group=group,
            status=BenchmarkStatus.NO_DATA,
            confidence=Confidence.NONE,
            reasons=("no completed sales in the window",),
            computed_at=now,
            window_start=window_start,
            n_sales=0,
            n_platforms=0,
            evidence=evidence,
            newest_sale_at=None,
        )
    found = _outliers([s.sale_price_huf for s in usable], policy)
    outliers = tuple(
        Outlier(s.sale_id, s.sale_price_huf, found.reasons[i], s.sold_at)
        for i, s in enumerate(usable)
        if i in found.indices
    )
    clean = [s for i, s in enumerate(usable) if i not in found.indices]
    n_platforms = len({s.platform_id for s in clean})
    newest = max((s.sold_at for s in clean), default=None)
    reasons: list[str] = []
    if found.method == "skipped":
        reasons.append(
            f"outlier check skipped: {len(usable)} sales (< {policy.outlier_min_samples})"
        )
    if len(clean) < policy.sold_min_samples or newest is None:
        need = f"only {len(clean)} completed sales (need {policy.sold_min_samples})"
        return SoldBenchmark(
            variant_id=variant_id,
            condition_group=group,
            status=BenchmarkStatus.INSUFFICIENT_DATA,
            confidence=Confidence.NONE,
            reasons=(need, *reasons),
            computed_at=now,
            window_start=window_start,
            n_sales=len(clean),
            n_platforms=n_platforms,
            evidence=evidence,
            newest_sale_at=newest,
            outliers=outliers,
        )
    stats = summarize(
        [s.sale_price_huf for s in clean], [s.sale_price_huf for s in usable], policy.trim_fraction
    )
    confidence, limits = _confidence(
        stats,
        n_platforms,
        Decimal(len(outliers)) / Decimal(len(usable)),
        policy,
        policy.sold_high_confidence_samples,
        policy.sold_min_samples,
    )
    reasons += limits
    confirmed = (SaleEvidence.PLATFORM_FINAL_PRICE, SaleEvidence.OWN_SALE)
    if not any(s.evidence in confirmed for s in clean):
        confidence = _cap(confidence, Confidence.MEDIUM)
        reasons.append("only user-reported sales; no platform-confirmed or own completed sale")
    status = BenchmarkStatus.OK
    if now - newest > timedelta(days=policy.stale_after_days * 4):
        status = BenchmarkStatus.STALE
        confidence = _cap(confidence, Confidence.LOW)
        reasons.append(f"newest sale is {(now - newest).days} days old")
    return SoldBenchmark(
        variant_id=variant_id,
        condition_group=group,
        status=status,
        confidence=confidence,
        reasons=tuple(reasons),
        computed_at=now,
        window_start=window_start,
        n_sales=len(clean),
        n_platforms=n_platforms,
        evidence=evidence,
        newest_sale_at=newest,
        outliers=outliers,
        sale_price=stats,
        buyer_delivery=_delivery([s.buyer_shipping_huf for s in clean]),
        median_days_listed=_median_int([s.days_listed for s in clean if s.days_listed is not None]),
        n_with_days_listed=sum(1 for s in clean if s.days_listed is not None),
    )


# --- unit price across pack sizes (opt-in) ---


def unit_price_across_packs(
    points: Sequence[ObservationPoint],
    product_id: int,
    pack_totals: dict[int, Decimal],
    canonical_unit: str,
    channel: Channel,
    policy: BenchmarkPolicy,
    now: datetime,
) -> UnitPriceBenchmark:
    """Compare the pack sizes of ONE product by HUF per canonical unit.

    Only for categories whose policy sets ``cross_variant_unit_price`` (food). Variants without a
    known pack size are left out, never estimated.
    """
    if not policy.cross_variant_unit_price:
        raise ValueError("this category does not allow comparing different variants")
    window_start = now - timedelta(days=policy.window_days)
    allowed = frozenset(pack_totals)
    eligible = [
        p
        for p in points
        if p.variant_id in pack_totals
        and window_start <= p.observed_at <= now
        and _exclusion(p, CG.NOT_APPLICABLE, channel, policy, allowed) is None
    ]
    samples = _offer_days(eligible)
    chuf = [_chuf(s.price, pack_totals[s.point.variant_id or 0]) for s in samples]
    per_variant = dict(Counter(s.point.variant_id or 0 for s in samples))

    def result(
        status: BenchmarkStatus,
        confidence: Confidence,
        reasons: tuple[str, ...],
        n: int,
        stats: PriceStats | None = None,
    ) -> UnitPriceBenchmark:
        return UnitPriceBenchmark(
            product_id=product_id,
            canonical_unit=canonical_unit,
            channel=channel,
            status=status,
            confidence=confidence,
            reasons=reasons,
            computed_at=now,
            n_samples=n,
            samples_per_variant=per_variant,
            unit_price=stats,
        )

    if not samples:
        return result(BenchmarkStatus.NO_DATA, Confidence.NONE, ("no eligible observations",), 0)
    found = _outliers(chuf, policy)
    clean = [c for i, c in enumerate(chuf) if i not in found.indices]
    if len(clean) < policy.min_samples:
        need = f"only {len(clean)} samples (need {policy.min_samples})"
        return result(BenchmarkStatus.INSUFFICIENT_DATA, Confidence.NONE, (need,), len(clean))
    stats = summarize(clean, chuf, policy.trim_fraction, unit="CHUF")
    n_sources = len({s.point.source_id for i, s in enumerate(samples) if i not in found.indices})
    confidence, limits = _confidence(
        stats,
        n_sources,
        Decimal(len(found.indices)) / Decimal(len(chuf)),
        policy,
        policy.high_confidence_samples,
        policy.min_samples,
    )
    return result(BenchmarkStatus.OK, confidence, tuple(limits), len(clean), stats)
