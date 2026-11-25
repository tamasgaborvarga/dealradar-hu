"""Both engines end to end on the database, plus configurable (audited) category parameters."""

from __future__ import annotations

from datetime import timedelta

import pytest

from dealradar.categories.registry import module_for
from dealradar.core.clock import utcnow
from dealradar.core.enums import (
    Actor,
    Category,
    Condition,
    ListingKind,
    MatchMethod,
    MatchStatus,
    PlatformKind,
    SaleEvidence,
    SellerKind,
)
from dealradar.db.models import AuditLog, Platform
from dealradar.db.session import Database
from dealradar.evaluation.params import PersonalParams, ResaleParams
from dealradar.evaluation.types import MatchInfo, PersonalVerdict, ResaleVerdict
from dealradar.services import evaluation, pricing
from tests import factories as f
from tests.category_helpers import norm
from tests.engine_fixtures import FEE, TAX
from tests.test_pricing_service import observe_days, offer, product

MATCHED = MatchInfo(MatchStatus.MATCHED, MatchMethod.GTIN, 100)


# --- configurable parameters ---


def test_overrides_are_validated() -> None:
    base = ResaleParams()
    with pytest.raises(ValueError, match="unknown"):
        evaluation.apply_overrides(base, {"min_net_profit": 1})  # typo must not be ignored
    with pytest.raises(ValueError, match="whole number"):
        evaluation.apply_overrides(base, {"min_roi_bp": "15%"})
    with pytest.raises(ValueError, match="negative"):
        evaluation.apply_overrides(base, {"return_cost_huf": -1})
    with pytest.raises(ValueError):
        evaluation.apply_overrides(base, {"min_sales_confidence": "SURE"})
    with pytest.raises(ValueError, match="true/false"):
        evaluation.apply_overrides(PersonalParams(), {"require_landed_comparison": 1})
    changed = evaluation.apply_overrides(
        base, {"min_net_profit_huf": 20_000, "pickup_travel_cost_huf": None}
    )
    assert changed.min_net_profit_huf == 20_000 and changed.source == "user override (settings)"
    assert evaluation.apply_overrides(base, {}) is base


def test_overrides_are_stored_and_audited(db: Database) -> None:
    evaluation.set_overrides(db, "resale", Category.TECH, {"min_roi_bp": 2_500})
    with db.read_session() as s:
        _, resale_params = evaluation.load_params(s, Category.TECH)
        assert resale_params.min_roi_bp == 2_500
        assert s.query(AuditLog).filter_by(entity="settings").count() == 1
    with pytest.raises(ValueError):
        evaluation.set_overrides(db, "resale", Category.TECH, {"bogus": 1})


def test_category_defaults_differ_where_categories_differ() -> None:
    assert module_for(Category.HOME).personal_params.require_landed_comparison
    assert not module_for(Category.TECH).personal_params.require_landed_comparison
    assert (
        module_for(Category.APPAREL).resale_params.return_rate_bp
        > module_for(Category.TECH).resale_params.return_rate_bp
    )
    assert (
        module_for(Category.HOME).resale_params.return_cost_huf
        > module_for(Category.TECH).resale_params.return_cost_huf
    )


# --- personal engine on the database ---


def test_personal_end_to_end(db: Database) -> None:
    with db.write_session() as s:
        variant = product(s, Category.TECH, "default")["default"]
        a, b = f.source(s, "a"), f.source(s, "b")
        for i, src in enumerate((a, b, a, b)):
            observe_days(s, offer(s, src, variant, f"o{i}"), [100_000, 100_000, 100_000])
        vid = variant.id
    listing = norm(
        Category.TECH,
        "Samsung 990 PRO 2TB NVMe SSD",
        brand="Samsung",
        price_text="80 000 Ft",
        warranty_text="5 év",
    )
    r = evaluation.evaluate_personal(db, listing, vid, MATCHED)
    assert r.benchmark_median_huf == 100_000 and r.discount_vs_median_bp == 2_000
    assert r.verdict is PersonalVerdict.GOOD_DEAL  # STRONG needs a HIGH-confidence benchmark
    assert r.decision_required


def test_personal_without_history_needs_review(db: Database) -> None:
    with db.write_session() as s:
        vid = product(s, Category.TECH, "default")["default"].id
    listing = norm(
        Category.TECH, "Samsung 990 PRO 2TB NVMe SSD", brand="Samsung", warranty_text="5 év"
    )
    r = evaluation.evaluate_personal(db, listing, vid, MATCHED)
    assert r.verdict is PersonalVerdict.MANUAL_REVIEW and "price_benchmark" in r.missing_inputs


# --- resale engine on the database ---


def _sales(db: Database, n: int, price: int = 60_000) -> int:
    with db.write_session() as s:
        variant = product(s, Category.TECH, "default")["default"]
        platform = Platform(key="synthetic", name="Synthetic auction", kind=PlatformKind.AUCTION)
        s.add(platform)
        s.flush()
        for i in range(n):
            pricing.record_completed_sale(
                s,
                variant_id=variant.id,
                platform_id=platform.id,
                evidence=SaleEvidence.PLATFORM_FINAL_PRICE,
                condition=Condition.USED_B,
                sale_price_huf=price,
                buyer_shipping_huf=1_500,
                sold_at=utcnow() - timedelta(days=i + 1),
                source_ref="synthetic",
                entered_by=Actor.USER,
                days_listed=10,
            )
        return variant.id


def _used_listing():  # type: ignore[no-untyped-def]
    return norm(
        Category.TECH,
        "Samsung 990 PRO 2TB NVMe SSD",
        brand="Samsung",
        price_text="40 000 Ft",
        condition_text="használt",
        warranty_text="nincs garancia",
        listing_kind=ListingKind.CLASSIFIED,
        seller_kind=SellerKind.PRIVATE,
    )


def test_resale_end_to_end(db: Database) -> None:
    vid = _sales(db, 6)
    r = evaluation.evaluate_resale(db, _used_listing(), vid, MATCHED, FEE, TAX)
    assert r.verdict is ResaleVerdict.PROFITABLE, (r.missing_inputs, r.review_flags, r.reasons)
    assert r.net_profit_huf == 9_570 and r.expected_sale_huf == 60_000


def test_resale_user_override_changes_verdict(db: Database) -> None:
    vid = _sales(db, 6)
    evaluation.set_overrides(db, "resale", Category.TECH, {"min_net_profit_huf": 20_000})
    r = evaluation.evaluate_resale(db, _used_listing(), vid, MATCHED, FEE, TAX)
    assert r.verdict is ResaleVerdict.MARGINAL
    assert any(a.source == "user override (settings)" for a in r.assumptions)


def test_resale_without_enough_sales_needs_review(db: Database) -> None:
    vid = _sales(db, 2)
    r = evaluation.evaluate_resale(db, _used_listing(), vid, MATCHED, FEE, TAX)
    assert r.verdict is ResaleVerdict.MANUAL_REVIEW and r.net_profit_huf is None


def test_food_resale_not_applicable(db: Database) -> None:
    with db.write_session() as s:
        vid = product(s, Category.FOOD, "500G", totals={"500G": "0.5"})["500G"].id
    listing = norm(
        Category.FOOD, "Kávé 500 g", brand="Synthetic", model="Kávé", condition_text=None
    )
    r = evaluation.evaluate_resale(db, listing, vid, MATCHED, FEE, TAX)
    assert r.verdict is ResaleVerdict.NOT_APPLICABLE
