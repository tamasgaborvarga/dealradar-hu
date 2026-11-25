"""Product identifier normalization: GTIN (EAN/UPC), MPN, style codes."""

from __future__ import annotations

import re

from dealradar.core.hu_parse import ParseError

_GTIN_LENGTHS = (8, 12, 13, 14)


def gtin_check_digit_ok(digits: str) -> bool:
    """GS1 mod-10 check digit, valid for GTIN-8/12/13/14."""
    body, check = digits[:-1], int(digits[-1])
    total = sum(int(d) * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(body)))
    return (10 - total % 10) % 10 == check


def normalize_gtin(text: str) -> str:
    """Return the GTIN as 14 digits (zero-padded). Raises ParseError if invalid.

    Padding makes UPC-A (12), EAN-13 and GTIN-14 of the same item compare equal.
    """
    digits = re.sub(r"[\s\-.]", "", text)
    if not digits.isdigit() or len(digits) not in _GTIN_LENGTHS:
        raise ParseError(f"GTIN must have 8, 12, 13 or 14 digits: {text!r}")
    if not gtin_check_digit_ok(digits):
        raise ParseError(f"GTIN check digit invalid: {text!r}")
    if set(digits) == {"0"}:
        raise ParseError("GTIN of zeros")
    return digits.zfill(14)


def is_restricted_gtin(text: str) -> bool:
    """True for GS1 restricted-circulation numbers (store-internal / variable-weight codes).

    EAN-13 prefixes 020-029 and 200-299 (and EAN-8 starting with 0 or 2) are assigned locally by
    retailers, so the same number can mean different products in different shops. They must not be
    used as global identifiers.
    """
    digits = re.sub(r"[\s\-.]", "", text)
    if len(digits) == 8:
        return digits[0] in "02"
    gtin14 = digits.zfill(14)
    prefix = int(gtin14[1:4])
    return 20 <= prefix <= 29 or 200 <= prefix <= 299


def code_key(text: str) -> str:
    """Comparison key for MPNs / style codes: uppercase, no spaces, dashes, dots or slashes.

    'dm0029-100' and 'DM0029 100' compare equal. Raises ParseError if too short to be meaningful.
    """
    key = re.sub(r"[\s\-./_]", "", text).upper()
    if len(key) < 3 or not re.fullmatch(r"[A-Z0-9#+]+", key):
        raise ParseError(f"not a usable part/style code: {text!r}")
    return key


def text_key(text: str | None) -> str | None:
    """Case/punctuation-insensitive key for brands and model names ('Samsung ' -> 'samsung')."""
    if text is None:
        return None
    key = re.sub(r"[^0-9a-zÀ-ɏ]+", " ", text.casefold()).strip()
    return key or None
