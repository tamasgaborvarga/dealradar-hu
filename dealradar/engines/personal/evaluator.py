"""Personal Deal Engine (docs/ENGINE_FORMULAS.md §1).

Order: collect missing inputs and review flags -> compute comparisons -> apply the user's own
limits -> classify. Any missing input or review flag -> MANUAL_REVIEW. The result recommends;
it never authorizes a purchase (``decision_required`` is always True).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from dealradar.core import hu
from dealradar.core.enums import Condition, MatchMethod, MatchStatus, WarrantyType
from dealradar.core.money import Bp
from dealradar.evaluation.costs import discount_bp, effective_price
from dealradar.evaluation.params import PersonalParams
from dealradar.evaluation.types import (
    Assumption,
    Level,
    PersonalInputs,
    PersonalVerdict,
    ValueKind,
    at_least,
)

UNUSABLE_BENCHMARK = ("NO_DATA", "INSUFFICIENT_DATA")


class WatchlistRelevance(StrEnum):
    NOT_WATCHED = "NOT_WATCHED"
    WATCHED = "WATCHED"
    TARGET_MET = "TARGET_MET"
    ABOVE_MAX_PRICE = "ABOVE_MAX_PRICE"
    CONDITION_NOT_ACCEPTED = "CONDITION_NOT_ACCEPTED"


@dataclass(frozen=True)
class PersonalResult:
    verdict: PersonalVerdict
    effective_price_huf: int | None  # item + delivery
    compared_price_huf: int | None  # the price actually compared with the benchmark
    comparison_basis: str | None  # "LANDED" (item + delivery) or "ITEM"
    benchmark_median_huf: int | None
    discount_vs_median_bp: Bp | None  # + = cheaper than the median
    discount_vs_min_bp: Bp | None  # + = cheaper than the historical minimum
    at_or_below_historical_min: bool | None
    watchlist: WatchlistRelevance
    reasons: tuple[str, ...]
    missing_inputs: tuple[str, ...]
    review_flags: tuple[str, ...]
    assumptions: tuple[Assumption, ...]
    engine: Literal["PERSONAL"] = "PERSONAL"
    decision_required: Literal[True] = True  # the engine never buys or authorizes buying


def _match_findings(inputs: PersonalInputs, missing: list[str], flags: list[str]) -> None:
    m, p = inputs.match, inputs.params
    if m.status is not MatchStatus.MATCHED:
        missing.append("product_match")
    elif m.method in (MatchMethod.FUZZY, MatchMethod.AI_SUGGESTED) and not m.confirmed_by_user:
        flags.append("match_not_confirmed")
    elif not m.confirmed_by_user and (
        m.confidence is None or m.confidence < p.min_match_confidence
    ):
        flags.append("match_confidence_low")


def evaluate(inputs: PersonalInputs) -> PersonalResult:
    p, cat, bench = inputs.params, inputs.category, inputs.benchmark
    missing = list(cat.missing_inputs)
    flags = list(cat.review_flags)
    reasons: list[str] = []
    assumptions: list[Assumption] = [
        Assumption(
            "thresholds",
            f"strong {p.strong_discount_bp} bp, good {p.good_discount_bp} bp, "
            f"fair tolerance {p.fair_tolerance_bp} bp",
            ValueKind.ASSUMPTION,
            p.source,
        ),
    ]
    _match_findings(inputs, missing, flags)

    if bench is None or bench.status in UNUSABLE_BENCHMARK:
        missing.append("price_benchmark")
        bench = None
    else:
        if bench.status == "STALE":
            flags.append("benchmark_stale")
        if not at_least(bench.confidence, Level(p.min_benchmark_confidence)):
            flags.append("benchmark_confidence_low")
        if inputs.condition_group is not None and bench.condition_group not in (
            inputs.condition_group,
            "NOT_APPLICABLE",
        ):
            flags.append("benchmark_condition_mismatch")

    # --- comparisons (facts vs. estimates) ---
    eff = effective_price(cat.price_huf, cat.shipping_huf, inputs.pickup_only)
    if cat.price_huf is None:
        missing.append("price")
    elif eff is None:
        missing.append("shipping")  # defence in depth: never assume free delivery
    if inputs.pickup_only:
        reasons.append("csak személyes átvétel: az útiköltség nincs benne az árban")
    compared: int | None = None
    basis: str | None = None
    median: int | None = None
    if bench is not None and cat.price_huf is not None:
        if bench.landed_median is not None and eff is not None:
            compared, basis, median = eff, "LANDED", bench.landed_median
        elif p.require_landed_comparison:
            flags.append("landed_benchmark_missing")
        elif bench.item_median is not None:
            compared, basis, median = cat.price_huf, "ITEM", bench.item_median
            reasons.append(
                "szállítási díj nélkül összehasonlítva (nincs szállítással számolt viszonyítási ár)"
            )
    disc = discount_bp(median, compared) if compared is not None and median else None
    disc_min: Bp | None = None
    at_min: bool | None = None
    if bench is not None and bench.item_min and cat.price_huf is not None:
        disc_min = discount_bp(bench.item_min, cat.price_huf)
        at_min = cat.price_huf <= bench.item_min
    if disc is not None:
        assumptions.append(
            Assumption(
                "benchmark median",
                f"{median} HUF ({basis}, {bench.n_samples if bench else 0} samples, "
                f"{bench.window_days if bench else 0} days)",
                ValueKind.ESTIMATE,
                "price observations",
            )
        )
        if disc >= p.suspicious_discount_bp:
            flags.append("too_good_to_be_true")
            reasons.append(
                f"{hu.pct(disc, signed=False)}-kal a szokásos ár alatt: "
                "árhiba, hamisítvány vagy rossz párosítás lehet"
            )

    # --- warranty ---
    used = cat.condition not in (None, Condition.NEW)
    min_w = p.min_warranty_months_used if used else p.min_warranty_months_new
    blocks: list[str] = []
    new_no_warranty = cat.condition is Condition.NEW and inputs.warranty_type is WarrantyType.NONE
    if new_no_warranty and p.flag_new_without_warranty:
        flags.append("new_without_warranty")
    if inputs.warranty_months is not None and inputs.warranty_months < min_w:
        blocks.append(
            f"a garancia ({inputs.warranty_months} hónap) kevesebb a minimumodnál ({min_w} hónap)"
        )

    # --- the user's own limits ---
    relevance = WatchlistRelevance.NOT_WATCHED
    w = inputs.watchlist
    if w is not None:
        relevance = WatchlistRelevance.WATCHED
        if w.acceptable_conditions is not None and cat.condition not in w.acceptable_conditions:
            relevance = WatchlistRelevance.CONDITION_NOT_ACCEPTED
            blocks.append(
                f"az állapot ({hu.label('condition', cat.condition)}) számodra nem elfogadható"
            )
        elif w.max_price_huf is not None and eff is not None and eff > w.max_price_huf:
            relevance = WatchlistRelevance.ABOVE_MAX_PRICE
            blocks.append(f"{hu.huf(eff)} több a maximális áradnál ({hu.huf(w.max_price_huf)})")
        elif w.target_price_huf is not None and eff is not None and eff <= w.target_price_huf:
            relevance = WatchlistRelevance.TARGET_MET
            reasons.append(f"eléri a célárad ({hu.huf(w.target_price_huf)})")
        if w.target_price_huf is not None or w.max_price_huf is not None:
            assumptions.append(
                Assumption(
                    "watchlist",
                    f"target {w.target_price_huf}, max {w.max_price_huf}",
                    ValueKind.USER_INPUT,
                    "watchlist",
                )
            )

    # --- classification ---
    verdict = _classify(
        missing, flags, blocks, disc, at_min, bench.confidence if bench else None, p, reasons
    )
    return PersonalResult(
        verdict=verdict,
        effective_price_huf=eff,
        compared_price_huf=compared,
        comparison_basis=basis,
        benchmark_median_huf=median,
        discount_vs_median_bp=disc,
        discount_vs_min_bp=disc_min,
        at_or_below_historical_min=at_min,
        watchlist=relevance,
        reasons=tuple([*reasons, *blocks]),
        missing_inputs=tuple(dict.fromkeys(missing)),
        review_flags=tuple(dict.fromkeys(flags)),
        assumptions=tuple(assumptions),
    )


def _classify(
    missing: list[str],
    flags: list[str],
    blocks: list[str],
    disc: Bp | None,
    at_min: bool | None,
    confidence: Level | None,
    p: PersonalParams,
    reasons: list[str],
) -> PersonalVerdict:
    if missing or flags:
        return PersonalVerdict.MANUAL_REVIEW
    if blocks:
        return PersonalVerdict.NOT_A_DEAL
    if disc is None:  # pragma: no cover - guarded by missing/flags above
        return PersonalVerdict.MANUAL_REVIEW
    strong = disc >= p.strong_discount_bp or (bool(at_min) and disc >= p.good_discount_bp)
    if strong:
        if confidence is not None and at_least(confidence, Level(p.strong_requires_confidence)):
            return PersonalVerdict.STRONG_DEAL
        reasons.append("kiemelkedő lenne, de az összehasonlító ár nem elég megbízható")
        return PersonalVerdict.GOOD_DEAL
    if disc >= p.good_discount_bp:
        return PersonalVerdict.GOOD_DEAL
    if disc >= -p.fair_tolerance_bp:
        return PersonalVerdict.FAIR_PRICE
    return PersonalVerdict.NOT_A_DEAL
