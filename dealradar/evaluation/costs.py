"""The ONLY place money formulas live (ARCHITECTURE.md §3). Integer HUF, basis points, Decimal.

Rounding: every line item is rounded to whole HUF (half away from zero) before summing, so a
printed breakdown always adds up exactly. Formulas are documented in docs/ENGINE_FORMULAS.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from dealradar.core.money import BP_PER_UNIT, Bp, Huf, apply_bp, bp_change, round_huf
from dealradar.evaluation.params import FeeProfile, TaxKind, TaxProfile

DAYS_PER_YEAR = 365


def effective_price(price: int | None, shipping: int | None, pickup_only: bool) -> int | None:
    """Item + inbound delivery. Unknown delivery -> None (never 0), unless pickup-only (0 here;
    pickup travel cost is a separate resale parameter)."""
    if price is None:
        return None
    if pickup_only:
        return price
    if shipping is None:
        return None
    return price + shipping


def discount_bp(reference: int, price: int) -> Bp:
    """How much cheaper ``price`` is than ``reference``: +2000 = 20 % below, -500 = 5 % above."""
    return Bp(-bp_change(Huf(reference), Huf(price)))


def commission(sale_price: int, buyer_shipping: int, fee: FeeProfile) -> int:
    """commission_bp x base, clamped to [commission_min, commission_cap]."""
    base = sale_price + (buyer_shipping if fee.commission_includes_shipping else 0)
    value = int(apply_bp(Huf(base), fee.commission_bp))
    value = max(value, fee.commission_min_huf)
    if fee.commission_cap_huf is not None:
        value = min(value, fee.commission_cap_huf)
    return value


def payment_fee(gross_received: int, fee: FeeProfile) -> int:
    """payment_fee_bp x everything the buyer pays + fixed part."""
    return int(apply_bp(Huf(gross_received), Bp(fee.payment_fee_bp))) + fee.payment_fixed_huf


def expected_cost(rate_bp: int, amount: int) -> int:
    """Probability-weighted cost: rate x amount (e.g. 3 % return rate x 3 000 HUF = 90 HUF)."""
    return int(apply_bp(Huf(amount), Bp(rate_bp)))


def holding_cost(capital: int, days: int, capital_bp_per_year: int, storage_per_day: int) -> int:
    """Opportunity cost of tied-up money + storage: capital x rate x days / 365 + storage x days."""
    interest = round_huf(
        Decimal(capital) * Decimal(capital_bp_per_year) * Decimal(days)
        / Decimal(BP_PER_UNIT) / Decimal(DAYS_PER_YEAR)
    )  # fmt: skip
    return int(interest) + storage_per_day * days


def tax_cost(profile: TaxProfile, revenue: int, pre_tax_profit: int) -> int:
    """User-selected tax assumption. Never negative: a loss produces no tax credit here."""
    if profile.kind is TaxKind.PERCENT_OF_REVENUE:
        return max(0, int(apply_bp(Huf(revenue), Bp(profile.rate_bp))))
    if profile.kind is TaxKind.PERCENT_OF_PROFIT:
        return int(apply_bp(Huf(max(0, pre_tax_profit)), Bp(profile.rate_bp)))
    if profile.kind is TaxKind.NO_TAX_DECLARED:
        return 0
    raise ValueError("no tax profile selected")


def roi_bp(net_profit: int, invested: int) -> Bp | None:
    """net / invested in basis points; None when nothing was invested (undefined, not infinite)."""
    if invested <= 0:
        return None
    ratio = Decimal(net_profit) * BP_PER_UNIT / Decimal(invested)
    return Bp(int(round_huf(ratio)))


@dataclass(frozen=True)
class ResaleScenario:
    """One sale-price scenario, every line in whole HUF. ``net_profit`` = income - costs."""

    sale_price: int
    buyer_shipping_charge: int
    acquisition_cost: int
    commission: int
    payment_fee: int
    fixed_fees: int  # fixed per-sale fee + listing fee
    outbound_shipping: int
    packaging: int
    expected_return_cost: int
    expected_defect_cost: int
    holding_cost: int
    tax: int
    net_profit: int
    roi_bp: Bp | None

    @property
    def income(self) -> int:
        return self.sale_price + self.buyer_shipping_charge

    @property
    def total_costs(self) -> int:
        return (
            self.acquisition_cost + self.commission + self.payment_fee + self.fixed_fees
            + self.outbound_shipping + self.packaging + self.expected_return_cost
            + self.expected_defect_cost + self.holding_cost + self.tax
        )  # fmt: skip


def resale_scenario(
    *,
    sale_price: int,
    buyer_shipping_charge: int,
    acquisition_cost: int,
    days_to_sell: int,
    fee: FeeProfile,
    tax: TaxProfile,
    return_rate_bp: int,
    return_cost_huf: int,
    defect_rate_bp: int,
    defect_loss_bp: int,
    capital_cost_bp_per_year: int,
    storage_cost_huf_per_day: int,
) -> ResaleScenario:
    if fee.outbound_shipping_cost_huf is None or fee.packaging_huf is None:
        raise ValueError("fee profile incomplete: outbound shipping and packaging are required")
    if min(sale_price, buyer_shipping_charge, acquisition_cost, days_to_sell) < 0:
        raise ValueError("negative input")
    gross = sale_price + buyer_shipping_charge
    comm = commission(sale_price, buyer_shipping_charge, fee)
    pay = payment_fee(gross, fee)
    fixed = fee.fixed_fee_huf + fee.listing_fee_huf
    ret = expected_cost(return_rate_bp, return_cost_huf)
    defect = expected_cost(defect_rate_bp, int(apply_bp(Huf(sale_price), Bp(defect_loss_bp))))
    hold = holding_cost(
        acquisition_cost, days_to_sell, capital_cost_bp_per_year, storage_cost_huf_per_day
    )
    pre_tax = (
        gross - acquisition_cost - comm - pay - fixed - fee.outbound_shipping_cost_huf
        - fee.packaging_huf - ret - defect - hold
    )  # fmt: skip
    tx = tax_cost(tax, sale_price, pre_tax)
    net = pre_tax - tx
    return ResaleScenario(
        sale_price=sale_price,
        buyer_shipping_charge=buyer_shipping_charge,
        acquisition_cost=acquisition_cost,
        commission=comm,
        payment_fee=pay,
        fixed_fees=fixed,
        outbound_shipping=fee.outbound_shipping_cost_huf,
        packaging=fee.packaging_huf,
        expected_return_cost=ret,
        expected_defect_cost=defect,
        holding_cost=hold,
        tax=tx,
        net_profit=net,
        roi_bp=roi_bp(net, acquisition_cost),
    )


def capital_exposure(acquisition_cost: int, fee: FeeProfile) -> int:
    """Cash out before any money comes back: acquisition + listing fee + packaging."""
    return acquisition_cost + fee.listing_fee_huf + (fee.packaging_huf or 0)
