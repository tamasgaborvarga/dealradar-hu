"""Bootstraps settings, logging and the database for an entry point (CLI or UI)."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from dealradar.core.config import Settings, get_settings
from dealradar.core.logging import configure_logging
from dealradar.db.session import Database

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class AppContext:
    settings: Settings
    db: Database


def build_app_context(settings: Settings | None = None) -> AppContext:
    settings = settings or get_settings()
    settings.ensure_dirs()
    configure_logging(settings.log_dir, settings.log_level)
    db = Database(settings)
    log.info("app context ready", extra={"data_dir": str(settings.resolved_data_dir)})
    return AppContext(settings=settings, db=db)
