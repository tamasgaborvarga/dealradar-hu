"""Manual refresh workflow on the database (mock sources only, no network)."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import func, select

from dealradar.core.clock import utcnow
from dealradar.core.enums import (
    AccessMethod,
    Category,
    FetchErrorKind,
    MatchStatus,
    RefreshScope,
    RunStatus,
    SourceStatus,
)
from dealradar.db.models import (
    Listing,
    Notification,
    PersonalEvaluation,
    PriceObservation,
    RefreshJob,
    Source,
    SourceRun,
    SourceRunError,
)
from dealradar.db.session import Database
from dealradar.services import refresh as refresh_mod
from dealradar.services import sources
from dealradar.services.catalog import restore_listing
from dealradar.services.refresh import RefreshEvent, freshness, refresh
from dealradar.sources.mock.transport import MockTransport
from dealradar.sources.requester import TransportResponse

NOW = utcnow() - timedelta(hours=1)


def _count(db: Database, model: type) -> int:
    with db.read_session() as s:
        return int(s.scalar(select(func.count()).select_from(model)) or 0)


def test_mock_sources_need_the_demo_opt_in(db: Database) -> None:
    sources.register_mock_sources(db)
    with db.write_session() as s:  # simulate a database where the opt-in was never given
        from dealradar.db.models import Setting

        s.delete(s.get(Setting, refresh_mod.DEMO_SETTING))
    report = refresh(db, RefreshScope.ALL, now=NOW)
    assert report.status is RunStatus.FAILED
    assert all(x.error_kind is FetchErrorKind.ACCESS_NOT_PERMITTED for x in report.sources)
    assert _count(db, PriceObservation) == 0


def test_refresh_all_records_everything(db: Database) -> None:
    assert sources.register_mock_sources(db) == ["mock_shop", "mock_shop_2", "mock_market"]
    events: list[RefreshEvent] = []
    report = refresh(db, RefreshScope.ALL, now=NOW, progress=events.append)
    assert report.status is RunStatus.OK
    assert {x.source_key for x in report.sources} == {"mock_shop", "mock_shop_2", "mock_market"}
    shop = next(x for x in report.sources if x.source_key == "mock_shop")
    assert shop.new_observations == 8 and shop.failed == 1  # the 'Ar: hivjon' item is unusable
    with db.read_session() as s:
        err = s.scalar(
            select(SourceRunError).where(SourceRunError.kind == FetchErrorKind.INVALID_RECORD)
        )
        assert err is not None and "ár" in err.message
        job = s.get(RefreshJob, report.job_id)
        assert job is not None and job.status is RunStatus.OK and job.finished_at is not None
        runs = s.scalars(select(SourceRun)).all()
        assert all(r.started_at and r.finished_at for r in runs)
        listing = s.scalar(select(Listing).where(Listing.external_id == "mock_shop:T-001"))
        assert listing is not None and listing.match_status is MatchStatus.MATCHED
        assert restore_listing(listing.normalized).variant_key == "1000GB"  # type: ignore[arg-type]
    assert _count(db, PersonalEvaluation) > 0
    kinds = [e.kind for e in events]
    assert kinds[0] == "JOB_STARTED" and kinds[-1] == "JOB_FINISHED"
    assert kinds.count("SOURCE_FINISHED") == 3


def test_refresh_one_category_and_one_source(db: Database) -> None:
    sources.register_mock_sources(db)
    food = refresh(db, RefreshScope.CATEGORY, "FOOD", now=NOW)
    assert {x.source_key for x in food.sources} == {
        "mock_shop",
        "mock_shop_2",
    }  # market has no food
    with db.read_session() as s:
        hints = set(s.scalars(select(Listing.category_hint)).all())
    assert hints == {Category.FOOD}
    one = refresh(db, RefreshScope.SOURCE, "mock_market", now=NOW)
    assert [x.source_key for x in one.sources] == ["mock_market"]
    with pytest.raises(ValueError):
        refresh(db, RefreshScope.CATEGORY, "CARS")
    with pytest.raises(ValueError):
        refresh(db, RefreshScope.SOURCE, "nope")


def test_duplicates_are_prevented_and_unchanged_prices_still_recorded(db: Database) -> None:
    sources.register_mock_sources(db)
    refresh(db, RefreshScope.SOURCE, "mock_shop", now=NOW, evaluate=False)
    first = _count(db, PriceObservation)
    again = refresh(
        db, RefreshScope.SOURCE, "mock_shop", now=NOW + timedelta(minutes=5), evaluate=False
    )
    assert again.sources[0].cache_hits > 0 and again.sources[0].duplicates == 8
    assert _count(db, PriceObservation) == first  # same fetch, not a new observation
    later = refresh(
        db, RefreshScope.SOURCE, "mock_shop", now=NOW + timedelta(minutes=50), evaluate=False
    )
    assert later.sources[0].new_observations == 0  # still within the cache TTL
    with db.read_session() as s:
        assert s.scalar(select(func.count()).select_from(PriceObservation)) == first


def test_blocked_source_stops_and_is_disabled(
    db: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    sources.register_mock_sources(db)

    def blocked_transport(adapter: object, clock: object) -> MockTransport:
        t = MockTransport()
        t.fail("api/offers", TransportResponse(403, {}, b""))
        return t

    monkeypatch.setattr(refresh_mod, "transport_for", blocked_transport)
    report = refresh(db, RefreshScope.SOURCE, "mock_shop", now=NOW)
    assert report.sources[0].status is RunStatus.BLOCKED
    with db.read_session() as s:
        src = s.scalar(select(Source).where(Source.key == "mock_shop"))
        assert src is not None and src.status is SourceStatus.BLOCKED
        assert (
            s.scalar(select(Notification).where(Notification.kind == "SOURCE_PROBLEM")) is not None
        )
    monkeypatch.undo()
    skipped = refresh(db, RefreshScope.SOURCE, "mock_shop", now=NOW)
    assert skipped.sources[0].error_kind is FetchErrorKind.ACCESS_NOT_PERMITTED
    with pytest.raises(ValueError):
        sources.reactivate_source(db, "mock_shop", "ok")
    sources.reactivate_source(db, "mock_shop", "re-checked: synthetic data, no restrictions")
    assert refresh(db, RefreshScope.SOURCE, "mock_shop", now=NOW).sources[0].status is RunStatus.OK


def test_rate_limit_and_adapter_crash_are_recorded(
    db: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    sources.register_mock_sources(db)

    def limited(adapter: object, clock: object) -> MockTransport:
        t = MockTransport()
        t.fail("category=TECH", TransportResponse(429, {"Retry-After": "7200"}, b""))
        return t

    monkeypatch.setattr(refresh_mod, "transport_for", limited)
    report = refresh(db, RefreshScope.SOURCE, "mock_shop_2", now=NOW)
    assert report.sources[0].error_kind is FetchErrorKind.RATE_LIMITED
    assert report.sources[0].status in (RunStatus.PARTIAL, RunStatus.FAILED)

    def broken_fetch(self: object, ctx: object, categories: object) -> object:
        raise RuntimeError("adapter bug")

    from dealradar.sources.mock.adapters import MockAdapter

    monkeypatch.undo()
    monkeypatch.setattr(MockAdapter, "fetch", broken_fetch)
    crash = refresh(db, RefreshScope.ALL, now=NOW)
    assert all(
        x.status is RunStatus.FAILED for x in crash.sources
    )  # each failed, none crashed the job
    assert all(x.error_kind is FetchErrorKind.INTERNAL for x in crash.sources)


def test_access_method_must_match_the_review(db: Database) -> None:
    sources.register_mock_sources(db)
    with db.write_session() as s:
        src = s.scalar(select(Source).where(Source.key == "mock_market"))
        assert src is not None
        src.access_method = AccessMethod.PUBLIC_HTML
    report = refresh(db, RefreshScope.SOURCE, "mock_market", now=NOW)
    assert report.sources[0].error_kind is FetchErrorKind.ACCESS_NOT_PERMITTED
    assert "(MOCK)" in report.sources[0].message


def test_staleness(db: Database) -> None:
    sources.register_mock_sources(db)
    assert all(f.stale for f in freshness(db))  # never refreshed
    refresh(db, RefreshScope.ALL, now=NOW, evaluate=False)
    assert not any(f.stale for f in freshness(db, now=NOW + timedelta(hours=1)))
    later = {f.source_key: f.stale for f in freshness(db, now=NOW + timedelta(hours=30))}
    assert later["mock_shop"]  # serves FOOD: 24 h freshness window
    assert not later["mock_market"]  # TECH/HOME only: 48 h window


def test_unreachable_telegram_never_breaks_a_refresh(
    monkeypatch: pytest.MonkeyPatch, settings: object
) -> None:
    """QA: Telegram configured but unreachable (the suite blocks the network): the refresh still
    succeeds, every notification stays in the inbox, marked FAILED, without the token."""
    from dealradar.core.config import get_settings, reset_settings_cache
    from dealradar.core.enums import TelegramStatus
    from dealradar.services import notify
    from dealradar.services.schema import upgrade_database

    monkeypatch.setenv("DEALRADAR_TELEGRAM_BOT_TOKEN", "999:fake-token")
    monkeypatch.setenv("DEALRADAR_TELEGRAM_CHAT_ID", "1")
    reset_settings_cache()
    cfg = get_settings()
    upgrade_database(cfg)
    db = Database(cfg)
    try:
        sources.register_mock_sources(db)

        def blocked(adapter: object, clock: object) -> MockTransport:
            t = MockTransport()
            t.fail("api/offers", TransportResponse(403, {}, b""))
            return t

        monkeypatch.setattr(refresh_mod, "transport_for", blocked)
        report = refresh(db, RefreshScope.ALL, now=NOW)  # returns normally, no exception
        assert {x.status for x in report.sources} == {RunStatus.BLOCKED}
        items = notify.inbox(db)
        assert len(items) == 3  # one per blocked source, all kept in the app
        assert items and all(i.telegram_status is TelegramStatus.FAILED for i in items)
        with db.read_session() as s:
            errors = s.scalars(select(Notification.telegram_error)).all()
        assert all(e and "fake-token" not in e for e in errors)
    finally:
        db.dispose()
