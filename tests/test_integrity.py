"""Database constraints and mutability guards from DATABASE_DESIGN.md."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError, StatementError

from dealradar.core.clock import utcnow
from dealradar.core.enums import Actor, Category, IdType, MatchStatus, SourceStatus
from dealradar.core.errors import ImmutableRowError
from dealradar.db.models import AuditLog, Listing, PriceObservation, Product, VariantIdentifier
from dealradar.db.repositories import AuditLogRepository
from dealradar.db.session import Database
from tests import factories as f


def test_source_cannot_be_active_without_access_review(db: Database) -> None:
    with pytest.raises(IntegrityError), db.write_session() as s:
        src = f.source(s)
        src.status = SourceStatus.ACTIVE


def test_access_review_requires_tos_review(db: Database) -> None:
    with pytest.raises(IntegrityError), db.write_session() as s:
        src = f.source(s)
        src.access_review_ok = True  # tos_reviewed_at missing


def test_source_active_after_complete_review(db: Database) -> None:
    with db.write_session() as s:
        src = f.source(s)
        src.tos_reviewed_at = utcnow()
        src.tos_note = "manual entry only"
        src.access_review_ok = True
        src.status = SourceStatus.ACTIVE


def test_global_identifier_unique_across_variants(db: Database) -> None:
    with pytest.raises(IntegrityError), db.write_session() as s:
        _, v1 = f.product(s)
        _, v2 = f.product(s)
        s.add(VariantIdentifier(variant_id=v1.id, id_type=IdType.GTIN, value="5901234123457"))
        s.add(VariantIdentifier(variant_id=v2.id, id_type=IdType.GTIN, value="5901234123457"))
        s.flush()


def test_shop_sku_unique_per_source_only(db: Database) -> None:
    with db.write_session() as s:
        a, b = f.source(s, "a"), f.source(s, "b")
        _, v = f.product(s)
        s.add(
            VariantIdentifier(variant_id=v.id, id_type=IdType.SHOP_SKU, value="X1", source_id=a.id)
        )
        s.add(
            VariantIdentifier(variant_id=v.id, id_type=IdType.SHOP_SKU, value="X1", source_id=b.id)
        )
    with pytest.raises(IntegrityError), db.write_session() as s:
        s.add(
            VariantIdentifier(variant_id=v.id, id_type=IdType.SHOP_SKU, value="X1", source_id=a.id)
        )


def test_shop_sku_needs_source_and_gtin_must_not_have_one(db: Database) -> None:
    with pytest.raises(IntegrityError), db.write_session() as s:
        _, v = f.product(s)
        s.add(VariantIdentifier(variant_id=v.id, id_type=IdType.SHOP_SKU, value="X1"))
    with pytest.raises(IntegrityError), db.write_session() as s:
        src = f.source(s, "c")
        _, v = f.product(s)
        s.add(VariantIdentifier(variant_id=v.id, id_type=IdType.GTIN, value="1", source_id=src.id))


def test_listing_matched_iff_product(db: Database) -> None:
    with pytest.raises(IntegrityError), db.write_session() as s:
        src = f.source(s)
        listing = f.offer(s, src).listing
        listing.match_status = MatchStatus.MATCHED  # without product_id
    with db.write_session() as s:
        src = f.source(s, "ok")
        prod, _ = f.product(s)
        listing = f.offer(s, src).listing
        listing.product_id = prod.id
        listing.match_status = MatchStatus.MATCHED


def test_unchanged_prices_are_still_stored(db: Database) -> None:
    with db.write_session() as s:
        off = f.offer(s, f.source(s))
        for hours in (3, 2, 1):
            f.observe(s, off, 10_000, hours_ago=hours)
        offer_id = off.id
    with db.read_session() as s:
        assert s.query(PriceObservation).filter_by(offer_id=offer_id).count() == 3


def test_one_observation_per_offer_and_instant(db: Database) -> None:
    from sqlalchemy.exc import IntegrityError as IE

    with pytest.raises(IE), db.write_session() as s:
        off = f.offer(s, f.source(s))
        first = f.observe(s, off)
        s.add(
            PriceObservation(
                **{
                    c.key: getattr(first, c.key)
                    for c in PriceObservation.__table__.columns
                    if c.key != "id"
                }
            )
        )
        s.flush()


def test_observation_price_cannot_change(db: Database) -> None:
    with pytest.raises(ImmutableRowError), db.write_session() as s:
        obs = f.observe(s, f.offer(s, f.source(s)))
        obs.price_huf = 1


def test_observations_cannot_be_deleted(db: Database) -> None:
    with pytest.raises(ImmutableRowError), db.write_session() as s:
        s.delete(f.observe(s, f.offer(s, f.source(s))))


def test_negative_price_rejected(db: Database) -> None:
    with pytest.raises(IntegrityError), db.write_session() as s:
        f.observe(s, f.offer(s, f.source(s)), price=-1)


def test_missing_price_only_when_not_buyable(db: Database) -> None:
    from dealradar.core.enums import Availability

    with db.write_session() as s:
        f.observe(
            s, f.offer(s, f.source(s), "manual:2"), None, availability=Availability.OUT_OF_STOCK
        )
    with pytest.raises(IntegrityError), db.write_session() as s:
        f.observe(
            s, f.offer(s, f.source(s, "b"), "manual:3"), None, availability=Availability.IN_STOCK
        )


def test_audit_log_immutable(db: Database) -> None:
    with db.write_session() as s:
        row = AuditLogRepository(s).record(actor=Actor.USER, entity="x", entity_id="1", action="a")
        row_id = row.id
    with pytest.raises(ImmutableRowError), db.write_session() as s:
        entry = s.get(AuditLog, row_id)
        assert entry is not None
        entry.action = "changed"


def test_naive_datetime_rejected(db: Database) -> None:
    with pytest.raises(StatementError), db.write_session() as s:
        listing = f.offer(s, f.source(s)).listing
        listing.last_seen_at = datetime(2030, 1, 1)


def test_datetimes_round_trip_as_utc(db: Database) -> None:
    with db.write_session() as s:
        listing_id = f.offer(s, f.source(s)).listing.id
    with db.read_session() as s:
        listing = s.get(Listing, listing_id)
        assert listing is not None
        assert listing.first_seen_at.utcoffset() == timedelta(0)


def test_invalid_enum_value_rejected(db: Database) -> None:
    with pytest.raises(StatementError), db.write_session() as s:
        s.add(Product(category="CARS", title="x", created_by="USER"))
        s.flush()


def test_foreign_keys_enforced(db: Database) -> None:
    with pytest.raises(IntegrityError), db.write_session() as s:
        s.add(Product(category=Category.TECH, title="x", created_by="USER", merged_into_id=999))
        s.flush()
