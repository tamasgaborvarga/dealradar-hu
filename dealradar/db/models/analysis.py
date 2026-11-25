"""Manual Claude analyses (DATABASE_DESIGN.md §10). Advisory records only - nothing here can
change prices, matches, benchmarks or evaluations."""

from __future__ import annotations

from datetime import datetime
from typing import Any, ClassVar

from sqlalchemy import JSON, Boolean, CheckConstraint, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from dealradar.core.clock import utcnow
from dealradar.core.enums import AnalysisStatus
from dealradar.db.base import Base, Mutability, UTCDateTime, enum_type


class AiRequest(Base):
    """A prepared analysis package and its prompt. IMMUTABLE except the status."""

    __tablename__ = "ai_requests"
    __mutability__: ClassVar[Mutability] = Mutability.IMMUTABLE
    __mutable_columns__: ClassVar[frozenset[str]] = frozenset({"status"})
    __table_args__ = (
        Index("ix_ai_requests_offer_created", "offer_id", "created_at"),
        CheckConstraint("expires_at > created_at", "expiry_after_creation"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[str] = mapped_column(String(64), unique=True)  # shown in the prompt
    offer_id: Mapped[int] = mapped_column(ForeignKey("offers.id"))
    schema_version: Mapped[str] = mapped_column(String(40))
    mode: Mapped[str] = mapped_column(String(16), default="CLIPBOARD")
    package_json: Mapped[dict[str, Any]] = mapped_column(JSON)  # what Claude was told
    prompt_text: Mapped[str] = mapped_column(Text)
    prompt_sha256: Mapped[str] = mapped_column(String(64))
    status: Mapped[AnalysisStatus] = mapped_column(
        enum_type(AnalysisStatus, "status"), default=AnalysisStatus.PREPARED
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)


class AiResponse(Base):
    """Every pasted answer, valid or not, with its timestamp. IMMUTABLE."""

    __tablename__ = "ai_responses"
    __mutability__: ClassVar[Mutability] = Mutability.IMMUTABLE
    __table_args__ = (
        Index("ix_ai_responses_request_received", "ai_request_id", "received_at"),
        CheckConstraint(
            "(valid = 1 AND parsed_json IS NOT NULL) OR (valid = 0 AND parsed_json IS NULL)",
            "parsed_iff_valid",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    ai_request_id: Mapped[int] = mapped_column(ForeignKey("ai_requests.id"))
    received_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    raw_text: Mapped[str] = mapped_column(Text)  # capped at 64 KB before storing
    valid: Mapped[bool] = mapped_column(Boolean)
    errors: Mapped[list[str] | None] = mapped_column(JSON(none_as_null=True))
    parsed_json: Mapped[dict[str, Any] | None] = mapped_column(JSON(none_as_null=True))
