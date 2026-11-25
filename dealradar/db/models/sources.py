"""Platforms, sources, collection runs and raw records (DATABASE_DESIGN.md §4)."""

from __future__ import annotations

from datetime import datetime
from typing import ClassVar

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from dealradar.core.clock import utcnow
from dealradar.core.enums import (
    AccessMethod,
    Actor,
    FetchErrorKind,
    PlatformKind,
    RefreshScope,
    RunStatus,
    SourceStatus,
)
from dealradar.core.errors import ImmutableRowError
from dealradar.db.base import Base, Mutability, UTCDateTime, enum_type


class Platform(Base):
    """A website/company that can be a data source and/or a sell channel. STATE."""

    __tablename__ = "platforms"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[PlatformKind] = mapped_column(enum_type(PlatformKind, "kind"))
    url: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    sources: Mapped[list[Source]] = relationship(back_populates="platform")


class Source(Base):
    """A way of obtaining data from a platform, with its access review. STATE."""

    __tablename__ = "sources"
    __table_args__ = (
        CheckConstraint("status != 'ACTIVE' OR access_review_ok = 1", name="active_needs_review"),
        CheckConstraint(
            "access_review_ok = 0 OR (tos_reviewed_at IS NOT NULL AND "
            "(access_method = 'MANUAL' OR robots_checked_at IS NOT NULL))",
            name="review_complete",
        ),
        CheckConstraint("min_interval_s >= 1", name="min_interval_positive"),
        CheckConstraint("raw_retention_days >= 0", name="retention_non_negative"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(64), unique=True)
    platform_id: Mapped[int] = mapped_column(ForeignKey("platforms.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    access_method: Mapped[AccessMethod] = mapped_column(enum_type(AccessMethod, "access_method"))
    robots_checked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    robots_allows: Mapped[bool | None] = mapped_column(Boolean)
    tos_reviewed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    tos_note: Mapped[str | None] = mapped_column(Text)
    access_review_ok: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[SourceStatus] = mapped_column(
        enum_type(SourceStatus, "status"), default=SourceStatus.DISABLED
    )
    min_interval_s: Mapped[int] = mapped_column(Integer, default=5)
    daily_request_cap: Mapped[int | None] = mapped_column(Integer)
    provides_completed_sales: Mapped[bool] = mapped_column(Boolean, default=False)
    raw_retention_days: Mapped[int] = mapped_column(Integer, default=30)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)

    platform: Mapped[Platform] = relationship(back_populates="sources")


class SourceRun(Base):
    """One collection run. Mutable while RUNNING, IMMUTABLE once finished."""

    __tablename__ = "source_runs"
    __mutability__: ClassVar[Mutability] = Mutability.IMMUTABLE
    __table_args__ = (
        CheckConstraint(
            "requests >= 0 AND fetched >= 0 AND parsed >= 0 AND failed >= 0", name="counts"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), index=True)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    status: Mapped[RunStatus] = mapped_column(
        enum_type(RunStatus, "status"), default=RunStatus.RUNNING
    )
    requests: Mapped[int] = mapped_column(Integer, default=0)
    fetched: Mapped[int] = mapped_column(Integer, default=0)
    parsed: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    error_summary: Mapped[str | None] = mapped_column(Text)
    refresh_job_id: Mapped[int | None] = mapped_column(ForeignKey("refresh_jobs.id"))
    new_observations: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    duplicates: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    retries: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    cache_hits: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    error_kind: Mapped[FetchErrorKind | None] = mapped_column(
        enum_type(FetchErrorKind, "error_kind")
    )

    def _validate_update(self, changed: set[str]) -> None:
        from sqlalchemy import inspect

        previous = inspect(self).committed_state.get("status", self.status)
        if previous != RunStatus.RUNNING:
            raise ImmutableRowError("finished source runs are immutable")


class RawRecord(Base):
    """A fetched payload. IMMUTABLE except parse status and file pruning."""

    __tablename__ = "raw_records"
    __mutability__: ClassVar[Mutability] = Mutability.IMMUTABLE
    __mutable_columns__: ClassVar[frozenset[str]] = frozenset({"parse_status", "storage_path"})

    id: Mapped[int] = mapped_column(primary_key=True)
    source_run_id: Mapped[int] = mapped_column(ForeignKey("source_runs.id"), index=True)
    external_ref: Mapped[str | None] = mapped_column(String(512))
    url: Mapped[str | None] = mapped_column(Text)
    fetched_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    storage_path: Mapped[str | None] = mapped_column(Text)
    http_status: Mapped[int | None] = mapped_column(Integer)
    parse_status: Mapped[str] = mapped_column(String(16), default="PENDING")


class RefreshJob(Base):
    """One user-started refresh (one source, one category or all). Mutable while RUNNING."""

    __tablename__ = "refresh_jobs"
    __mutability__: ClassVar[Mutability] = Mutability.IMMUTABLE

    id: Mapped[int] = mapped_column(primary_key=True)
    scope: Mapped[RefreshScope] = mapped_column(enum_type(RefreshScope, "scope"))
    target: Mapped[str | None] = mapped_column(String(64))
    requested_by: Mapped[Actor] = mapped_column(enum_type(Actor, "requested_by"))
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    status: Mapped[RunStatus] = mapped_column(
        enum_type(RunStatus, "status"), default=RunStatus.RUNNING
    )

    def _validate_update(self, changed: set[str]) -> None:
        from sqlalchemy import inspect

        previous = inspect(self).committed_state.get("status", self.status)
        if previous != RunStatus.RUNNING:
            raise ImmutableRowError("finished refresh jobs are immutable")


class SourceRunError(Base):
    """One recorded problem in a source run (record-level or run-level). IMMUTABLE."""

    __tablename__ = "source_run_errors"
    __mutability__: ClassVar[Mutability] = Mutability.IMMUTABLE

    id: Mapped[int] = mapped_column(primary_key=True)
    source_run_id: Mapped[int] = mapped_column(ForeignKey("source_runs.id"), index=True)
    at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    kind: Mapped[FetchErrorKind] = mapped_column(enum_type(FetchErrorKind, "kind"))
    external_ref: Mapped[str | None] = mapped_column(String(512))
    message: Mapped[str] = mapped_column(String(500))
