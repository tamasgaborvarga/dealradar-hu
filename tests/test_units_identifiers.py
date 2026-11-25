from __future__ import annotations

from decimal import Decimal

import pytest

from dealradar.core.enums import CanonicalUnit
from dealradar.core.hu_parse import ParseError
from dealradar.core.identifiers import (
    code_key,
    gtin_check_digit_ok,
    is_restricted_gtin,
    normalize_gtin,
    text_key,
)
from dealradar.core.money import Huf
from dealradar.core.units import (
    PackSize,
    Quantity,
    Unit,
    find_pack_sizes,
    parse_pack_size,
    parse_quantity,
    parse_unit_price_chuf,
    unit_price_chuf,
)
from tests.category_helpers import gtin


@pytest.mark.parametrize(
    ("text", "key", "total", "unit"),
    [
        ("500 g", "500G", "0.5", CanonicalUnit.KG),
        ("0,5 kg", "500G", "0.5", CanonicalUnit.KG),
        ("1 kg", "1000G", "1", CanonicalUnit.KG),
        ("1,5 l", "1500ML", "1.5", CanonicalUnit.L),
        ("1.5l", "1500ML", "1.5", CanonicalUnit.L),
        ("330 ml", "330ML", "0.33", CanonicalUnit.L),
        ("33 cl", "330ML", "0.33", CanonicalUnit.L),
        ("5 dl", "500ML", "0.5", CanonicalUnit.L),
        ("6 x 330 ml", "6X330ML", "1.98", CanonicalUnit.L),
        ("6x0,33l", "6X330ML", "1.98", CanonicalUnit.L),
        ("330 ml x 6", "6X330ML", "1.98", CanonicalUnit.L),
        ("2 db x 500 g", "2X500G", "1", CanonicalUnit.KG),
        ("4*125g", "4X125G", "0.5", CanonicalUnit.KG),
        ("10 db", "10PC", "10", CanonicalUnit.PIECE),
        ("16 tekercs", "16PC", "16", CanonicalUnit.PIECE),
        ("2,5 m2", "2.5M2", "2.5", CanonicalUnit.M2),
    ],
)
def test_parse_pack_size(text: str, key: str, total: str, unit: CanonicalUnit) -> None:
    pack = parse_pack_size(text)
    assert pack.key() == key
    assert pack.total_canonical == Decimal(total)
    assert pack.canonical_unit is unit


@pytest.mark.parametrize("text", ["", "500", "g", "0 g", "500 g + 50 g", "fél kiló", "3 x"])
def test_parse_pack_size_rejects(text: str) -> None:
    with pytest.raises(ParseError):
        parse_pack_size(text)


def test_find_pack_sizes_in_title() -> None:
    assert [p.key() for p in find_pack_sizes("Coca-Cola Zero 6 x 330 ml doboz")] == ["6X330ML"]
    assert [p.key() for p in find_pack_sizes("Milka 100 g + 20 g ajándék")] == ["100G", "20G"]
    assert find_pack_sizes("Mosogatószer citrom") == []


@pytest.mark.parametrize(
    ("price", "pack", "expected_chuf"),
    [
        (899, "500 g", 179_800),  # 1 798,00 Ft/kg
        (1_299, "6 x 330 ml", 65_606),  # 656,06 Ft/l
        (2_490, "16 tekercs", 15_563),  # 155,63 Ft/db (155.625 rounds half up)
        (0, "1 kg", 0),
    ],
)
def test_unit_price_chuf(price: int, pack: str, expected_chuf: int) -> None:
    assert unit_price_chuf(Huf(price), parse_pack_size(pack)) == expected_chuf


@pytest.mark.parametrize(
    ("text", "chuf", "unit"),
    [
        ("1 798 Ft/kg", 179_800, CanonicalUnit.KG),
        ("179,80 Ft/100 g", 179_800, CanonicalUnit.KG),
        ("499 Ft/l", 49_900, CanonicalUnit.L),
        ("65,61 Ft/100 ml", 65_610, CanonicalUnit.L),
        ("155,63 Ft/db", 15_563, CanonicalUnit.PIECE),
    ],
)
def test_parse_unit_price(text: str, chuf: int, unit: CanonicalUnit) -> None:
    assert parse_unit_price_chuf(text) == (chuf, unit)


def test_quantity_validation() -> None:
    assert parse_quantity("250 gr") == Quantity(Decimal(250), Unit.G)
    with pytest.raises(ParseError):
        PackSize(0, Quantity(Decimal(1), Unit.KG))


def test_gtin_normalization_and_check_digit() -> None:
    ean13 = gtin("599000000001")
    assert len(ean13) == 13 and gtin_check_digit_ok(ean13)
    assert normalize_gtin(ean13) == "0" + ean13
    assert normalize_gtin(f"{ean13[:4]} {ean13[4:]}") == "0" + ean13
    upc = gtin("03600029145")  # 11-digit body -> UPC-A
    assert normalize_gtin(upc) == normalize_gtin("0" + upc)  # UPC-A == EAN-13 with leading 0
    wrong = ean13[:-1] + str((int(ean13[-1]) + 1) % 10)
    for bad in (wrong, "12345", "abcdefghijklm", "0000000000000"):
        with pytest.raises(ParseError):
            normalize_gtin(bad)


def test_restricted_gtins() -> None:
    assert is_restricted_gtin(gtin("200000000001"))  # in-store / variable weight
    assert is_restricted_gtin(gtin("020000000001"))
    assert is_restricted_gtin("20123455")  # EAN-8 starting with 2
    assert not is_restricted_gtin(gtin("599000000001"))  # Hungarian GS1 prefix


def test_code_and_text_keys() -> None:
    assert code_key("dm0029-100") == code_key("DM0029 100") == "DM0029100"
    assert code_key("MZ-V9P2T0BW") == "MZV9P2T0BW"
    with pytest.raises(ParseError):
        code_key("ab")
    assert text_key("  Samsung  ") == "samsung"
    assert text_key("Bosch Serie | 6") == "bosch serie 6"
    assert text_key("Túró Rudi") == "túró rudi"
    assert text_key("---") is None
