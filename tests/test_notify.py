"""Notifications: in-app inbox always; Telegram optional, failure-safe, token never leaked."""

from __future__ import annotations

import json

import pytest

from dealradar.core.config import Settings, get_settings, reset_settings_cache
from dealradar.core.enums import TelegramStatus
from dealradar.db.session import Database
from dealradar.services import notify

TOKEN = "123456:SECRET-test-token"


def _ok(url: str, data: dict[str, str]) -> tuple[int, str]:
    return 200, json.dumps({"ok": True})


def _with_telegram(monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setenv("DEALRADAR_TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("DEALRADAR_TELEGRAM_CHAT_ID", "42")
    reset_settings_cache()
    return get_settings()


def test_works_without_telegram(db: Database) -> None:
    assert not db.settings.telegram_enabled

    def never(url: str, data: dict[str, str]) -> tuple[int, str]:
        raise AssertionError("must not call Telegram when it is not configured")

    assert notify.notify(db, kind="T", title="t", body="b", dedupe_key="k1", post=never)
    [item] = notify.inbox(db)
    assert item.telegram_status is TelegramStatus.NOT_CONFIGURED and not item.read
    ok, error = notify.send_test_message(db, post=never)
    assert not ok and error == "nincs beállítva"


def test_dedupe_and_mark_read(db: Database) -> None:
    assert notify.notify(db, kind="T", title="t", body="b", dedupe_key="same")
    assert not notify.notify(db, kind="T", title="t2", body="b2", dedupe_key="same")
    assert len(notify.inbox(db)) == 1
    assert notify.mark_all_read(db) == 1
    assert notify.inbox(db, unread_only=True) == []


def test_sent_when_configured(db: Database, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _with_telegram(monkeypatch)
    sent: list[tuple[str, dict[str, str]]] = []

    def post(url: str, data: dict[str, str]) -> tuple[int, str]:
        sent.append((url, data))
        return _ok(url, data)

    db2 = Database(settings)
    try:
        notify.notify(db2, kind="T", title="Deal <b>x</b>", body="body", dedupe_key="k", post=post)
        assert notify.inbox(db2)[0].telegram_status is TelegramStatus.SENT
    finally:
        db2.dispose()
    assert sent[0][1]["chat_id"] == "42" and "parse_mode" not in sent[0][1]  # plain text only


@pytest.mark.parametrize(
    "post",
    [
        lambda url, data: (401, f'{{"ok":false,"description":"bad token {TOKEN}"}}'),
        lambda url, data: (0, "network error: URLError"),
        lambda url, data: (200, "not json"),
    ],
)
def test_failures_are_recorded_and_never_raise(
    db: Database, monkeypatch: pytest.MonkeyPatch, post: notify.Poster
) -> None:
    db2 = Database(_with_telegram(monkeypatch))
    try:
        assert notify.notify(db2, kind="T", title="t", body="b", dedupe_key="k", post=post)
        [item] = notify.inbox(db2)
        assert item.telegram_status is TelegramStatus.FAILED
    finally:
        db2.dispose()


def test_token_is_scrubbed_from_errors(monkeypatch: pytest.MonkeyPatch, settings: Settings) -> None:
    s = _with_telegram(monkeypatch)

    def boom(url: str, data: dict[str, str]) -> tuple[int, str]:
        raise RuntimeError(f"failed calling {url}")

    ok, error = notify.send_telegram(s, "x", boom)
    assert not ok and error is not None and TOKEN not in error and "<token>" in error
    ok, error = notify.send_telegram(s, "x", lambda u, d: (401, f"bad {TOKEN}"))
    assert error is not None and TOKEN not in error


def test_real_http_poster_never_raises_and_hits_no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """The default poster turns a network failure into (0, message) - here the suite-wide guard
    refuses the connection, proving no test can reach Telegram."""
    s = _with_telegram(monkeypatch)
    ok, error = notify.send_telegram(s, "x")
    assert not ok and error is not None and TOKEN not in error
