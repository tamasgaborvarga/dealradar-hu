"""Pricing on the shared database: recording, snapshots, variant isolation, category policies."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from dealradar.core.clock import utcnow
from dealradar.core.enums import (
    Actor,
    Availability,
    CanonicalUnit,
    Category,
    Condition,
    ListingKind,
    PlatformKind,
    ProductOrigin,
    SaleEvidence,
)
from dealradar.db.models import (
    FoodAttributes,
    Listing,
    Offer,
    Platform,
    PriceObservation,
    Product,
    ProductVariant,
    Source,
)
from dealradar.db.session import Database
from dealradar.pricing.types import BenchmarkStatus, Channel, ConditionGroup, PriceKind
from dealradar.services import pricing
from tests import factories as f


def product(
    s: Session, category: Category, *keys: str, totals: dict[str, str] | None = None
) -> dict[str, ProductVariant]:
    prod = Product(category=category, title=f"Synthetic {category}", created_by=ProductOrigin.USER)
    variants = {
        k: ProductVariant(
            product=prod,
            variant_key=k,
            variant_attrs={"total_canonical": totals[k]} if totals and k in totals else None,
        )
        for k in keys
    }
    s.add_all([prod, *variants.values()])
    s.flush()
    if category is Category.FOOD:
        s.add(FoodAttributes(product_id=prod.id, canonical_unit=CanonicalUnit.KG))
        s.flush()
    return variants


def offer(
    s: Session, src: Source, variant: ProductVariant | None, ext: str,
    condition: Condition | None = Condition.NEW, kind: ListingKind = ListingKind.RETAIL,
    currency: str = "HUF",
) -> Offer:  # fmt: skip
    listing = Listing(source_id=src.id, external_id=ext, title="synthetic", listing_kind=kind,
                      condition=condition)  # fmt: skip
    off = Offer(listing=listing, variant_id=variant.id if variant else None, currency=currency)
    s.add_all([listing, off])
    s.flush()
    return off


def observe_days(
    s: Session, off: Offer, prices: list[int], start_days_ago: float = 0, shipping: int | None = 0
) -> None:
    now = utcnow()
    for i, price in enumerate(prices):
        pricing.record_observation(
            s, off.id, observed_at=now - timedelta(days=start_days_ago + i, minutes=1),
            price_huf=price, shipping_huf=shipping, availability=Availability.IN_STOCK,
        )  # fmt: skip


def test_record_observation_snapshots_listing_state(db: Database) -> None:
    with db.write_session() as s:
        src = f.source(s)
        off = offer(s, src, product(s, Category.TECH, "default")["default"], "a",
                    condition=Condition.USED_A, kind=ListingKind.CLASSIFIED)  # fmt: skip
        obs = pricing.record_observation(s, off.id, observed_at=utcnow() - timedelta(hours=1),
                                         price_huf=45_000, shipping_huf=None,
                                         availability=Availability.UNKNOWN)  # fmt: skip
        off.listing.condition = Condition.USED_C  # the ad is edited later
        obs_id, src_id = obs.id, src.id
    with db.read_session() as s:
        stored = s.get(PriceObservation, obs_id)
        assert stored is not None
        assert (stored.condition, stored.listing_kind, stored.source_id) == (
            Condition.USED_A, ListingKind.CLASSIFIED, src_id,
        )  # fmt: skip
        assert stored.shipping_huf is None  # unknown stays unknown


def test_record_observation_rejects_bad_input(db: Database) -> None:
    with db.write_session() as s:
        off = offer(s, f.source(s), None, "a", currency="EUR")
        off_id = off.id
    with pytest.raises(ValueError, match="FX"), db.write_session() as s:
        pricing.record_observation(s, off_id, observed_at=utcnow(), price_huf=1, shipping_huf=0,
                                   availability=Availability.IN_STOCK)  # fmt: skip
    with pytest.raises(ValueError, match="future"), db.write_session() as s:
        later = utcnow() + timedelta(hours=1)
        pricing.record_observation(s, off_id, observed_at=later, price_huf=1, shipping_huf=0,
                                   availability=Availability.IN_STOCK)  # fmt: skip
    with pytest.raises(ValueError, match="unknown offer"), db.write_session() as s:
        pricing.record_observation(s, 999, observed_at=utcnow(), price_huf=1, shipping_huf=0,
                                   availability=Availability.IN_STOCK)  # fmt: skip


def test_benchmark_only_counts_the_requested_variant(db: Database) -> None:
    with db.write_session() as s:
        variants = product(s, Category.APPAREL, "EU42", "EU43")
        src_a, src_b = f.source(s, "a"), f.source(s, "b")
        for i, src in enumerate((src_a, src_b, src_a)):
            observe_days(s, offer(s, src, variants["EU42"], f"42-{i}"), [30_000, 30_500, 29_900])
            observe_days(s, offer(s, src, variants["EU43"], f"43-{i}"), [18_000, 18_200, 17_900])
        observe_days(s, offer(s, src_a, None, "unmatched"), [1_000] * 3)  # never counted
        v42 = variants["EU42"].id
    b = pricing.advertised_benchmark(db, v42, ConditionGroup.NEW, Channel.RETAIL)
    assert b.status is BenchmarkStatus.OK
    assert b.item is not None and b.item.min >= 29_900 and b.n_offers == 3 and b.n_sources == 2


def test_merged_variant_history_follows_the_merge(db: Database) -> None:
    with db.write_session() as s:
        variants = product(s, Category.TECH, "1000GB", "1TB")
        src = f.source(s)
        for i in range(3):
            observe_days(s, offer(s, src, variants["1TB"], f"dup-{i}"), [40_000, 40_500])
        variants["1TB"].merged_into_id = variants["1000GB"].id
        survivor = variants["1000GB"].id
    b = pricing.advertised_benchmark(db, survivor, ConditionGroup.NEW, Channel.RETAIL)
    assert b.n_samples == 6 and b.status is BenchmarkStatus.OK


def test_category_policy_is_applied(db: Database) -> None:
    with db.write_session() as s:
        food = product(s, Category.FOOD, "500G", totals={"500G": "0.5"})["500G"]
        tech = product(s, Category.TECH, "default")["default"]
        src = f.source(s)
        for i in range(3):
            observe_days(
                s, offer(s, src, food, f"f{i}", condition=None), [899, 899], start_days_ago=40
            )
            observe_days(s, offer(s, src, tech, f"t{i}"), [899, 899], start_days_ago=40)
        food_id, tech_id = food.id, tech.id
    food_b = pricing.advertised_benchmark(db, food_id, ConditionGroup.NEW, Channel.RETAIL)
    tech_b = pricing.advertised_benchmark(db, tech_id, ConditionGroup.NEW, Channel.RETAIL)
    assert food_b.status is BenchmarkStatus.NO_DATA  # food window is 30 days
    assert tech_b.status is BenchmarkStatus.STALE  # tech window is 90 days, data 40 days old


def test_food_unit_price_on_database(db: Database) -> None:
    with db.write_session() as s:
        variants = product(s, Category.FOOD, "500G", "1000G", totals={"500G": "0.5", "1000G": "1"})
        src = f.source(s)
        for i in range(3):
            observe_days(s, offer(s, src, variants["500G"], f"s{i}", condition=None), [899, 899])
            observe_days(
                s, offer(s, src, variants["1000G"], f"b{i}", condition=None), [1_599, 1_599]
            )
        small, product_id = variants["500G"].id, variants["500G"].product_id
    per_variant = pricing.advertised_benchmark(db, small, ConditionGroup.NEW, Channel.RETAIL)
    assert per_variant.unit_price is not None and per_variant.unit_price.trimmed_median == 179_800
    across = pricing.unit_price_across_packs(db, product_id, Channel.RETAIL)
    assert across.status is BenchmarkStatus.OK and across.canonical_unit == "KG"
    assert across.unit_price is not None and across.unit_price.min == 159_900


def test_cross_variant_comparison_refused_for_tech(db: Database) -> None:
    with db.write_session() as s:
        product_id = product(s, Category.TECH, "default")["default"].product_id
    with pytest.raises(ValueError, match="does not allow"):
        pricing.unit_price_across_packs(db, product_id, Channel.RETAIL)


def test_completed_sales_are_separate_from_advertised_prices(db: Database) -> None:
    with db.write_session() as s:
        variant = product(s, Category.TECH, "default")["default"]
        platform = Platform(
            key="synthetic-auction", name="Synthetic auction", kind=PlatformKind.AUCTION
        )
        s.add(platform)
        s.flush()
        src = f.source(s)
        for i in range(3):  # high asking prices
            observe_days(s, offer(s, src, variant, f"ask{i}", condition=Condition.USED_B,
                                  kind=ListingKind.CLASSIFIED), [95_000, 95_000])  # fmt: skip
        for i, price in enumerate([70_000, 72_000, 71_000, 69_000]):
            pricing.record_completed_sale(
                s, variant_id=variant.id, platform_id=platform.id,
                evidence=SaleEvidence.PLATFORM_FINAL_PRICE, condition=Condition.USED_B,
                sale_price_huf=price, buyer_shipping_huf=1_990,
                sold_at=utcnow() - timedelta(days=i + 1), source_ref="synthetic fixture",
                entered_by=Actor.USER, days_listed=4,
            )  # fmt: skip
        vid = variant.id
    sold = pricing.sold_benchmark(db, vid, ConditionGroup.USED)
    asked = pricing.advertised_benchmark(db, vid, ConditionGroup.USED, Channel.SECONDHAND)
    assert sold.price_kind is PriceKind.SOLD and asked.price_kind is PriceKind.ADVERTISED
    assert sold.sale_price is not None and sold.sale_price.max == 72_000  # asks never leak in
    assert asked.item is not None and asked.item.min == 95_000  # sales never leak in
    assert sold.buyer_delivery is not None and sold.buyer_delivery.median_huf == 1_990


def test_completed_sale_constraints(db: Database) -> None:
    with pytest.raises(IntegrityError), db.write_session() as s:
        variant = product(s, Category.TECH, "default")["default"]
        platform = Platform(key="p", name="p", kind=PlatformKind.OTHER)
        s.add(platform)
        s.flush()
        pricing.record_completed_sale(
            s, variant_id=variant.id, platform_id=platform.id, evidence=SaleEvidence.USER_REPORTED,
            condition=Condition.USED, sale_price_huf=0, buyer_shipping_huf=None,
            sold_at=utcnow(), source_ref="x", entered_by=Actor.USER,
        )  # fmt: skip


def test_insufficient_data_is_explicit_on_the_database(db: Database) -> None:
    with db.write_session() as s:
        variant = product(s, Category.HOME, "default")["default"]
        observe_days(s, offer(s, f.source(s), variant, "only"), [150_000])
        vid = variant.id
    b = pricing.advertised_benchmark(db, vid, ConditionGroup.NEW, Channel.RETAIL)
    assert b.status is BenchmarkStatus.INSUFFICIENT_DATA and b.item is None
    assert pricing.sold_benchmark(db, vid, ConditionGroup.NEW).status is BenchmarkStatus.NO_DATA
