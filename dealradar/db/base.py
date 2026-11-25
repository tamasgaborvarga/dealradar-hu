"""Declarative base, column helpers and mutability guards (DATABASE_DESIGN.md §1)."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, ClassVar

from sqlalchemy import DateTime, Enum, MetaData, event, inspect
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import DeclarativeBase, Mapper
from sqlalchemy.types import TypeDecorator

from dealradar.core.errors import ImmutableRowError

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Mutability(StrEnum):
    STATE = "STATE"  # mutable current state
    IMMUTABLE = "IMMUTABLE"  # insert only (listed columns excepted)
    LEDGER = "LEDGER"  # insert only, corrections are reversal rows
    SPAN = "SPAN"  # insert only, except closing/confirming the open span


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)

    __mutability__: ClassVar[Mutability] = Mutability.STATE
    __mutable_columns__: ClassVar[frozenset[str]] = frozenset()

    def _validate_update(self, changed: set[str]) -> None:
        """Raise if this update is not allowed by the table's mutability class."""
        if self.__mutability__ is Mutability.STATE:
            return
        forbidden = changed - self.__mutable_columns__
        if forbidden:
            raise ImmutableRowError(
                f"{type(self).__name__} is {self.__mutability__}: "
                f"columns {sorted(forbidden)} may not be updated"
            )


@event.listens_for(Base, "before_update", propagate=True)
def _guard_update(_mapper: Mapper[Any], _connection: Any, target: Base) -> None:
    state = inspect(target)
    changed = {attr.key for attr in state.attrs if attr.history.has_changes()}
    if changed:
        target._validate_update(changed)


@event.listens_for(Base, "before_delete", propagate=True)
def _guard_delete(_mapper: Mapper[Any], _connection: Any, target: Base) -> None:
    if target.__mutability__ is not Mutability.STATE:
        raise ImmutableRowError(f"{type(target).__name__} rows may not be deleted")


class UTCDateTime(TypeDecorator[datetime]):
    """Stores timezone-aware datetimes as UTC; returns aware UTC datetimes. Rejects naive input."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetime not allowed; use dealradar.core.clock.utcnow()")
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=UTC)


def enum_type(enum_cls: type[StrEnum], name: str) -> Enum:
    """TEXT column + CHECK constraint holding the enum's values (no native enum in SQLite)."""
    return Enum(
        enum_cls,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=32,
        validate_strings=True,
        values_callable=lambda members: [m.value for m in members],
    )
