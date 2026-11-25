from __future__ import annotations

from pathlib import Path

import pytest

from dealradar import cli
from dealradar.core.config import Settings
from dealradar.db.session import Database
from dealradar.services.health import (
    STREAMLIT_CONFIG,
    Status,
    _ui_exposure,
    overall,
    read_streamlit_config_file,
    run_health_checks,
)


def _by_name(settings: Settings, db: Database) -> dict[str, Status]:
    return {r.name: r.status for r in run_health_checks(settings, db)}


def test_health_ok_after_migration(db: Database, settings: Settings) -> None:
    results = run_health_checks(settings, db)
    assert overall(results) is Status.OK, results


def test_health_fails_before_migration(settings: Settings) -> None:
    db = Database(settings)
    try:
        assert _by_name(settings, db)["schema"] is Status.FAIL
    finally:
        db.dispose()


def test_committed_streamlit_config_is_local_only() -> None:
    options = read_streamlit_config_file(STREAMLIT_CONFIG)
    assert options["server.address"] == "127.0.0.1"
    assert options["browser.gatherUsageStats"] is False


@pytest.mark.parametrize(
    "options",
    [
        {"server.address": "0.0.0.0", "browser.gatherUsageStats": False},
        {"server.address": None, "browser.gatherUsageStats": False},
        {"server.address": "127.0.0.1", "browser.gatherUsageStats": True},
    ],
)
def test_exposed_ui_fails(options: dict[str, object]) -> None:
    assert _ui_exposure(options, "test").status is Status.FAIL


def test_missing_config_file_fails(tmp_path: Path) -> None:
    assert (
        _ui_exposure(read_streamlit_config_file(tmp_path / "none.toml"), "x").status is Status.FAIL
    )


def test_cli_upgrade_status_health(settings: Settings, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["db", "status"]) == 1  # not initialised yet
    assert cli.main(["db", "upgrade"]) == 0
    assert cli.main(["db", "status"]) == 0
    assert cli.main(["health"]) == 0
    assert cli.main(["db", "backup"]) == 0
    out = capsys.readouterr().out
    assert "naprakész" in out and "Összesítve: OK" in out
    assert list(settings.backup_dir.glob("dealradar-*-manual.db"))


def test_cli_ui_flags_force_local_binding() -> None:
    assert "--server.address=127.0.0.1" in cli.STREAMLIT_FLAGS
    assert "--browser.gatherUsageStats=false" in cli.STREAMLIT_FLAGS
