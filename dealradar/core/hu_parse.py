"""Parsing of Hungarian number and price strings.

Conventions in Hungarian shops: space (often NBSP / narrow NBSP) or dot as thousands separator,
comma as decimal separator, "Ft" / "HUF" / ",-" suffixes. Anything ambiguous raises ParseError -
callers turn that into a validation issue, never into a guess.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

_SPACE_CHARS = dict.fromkeys(map(ord, "\u00a0\u202f\u2007\u2009\t"), " ")
_CURRENCY = re.compile(r"(?<![a-zá-ű])(huf|ft|forint)(?![a-zá-ű])\.?", re.IGNORECASE)
_RANGE = re.compile(
    r"\d\s*[-\u2013\u2014]\s*\d|\btól\b|-tól|\bfrom\b|\bmax\.?\b|\bkb\.?\b|~", re.IGNORECASE
)


class ParseError(ValueError):
    """The text cannot be interpreted unambiguously."""


def normalize_spaces(text: str) -> str:
    return re.sub(r" +", " ", text.translate(_SPACE_CHARS)).strip()


def parse_hu_number(text: str) -> Decimal:
    """'1 299' -> 1299, '1.299' -> 1299, '1 299,90' -> 1299.90, '0,5' -> 0.5, '12.5' -> 12.5.

    Raises ParseError for ambiguous forms such as '1,299' (thousands or decimal?).
    """
    s = normalize_spaces(text)
    if not re.fullmatch(r"[+-]?\d[\d .,]*", s):
        raise ParseError(f"not a number: {text!r}")
    if " " in s:
        groups = s.lstrip("+-").split(" ")
        tail = groups[-1]
        last_int = re.split(r"[.,]", tail)[0]
        head_ok = groups[0] and len(groups[0].lstrip("+-")) <= 3
        if not head_ok or not all(len(g) == 3 for g in [*groups[1:-1], last_int]):
            raise ParseError(f"invalid digit grouping: {text!r}")
        s = s.replace(" ", "")
    has_comma, has_dot = "," in s, "." in s
    if has_comma and has_dot:
        if s.rfind(",") > s.rfind("."):  # 1.299,90 (HU)
            int_part, dec = s.rsplit(",", 1)
            _check_groups(int_part, ".", text)
            s = int_part.replace(".", "") + "." + dec
        else:  # 1,299.90 (EN)
            int_part, dec = s.rsplit(".", 1)
            _check_groups(int_part, ",", text)
            s = int_part.replace(",", "") + "." + dec
    elif has_comma:
        parts = s.split(",")
        if len(parts) == 2 and 1 <= len(parts[1]) <= 2:
            s = parts[0] + "." + parts[1]  # decimal comma
        elif len(parts) == 2 and len(parts[1]) == 3:
            raise ParseError(f"ambiguous comma (thousands or decimal?): {text!r}")
        else:
            _check_groups(s, ",", text)
            s = s.replace(",", "")
    elif has_dot:
        parts = s.split(".")
        if len(parts) == 2 and 1 <= len(parts[1]) <= 2:
            pass  # decimal dot, e.g. 12.5
        else:
            _check_groups(s, ".", text)  # 1.299 / 1.299.000
            s = s.replace(".", "")
    try:
        return Decimal(s)
    except InvalidOperation as exc:  # pragma: no cover - regex above prevents this
        raise ParseError(f"not a number: {text!r}") from exc


def _check_groups(s: str, sep: str, original: str) -> None:
    groups = s.lstrip("+-").split(sep)
    if not groups[0] or len(groups[0]) > 3 or not all(len(g) == 3 for g in groups[1:]):
        raise ParseError(f"invalid digit grouping: {original!r}")


def parse_price(text: str) -> Decimal:
    """Parse a total price in HUF: '12 990 Ft', '1.299,-', 'HUF 4 590', '1 299,90 Ft'.

    Rejects ranges ('1 299 - 1 499 Ft', '1 299 Ft-tól'), approximations and per-unit prices
    ('12 990 Ft/kg' - use ``parse_unit_price_text``). Negative prices are rejected.
    """
    s = normalize_spaces(text)
    if not s:
        raise ParseError("empty price")
    if "/" in s:
        raise ParseError(f"per-unit price where a total price was expected: {text!r}")
    if _RANGE.search(s):
        raise ParseError(f"price range or approximation: {text!r}")
    s = _CURRENCY.sub("", s)
    s = re.sub(r"[,.]-$|[,.]\s*-+\s*$|-+$", "", s.strip()).strip()
    if s.startswith("-"):
        raise ParseError(f"negative price: {text!r}")
    value = parse_hu_number(s)
    if value < 0:
        raise ParseError(f"negative price: {text!r}")
    return value


def split_unit_price(text: str) -> tuple[Decimal, str]:
    """'12 990 Ft/kg' -> (12990, 'kg'); '499 Ft / 100 g' -> (499, '100 g')."""
    s = normalize_spaces(text)
    if s.count("/") != 1:
        raise ParseError(f"not a unit price: {text!r}")
    price_part, unit_part = s.split("/")
    unit_part = unit_part.strip()
    if not unit_part:
        raise ParseError(f"unit missing: {text!r}")
    return parse_price(price_part), unit_part
