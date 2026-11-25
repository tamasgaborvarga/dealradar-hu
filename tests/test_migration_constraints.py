"""SQLite batch migrations rebuild tables; prove that no constraint or index was silently lost.

compare_metadata() checks columns, types and indexes but not CHECK constraints, so this test
compares the constraint names in the migrated database with a database built from the models.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from sqlalchemy import create_engine

import dealradar.db.models  # noqa: F401
from dealradar.core.config import Settings
from dealradar.db.base import Base
from dealradar.db.session import Database

_CONSTRAINT = re.compile(r"CONSTRAINT\s+(\w+)\s+(CHECK|FOREIGN KEY|PRIMARY KEY|UNIQUE)", re.I)


def _schema(path: Path) -> dict[str, set[str]]:
    conn = sqlite3.connect(path)
    try:
        rows = conn.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_master "
            "WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%' AND name != 'alembic_version'"
        ).fetchall()
    finally:
        conn.close()
    out: dict[str, set[str]] = {}
    for kind, name, table, sql in rows:
        items = out.setdefault(table, set())
        if kind == "index":
            items.add(f"index:{name}")
        else:
            items.update(f"{m.group(2).upper()}:{m.group(1)}" for m in _CONSTRAINT.finditer(sql))
    return out


def test_migrated_schema_has_every_model_constraint(
    db: Database, settings: Settings, tmp_path: Path
) -> None:
    reference = tmp_path / "reference.db"
    engine = create_engine(f"sqlite:///{reference.as_posix()}")
    Base.metadata.create_all(engine)
    engine.dispose()

    migrated, expected = _schema(settings.db_path), _schema(reference)
    # guard against a vacuous comparison: known constraints must be found at all
    assert {"CHECK:ck_listings_condition", "CHECK:ck_listings_matched_iff_product"} <= migrated[
        "listings"
    ]
    assert "CHECK:ck_product_attrs_food_canonical_unit" in migrated["product_attrs_food"]
    assert "index:uq_variant_identifiers_global" in migrated["variant_identifiers"]
    assert migrated.keys() == expected.keys()
    for table, names in expected.items():
        assert migrated[table] == names, (table, names ^ migrated[table])


def test_used_condition_accepted_after_migration(db: Database) -> None:
    from dealradar.core.enums import Condition
    from tests import factories as f

    with db.write_session() as s:
        listing = f.offer(s, f.source(s)).listing
        listing.condition = Condition.USED
