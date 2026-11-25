"""Engine-facing data shapes (pure). Services build them from the database; engines only read them.

The two engines share these *input* shapes but nothing else: separate verdict enums, separate
result types, no combined score anywhere (ADR-002).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from dealradar.core.enums import (
    Condition,
    MatchMethod,
    MatchStatus,
    WarrantyType,
)
from dealradar.core.enums import PersonalVerdict as PersonalVerdict  # re-export
from dealradar.core.enums import ResaleVerdict as ResaleVerdict  # re-export
from dealradar.evaluation.inputs import CategoryEvaluationInputs
from dealradar.evaluation.params import FeeProfile, PersonalParams, ResaleParams, TaxProfile


class Level(StrEnum):
    """Confidence levels as produced by the pricing engine (same values)."""

    NONE = "NONE"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


LEVEL_ORDER = (Level.NONE, Level.LOW, Level.MEDIUM, Level.HIGH)


def at_least(level: Level, minimum: Level) -> bool:
    return LEVEL_ORDER.index(level) >= LEVEL_ORDER.index(minimum)


class ValueKind(StrEnum):
    """Every number in a result says what kind of number it is."""

    FACT = "FACT"  # observed (listing price, recorded sale)
    USER_INPUT = "USER_INPUT"  # fee / tax profile, watchlist, override
    ESTIMATE = "ESTIMATE"  # derived from data (median of completed sales, days to sell)
    ASSUMPTION = "ASSUMPTION"  # default parameter not measured (return rate, capital cost)


@dataclass(frozen=True)
class Assumption:
    name: str
    value: str
    kind: ValueKind
    source: str


@dataclass(frozen=True)
class MatchInfo:
    status: MatchStatus
    method: MatchMethod | None = None
    confidence: int | None = None  # 0..100
    confirmed_by_user: bool = False


@dataclass(frozen=True)
class AdvertisedView:
    """What the personal engine needs from an advertised-price benchmark."""

    status: str  # OK / STALE / INSUFFICIENT_DATA / NO_DATA
    confidence: Level
    condition_group: str
    n_samples: int
    item_median: int | None  # trimmed median of item prices
    item_min: int | None  # historical minimum (outlier-free, within the window)
    landed_median: int | None  # item + delivery, if enough samples with known delivery
    window_days: int


@dataclass(frozen=True)
class SoldView:
    """Completed-sale evidence only. Asking prices can never be put here (ADR-006)."""

    status: str
    confidence: Level
    condition_group: str
    n_sales: int
    n_platforms: int
    window_days: int
    p25: int | None
    median: int | None
    p75: int | None
    median_days_listed: int | None
    n_with_days_listed: int
    buyer_shipping_median: int | None
    user_reported_only: bool


@dataclass(frozen=True)
class WatchlistTarget:
    target_price_huf: int | None = None  # "I would buy at or below this"
    max_price_huf: int | None = None  # "never above this"
    acceptable_conditions: frozenset[Condition] | None = None  # None = any


@dataclass(frozen=True)
class PersonalInputs:
    category: CategoryEvaluationInputs
    condition_group: str | None  # of the listing; must equal the benchmark's
    warranty_months: int | None
    warranty_type: WarrantyType | None
    pickup_only: bool
    match: MatchInfo
    benchmark: AdvertisedView | None
    watchlist: WatchlistTarget | None
    params: PersonalParams


@dataclass(frozen=True)
class ResaleInputs:
    category: CategoryEvaluationInputs
    condition_group: str | None
    pickup_only: bool
    match: MatchInfo
    completed_sales: SoldView | None
    fee_profile: FeeProfile | None
    tax_profile: TaxProfile | None
    params: ResaleParams
    # Display-only context. The resale engine never reads it for any calculation (tested).
    context_asking_median: int | None = None
