"""Engine creation (SQLite PRAGMAs) and read/write session scopes."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from dealradar.core.config import Settings
from dealradar.db.lock import WriterLock

_READONLY = "dealradar_readonly"


def create_db_engine(url: str) -> Engine:
    engine = create_engine(url)

    @event.listens_for(engine, "connect")
    def _set_pragmas(dbapi_connection: Any, _record: Any) -> None:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA busy_timeout=5000")
        finally:
            cursor.close()

    return engine


@event.listens_for(Session, "before_flush")
def _block_readonly_writes(session: Session, _ctx: Any, _instances: Any) -> None:
    if session.info.get(_READONLY) and (session.new or session.dirty or session.deleted):
        raise PermissionError(
            "write attempted in a read-only session; use Database.write_session()"
        )


class Database:
    """Owns the engine. Reads use ``read_session``; every write goes through ``write_session``."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.engine = create_db_engine(settings.db_url)
        self._sessions = sessionmaker(self.engine, expire_on_commit=False)

    @contextmanager
    def read_session(self) -> Iterator[Session]:
        session = self._sessions()
        session.info[_READONLY] = True
        try:
            yield session
        finally:
            session.rollback()
            session.close()

    @contextmanager
    def write_session(self) -> Iterator[Session]:
        with WriterLock(self.settings.lock_path, self.settings.lock_timeout_s):
            session = self._sessions()
            try:
                yield session
                session.commit()
            except BaseException:
                session.rollback()
                raise
            finally:
                session.close()

    def dispose(self) -> None:
        self.engine.dispose()
