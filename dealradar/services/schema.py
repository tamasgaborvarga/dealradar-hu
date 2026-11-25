"""Schema status and explicit upgrades (ADR-004). The app never upgrades on its own."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine

import dealradar.migrations as migrations_pkg
from dealradar.core.config import Settings
from dealradar.db.lock import WriterLock
from dealradar.services.backup import backup_database

log = logging.getLogger(__name__)


class SchemaState(StrEnum):
    NOT_INITIALISED = "NOT_INITIALISED"
    OUT_OF_DATE = "OUT_OF_DATE"
    UP_TO_DATE = "UP_TO_DATE"
    UNKNOWN_REVISION = "UNKNOWN_REVISION"  # DB is newer than this code


@dataclass(frozen=True)
class SchemaStatus:
    state: SchemaState
    current: str | None
    head: str | None

    @property
    def ready(self) -> bool:
        return self.state is SchemaState.UP_TO_DATE


def alembic_config(db_url: str) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(Path(migrations_pkg.__file__).parent))
    # Alembic's config is a ConfigParser: '%' must be doubled. Non-ASCII paths (e.g. an accented
    # user folder) become %-encoded in rendered URLs, so this is required on such machines.
    cfg.set_main_option("sqlalchemy.url", db_url.replace("%", "%%"))
    return cfg


def head_revision(db_url: str) -> str | None:
    return ScriptDirectory.from_config(alembic_config(db_url)).get_current_head()


def schema_status(engine: Engine) -> SchemaStatus:
    url = engine.url.render_as_string(hide_password=False)
    script = ScriptDirectory.from_config(alembic_config(url))
    head = script.get_current_head()
    with engine.connect() as conn:
        current = MigrationContext.configure(conn).get_current_revision()
    if current is None:
        state = SchemaState.NOT_INITIALISED
    elif current == head:
        state = SchemaState.UP_TO_DATE
    else:
        try:
            known = script.get_revision(current) is not None
        except Exception:  # alembic raises ResolutionError subclasses for unknown ids
            known = False
        state = SchemaState.OUT_OF_DATE if known else SchemaState.UNKNOWN_REVISION
    return SchemaStatus(state=state, current=current, head=head)


def upgrade_database(settings: Settings) -> Path | None:
    """Back up (if a DB exists) and upgrade to head while holding the writer lock.

    Returns the backup path (None for a brand-new database).
    """
    settings.ensure_dirs()
    with WriterLock(settings.lock_path, settings.lock_timeout_s):
        backup = backup_database(settings, label="pre-migration")
        command.upgrade(alembic_config(settings.db_url), "head")
    log.info("database upgraded to head", extra={"backup": str(backup) if backup else None})
    return backup
