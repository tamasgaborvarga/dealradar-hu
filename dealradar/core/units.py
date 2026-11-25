"""Quantities, pack sizes and unit prices (food, home consumables).

Canonical units: KG, L, PIECE, M2. Unit prices are integer centi-HUF per canonical unit (ADR-007).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

from dealradar.core.enums import CanonicalUnit
from dealradar.core.hu_parse import ParseError, normalize_spaces, parse_hu_number, split_unit_price
from dealradar.core.money import Huf


class Unit(StrEnum):
    G = "G"
    KG = "KG"
    ML = "ML"
    CL = "CL"
    DL = "DL"
    L = "L"
    PIECE = "PIECE"
    M2 = "M2"


# unit -> (canonical unit, factor to canonical, smallest display unit, factor to smallest)
_UNIT_TABLE: dict[Unit, tuple[CanonicalUnit, Decimal, str, Decimal]] = {
    Unit.G: (CanonicalUnit.KG, Decimal("0.001"), "G", Decimal(1)),
    Unit.KG: (CanonicalUnit.KG, Decimal(1), "G", Decimal(1000)),
    Unit.ML: (CanonicalUnit.L, Decimal("0.001"), "ML", Decimal(1)),
    Unit.CL: (CanonicalUnit.L, Decimal("0.01"), "ML", Decimal(10)),
    Unit.DL: (CanonicalUnit.L, Decimal("0.1"), "ML", Decimal(100)),
    Unit.L: (CanonicalUnit.L, Decimal(1), "ML", Decimal(1000)),
    Unit.PIECE: (CanonicalUnit.PIECE, Decimal(1), "PC", Decimal(1)),
    Unit.M2: (CanonicalUnit.M2, Decimal(1), "M2", Decimal(1)),
}

_ALIASES: dict[str, Unit] = {
    "g": Unit.G, "gr": Unit.G, "gramm": Unit.G, "gram": Unit.G,
    "kg": Unit.KG, "kilogramm": Unit.KG, "kilogram": Unit.KG,
    "ml": Unit.ML, "cl": Unit.CL, "dl": Unit.DL,
    "l": Unit.L, "liter": Unit.L, "litre": Unit.L, "ltr": Unit.L, "lit": Unit.L,
    "db": Unit.PIECE, "darab": Unit.PIECE, "pcs": Unit.PIECE, "pc": Unit.PIECE,
    "piece": Unit.PIECE, "pieces": Unit.PIECE, "tekercs": Unit.PIECE, "tabletta": Unit.PIECE,
    "m2": Unit.M2, "m²": Unit.M2, "nm": Unit.M2,
}  # fmt: skip

_UNIT_RE = "|".join(sorted((re.escape(a) for a in _ALIASES), key=len, reverse=True))
_NUM = r"\d+(?:[.,]\d+)?"
_QTY = rf"(?P<amount>{_NUM})\s*(?P<unit>{_UNIT_RE})\b"
_PACK_PATTERNS = (
    re.compile(rf"^(?P<count>\d+)\s*(?:db\s*)?[x\u00d7*]\s*{_QTY}$", re.IGNORECASE),  # 6 x 330 ml
    re.compile(rf"^{_QTY}\s*[x\u00d7*]\s*(?P<count>\d+)(?:\s*db)?$", re.IGNORECASE),  # 330 ml x 6
    re.compile(rf"^{_QTY}$", re.IGNORECASE),  # 500 g
)
QUANTITY_IN_TEXT = re.compile(
    rf"(?:(?P<count>\d+)\s*(?:db\s*)?[x\u00d7*]\s*)?(?P<amount>{_NUM})\s*(?P<unit>{_UNIT_RE})\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Quantity:
    amount: Decimal
    unit: Unit

    def __post_init__(self) -> None:
        if self.amount <= 0:
            raise ParseError("quantity must be positive")

    @property
    def canonical_unit(self) -> CanonicalUnit:
        return _UNIT_TABLE[self.unit][0]

    @property
    def canonical_amount(self) -> Decimal:
        return self.amount * _UNIT_TABLE[self.unit][1]

    def small_key(self) -> str:
        """'0,5 kg' -> '500G', '33 cl' -> '330ML', '10 db' -> '10PC'."""
        _, _, label, factor = _UNIT_TABLE[self.unit]
        text = format(self.amount * factor, "f")
        if "." in text:
            text = text.rstrip("0").rstrip(".")
        return f"{text}{label}"


@dataclass(frozen=True)
class PackSize:
    count: int
    each: Quantity

    def __post_init__(self) -> None:
        if self.count < 1:
            raise ParseError("pack count must be >= 1")

    @property
    def canonical_unit(self) -> CanonicalUnit:
        return self.each.canonical_unit

    @property
    def total_canonical(self) -> Decimal:
        return self.each.canonical_amount * self.count

    def key(self) -> str:
        """Variant key: '500G', '6X330ML'. Identical for '0,5 kg' and '500 g'."""
        each = self.each.small_key()
        return each if self.count == 1 else f"{self.count}X{each}"


def parse_unit(text: str) -> Unit:
    unit = _ALIASES.get(normalize_spaces(text).lower().rstrip("."))
    if unit is None:
        raise ParseError(f"unknown unit: {text!r}")
    return unit


def parse_quantity(text: str) -> Quantity:
    """'500 g', '0,5 kg', '1.5l', '10 db'."""
    m = re.fullmatch(_QTY, normalize_spaces(text), re.IGNORECASE)
    if not m:
        raise ParseError(f"not a quantity: {text!r}")
    return Quantity(parse_hu_number(m["amount"]), parse_unit(m["unit"]))


def parse_pack_size(text: str) -> PackSize:
    """'6 x 330 ml', '6x0,33l', '330 ml x 6', '2 db x 500 g', '500 g'."""
    s = normalize_spaces(text)
    for pattern in _PACK_PATTERNS:
        m = pattern.fullmatch(s)
        if m:
            count = int(m["count"]) if m.groupdict().get("count") else 1
            return PackSize(count, Quantity(parse_hu_number(m["amount"]), parse_unit(m["unit"])))
    raise ParseError(f"not a pack size: {text!r}")


def find_pack_sizes(text: str) -> list[PackSize]:
    """All pack sizes mentioned in free text (e.g. a title). Callers decide on ambiguity."""
    found: list[PackSize] = []
    for m in QUANTITY_IN_TEXT.finditer(normalize_spaces(text)):
        try:
            qty = Quantity(parse_hu_number(m["amount"]), parse_unit(m["unit"]))
            found.append(PackSize(int(m["count"]) if m["count"] else 1, qty))
        except ParseError:
            continue
    unique: list[PackSize] = []
    for p in found:
        if p not in unique:
            unique.append(p)
    return unique


def unit_price_chuf(price: Huf, pack: PackSize) -> int:
    """Centi-HUF per canonical unit: 899 HUF for 500 g -> 179 800 (= 1 798,00 HUF/kg)."""
    if price < 0:
        raise ValueError("price must be non-negative")
    value = Decimal(price) * 100 / pack.total_canonical
    return int(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def parse_unit_price_chuf(text: str) -> tuple[int, CanonicalUnit]:
    """Shelf-label unit price -> (centi-HUF per canonical unit, unit).

    '1 798 Ft/kg' -> (179800, KG); '179,80 Ft/100 g' -> (179800, KG); '499 Ft/l' -> (49900, L).
    """
    price, unit_text = split_unit_price(text)
    unit_text = unit_text.strip()
    if re.match(r"^\d", unit_text):
        qty = parse_quantity(unit_text)
    else:
        qty = Quantity(Decimal(1), parse_unit(unit_text))
    value = price * 100 / qty.canonical_amount
    return int(value.quantize(Decimal(1), rounding=ROUND_HALF_UP)), qty.canonical_unit
