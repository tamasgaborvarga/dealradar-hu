"""Consistent SQLite backups via the online backup API."""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from dealradar.core.clock import utcnow
from dealradar.core.config import Settings

log = logging.getLogger(__name__)


def has_tables(db_path: Path) -> bool:
    """True if the file is a SQLite database with at least one table.

    Opening a connection (e.g. ``dealradar db status``) creates an empty file, so mere
    existence of the file does not mean there is anything worth backing up.
    """
    if not db_path.exists():
        return False
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute("SELECT count(*) FROM sqlite_master WHERE type = 'table'").fetchone()
    finally:
        conn.close()
    return bool(row and row[0])


def backup_database(settings: Settings, label: str = "manual") -> Path | None:
    """Copy the database to ``<data_dir>/backups``. Returns None if there is nothing to back up.

    Caller is responsible for holding the writer lock if writes must be excluded.
    """
    try:
        if not has_tables(settings.db_path):
            return None
    except sqlite3.DatabaseError as exc:
        raise RuntimeError(
            f"a mentés nem ment át az integritás-ellenőrzésen ({exc}); az adatbázis sérült lehet, "
            "állíts vissza egy korábbi mentést"
        ) from exc
    settings.backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = utcnow().strftime("%Y%m%d-%H%M%S")
    target = settings.backup_dir / f"dealradar-{stamp}-{label}.db"
    src = sqlite3.connect(settings.db_path)
    dst = sqlite3.connect(target)
    try:
        src.backup(dst)
        check = dst.execute("PRAGMA quick_check").fetchone()
    except sqlite3.DatabaseError as exc:
        check = (f"error: {exc}",)
    finally:
        dst.close()
        src.close()
    if not check or check[0] != "ok":
        # A copy of a damaged database is not a backup (QA finding): keep nothing that looks
        # like one, and stop the caller (e.g. an upgrade) from continuing.
        target.unlink(missing_ok=True)
        raise RuntimeError(
            f"a mentés nem ment át az integritás-ellenőrzésen ({check[0] if check else '?'}); "
            "az adatbázis sérült lehet, állíts vissza egy korábbi mentést"
        )
    log.info("database backup written", extra={"path": str(target)})
    return target
