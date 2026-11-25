"""Synthetic catalog. Fictional brands; prices are made up and drift deterministically per day."""

from __future__ import annotations

from datetime import date
from typing import Any


def _gtin(body: str) -> str:
    """Synthetic barcode with a valid check digit (demo data only)."""
    total = sum(int(d) * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(body)))
    return body + str((10 - total % 10) % 10)


SHOP: dict[str, list[dict[str, Any]]] = {
    "TECH": [
        {
            "id": "T-001",
            "title": "Demotron DX900 1TB NVMe PCIe 4.0 M.2 2280 SSD",
            "brand": "Demotron",
            "model": "DX900",
            "mpn": "DX900-1T",
            "base": 32_990,
            "shipping": "ingyenes",
            "warranty": "5 év gyártói garancia",
            "stock": "IN_STOCK",
        },
        {
            "id": "T-002",
            "title": "Demotron DX900 2TB NVMe PCIe 4.0 M.2 2280 SSD",
            "brand": "Demotron",
            "model": "DX900",
            "mpn": "DX900-2T",
            "base": 59_990,
            "shipping": "ingyenes",
            "warranty": "5 év gyártói garancia",
            "stock": "LIMITED",
        },
        {
            "id": "T-003",
            "title": "Fictiva Volt 32GB (2x16GB) DDR5 6000MHz memória",
            "brand": "Fictiva",
            "model": "Volt",
            "mpn": "FV-32-6000",
            "flash": True,  # demo: 25 % cheaper today at mock-shop-2
            "base": 41_990,
            "shipping": "1 490 Ft",
            "warranty": "3 év",
            "stock": "IN_STOCK",
        },
        {
            "id": "T-004",
            "title": "Demotron DX900 4TB NVMe SSD",
            "brand": "Demotron",
            "model": "DX900",
            "mpn": "DX900-4T",
            "base": None,
            "price_text": "Ár: hívjon",
            "shipping": "ingyenes",
            "warranty": "5 év",
            "stock": "IN_STOCK",
        },  # unusable: no price while in stock
    ],
    "APPAREL": [
        {
            "id": "A-001",
            "title": "Exemplar Runner 2 férfi futócipő",
            "brand": "Exemplar",
            "model": "Runner 2",
            "style_code": "EX-RUN2-01",
            "variant": "EU 42",
            "color": "fehér",
            "base": 29_990,
            "shipping": "1 290 Ft",
            "stock": "IN_STOCK",
        },
        {
            "id": "A-002",
            "title": "Exemplar Runner 2 férfi futócipő",
            "brand": "Exemplar",
            "model": "Runner 2",
            "style_code": "EX-RUN2-01",
            "variant": "EU 43",
            "color": "fehér",
            "base": 29_990,
            "shipping": "1 290 Ft",
            "stock": "OUT_OF_STOCK",
        },
    ],
    "FOOD": [
        {
            "id": "F-001",
            "title": "Mintakávé pörkölt őrölt kávé 500 g",
            "brand": "Mintakávé",
            "gtin": _gtin("599999000001"),
            "model": "Pörkölt őrölt kávé",
            "base": 2_490,
            "shipping": "990 Ft",
            "stock": "IN_STOCK",
            "condition": None,
            "attributes": {"Minőségét megőrzi": "2027.06.30."},
        },
        {
            "id": "F-002",
            "title": "Mintakávé pörkölt őrölt kávé 1 kg",
            "brand": "Mintakávé",
            "gtin": _gtin("599999000002"),
            "model": "Pörkölt őrölt kávé",
            "base": 4_590,
            "shipping": "990 Ft",
            "stock": "IN_STOCK",
            "condition": None,
        },
    ],
    "HOME": [
        {
            "id": "H-001",
            "title": "Probaline WM8000X elöltöltős mosógép",
            "brand": "Probaline",
            "model": "WM8000X",
            "base": 159_990,
            "shipping": "6 990 Ft",
            "warranty": "3 év",
            "stock": "IN_STOCK",
            "attributes": {
                "Méretek (Sz x Ma x Mé)": "60 x 85 x 55 cm",
                "Súly": "62 kg",
                "Energiaosztály": "A",
            },
        },
    ],
}

MARKET: dict[str, list[dict[str, Any]]] = {
    "TECH": [
        {
            "id": "m-101",
            "title": "Demotron DX900 1TB NVMe PCIe 4.0 SSD, keveset használt",
            "brand": "Demotron",
            "model": "DX900",
            "mpn": "DX900-1T",
            "base": 21_000,
            "shipping": "Csak személyes átvétel",
            "condition": "használt",
            "warranty": "nincs garancia",
            "stock": "UNKNOWN",
        },
    ],
    "HOME": [
        {
            "id": "m-301",
            "title": "Probaline WM8000X mosógép",
            "brand": "Probaline",
            "model": "WM8000X",
            "base": 85_000,
            "shipping": "Csak személyes átvétel",
            "condition": "használt",
            "warranty": "nincs garancia",
            "stock": "UNKNOWN",
            "attributes": {"Méretek (Sz x Ma x Mé)": "60 x 85 x 55 cm", "Súly": "62 kg"},
        },
    ],
}


def price_on(base: int, day: date, index: int) -> int:
    """Deterministic +-5 % daily drift, rounded to 10 HUF."""
    step = (day.toordinal() * 7 + index * 13) % 11 - 5
    return round(base * (100 + step) / 100 / 10) * 10


def huf_text(value: int) -> str:
    return f"{value:,}".replace(",", " ") + " Ft"
