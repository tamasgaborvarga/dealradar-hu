"""Settings and audit log (DATABASE_DESIGN.md §12)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, ClassVar

from sqlalchemy import JSON, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from dealradar.core.clock import utcnow
from dealradar.core.enums import Actor
from dealradar.db.base import Base, Mutability, UTCDateTime, enum_type


class Setting(Base):
    """Key/value user settings. STATE; every user change is audited by the repository."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class AuditLog(Base):
    """Who changed what. IMMUTABLE."""

    __tablename__ = "audit_log"
    __mutability__: ClassVar[Mutability] = Mutability.IMMUTABLE

    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    actor: Mapped[Actor] = mapped_column(enum_type(Actor, "actor"))
    entity: Mapped[str] = mapped_column(String(64))
    entity_id: Mapped[str] = mapped_column(String(128))
    action: Mapped[str] = mapped_column(String(32))
    before: Mapped[Any | None] = mapped_column(JSON)
    after: Mapped[Any | None] = mapped_column(JSON)
    schema_version: Mapped[int] = mapped_column(Integer, default=1)
