from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest
from pydantic import ValidationError

from dealradar.core.config import Settings, get_settings, reset_settings_cache
from dealradar.core.logging import configure_logging


def test_env_overrides(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEALRADAR_DATA_DIR", str(tmp_path / "x"))
    monkeypatch.setenv("DEALRADAR_LOG_LEVEL", "DEBUG")
    reset_settings_cache()
    s = get_settings()
    assert s.db_path == (tmp_path / "x" / "dealradar.db").resolve()
    assert s.log_level == "DEBUG"
    assert s.db_url.startswith("sqlite:///")
    reset_settings_cache()


def test_invalid_env_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEALRADAR_LOCK_TIMEOUT_S", "-1")
    with pytest.raises(ValidationError):
        Settings()


def test_json_log_line_written(settings: Settings) -> None:
    configure_logging(settings.log_dir, "INFO")
    logging.getLogger("dealradar.test").info("hello", extra={"source": "unit"})
    for h in logging.getLogger().handlers:
        h.flush()
    lines = (settings.log_dir / "dealradar.jsonl").read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[-1])
    assert record["msg"] == "hello"
    assert record["level"] == "INFO"
    assert record["extra"] == {"source": "unit"}


def test_configure_logging_is_idempotent(settings: Settings) -> None:
    configure_logging(settings.log_dir)
    configure_logging(settings.log_dir)
    ours = [h for h in logging.getLogger().handlers if getattr(h, "_dealradar_handler", False)]
    assert len(ours) == 2  # one file + one console handler
