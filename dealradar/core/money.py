"""Money primitives (ADR-007): integer HUF, basis points, Decimal arithmetic, never floats."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import NewType

Huf = NewType("Huf", int)
"""Whole Hungarian forints, gross (VAT-inclusive)."""

Bp = NewType("Bp", int)
"""Basis points: 1 bp = 0.01 %, 10 000 bp = 100 %."""

BP_PER_UNIT = 10_000


def huf(value: int) -> Huf:
    """Validate and tag an integer HUF amount. Rejects bool and non-int values."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("HUF amounts must be int")
    return Huf(value)


def round_huf(amount: Decimal) -> Huf:
    """Round to whole HUF, half away from zero. The single rounding policy of the project."""
    if not isinstance(amount, Decimal):
        raise TypeError("round_huf expects Decimal")
    return Huf(int(amount.quantize(Decimal(1), rounding=ROUND_HALF_UP)))


def apply_bp(amount: Huf, rate: Bp) -> Huf:
    """``amount * rate / 10 000`` rounded to whole HUF (5 % of 12 990 HUF -> 650 HUF)."""
    return round_huf(Decimal(amount) * Decimal(rate) / Decimal(BP_PER_UNIT))


def bp_change(reference: Huf, value: Huf) -> Bp:
    """Relative change from ``reference`` to ``value`` in basis points (negative = cheaper)."""
    if reference <= 0:
        raise ValueError("reference must be positive")
    ratio = (Decimal(value) - Decimal(reference)) * Decimal(BP_PER_UNIT) / Decimal(reference)
    return Bp(int(ratio.quantize(Decimal(1), rounding=ROUND_HALF_UP)))
