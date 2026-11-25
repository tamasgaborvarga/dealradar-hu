from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from dealradar.core.config import Settings, get_settings, reset_settings_cache
from dealradar.db.session import Database
from dealradar.services.schema import upgrade_database

_LOOPBACK = ("127.0.0.1", "::1", "localhost")


@pytest.fixture(autouse=True)
def _isolated_from_the_outside(monkeypatch: pytest.MonkeyPatch) -> None:
    """No test may reach the network or use the user's real credentials (QA finding).

    - Telegram credentials from a developer's .env are neutralized (environment variables win
      over .env; empty values mean "not configured"). Tests that need Telegram set fakes.
    - Outbound connections are refused; loopback stays allowed (asyncio uses local socket pairs).
    """
    import socket

    monkeypatch.setenv("DEALRADAR_TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setenv("DEALRADAR_TELEGRAM_CHAT_ID", "")
    real_connect = socket.socket.connect

    def guarded_connect(self: socket.socket, address: object) -> None:
        host = address[0] if isinstance(address, tuple) else address
        if isinstance(host, str) and host not in _LOOPBACK:
            raise AssertionError(f"network access attempted in a test: {address!r}")
        real_connect(self, address)  # type: ignore[arg-type]

    def no_dns(host: object, *args: object, **kwargs: object) -> object:
        if host in _LOOPBACK or host is None:
            return real_getaddrinfo(host, *args, **kwargs)  # type: ignore[arg-type]
        raise AssertionError(f"DNS lookup attempted in a test: {host!r}")

    real_getaddrinfo = socket.getaddrinfo
    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket, "getaddrinfo", no_dns)


@pytest.fixture
def settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Settings]:
    """Isolated data dir per test, applied through the real environment-variable path."""
    monkeypatch.setenv("DEALRADAR_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DEALRADAR_LOCK_TIMEOUT_S", "2")
    reset_settings_cache()
    s = get_settings()
    s.ensure_dirs()
    yield s
    reset_settings_cache()


@pytest.fixture
def db(settings: Settings) -> Iterator[Database]:
    """A database migrated to head with the real Alembic migrations."""
    upgrade_database(settings)
    database = Database(settings)
    yield database
    database.dispose()
