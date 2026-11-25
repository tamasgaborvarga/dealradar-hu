"""Read model for the source registry page."""

from __future__ import annotations

from dataclasses import dataclass

from dealradar.db.repositories import SourceRepository
from dealradar.db.session import Database


@dataclass(frozen=True)
class SourceRow:
    key: str
    name: str
    platform: str
    access_method: str
    status: str
    access_review_ok: bool


def list_sources(db: Database) -> list[SourceRow]:
    with db.read_session() as s:
        return [
            SourceRow(
                key=src.key,
                name=src.name,
                platform=plat.name,
                access_method=src.access_method.value,
                status=src.status.value,
                access_review_ok=src.access_review_ok,
            )
            for src, plat in SourceRepository(s).list_with_platform()
        ]


# --- registration (demo opt-in) and re-activation ---

DEMO_SETTING = "demo.mock_sources_allowed"


def mock_sources_present(db: Database) -> bool:
    from sqlalchemy import select

    from dealradar.core.enums import AccessMethod
    from dealradar.db.models import Source

    with db.read_session() as s:
        return (
            s.scalar(select(Source.id).where(Source.access_method == AccessMethod.MOCK)) is not None
        )


def register_mock_sources(db: Database) -> list[str]:
    """Explicit demo opt-in: allow synthetic MOCK sources in THIS database and register them.
    Synthetic prices then live next to any real data - use a separate DEALRADAR_DATA_DIR."""
    from sqlalchemy import select

    from dealradar.core.clock import utcnow
    from dealradar.core.enums import AccessMethod, Actor, PlatformKind, SourceStatus
    from dealradar.db.models import Platform, Source
    from dealradar.db.repositories import SettingsRepository
    from dealradar.sources.registry import ADAPTERS

    now = utcnow()
    created = []
    with db.write_session() as s:
        SettingsRepository(s).set_value(DEMO_SETTING, True, Actor.USER)
        for adapter in ADAPTERS.values():
            if adapter.access_method is not AccessMethod.MOCK:
                continue
            if s.scalar(select(Source.id).where(Source.key == adapter.key)) is not None:
                continue
            platform = Platform(
                key=f"platform-{adapter.key}", name=adapter.name, kind=PlatformKind.OTHER, url=None
            )
            s.add(
                Source(
                    key=adapter.key,
                    name=adapter.name,
                    platform=platform,
                    access_method=AccessMethod.MOCK,
                    robots_checked_at=now,
                    robots_allows=True,
                    tos_reviewed_at=now,
                    tos_note=adapter.terms_note,
                    access_review_ok=True,
                    status=SourceStatus.ACTIVE,
                    min_interval_s=1,
                    daily_request_cap=500,
                )
            )
            created.append(adapter.key)
    return created


def reactivate_source(db: Database, key: str, review_note: str) -> None:
    """After a BLOCKED/DISABLED state the user must re-review access before running it again."""
    from sqlalchemy import select

    from dealradar.core.clock import utcnow
    from dealradar.core.enums import Actor, SourceStatus
    from dealradar.db.models import Source
    from dealradar.db.repositories import AuditLogRepository

    if len(review_note.strip()) < 10:
        raise ValueError(
            "írd le legalább 10 karakterben, mit ellenőriztél újra (feltételek, robots.txt)"
        )
    with db.write_session() as s:
        src = s.scalar(select(Source).where(Source.key == key))
        if src is None:
            raise ValueError(f"nincs ilyen forrás: {key}")
        before = src.status.value
        src.status = SourceStatus.ACTIVE
        src.tos_reviewed_at = utcnow()
        src.tos_note = review_note.strip()[:2000]
        src.access_review_ok = True
        AuditLogRepository(s).record(
            actor=Actor.USER,
            entity="sources",
            entity_id=key,
            action="reactivated",
            before=before,
            after="ACTIVE",
        )
