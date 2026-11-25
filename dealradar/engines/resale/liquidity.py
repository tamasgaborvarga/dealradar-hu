"""Liquidity and time-to-sell, from completed sales only (docs/ENGINE_FORMULAS.md §2.4)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

from dealradar.evaluation.params import ResaleParams
from dealradar.evaluation.types import LEVEL_ORDER, Level, SoldView


class LiquidityClass(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class Liquidity:
    liquidity: LiquidityClass
    confidence: Level
    sales_per_30d: Decimal | None
    est_days_to_sell: int | None
    basis: str  # how est_days_to_sell was derived


MIN_SALES_WITH_DAYS = 3


def assess(sold: SoldView | None, p: ResaleParams) -> Liquidity:
    if sold is None or sold.n_sales == 0 or sold.window_days <= 0:
        return Liquidity(LiquidityClass.UNKNOWN, Level.NONE, None, None, "nincs lezárt eladás")
    rate = Decimal(sold.n_sales) * 30 / Decimal(sold.window_days)
    if sold.median_days_listed is not None and sold.n_with_days_listed >= MIN_SALES_WITH_DAYS:
        days = sold.median_days_listed
        basis = f"{sold.n_with_days_listed} lezárt eladás hirdetési idejének mediánja"
        confidence = sold.confidence
    else:
        # Fallback: one sale every 30/rate days. Assumes we would capture the average demand.
        days = int((Decimal(30) / rate).quantize(Decimal(1), rounding=ROUND_HALF_UP))
        basis = (
            f"az eladások gyakoriságából ({rate:.2f} eladás / 30 nap); a hirdetési idő nem ismert"
        )
        confidence = LEVEL_ORDER[
            min(LEVEL_ORDER.index(sold.confidence), LEVEL_ORDER.index(Level.LOW))
        ]
    if rate >= p.liquidity_high_sales_per_30d and days <= p.liquidity_high_max_days:
        cls = LiquidityClass.HIGH
    elif rate >= p.liquidity_medium_sales_per_30d and days <= p.liquidity_medium_max_days:
        cls = LiquidityClass.MEDIUM
    else:
        cls = LiquidityClass.LOW
    return Liquidity(cls, confidence, rate, days, basis)
