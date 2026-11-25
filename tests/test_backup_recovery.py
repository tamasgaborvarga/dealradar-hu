"""QA: damaged databases are detected, never backed up as if healthy, and restorable."""

from __future__ import annotations

import os
import shutil
import sqlite3
from pathlib import Path

import pytest

from dealradar.core.config import Settings
from dealradar.db.session import Database
from dealradar.services.backup import backup_database
from dealradar.services.health import Status, run_health_checks


def _damage(path: Path) -> None:
    size = path.stat().st_size
    with path.open("r+b") as f:  # overwrite everything after the header page with garbage
        f.seek(4096)
        f.write(os.urandom(max(size - 4096, 8192)))


def _check(db: Database) -> Status:
    return next(r.status for r in run_health_checks(db.settings, db) if r.name == "db_connection")


def test_backup_restore_round_trip(db: Database, settings: Settings) -> None:
    assert _check(db) is Status.OK
    backup = backup_database(settings)
    assert backup is not None
    with sqlite3.connect(backup) as conn:
        assert conn.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    db.dispose()
    _damage(settings.db_path)
    damaged = Database(settings)
    try:
        assert _check(damaged) is Status.FAIL
        with pytest.raises(RuntimeError, match="integritás"):
            backup_database(settings, "after-damage")
        assert len(list(settings.backup_dir.glob("*.db"))) == 1  # no bad copy left behind
    finally:
        damaged.dispose()
    for suffix in ("-wal", "-shm"):  # documented restore procedure (README)
        Path(str(settings.db_path) + suffix).unlink(missing_ok=True)
    shutil.copyfile(backup, settings.db_path)
    restored = Database(settings)
    try:
        assert _check(restored) is Status.OK
    finally:
        restored.dispose()
