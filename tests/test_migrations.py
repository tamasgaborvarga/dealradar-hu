from __future__ import annotations

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import inspect

import dealradar.db.models  # noqa: F401
from dealradar.core.config import Settings
from dealradar.db.base import Base
from dealradar.db.session import Database
from dealradar.services.schema import (
    SchemaState,
    alembic_config,
    schema_status,
    upgrade_database,
)


def test_new_database_is_not_initialised(settings: Settings) -> None:
    db = Database(settings)
    try:
        assert schema_status(db.engine).state is SchemaState.NOT_INITIALISED
    finally:
        db.dispose()


def test_first_upgrade_after_status_check_makes_no_empty_backup(settings: Settings) -> None:
    db = Database(settings)
    try:
        schema_status(db.engine)  # creates an empty database file
    finally:
        db.dispose()
    assert settings.db_path.exists()
    assert upgrade_database(settings) is None
    assert list(settings.backup_dir.glob("*.db")) == []


def test_upgrade_reaches_head_and_matches_models(db: Database) -> None:
    status = schema_status(db.engine)
    assert status.state is SchemaState.UP_TO_DATE
    with db.engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == [], f"models and migrations differ: {diff}"


def test_all_phase1_tables_exist(db: Database) -> None:
    tables = set(inspect(db.engine).get_table_names())
    expected = set(Base.metadata.tables)
    assert expected <= tables


def test_second_upgrade_backs_up_and_is_noop(db: Database, settings: Settings) -> None:
    backup = upgrade_database(settings)
    assert backup is not None and backup.exists()
    assert schema_status(db.engine).ready


def test_downgrade_and_reupgrade(db: Database, settings: Settings) -> None:
    cfg = alembic_config(settings.db_url)
    command.downgrade(cfg, "base")
    assert schema_status(db.engine).state is SchemaState.NOT_INITIALISED
    command.upgrade(cfg, "head")
    assert schema_status(db.engine).ready


def test_0003_refuses_to_drop_existing_price_history(settings: Settings) -> None:
    """ADR-039: replacing price_spans must never silently discard recorded history."""
    import sqlite3

    import pytest

    cfg = alembic_config(settings.db_url)
    command.upgrade(cfg, "0002")
    conn = sqlite3.connect(settings.db_path)  # plain connection: FK checks off for the fixture row
    conn.execute(
        "INSERT INTO price_spans (offer_id, price_huf, in_stock, first_seen_at, last_confirmed_at)"
        " VALUES (1, 1000, 1, '2026-11-01 00:00:00.000000', '2026-11-02 00:00:00.000000')"
    )
    conn.commit()
    conn.close()
    with pytest.raises(RuntimeError, match="price_spans contains 1 rows"):
        command.upgrade(cfg, "head")
    db = Database(settings)
    try:
        assert schema_status(db.engine).current == "0002"  # nothing was applied
    finally:
        db.dispose()


def test_unknown_revision_detected(db: Database) -> None:
    with db.engine.begin() as conn:
        conn.exec_driver_sql("UPDATE alembic_version SET version_num = 'ffffffff'")
    assert schema_status(db.engine).state is SchemaState.UNKNOWN_REVISION
