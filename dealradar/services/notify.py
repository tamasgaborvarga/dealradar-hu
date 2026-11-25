"""Notifications: in-app inbox (always) + optional Telegram (free Bot API, user-configured).

Telegram is never required: without a token and chat id nothing is sent, and a sending failure
never breaks the caller. The bot token is never logged or stored in the database.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select

from dealradar.core.clock import utcnow
from dealradar.core.config import Settings
from dealradar.core.enums import TelegramStatus
from dealradar.db.models import Notification
from dealradar.db.session import Database
from dealradar.normalize.text import clean_text

log = logging.getLogger(__name__)
TELEGRAM_API = "https://api.telegram.org"
TIMEOUT_S = 10.0
MAX_TEXT = 3_500  # Telegram limit is 4 096 characters

Poster = Callable[[str, dict[str, str]], tuple[int, str]]


def _http_post(url: str, data: dict[str, str]) -> tuple[int, str]:
    body = urllib.parse.urlencode(data).encode("utf-8")
    request = urllib.request.Request(url, data=body, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
            return int(response.status), response.read(4_096).decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return int(exc.code), exc.read(4_096).decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return 0, f"hálózati hiba: {type(exc).__name__}"


def _scrub(text: str, settings: Settings) -> str:
    token = settings.telegram_bot_token.get_secret_value() if settings.telegram_bot_token else ""
    return text.replace(token, "<token>") if token else text


def send_telegram(
    settings: Settings, text: str, post: Poster = _http_post
) -> tuple[bool, str | None]:
    """Send one message. Returns (ok, error). Never raises."""
    if not settings.telegram_enabled:
        return False, "nincs beállítva"
    assert settings.telegram_bot_token is not None and settings.telegram_chat_id is not None
    url = f"{TELEGRAM_API}/bot{settings.telegram_bot_token.get_secret_value()}/sendMessage"
    data = {
        "chat_id": settings.telegram_chat_id,
        "text": (clean_text(text, MAX_TEXT) or "")[:MAX_TEXT],
        "disable_web_page_preview": "true",
    }
    try:
        status, body = post(url, data)
    except Exception as exc:  # a broken poster must not break the caller
        return False, _scrub(f"{type(exc).__name__}: {exc}", settings)[:300]
    if status == 200:
        try:
            if json.loads(body).get("ok") is True:
                return True, None
        except (ValueError, AttributeError):
            pass
    return False, _scrub(f"HTTP {status}: {body}", settings)[:300]


@dataclass(frozen=True)
class InboxItem:
    id: int
    created_at: datetime
    kind: str
    title: str
    body: str
    offer_id: int | None
    read: bool
    telegram_status: TelegramStatus


def notify(
    db: Database,
    *,
    kind: str,
    title: str,
    body: str,
    dedupe_key: str,
    offer_id: int | None = None,
    post: Poster = _http_post,
) -> bool:
    """Create an inbox entry once per dedupe_key and mirror it to Telegram if configured.
    Returns True if a new notification was created."""
    settings = db.settings
    with db.write_session() as s:
        if s.scalar(select(Notification.id).where(Notification.dedupe_key == dedupe_key)):
            return False
        note = Notification(
            kind=kind,
            title=(clean_text(title, 200) or kind)[:200],
            body=clean_text(body, 2_000) or "",
            offer_id=offer_id,
            dedupe_key=dedupe_key[:200],
            telegram_status=TelegramStatus.NOT_CONFIGURED,
        )
        s.add(note)
        s.flush()
        note_id = note.id
    if settings.telegram_enabled:
        ok, error = send_telegram(settings, f"DealRadar: {title}\n{body}", post)
        if not ok:
            log.warning("telegram notification failed", extra={"error": error})
        with db.write_session() as s:
            row = s.get(Notification, note_id)
            if row is not None:
                row.telegram_status = TelegramStatus.SENT if ok else TelegramStatus.FAILED
                row.telegram_error = error
    return True


def inbox(db: Database, *, unread_only: bool = False, limit: int = 50) -> list[InboxItem]:
    with db.read_session() as s:
        stmt = select(Notification).order_by(Notification.id.desc()).limit(limit)
        if unread_only:
            stmt = stmt.where(Notification.read_at.is_(None))
        return [
            InboxItem(
                n.id,
                n.created_at,
                n.kind,
                n.title,
                n.body,
                n.offer_id,
                n.read_at is not None,
                n.telegram_status,
            )
            for n in s.scalars(stmt).all()
        ]


def mark_all_read(db: Database) -> int:
    now = utcnow()
    with db.write_session() as s:
        rows = s.scalars(select(Notification).where(Notification.read_at.is_(None))).all()
        for row in rows:
            row.read_at = now
        return len(rows)


def send_test_message(db: Database, post: Poster = _http_post) -> tuple[bool, str | None]:
    return send_telegram(
        db.settings, "DealRadar tesztüzenet: a Telegram-értesítések működnek.", post
    )
