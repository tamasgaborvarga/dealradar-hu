"""Alembic environment. Uses the DealRadar engine factory so SQLite PRAGMAs always apply."""

from __future__ import annotations

from alembic import context

import dealradar.db.models  # noqa: F401  (registers all tables)
from dealradar.core.config import get_settings
from dealradar.db.base import Base
from dealradar.db.session import create_db_engine

config = context.config
target_metadata = Base.metadata


def _url() -> str:
    return config.get_main_option("sqlalchemy.url") or get_settings().db_url


def run_migrations_offline() -> None:
    context.configure(
        url=_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:
        _run(connection)
        return
    engine = create_db_engine(_url())
    try:
        with engine.connect() as conn:
            _run(conn)
    finally:
        engine.dispose()


def _run(connection: object) -> None:
    context.configure(
        connection=connection,  # type: ignore[arg-type]
        target_metadata=target_metadata,
        render_as_batch=True,  # SQLite needs batch mode for ALTER operations
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
