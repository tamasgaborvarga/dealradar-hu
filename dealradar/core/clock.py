"""Single source of 'now' (always timezone-aware UTC)."""

from datetime import UTC, datetime


def utcnow() -> datetime:
    return datetime.now(tz=UTC)
