"""Builders for engine tests (synthetic values only)."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from dealradar.core.enums import (
    Category,
    Condition,
    MatchMethod,
    MatchStatus,
    SellerKind,
    WarrantyType,
)
from dealradar.core.money import Bp
from dealradar.evaluation.inputs import CategoryEvaluationInputs
from dealradar.evaluation.params import (
    FeeProfile,
    PersonalParams,
    ResaleParams,
    TaxKind,
    TaxProfile,
)
from dealradar.evaluation.types import (
    AdvertisedView,
    Level,
    MatchInfo,
    PersonalInputs,
    ResaleInputs,
    SoldView,
)

MATCHED = MatchInfo(MatchStatus.MATCHED, MatchMethod.GTIN, 100)


def category_inputs(**kw: Any) -> CategoryEvaluationInputs:
    data: dict[str, Any] = {
        "category": Category.TECH,
        "price_huf": 80_000,
        "shipping_huf": 0,
        "condition": Condition.NEW,
        "seller_kind": SellerKind.RETAILER,
        "resale_applicable": True,
    }
    data.update(kw)
    return CategoryEvaluationInputs(**data)


def advertised(**kw: Any) -> AdvertisedView:
    data: dict[str, Any] = {
        "status": "OK", "confidence": Level.HIGH, "condition_group": "NEW", "n_samples": 40,
        "item_median": 100_000, "item_min": 85_000, "landed_median": None, "window_days": 90,
    }  # fmt: skip
    data.update(kw)
    return AdvertisedView(**data)


def personal_inputs(price: int = 80_000, **kw: Any) -> PersonalInputs:
    cat_kw = {"price_huf": price, **kw.pop("category_kw", {})}
    data: dict[str, Any] = {
        "category": category_inputs(**cat_kw),
        "condition_group": "NEW",
        "warranty_months": 24,
        "warranty_type": WarrantyType.MANUFACTURER_HU,
        "pickup_only": False,
        "match": MATCHED,
        "benchmark": advertised(),
        "watchlist": None,
        "params": PersonalParams(),
    }
    data.update(kw)
    return PersonalInputs(**data)


FEE = FeeProfile(
    platform="synthetic marketplace", commission_bp=Bp(1_000), commission_min_huf=200,
    payment_fee_bp=Bp(150), payment_fixed_huf=50, outbound_shipping_cost_huf=1_990,
    packaging_huf=500, verified=True,
)  # fmt: skip
TAX = TaxProfile(TaxKind.PERCENT_OF_PROFIT, Bp(1_500), verified=True)


def sold(**kw: Any) -> SoldView:
    data: dict[str, Any] = {
        "status": "OK", "confidence": Level.HIGH, "condition_group": "USED", "n_sales": 10,
        "n_platforms": 2, "window_days": 180, "p25": 60_000, "median": 60_000, "p75": 60_000,
        "median_days_listed": 10, "n_with_days_listed": 10, "buyer_shipping_median": 1_500,
        "user_reported_only": False,
    }  # fmt: skip
    data.update(kw)
    return SoldView(**data)


def resale_inputs(price: int = 40_000, **kw: Any) -> ResaleInputs:
    cat_kw = {"price_huf": price, "condition": Condition.USED_B, **kw.pop("category_kw", {})}
    params_kw = kw.pop("params_kw", {})
    data: dict[str, Any] = {
        "category": category_inputs(**cat_kw),
        "condition_group": "USED",
        "pickup_only": False,
        "match": MATCHED,
        "completed_sales": sold(),
        "fee_profile": FEE,
        "tax_profile": TAX,
        "params": replace(ResaleParams(), **params_kw),
    }
    data.update(kw)
    return ResaleInputs(**data)
