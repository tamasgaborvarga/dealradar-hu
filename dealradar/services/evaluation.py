"""Builds engine inputs from the database and runs the two engines - separately, never combined.

Nothing here buys anything or marks anything as approved: results are recommendations that need a
user decision (``decision_required``).
"""

from __future__ import annotations

import dataclasses
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from dealradar.categories.registry import module_for
from dealradar.core.enums import Actor, Category
from dealradar.db.repositories import SettingsRepository
from dealradar.db.session import Database
from dealradar.engines import personal, resale
from dealradar.evaluation.params import FeeProfile, PersonalParams, ResaleParams, TaxProfile
from dealradar.evaluation.types import (
    AdvertisedView,
    Level,
    MatchInfo,
    PersonalInputs,
    ResaleInputs,
    SoldView,
    WatchlistTarget,
)
from dealradar.normalize.types import NormalizedListing
from dealradar.pricing.types import (
    AdvertisedBenchmark,
    ConditionGroup,
    SoldBenchmark,
    channel_of,
    condition_group,
)
from dealradar.services import pricing

_LEVEL_FIELDS = {"min_benchmark_confidence", "strong_requires_confidence", "min_sales_confidence"}


# --- configurable parameters ---


def _settings_key(engine: str, category: Category) -> str:
    return f"engine.{engine}.{category.value}"


def apply_overrides[P: (PersonalParams, ResaleParams)](defaults: P, overrides: dict[str, Any]) -> P:
    """Validated override of category defaults. Unknown keys, wrong types and negative numbers
    are rejected - a typo must never silently fall back to a default."""
    fields = {f.name: f for f in dataclasses.fields(defaults) if f.name != "source"}
    clean: dict[str, Any] = {}
    for key, value in overrides.items():
        if key not in fields:
            raise ValueError(f"unknown parameter {key!r}")
        current = getattr(defaults, key)
        if key in _LEVEL_FIELDS:
            clean[key] = Level(value).value
        elif isinstance(current, bool):
            if not isinstance(value, bool):
                raise ValueError(f"{key} must be true/false")
            clean[key] = value
        else:
            if value is None and key == "pickup_travel_cost_huf":
                clean[key] = None
                continue
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{key} must be a whole number")
            if value < 0:
                raise ValueError(f"{key} must not be negative")
            clean[key] = value
    if not clean:
        return defaults
    return dataclasses.replace(defaults, **clean, source="user override (settings)")


def load_params(session: Session, category: Category) -> tuple[PersonalParams, ResaleParams]:
    module = module_for(category)
    repo = SettingsRepository(session)
    personal_over = repo.get_value(_settings_key("personal", category), {}) or {}
    resale_over = repo.get_value(_settings_key("resale", category), {}) or {}
    return (
        apply_overrides(module.personal_params, personal_over),
        apply_overrides(module.resale_params, resale_over),
    )


def set_overrides(db: Database, engine: str, category: Category, overrides: dict[str, Any]) -> None:
    """Store user overrides (validated first, audited by the settings repository)."""
    module = module_for(category)
    if engine == "personal":
        apply_overrides(module.personal_params, overrides)
    elif engine == "resale":
        apply_overrides(module.resale_params, overrides)
    else:
        raise ValueError("engine must be 'personal' or 'resale'")
    with db.write_session() as s:
        SettingsRepository(s).set_value(_settings_key(engine, category), overrides, Actor.USER)


# --- benchmark views ---


def advertised_view(b: AdvertisedBenchmark, window_days: int) -> AdvertisedView:
    return AdvertisedView(
        status=b.status.value,
        confidence=Level(b.confidence.value),
        condition_group=b.key.condition_group.value,
        n_samples=b.n_samples,
        item_median=b.item.trimmed_median if b.item else None,
        item_min=b.item.min if b.item else None,
        landed_median=b.landed.trimmed_median if b.landed else None,
        window_days=window_days,
    )


def sold_view(b: SoldBenchmark, window_days: int) -> SoldView:
    s = b.sale_price
    return SoldView(
        status=b.status.value,
        confidence=Level(b.confidence.value),
        condition_group=b.condition_group.value,
        n_sales=b.n_sales,
        n_platforms=b.n_platforms,
        window_days=window_days,
        p25=s.p25 if s else None,
        median=s.trimmed_median if s else None,
        p75=s.p75 if s else None,
        median_days_listed=b.median_days_listed,
        n_with_days_listed=b.n_with_days_listed,
        buyer_shipping_median=b.buyer_delivery.median_huf if b.buyer_delivery else None,
        user_reported_only=bool(b.evidence) and set(b.evidence) == {"USER_REPORTED"},
    )


def _group(listing: NormalizedListing) -> ConditionGroup | None:
    if not module_for(listing.category).benchmark_policy.condition_relevant:
        return ConditionGroup.NOT_APPLICABLE
    return condition_group(listing.condition)


# --- the two engines, run separately ---


def evaluate_personal(
    db: Database,
    listing: NormalizedListing,
    variant_id: int | None,
    match: MatchInfo,
    watchlist: WatchlistTarget | None = None,
    now: datetime | None = None,
) -> personal.PersonalResult:
    module = module_for(listing.category)
    group = _group(listing)
    bench_view: AdvertisedView | None = None
    if group is not None and variant_id is not None:
        bench = pricing.advertised_benchmark(
            db, variant_id, group, channel_of(listing.listing_kind), now
        )
        bench_view = advertised_view(bench, module.benchmark_policy.window_days)
    with db.read_session() as s:
        personal_params, _ = load_params(s, listing.category)
    return personal.evaluate(
        PersonalInputs(
            category=module.evaluation_inputs(listing),
            condition_group=group.value if group else None,
            warranty_months=listing.warranty_months,
            warranty_type=listing.warranty_type,
            pickup_only=listing.pickup_only,
            match=match,
            benchmark=bench_view,
            watchlist=watchlist,
            params=personal_params,
        )
    )


def evaluate_resale(
    db: Database,
    listing: NormalizedListing,
    variant_id: int | None,
    match: MatchInfo,
    fee_profile: FeeProfile | None,
    tax_profile: TaxProfile | None,
    now: datetime | None = None,
) -> resale.ResaleResult:
    module = module_for(listing.category)
    group = _group(listing)
    sold: SoldView | None = None
    if variant_id is not None and group is not None and group is not ConditionGroup.NOT_APPLICABLE:
        sb = pricing.sold_benchmark(db, variant_id, group, now)
        sold = sold_view(sb, module.benchmark_policy.sold_window_days)
    with db.read_session() as s:
        _, resale_params = load_params(s, listing.category)
    return resale.evaluate(
        ResaleInputs(
            category=module.evaluation_inputs(listing),
            condition_group=group.value if group else None,
            pickup_only=listing.pickup_only,
            match=match,
            completed_sales=sold,
            fee_profile=fee_profile,
            tax_profile=tax_profile,
            params=resale_params,
        )
    )
