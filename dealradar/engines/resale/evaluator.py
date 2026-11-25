"""Resale Deal Engine (docs/ENGINE_FORMULAS.md §2).

Expected selling prices come ONLY from completed sales (``SoldView``). Asking prices are not an
input of any calculation here. Missing critical inputs -> MANUAL_REVIEW with no profit numbers.
Review flags (e.g. unverified fees) -> numbers are computed but labelled provisional and the
verdict stays MANUAL_REVIEW. The engine never authorizes a purchase.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from dealradar.core import hu
from dealradar.core.enums import MatchMethod, MatchStatus
from dealradar.core.money import Bp
from dealradar.engines.resale.liquidity import Liquidity, LiquidityClass, assess
from dealradar.evaluation.costs import ResaleScenario, capital_exposure, resale_scenario
from dealradar.evaluation.params import TaxKind
from dealradar.evaluation.types import (
    Assumption,
    Level,
    ResaleInputs,
    ResaleVerdict,
    ValueKind,
    at_least,
)

UNUSABLE = ("NO_DATA", "INSUFFICIENT_DATA")


@dataclass(frozen=True)
class ResaleResult:
    verdict: ResaleVerdict
    acquisition_cost_huf: int | None
    expected_sale_low_huf: int | None  # p25 of completed sales
    expected_sale_huf: int | None  # median of completed sales
    expected_sale_high_huf: int | None  # p75 of completed sales
    scenarios: dict[str, ResaleScenario] | None  # "low" / "expected" / "high"
    net_profit_low_huf: int | None
    net_profit_huf: int | None
    net_profit_high_huf: int | None
    roi_bp: Bp | None
    capital_exposure_huf: int | None
    liquidity: Liquidity
    provisional: bool  # numbers computed while review flags are open
    reasons: tuple[str, ...]
    missing_inputs: tuple[str, ...]
    review_flags: tuple[str, ...]
    assumptions: tuple[Assumption, ...]
    price_source: Literal["COMPLETED_SALES"] = "COMPLETED_SALES"
    engine: Literal["RESALE"] = "RESALE"
    decision_required: Literal[True] = True


def _empty(
    verdict: ResaleVerdict,
    liquidity: Liquidity,
    reasons: list[str],
    missing: list[str],
    flags: list[str],
    assumptions: list[Assumption],
    acquisition: int | None = None,
) -> ResaleResult:
    return ResaleResult(
        verdict=verdict,
        acquisition_cost_huf=acquisition,
        expected_sale_low_huf=None,
        expected_sale_huf=None,
        expected_sale_high_huf=None,
        scenarios=None,
        net_profit_low_huf=None,
        net_profit_huf=None,
        net_profit_high_huf=None,
        roi_bp=None,
        capital_exposure_huf=None,
        liquidity=liquidity,
        provisional=False,
        reasons=tuple(reasons),
        missing_inputs=tuple(dict.fromkeys(missing)),
        review_flags=tuple(dict.fromkeys(flags)),
        assumptions=tuple(assumptions),
    )


def evaluate(inputs: ResaleInputs) -> ResaleResult:
    p, cat, sold = inputs.params, inputs.category, inputs.completed_sales
    fee, tax = inputs.fee_profile, inputs.tax_profile
    liquidity = assess(sold if sold is not None and sold.status not in UNUSABLE else None, p)
    reasons: list[str] = []
    assumptions: list[Assumption] = []

    if not cat.resale_applicable:
        return _empty(
            ResaleVerdict.NOT_APPLICABLE,
            liquidity,
            ["ebben a kategóriában a továbbértékesítés nem alkalmazható"],
            [],
            [],
            [],
        )

    missing = list(cat.missing_inputs)
    flags = list(cat.review_flags)

    # --- product identity ---
    m = inputs.match
    if m.status is not MatchStatus.MATCHED:
        missing.append("product_match")
    elif m.method in (MatchMethod.FUZZY, MatchMethod.AI_SUGGESTED) and not m.confirmed_by_user:
        flags.append("match_not_confirmed")

    # --- acquisition cost ---
    acquisition: int | None = None
    if cat.price_huf is not None:
        if inputs.pickup_only:
            if p.pickup_travel_cost_huf is None:
                missing.append("pickup_travel_cost")
            else:
                acquisition = cat.price_huf + p.pickup_travel_cost_huf
                assumptions.append(
                    Assumption(
                        "pickup travel cost",
                        f"{p.pickup_travel_cost_huf} HUF",
                        ValueKind.ASSUMPTION,
                        p.source,
                    )
                )
        elif cat.shipping_huf is not None:
            acquisition = cat.price_huf + cat.shipping_huf
        else:
            missing.append("shipping")  # defence in depth: never assume free delivery
    else:
        missing.append("price")
    if cat.condition is None:
        missing.append("condition")

    # --- completed-sale evidence (never asking prices) ---
    if sold is None or sold.status in UNUSABLE or sold.median is None:
        missing.append("completed_sales")
    else:
        if sold.n_sales < p.min_completed_sales:
            missing.append("completed_sales")
            reasons.append(f"{sold.n_sales} lezárt eladás, legalább {p.min_completed_sales} kell")
        if inputs.condition_group is not None and sold.condition_group != inputs.condition_group:
            flags.append("sales_condition_mismatch")
        if sold.status == "STALE":
            flags.append("completed_sales_stale")
        if not at_least(sold.confidence, Level(p.min_sales_confidence)):
            flags.append("completed_sales_confidence_low")
        if sold.user_reported_only:
            reasons.append("minden lezárt eladás saját rögzítésű (nincs platform által igazolt ár)")

    # --- fee and tax profiles (user input, never defaults) ---
    if fee is None:
        missing.append("fee_profile")
    else:
        if fee.outbound_shipping_cost_huf is None:
            missing.append("outbound_shipping_cost")
        if fee.packaging_huf is None:
            missing.append("packaging_cost")
        if not fee.verified:
            flags.append("fee_profile_unverified")
    if tax is None or tax.kind is TaxKind.NONE_SELECTED:
        missing.append("tax_profile")
    elif not tax.verified:
        flags.append("tax_profile_unverified")

    if liquidity.est_days_to_sell is None and "completed_sales" not in missing:
        missing.append("time_to_sell")

    if missing:
        reasons.insert(0, "hiányzó alapadatok miatt a nyereség nincs kiszámolva")
        return _empty(
            ResaleVerdict.MANUAL_REVIEW,
            liquidity,
            reasons,
            missing,
            flags,
            assumptions,
            acquisition,
        )

    assert acquisition is not None and sold is not None and fee is not None and tax is not None
    assert sold.median is not None and liquidity.est_days_to_sell is not None
    days = liquidity.est_days_to_sell
    low = sold.p25 if sold.p25 is not None else sold.median
    high = sold.p75 if sold.p75 is not None else sold.median
    if sold.buyer_shipping_median is not None:
        buyer_ship = sold.buyer_shipping_median
        assumptions.append(
            Assumption(
                "buyer shipping charge",
                f"{buyer_ship} HUF (median of sales)",
                ValueKind.ESTIMATE,
                "completed sales",
            )
        )
    else:
        buyer_ship = 0
        assumptions.append(
            Assumption(
                "buyer shipping charge",
                "0 HUF (unknown; conservative)",
                ValueKind.ASSUMPTION,
                "engine rule",
            )
        )
    assumptions += [
        Assumption(
            "expected sale price",
            f"p25 {low} / median {sold.median} / p75 {high} HUF",
            ValueKind.ESTIMATE,
            f"{sold.n_sales} completed sales, {sold.window_days} days",
        ),
        Assumption("time to sell", f"{days} days", ValueKind.ESTIMATE, liquidity.basis),
        Assumption(
            "fees",
            f"{fee.platform}: commission {fee.commission_bp} bp, payment "
            f"{fee.payment_fee_bp} bp + {fee.payment_fixed_huf} HUF, shipping "
            f"{fee.outbound_shipping_cost_huf} HUF, packaging {fee.packaging_huf} HUF",
            ValueKind.USER_INPUT,
            "fee profile" + (" (verified)" if fee.verified else " (UNVERIFIED)"),
        ),
        Assumption(
            "tax",
            f"{tax.kind} {tax.rate_bp} bp",
            ValueKind.USER_INPUT,
            "tax profile" + (" (verified)" if tax.verified else " (UNVERIFIED)"),
        ),
        Assumption(
            "returns / defects",
            f"return {p.return_rate_bp} bp x {p.return_cost_huf} HUF; "
            f"defect {p.defect_rate_bp} bp x {p.defect_loss_bp} bp of price",
            ValueKind.ASSUMPTION,
            p.source,
        ),
        Assumption(
            "holding cost",
            f"{p.capital_cost_bp_per_year} bp / year + {p.storage_cost_huf_per_day} HUF / day",
            ValueKind.ASSUMPTION,
            p.source,
        ),
    ]

    def scenario(price: int) -> ResaleScenario:
        return resale_scenario(
            sale_price=price,
            buyer_shipping_charge=buyer_ship,
            acquisition_cost=acquisition,
            days_to_sell=days,
            fee=fee,
            tax=tax,
            return_rate_bp=p.return_rate_bp,
            return_cost_huf=p.return_cost_huf,
            defect_rate_bp=p.defect_rate_bp,
            defect_loss_bp=p.defect_loss_bp,
            capital_cost_bp_per_year=p.capital_cost_bp_per_year,
            storage_cost_huf_per_day=p.storage_cost_huf_per_day,
        )

    scenarios = {"low": scenario(low), "expected": scenario(sold.median), "high": scenario(high)}
    exp, worst = scenarios["expected"], scenarios["low"]
    provisional = bool(flags)

    if flags:
        verdict = ResaleVerdict.MANUAL_REVIEW
        reasons.append("a számok ideiglenesek, amíg a jelzett kérdések nincsenek tisztázva")
    elif exp.net_profit <= 0:
        verdict = ResaleVerdict.NOT_PROFITABLE
        reasons.append(f"várható nettó eredmény: {hu.huf(exp.net_profit)}")
    else:
        shortfalls = []
        if exp.net_profit < p.min_net_profit_huf:
            shortfalls.append(
                f"nettó haszon {hu.huf(exp.net_profit)}, a minimum {hu.huf(p.min_net_profit_huf)}"
            )
        if exp.roi_bp is None or exp.roi_bp < p.min_roi_bp:
            roi, min_roi = hu.pct(exp.roi_bp, signed=False), hu.pct(p.min_roi_bp, signed=False)
            shortfalls.append(f"megtérülés {roi}, a minimum {min_roi}")
        if worst.net_profit < 0:
            shortfalls.append(f"alacsony (p25) eladási árnál {hu.huf(-worst.net_profit)} veszteség")
        if liquidity.liquidity in (LiquidityClass.LOW, LiquidityClass.UNKNOWN):
            shortfalls.append(f"eladhatóság: {hu.label('liquidity', liquidity.liquidity)}")
        if days > p.max_days_to_sell:
            shortfalls.append(
                f"várhatóan {days} nap alatt adható el, a maximum {p.max_days_to_sell} nap"
            )
        verdict = ResaleVerdict.MARGINAL if shortfalls else ResaleVerdict.PROFITABLE
        reasons += shortfalls

    return ResaleResult(
        verdict=verdict,
        acquisition_cost_huf=acquisition,
        expected_sale_low_huf=low,
        expected_sale_huf=sold.median,
        expected_sale_high_huf=high,
        scenarios=scenarios,
        net_profit_low_huf=worst.net_profit,
        net_profit_huf=exp.net_profit,
        net_profit_high_huf=scenarios["high"].net_profit,
        roi_bp=exp.roi_bp,
        capital_exposure_huf=capital_exposure(acquisition, fee),
        liquidity=liquidity,
        provisional=provisional,
        reasons=tuple(reasons),
        missing_inputs=(),
        review_flags=tuple(dict.fromkeys(flags)),
        assumptions=tuple(assumptions),
    )
