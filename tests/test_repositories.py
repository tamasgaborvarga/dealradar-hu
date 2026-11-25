from __future__ import annotations

import pytest

from dealradar.core.enums import Actor, Category, IdType, MatchStatus
from dealradar.db.models import AuditLog, Platform, ProductVariant, VariantIdentifier
from dealradar.db.repositories import (
    ListingRepository,
    PriceObservationRepository,
    ProductRepository,
    SettingsRepository,
    SourceRepository,
)
from dealradar.db.session import Database
from dealradar.services.overview import system_overview
from tests import factories as f


def test_counts_cover_every_category(db: Database) -> None:
    with db.write_session() as s:
        f.product(s, Category.FOOD, "1KG")
        prod, _ = f.product(s, Category.APPAREL, "EU42")
        s.add(ProductVariant(product_id=prod.id, variant_key="EU43"))
    with db.read_session() as s:
        repo = ProductRepository(s)
        assert repo.count_by_category() == {
            Category.TECH: 0,
            Category.APPAREL: 1,
            Category.FOOD: 1,
            Category.HOME: 0,
        }
        assert repo.count_variants_by_category()[Category.APPAREL] == 2


def test_find_variant_by_identifier(db: Database) -> None:
    with db.write_session() as s:
        _, v = f.product(s)
        s.add(VariantIdentifier(variant_id=v.id, id_type=IdType.MPN, value="ABC-123"))
        variant_id = v.id
    with db.read_session() as s:
        repo = ProductRepository(s)
        found = repo.find_variant_by_identifier(IdType.MPN, "ABC-123")
        assert found is not None and found.id == variant_id
        assert repo.find_variant_by_identifier(IdType.MPN, "nope") is None
        with pytest.raises(ValueError):
            repo.find_variant_by_identifier(IdType.SHOP_SKU, "x")


def test_listing_and_observation_lookups(db: Database) -> None:
    with db.write_session() as s:
        src = f.source(s)
        off = f.offer(s, src, "url:abc")
        prod, _ = f.product(s, Category.HOME)
        off.listing.product_id = prod.id
        off.listing.match_status = MatchStatus.MATCHED
        f.observe(s, off, 5_490, hours_ago=2)
        f.observe(s, off, 4_990, hours_ago=1)
        src_id, off_id = src.id, off.id
    with db.read_session() as s:
        assert ListingRepository(s).get_by_external_id(src_id, "url:abc") is not None
        assert ListingRepository(s).count_matched_by_category()[Category.HOME] == 1
        assert ListingRepository(s).count_unmatched() == 0
        latest = PriceObservationRepository(s).latest_for_offer(off_id)
        assert latest is not None and latest.price_huf == 4_990
        assert PriceObservationRepository(s).count_for_offer(off_id) == 2
        assert SourceRepository(s).get_by_key("manual") is not None


def test_settings_changes_are_audited(db: Database) -> None:
    with db.write_session() as s:
        SettingsRepository(s).set_value("ui.language", "en", Actor.USER)
        SettingsRepository(s).set_value("ui.language", "hu", Actor.USER)
    with db.read_session() as s:
        assert SettingsRepository(s).get_value("ui.language") == "hu"
        assert SettingsRepository(s).get_value("missing", 42) == 42
        entries = s.query(AuditLog).order_by(AuditLog.id).all()
        assert [(e.action, e.before, e.after) for e in entries] == [
            ("create", None, "en"),
            ("update", "en", "hu"),
        ]


def test_read_session_refuses_writes(db: Database) -> None:
    with pytest.raises(PermissionError), db.read_session() as s:
        s.add(Platform(key="x", name="x", kind="OTHER"))
        s.flush()


def test_write_session_rolls_back_on_error(db: Database) -> None:
    with pytest.raises(RuntimeError), db.write_session() as s:
        f.source(s, "rollback")
        raise RuntimeError("boom")
    with db.read_session() as s:
        assert SourceRepository(s).get_by_key("rollback") is None


def test_list_limit_validated(db: Database) -> None:
    with db.read_session() as s, pytest.raises(ValueError):
        SourceRepository(s).list(limit=0)


def test_system_overview_empty_db(db: Database) -> None:
    overview = system_overview(db)
    assert [c.info.key for c in overview.categories] == list(Category)
    assert all(c.products == 0 for c in overview.categories)
    assert overview.sources == 0
