from __future__ import annotations

from decimal import Decimal

import pytest

from dealradar.core.hu_parse import ParseError, parse_hu_number, parse_price, split_unit_price

NBSP, NNBSP = "\u00a0", "\u202f"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("12990", "12990"),
        ("12 990", "12990"),
        (f"12{NBSP}990", "12990"),
        (f"12{NNBSP}990", "12990"),
        ("1 299 990", "1299990"),
        ("1.299", "1299"),
        ("1.299.000", "1299000"),
        ("1 299,90", "1299.90"),
        ("1.299,90", "1299.90"),
        ("1,299.90", "1299.90"),
        ("0,5", "0.5"),
        ("12,5", "12.5"),
        ("12.5", "12.5"),
        ("12.50", "12.50"),
        ("0", "0"),
        ("1,299,000", "1299000"),
    ],
)
def test_parse_hu_number(text: str, expected: str) -> None:
    assert parse_hu_number(text) == Decimal(expected)


@pytest.mark.parametrize(
    "text", ["1,299", "12 99", "1 2990", "abc", "", "1.29.9", "12,345.6.7", "1 000,"]
)
def test_parse_hu_number_rejects_ambiguous(text: str) -> None:
    with pytest.raises(ParseError):
        parse_hu_number(text)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("12 990 Ft", 12990),
        ("12990Ft", 12990),
        ("12 990 Ft.", 12990),
        ("12 990 HUF", 12990),
        ("HUF 12 990", 12990),
        ("12.990 Ft", 12990),
        ("1.299,-", 1299),
        ("1 299,- Ft", 1299),
        ("1299.-", 1299),
        ("1 299 Ft-", 1299),
        (f"24{NBSP}990{NBSP}Ft", 24990),
        ("249 990 forint", 249990),
        ("899 Ft", 899),
        ("1 299,90 Ft", Decimal("1299.90")),
        ("0 Ft", 0),
        ("  5 490 Ft  ", 5490),
    ],
)
def test_parse_price(text: str, expected: int | Decimal) -> None:
    assert parse_price(text) == Decimal(expected)


@pytest.mark.parametrize(
    "text",
    [
        "1 299 - 1 499 Ft",
        "1 299\u20131 499 Ft",
        "1 299 Ft-tól",
        "kb. 5000 Ft",
        "~5000 Ft",
        "max. 5000 Ft",
        "12 990 Ft/kg",
        "-500 Ft",
        "",
        "ingyenes",
        "Ár: hívjon",
    ],
)
def test_parse_price_rejects(text: str) -> None:
    with pytest.raises(ParseError):
        parse_price(text)


def test_split_unit_price() -> None:
    assert split_unit_price("12 990 Ft/kg") == (Decimal(12990), "kg")
    assert split_unit_price("499 Ft / 100 g") == (Decimal(499), "100 g")
    with pytest.raises(ParseError):
        split_unit_price("499 Ft")
    with pytest.raises(ParseError):
        split_unit_price("499 Ft/")
