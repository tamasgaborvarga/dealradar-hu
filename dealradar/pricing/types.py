"""Pricing data shapes, benchmark keys and the category-tunable BenchmarkPolicy."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from dealradar.core.enums import Availability, Condition, ListingKind, SaleEvidence


class ConditionGroup(StrEnum):
    """Conditions that may be compared with each other (requirement: never mix them)."""

    NEW = "NEW"
    OPEN_BOX = "OPEN_BOX"
    REFURBISHED = "REFURBISHED"
    USED = "USED"  # USED, USED_A, USED_B, USED_C
    FOR_PARTS = "FOR_PARTS"
    NOT_APPLICABLE = "NOT_APPLICABLE"  # categories where condition is not an input (food)


_GROUPS = {
    Condition.NEW: ConditionGroup.NEW,
    Condition.OPEN_BOX: ConditionGroup.OPEN_BOX,
    Condition.REFURBISHED: ConditionGroup.REFURBISHED,
    Condition.USED: ConditionGroup.USED,
    Condition.USED_A: ConditionGroup.USED,
    Condition.USED_B: ConditionGroup.USED,
    Condition.USED_C: ConditionGroup.USED,
    Condition.FOR_PARTS: ConditionGroup.FOR_PARTS,
}


def condition_group(condition: Condition | None) -> ConditionGroup | None:
    """None stays None: an unknown condition is never assumed to be new."""
    return None if condition is None else _GROUPS[condition]


class Channel(StrEnum):
    RETAIL = "RETAIL"  # shops and third-party sellers inside shops
    SECONDHAND = "SECONDHAND"  # classifieds and auctions (asking prices)
    FLYER = "FLYER"  # store promotions


_CHANNELS = {
    ListingKind.RETAIL: Channel.RETAIL,
    ListingKind.MARKETPLACE: Channel.RETAIL,
    ListingKind.CLASSIFIED: Channel.SECONDHAND,
    ListingKind.AUCTION: Channel.SECONDHAND,
    ListingKind.FLYER: Channel.FLYER,
}


def channel_of(kind: ListingKind) -> Channel:
    return _CHANNELS[kind]


class PriceKind(StrEnum):
    ADVERTISED = "ADVERTISED"
    SOLD = "SOLD"


class BenchmarkStatus(StrEnum):
    OK = "OK"
    STALE = "STALE"  # enough data, but the newest sample is too old
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"  # some data, not enough for a benchmark
    NO_DATA = "NO_DATA"


class Confidence(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    NONE = "NONE"


@dataclass(frozen=True)
class BenchmarkPolicy:
    """Category-specific benchmark parameters (defaults are documented heuristics, ADR-041)."""

    window_days: int = 90
    min_samples: int = 5  # offer-days (advertised) needed for any statistic
    min_distinct_offers: int = 2
    condition_relevant: bool = True
    # outliers
    outlier_min_samples: int = 5
    outlier_mad_z: Decimal = Decimal("3.5")  # modified z-score limit (Iglewicz & Hoaglin)
    outlier_rel_when_mad_zero: Decimal = Decimal("0.5")  # 50 % away from the median
    trim_fraction: Decimal = Decimal("0.10")  # for the trimmed mean
    # freshness
    current_max_age_hours: int = 48
    stale_after_days: int = 14
    # filters
    include_loyalty_only: bool = False
    include_multibuy: bool = False
    # confidence
    high_confidence_samples: int = 20
    min_sources_for_high: int = 2
    max_dispersion_for_high: Decimal = Decimal("0.25")  # (p75 - p25) / median
    max_outlier_share_for_high: Decimal = Decimal("0.2")
    # category features
    landed_price_relevant: bool = False  # delivery is a large part of the cost (bulky goods)
    unit_price_basis: bool = False  # compare HUF per kg / l / piece
    cross_variant_unit_price: bool = False  # allow a unit-price roll-up across pack sizes
    # completed sales
    sold_window_days: int = 180
    sold_min_samples: int = 3
    sold_high_confidence_samples: int = 10


@dataclass(frozen=True)
class BenchmarkKey:
    variant_id: int
    condition_group: ConditionGroup
    channel: Channel


@dataclass(frozen=True)
class ObservationPoint:
    """One advertised-price observation as the pricing engine sees it."""

    observation_id: int
    offer_id: int
    variant_id: int | None  # the offer's current match
    source_id: int
    observed_at: datetime
    price_huf: int | None
    shipping_huf: int | None
    availability: Availability
    condition: Condition | None
    listing_kind: ListingKind
    loyalty_only: bool = False
    min_quantity: int = 1


@dataclass(frozen=True)
class SalePoint:
    sale_id: int
    variant_id: int
    platform_id: int
    evidence: SaleEvidence
    condition: Condition
    sale_price_huf: int
    buyer_shipping_huf: int | None
    sold_at: datetime
    days_listed: int | None


@dataclass(frozen=True)
class PriceStats:
    """Robust summary. Values in ``unit`` (HUF, or CHUF = centi-HUF per kg/l/piece).

    ``median_all`` uses every eligible sample. ``trimmed_median`` is the median after suspicious
    outliers are removed (trimming equally from both tails would leave the median unchanged, so
    the robust variant removes flagged outliers instead). Quantiles and ``trimmed_mean`` are
    computed on the outlier-free set.
    """

    unit: str
    n: int
    min: int
    p10: int
    p25: int
    trimmed_median: int
    p75: int
    p90: int
    max: int
    median_all: int
    trimmed_mean: int | None

    @property
    def dispersion(self) -> Decimal:
        """Interquartile range relative to the median (0 = all equal)."""
        if self.trimmed_median == 0:
            return Decimal(0)
        return Decimal(self.p75 - self.p25) / Decimal(self.trimmed_median)


@dataclass(frozen=True)
class DeliveryStats:
    """Delivery cost kept apart from the item price; unknown is never treated as free."""

    n_known: int
    n_unknown: int
    n_free: int
    median_huf: int | None
    min_huf: int | None
    max_huf: int | None


@dataclass(frozen=True)
class Outlier:
    ref_id: int  # offer_id (advertised) or sale_id (sold)
    value: int
    reason: str
    at: datetime


@dataclass(frozen=True)
class CurrentPrice:
    """A fact, not an estimate: the cheapest buyable offer seen recently."""

    offer_id: int
    source_id: int
    price_huf: int
    shipping_huf: int | None
    observed_at: datetime
    flagged_outlier: bool


@dataclass(frozen=True)
class AdvertisedBenchmark:
    key: BenchmarkKey
    status: BenchmarkStatus
    confidence: Confidence
    reasons: tuple[str, ...]
    computed_at: datetime
    window_start: datetime
    n_observations: int  # eligible raw observations
    n_samples: int  # offer-days after de-duplication and outlier removal
    n_offers: int
    n_sources: int
    newest_sample_at: datetime | None
    excluded: dict[str, int] = field(default_factory=dict)
    outliers: tuple[Outlier, ...] = ()
    item: PriceStats | None = None
    landed: PriceStats | None = None  # item + delivery, only samples with known delivery
    delivery: DeliveryStats | None = None
    unit_price: PriceStats | None = None  # CHUF, categories with unit_price_basis
    lowest_current: CurrentPrice | None = None
    price_kind: PriceKind = PriceKind.ADVERTISED


@dataclass(frozen=True)
class SoldBenchmark:
    variant_id: int
    condition_group: ConditionGroup
    status: BenchmarkStatus
    confidence: Confidence
    reasons: tuple[str, ...]
    computed_at: datetime
    window_start: datetime
    n_sales: int
    n_platforms: int
    evidence: dict[str, int]
    newest_sale_at: datetime | None
    outliers: tuple[Outlier, ...] = ()
    sale_price: PriceStats | None = None
    buyer_delivery: DeliveryStats | None = None
    median_days_listed: int | None = None
    n_with_days_listed: int = 0
    price_kind: PriceKind = PriceKind.SOLD


@dataclass(frozen=True)
class UnitPriceBenchmark:
    """Unit-price roll-up across the pack sizes of ONE product (opt-in per category)."""

    product_id: int
    canonical_unit: str
    channel: Channel
    status: BenchmarkStatus
    confidence: Confidence
    reasons: tuple[str, ...]
    computed_at: datetime
    n_samples: int
    samples_per_variant: dict[int, int]
    unit_price: PriceStats | None = None
    basis: str = "UNIT_PRICE_ACROSS_PACK_SIZES"
