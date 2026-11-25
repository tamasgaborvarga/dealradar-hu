"""Configurable engine parameters, fee and tax profiles.

Every default here is a documented heuristic or a neutral placeholder - NOT market data
(docs/ENGINE_FORMULAS.md). Category modules supply their own defaults; users override them via
settings (audited). Fee and tax profiles have no defaults at all: the user enters and verifies them.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from dealradar.core.money import Bp


@dataclass(frozen=True)
class PersonalParams:
    strong_discount_bp: int = 2_000  # >= 20 % below the median
    good_discount_bp: int = 1_000  # >= 10 % below the median
    fair_tolerance_bp: int = 300  # up to 3 % above the median is still FAIR
    suspicious_discount_bp: int = 5_000  # >= 50 % below the median -> MANUAL_REVIEW
    min_match_confidence: int = 90
    min_benchmark_confidence: str = "MEDIUM"  # LOW benchmarks -> MANUAL_REVIEW
    strong_requires_confidence: str = "HIGH"  # STRONG needs a HIGH-confidence benchmark
    require_landed_comparison: bool = False  # bulky goods: compare item + delivery
    min_warranty_months_new: int = 0
    min_warranty_months_used: int = 0
    flag_new_without_warranty: bool = True
    source: str = "category default"


@dataclass(frozen=True)
class ResaleParams:
    min_completed_sales: int = 3  # OPEN-15
    min_sales_confidence: str = "MEDIUM"
    min_net_profit_huf: int = 5_000
    min_roi_bp: int = 1_500  # 15 %
    max_days_to_sell: int = 60
    return_rate_bp: int = 300  # 3 % of sales come back
    return_cost_huf: int = 3_000  # cost per returned item (shipping both ways, handling)
    defect_rate_bp: int = 200  # 2 % turn out defective / not as described
    defect_loss_bp: int = 5_000  # a defect loses 50 % of the sale price
    capital_cost_bp_per_year: int = 800  # 8 % / year opportunity cost of tied-up money
    storage_cost_huf_per_day: int = 0
    pickup_travel_cost_huf: int | None = None  # must be set before pickup-only buys are evaluated
    liquidity_high_sales_per_30d: int = 4
    liquidity_high_max_days: int = 14
    liquidity_medium_sales_per_30d: int = 1
    liquidity_medium_max_days: int = 45
    source: str = "category default"


@dataclass(frozen=True)
class FeeProfile:
    """Selling costs on one platform, entered by the user from the platform's current terms."""

    platform: str
    commission_bp: Bp
    commission_min_huf: int = 0
    commission_cap_huf: int | None = None
    commission_includes_shipping: bool = False
    fixed_fee_huf: int = 0  # per sale
    listing_fee_huf: int = 0  # paid up front, also if it does not sell
    payment_fee_bp: int = 0  # basis points
    payment_fixed_huf: int = 0
    outbound_shipping_cost_huf: int | None = None  # what the seller pays the carrier
    packaging_huf: int | None = None
    verified: bool = False  # the user checked these numbers against the platform's terms
    note: str = ""


class TaxKind(StrEnum):
    NONE_SELECTED = "NONE_SELECTED"  # not decided -> MANUAL_REVIEW
    NO_TAX_DECLARED = "NO_TAX_DECLARED"  # user states no tax applies (their responsibility)
    PERCENT_OF_PROFIT = "PERCENT_OF_PROFIT"
    PERCENT_OF_REVENUE = "PERCENT_OF_REVENUE"


@dataclass(frozen=True)
class TaxProfile:
    """A user assumption about tax, never legal advice (PRODUCT_SPEC §7, OPEN-7)."""

    kind: TaxKind
    rate_bp: int = 0  # basis points
    verified: bool = False  # e.g. confirmed with an accountant
    note: str = ""
