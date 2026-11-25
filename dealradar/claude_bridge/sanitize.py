"""Untrusted listing text -> safe to embed in a prompt (ARCHITECTURE.md §9)."""

from __future__ import annotations

import re

from dealradar.normalize.text import clean_text

MAX_TITLE = 300
MAX_DESCRIPTION = 2_000
_DELIMITER_SPOOF = re.compile(r"</?\s*untrusted[^>]*>?", re.IGNORECASE)
_FENCE = re.compile(r"`{3,}")


def untrusted(text: str | None, max_len: int) -> str | None:
    """Clean (HTML, control, zero-width and bidi characters removed, whitespace collapsed), remove
    anything that imitates our data delimiters or code fences, and cap the length."""
    cleaned = clean_text(text, max_len * 2)
    if cleaned is None:
        return None
    cleaned = _DELIMITER_SPOOF.sub("[removed]", cleaned)
    cleaned = _FENCE.sub("'''", cleaned)
    if len(cleaned) > max_len:
        cleaned = cleaned[:max_len].rstrip() + " [truncated]"
    return cleaned
