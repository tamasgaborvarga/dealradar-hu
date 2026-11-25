"""Sanitizing untrusted text from listings (ARCHITECTURE.md §12)."""

from __future__ import annotations

import re
import unicodedata

_INVISIBLE = re.compile(
    "[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f-\u009f"  # control chars (keep \t \n \r)
    "\u200b-\u200f\u202a-\u202e\u2060-\u2064\u2066-\u2069\ufeff]"  # zero-width / bidi overrides
)
_TAGS = re.compile(r"<[^>]{0,500}>")


def clean_text(text: str | None, max_len: int) -> str | None:
    """NFKC-normalize, strip HTML tags, control/zero-width/bidi chars, collapse whitespace, cap."""
    if text is None:
        return None
    s = unicodedata.normalize("NFKC", text)
    s = _TAGS.sub(" ", s)
    s = _INVISIBLE.sub("", s)
    s = re.sub(r"\s+", " ", s).strip()
    if len(s) > max_len:
        s = s[:max_len].rstrip()
    return s or None
