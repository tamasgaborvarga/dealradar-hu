"""Basic health checks shared by ``dealradar health`` and the System health page."""

from __future__ import annotations

import shutil
import sqlite3
import sys
import tomllib
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from sqlalchemy import text

from dealradar.core import hu
from dealradar.core.config import Settings
from dealradar.core.errors import LockTimeoutError
from dealradar.db.lock import WriterLock
from dealradar.db.session import Database
from dealradar.services.schema import SchemaState, schema_status

PROJECT_ROOT = Path(__file__).resolve().parents[2]
STREAMLIT_CONFIG = PROJECT_ROOT / ".streamlit" / "config.toml"
MIN_FREE_BYTES = 500 * 1024 * 1024


class Status(StrEnum):
    OK = "OK"
    WARN = "WARN"
    FAIL = "FAIL"


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: Status
    detail: str


def _python() -> CheckResult:
    ok = sys.version_info >= (3, 12)
    return CheckResult("python_version", Status.OK if ok else Status.FAIL, sys.version.split()[0])


def _data_dir(settings: Settings) -> CheckResult:
    probe = settings.resolved_data_dir / f".write-probe-{uuid.uuid4().hex}"
    try:
        settings.ensure_dirs()
        probe.write_bytes(b"ok")
        probe.unlink()
    except OSError as exc:
        return CheckResult("data_dir_writable", Status.FAIL, f"{settings.resolved_data_dir}: {exc}")
    return CheckResult("data_dir_writable", Status.OK, str(settings.resolved_data_dir))


def _disk(settings: Settings) -> CheckResult:
    free = shutil.disk_usage(settings.resolved_data_dir).free
    status = Status.OK if free >= MIN_FREE_BYTES else Status.WARN
    return CheckResult("disk_free", status, f"{free // (1024 * 1024)} MB szabad")


def _sqlite_features() -> CheckResult:
    conn = sqlite3.connect(":memory:")
    try:
        json_ok = conn.execute("SELECT json_array_length('[1,2]')").fetchone()[0] == 2
    except sqlite3.OperationalError:
        json_ok = False
    finally:
        conn.close()
    version = sqlite3.sqlite_version
    ok = json_ok and tuple(int(p) for p in version.split(".")[:2]) >= (3, 35)
    return CheckResult(
        "sqlite_features",
        Status.OK if ok else Status.FAIL,
        f"SQLite {version}, JSON1 {'elérhető' if json_ok else 'HIÁNYZIK'}",
    )


def _db_connection(db: Database) -> CheckResult:
    try:
        with db.engine.connect() as conn:
            fk = conn.execute(text("PRAGMA foreign_keys")).scalar()
            journal = conn.execute(text("PRAGMA journal_mode")).scalar()
            integrity = conn.execute(text("PRAGMA quick_check")).scalar()
    except Exception as exc:
        return CheckResult("db_connection", Status.FAIL, str(exc))
    ok = fk == 1 and str(journal).lower() == "wal" and integrity == "ok"
    return CheckResult(
        "db_connection",
        Status.OK if ok else Status.FAIL,
        f"idegen kulcsok={fk}, napló={journal}, integritás={integrity}",
    )


def _schema(db: Database) -> CheckResult:
    try:
        st = schema_status(db.engine)
    except Exception as exc:
        return CheckResult("schema", Status.FAIL, str(exc))
    detail = f"{hu.label('schema_state', st.state)} (jelenlegi={st.current}, legfrissebb={st.head})"
    if st.state is SchemaState.NOT_INITIALISED or st.state is SchemaState.OUT_OF_DATE:
        detail += " -> futtasd: dealradar db upgrade"
    return CheckResult("schema", Status.OK if st.ready else Status.FAIL, detail)


def _writer_lock(settings: Settings) -> CheckResult:
    try:
        with WriterLock(settings.lock_path, timeout_s=0.5):
            pass
    except LockTimeoutError:
        return CheckResult("writer_lock", Status.WARN, "foglalt: egy másik írási művelet fut")
    return CheckResult("writer_lock", Status.OK, "szabad")


def read_streamlit_config_file(path: Path = STREAMLIT_CONFIG) -> dict[str, Any]:
    """Flatten ``.streamlit/config.toml`` to ``{"server.address": ...}`` form."""
    if not path.exists():
        return {}
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    return {
        f"{section}.{key}": value
        for section, values in data.items()
        if isinstance(values, dict)
        for key, value in values.items()
    }


def _ui_exposure(options: Mapping[str, Any], origin: str) -> CheckResult:
    address = options.get("server.address")
    stats = options.get("browser.gatherUsageStats")
    problems = []
    if address not in ("127.0.0.1", "localhost"):
        problems.append(f"server.address={address!r} (127.0.0.1 kell)")
    if stats is not False:
        problems.append(f"browser.gatherUsageStats={stats!r} (false kell)")
    if problems:
        return CheckResult("ui_local_only", Status.FAIL, f"{origin}: " + "; ".join(problems))
    return CheckResult(
        "ui_local_only", Status.OK, f"{origin}: csak {address} címen, telemetria kikapcsolva"
    )


def _sources(db: Database) -> CheckResult:
    from dealradar.services.refresh import freshness

    try:
        rows = freshness(db)
    except Exception as exc:  # schema missing etc. - reported by the schema check
        return CheckResult("sources", Status.WARN, f"nem ellenőrizhető: {type(exc).__name__}")
    mock = [r.source_key for r in rows if r.access_method.value == "MOCK"]
    stale = [r.source_key for r in rows if r.stale]
    blocked = [r.source_key for r in rows if r.status.value == "BLOCKED"]
    problems = []
    if mock:
        problems.append(f"SZINTETIKUS demóforrások vannak: {', '.join(mock)}")
    if stale:
        problems.append(f"elavult: {', '.join(stale)}")
    if blocked:
        problems.append(f"letiltva (újra kell ellenőrizni): {', '.join(blocked)}")
    if not rows:
        return CheckResult("sources", Status.OK, "nincs regisztrált forrás")
    return CheckResult(
        "sources",
        Status.WARN if problems else Status.OK,
        "; ".join(problems) or f"{len(rows)} sources fresh",
    )


def _telegram(settings: Settings) -> CheckResult:
    state = "beállítva" if settings.telegram_enabled else "nincs beállítva (nem kötelező)"
    return CheckResult("telegram", Status.OK, state)


def run_health_checks(
    settings: Settings,
    db: Database,
    ui_options: Mapping[str, Any] | None = None,
) -> list[CheckResult]:
    """Run all checks. ``ui_options`` = live Streamlit options when called from the UI;
    otherwise the committed config file is checked."""
    checks: list[Callable[[], CheckResult]] = [
        _python,
        _sqlite_features,
        lambda: _data_dir(settings),
        lambda: _disk(settings),
        lambda: _db_connection(db),
        lambda: _schema(db),
        lambda: _writer_lock(settings),
        lambda: _sources(db),
        lambda: _telegram(settings),
        lambda: (
            _ui_exposure(ui_options, "running app")
            if ui_options is not None
            else _ui_exposure(read_streamlit_config_file(), str(STREAMLIT_CONFIG.name))
        ),
    ]
    results = []
    for check in checks:
        try:
            results.append(check())
        except Exception as exc:  # a broken check must not hide the others
            results.append(CheckResult(getattr(check, "__name__", "check"), Status.FAIL, repr(exc)))
    return results


def overall(results: list[CheckResult]) -> Status:
    if any(r.status is Status.FAIL for r in results):
        return Status.FAIL
    if any(r.status is Status.WARN for r in results):
        return Status.WARN
    return Status.OK
