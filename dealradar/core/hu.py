"""Hungarian user-facing text: labels for every enum value and code, and number / date formats.

Code, database values, logs and developer docs stay English (ADR-056). Everything the user sees
goes through this module, so the wording is consistent everywhere (UI, CLI, notifications).
A test checks that every enum member and every missing-input / review-flag code has a label.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

NBSP = "\u00a0"  # keeps "12 345 Ft" and "12,5 %" together on one line

try:
    LOCAL_TZ: ZoneInfo | None = ZoneInfo("Europe/Budapest")
except ZoneInfoNotFoundError:  # tzdata missing: fall back to UTC and say so
    LOCAL_TZ = None

LABELS: dict[str, dict[str, str]] = {
    "category": {
        "TECH": "Műszaki cikkek",
        "APPAREL": "Ruha, cipő, sport",
        "FOOD": "Élelmiszer",
        "HOME": "Otthon és háztartás",
    },
    "category_scope": {
        "TECH": "Processzorok, videokártyák, memóriák, SSD-k, laptopok, monitorok, elektronika",
        "APPAREL": "Ruházat, sneakerek, sportruházat és sportfelszerelés",
        "FOOD": "Csomagolt élelmiszer, bevásárlás, nagy kiszerelések",
        "HOME": "Háztartási gépek, bútor, konyha, kert és barkács",
    },
    "category_variant": {
        "TECH": "konfiguráció vagy kapacitás (pl. SSD-méret, RAM-készlet)",
        "APPAREL": "méret (a termék = márka + modell + színváltozat)",
        "FOOD": "kiszerelés (pl. 500 g, 6 x 330 ml)",
        "HOME": "szín, ha az árat befolyásolja, egyébként egy változat",
    },
    "personal_verdict": {
        "STRONG_DEAL": "Kiemelkedő ajánlat",
        "GOOD_DEAL": "Jó ajánlat",
        "FAIR_PRICE": "Átlagos ár",
        "NOT_A_DEAL": "Nem éri meg",
        "MANUAL_REVIEW": "Kézi ellenőrzés",
    },
    "resale_verdict": {
        "PROFITABLE": "Nyereséges",
        "MARGINAL": "Kis haszon",
        "NOT_PROFITABLE": "Nem nyereséges",
        "MANUAL_REVIEW": "Kézi ellenőrzés",
        "NOT_APPLICABLE": "Nem alkalmazható",
    },
    "decision": {
        "WATCH": "Figyelem",
        "REJECT": "Elutasítom",
        "RESTORE": "Visszaállítom",
        "BOUGHT": "Megvettem",
    },
    "reject_reason": {
        "TOO_EXPENSIVE": "Túl drága",
        "WRONG_MATCH": "Rossz termékpárosítás",
        "BAD_CONDITION": "Rossz állapot",
        "SUSPECTED_SCAM": "Gyanús, átverés lehet",
        "NOT_INTERESTED": "Nem érdekel",
        "OUT_OF_STOCK": "Nincs készleten",
        "OTHER": "Egyéb",
    },
    "intent": {"RESALE": "Továbbértékesítés", "PERSONAL": "Saját használat"},
    "item_status": {
        "IN_STOCK": "Raktáron",
        "LISTED": "Meghirdetve",
        "SOLD": "Eladva",
        "RETURNED_TO_SELLER": "Visszaküldve az eladónak",
        "WRITTEN_OFF": "Leírva",
        "PERSONAL_USE": "Saját használatban",
    },
    "tx_type": {
        "PURCHASE": "Vételár",
        "INBOUND_SHIPPING": "Beszállítás",
        "SALE": "Eladási ár",
        "PLATFORM_FEE": "Platformdíj",
        "PAYMENT_FEE": "Fizetési díj",
        "OUTBOUND_SHIPPING": "Kiszállítás",
        "PACKAGING": "Csomagolás",
        "REFUND_GIVEN": "Visszatérítés a vevőnek",
        "REFUND_RECEIVED": "Visszatérítés az eladótól",
        "TAX": "Adó",
        "OTHER_COST": "Egyéb költség",
        "OTHER_INCOME": "Egyéb bevétel",
    },
    "direction": {"IN": "Bevétel", "OUT": "Kiadás"},
    "condition": {
        "NEW": "Új",
        "OPEN_BOX": "Bontott",
        "REFURBISHED": "Felújított",
        "USED": "Használt",
        "USED_A": "Használt, kiváló",
        "USED_B": "Használt, jó",
        "USED_C": "Használt, elfogadható",
        "FOR_PARTS": "Alkatrésznek",
    },
    "availability": {
        "IN_STOCK": "Raktáron",
        "LIMITED": "Korlátozott készlet",
        "PREORDER": "Előrendelhető",
        "OUT_OF_STOCK": "Nincs készleten",
        "UNKNOWN": "Ismeretlen",
    },
    "listing_kind": {
        "RETAIL": "Webáruház",
        "MARKETPLACE": "Piactér",
        "CLASSIFIED": "Apróhirdetés",
        "AUCTION": "Aukció",
        "FLYER": "Akciós újság",
    },
    "seller_kind": {
        "RETAILER": "Kereskedő",
        "BUSINESS_SELLER": "Céges eladó",
        "PRIVATE": "Magánszemély",
    },
    "warranty_type": {
        "MANUFACTURER_HU": "gyártói, magyar",
        "MANUFACTURER_EU": "gyártói, EU-s",
        "SELLER": "eladói",
        "NONE": "nincs",
    },
    "match_status": {
        "UNMATCHED": "Nincs párosítva",
        "PENDING_REVIEW": "Ellenőrzésre vár",
        "MATCHED": "Párosítva",
        "REJECTED": "Elutasítva",
    },
    "match_method": {
        "GTIN": "Vonalkód",
        "MPN": "Gyártói cikkszám",
        "STYLE_CODE": "Modellkód",
        "RULE": "Szabály",
        "FUZZY": "Hasonlóság",
        "USER": "Kézi",
        "AI_SUGGESTED": "MI-javaslat",
    },
    "candidate_status": {
        "OPEN": "Nyitott",
        "ACCEPTED": "Elfogadva",
        "REJECTED": "Elutasítva",
        "SUPERSEDED": "Felülírva",
    },
    "source_status": {
        "DISABLED": "Kikapcsolva",
        "ACTIVE": "Aktív",
        "DEGRADED": "Akadozik",
        "BLOCKED": "Letiltva",
    },
    "run_status": {
        "RUNNING": "Fut",
        "OK": "Sikeres",
        "PARTIAL": "Részleges",
        "FAILED": "Sikertelen",
        "BLOCKED": "Letiltva",
    },
    "fetch_error": {
        "ACCESS_NOT_PERMITTED": "Hozzáférés nem engedélyezett",
        "ROBOTS_DISALLOWED": "A robots.txt tiltja",
        "BLOCKED": "A forrás letiltott",
        "RATE_LIMITED": "Túl sok kérés",
        "TIMEOUT": "Időtúllépés",
        "UNAVAILABLE": "A forrás nem elérhető",
        "CLIENT_ERROR": "Hibás kérés",
        "DAILY_CAP_REACHED": "Elérte a napi kérés-limitet",
        "PARSE_ERROR": "Feldolgozási hiba",
        "INVALID_RECORD": "Használhatatlan tétel",
        "INTERNAL": "Belső hiba",
    },
    "access_method": {
        "OFFICIAL_API": "Hivatalos API",
        "FEED": "Adatfolyam",
        "PUBLIC_HTML": "Nyilvános oldal",
        "PUBLIC_HTML_JS": "Nyilvános oldal (JavaScript)",
        "MANUAL": "Kézi",
        "MOCK": "Demó (szintetikus)",
    },
    "refresh_scope": {"SOURCE": "Egy forrás", "CATEGORY": "Egy kategória", "ALL": "Minden forrás"},
    "telegram_status": {
        "NOT_CONFIGURED": "Csak az appban",
        "SENT": "Telegramon elküldve",
        "FAILED": "Telegram sikertelen",
    },
    "watchlist": {
        "NOT_WATCHED": "Nincs figyelőlistán",
        "WATCHED": "Figyelőlistán",
        "TARGET_MET": "Célár elérve",
        "ABOVE_MAX_PRICE": "A maximális ár felett",
        "CONDITION_NOT_ACCEPTED": "Az állapot nem megfelelő",
    },
    "tax_kind": {
        "NONE_SELECTED": "Nincs kiválasztva",
        "NO_TAX_DECLARED": "Nem adózik (saját nyilatkozat)",
        "PERCENT_OF_PROFIT": "A haszon százaléka",
        "PERCENT_OF_REVENUE": "A bevétel százaléka",
    },
    "level": {"NONE": "Nincs", "LOW": "Alacsony", "MEDIUM": "Közepes", "HIGH": "Magas"},
    "liquidity": {
        "HIGH": "Gyorsan eladható",
        "MEDIUM": "Közepesen eladható",
        "LOW": "Lassan eladható",
        "UNKNOWN": "Nem ismert",
    },
    "value_kind": {
        "FACT": "Tény",
        "USER_INPUT": "Saját beállítás",
        "ESTIMATE": "Becslés",
        "ASSUMPTION": "Feltételezés",
    },
    "recommendation": {
        "CONSIDER": "Megfontolandó",
        "WAIT": "Érdemes várni",
        "AVOID": "Kerülendő",
        "NEEDS_MORE_INFO": "Több információ kell",
    },
    "risk_flag": {
        "COUNTERFEIT_RISK": "Hamisítvány lehet",
        "SCAM_RISK": "Átverés lehet",
        "WRONG_PRODUCT_MATCH": "Rossz termékpárosítás",
        "PRICE_ERROR_LIKELY": "Valószínű árhiba",
        "CONDITION_CONCERN": "Kérdéses állapot",
        "WARRANTY_CONCERN": "Kérdéses garancia",
        "SELLER_CONCERN": "Kérdéses eladó",
        "LISTING_INCONSISTENT": "Ellentmondásos hirdetés",
        "MISSING_KEY_INFO": "Hiányzó fontos adat",
        "OTHER": "Egyéb",
    },
    "schema_state": {
        "NOT_INITIALISED": "nincs létrehozva",
        "OUT_OF_DATE": "elavult",
        "UP_TO_DATE": "naprakész",
        "UNKNOWN_REVISION": "ismeretlen verzió",
    },
    "health_status": {"OK": "rendben", "WARN": "figyelmeztetés", "FAIL": "hiba"},
    "health_check": {
        "python_version": "Python-verzió",
        "sqlite_features": "SQLite-képességek",
        "data_dir_writable": "Adatmappa írható",
        "disk_free": "Szabad lemezhely",
        "db_connection": "Adatbázis",
        "schema": "Adatbázis-séma",
        "writer_lock": "Írási zár",
        "sources": "Források",
        "telegram": "Telegram",
        "ui_local_only": "Csak helyi elérés",
    },
    "benchmark_status": {
        "OK": "Rendben",
        "STALE": "Elavult",
        "INSUFFICIENT_DATA": "Kevés adat",
        "NO_DATA": "Nincs adat",
    },
    "sale_evidence": {
        "PLATFORM_FINAL_PRICE": "Platform által igazolt",
        "USER_REPORTED": "Saját rögzítés",
        "OWN_SALE": "Saját eladás",
    },
    # missing_inputs and review_flags codes produced by the engines and category modules
    "code": {
        "authenticity_unknown": "az eredetiség nem ellenőrizhető",
        "benchmark_condition_mismatch": "az összehasonlító ár más állapotú termékekből van",
        "benchmark_confidence_low": "az összehasonlító ár bizonytalan",
        "benchmark_stale": "az összehasonlító ár elavult",
        "completed_sales_confidence_low": "kevés vagy bizonytalan lezárt eladás",
        "completed_sales_stale": "a lezárt eladások régiek",
        "fee_profile_unverified": "a díjprofil nincs ellenőrizve",
        "kind_unknown": "a hirdetés típusa ismeretlen",
        "landed_benchmark_missing": "nincs szállítással együtt számolt összehasonlító ár",
        "match_confidence_low": "bizonytalan termékpárosítás",
        "match_not_confirmed": "a termékpárosítás nincs megerősítve",
        "new_without_warranty": "újként hirdetik, de garancia nélkül",
        "sales_condition_mismatch": "a lezárt eladások más állapotú termékekből vannak",
        "size_system_inferred": "a méretrendszer csak kikövetkeztetett",
        "tax_profile_unverified": "az adóprofil nincs ellenőrizve",
        "too_good_to_be_true": "gyanúsan olcsó",
        "brand": "márka",
        "completed_sales": "lezárt eladások",
        "condition": "állapot",
        "delivery_requirements": "szállítási feltételek",
        "fee_profile": "díjprofil",
        "outbound_shipping_cost": "kiszállítási költség",
        "package_size": "kiszerelés",
        "packaging_cost": "csomagolási költség",
        "pickup_travel_cost": "személyes átvétel útiköltsége",
        "price": "ár",
        "price_benchmark": "összehasonlító ár",
        "product_match": "termékpárosítás",
        "shipping": "szállítási díj",
        "size": "méret",
        "tax_profile": "adóprofil",
        "time_to_sell": "eladási idő",
        "unit_price": "egységár",
        "variant": "változat",
        "warranty": "garancia",
    },
}


def label(domain: str, value: object) -> str:
    """Hungarian label for an enum member or code; the raw value if none exists (never fails)."""
    if value is None:
        return "-"
    key = value.value if isinstance(value, Enum) else str(value)
    return LABELS.get(domain, {}).get(key, key)


def huf(value: int | None) -> str:
    """12345 -> "12 345 Ft" (non-breaking spaces); None -> "-"."""
    if value is None:
        return "-"
    sign = "-" if value < 0 else ""
    return f"{sign}{abs(value):,}".replace(",", NBSP) + f"{NBSP}Ft"


def pct(bp: int | None, signed: bool = True) -> str:
    """Basis points -> "+12,5 %" (Hungarian decimal comma)."""
    if bp is None:
        return "-"
    text = f"{bp / 100:+.1f}" if signed else f"{bp / 100:.1f}"
    return text.replace(".", ",") + f"{NBSP}%"


def local(dt: datetime) -> datetime:
    aware = dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)
    return aware.astimezone(LOCAL_TZ) if LOCAL_TZ is not None else aware


def when(dt: datetime | None, with_time: bool = True) -> str:
    """Local (Budapest) time in Hungarian order: "2026. 11. 24. 22:16"."""
    if dt is None:
        return "-"
    d = local(dt)
    text = f"{d:%Y}. {d:%m}. {d:%d}."
    if with_time:
        text += f" {d:%H:%M}"
    return text if LOCAL_TZ is not None else text + " (UTC)"


def codes(values: object) -> str:
    """Comma-separated Hungarian labels of missing-input / review-flag codes."""
    if not values:
        return "-"
    return ", ".join(label("code", v) for v in values)  # type: ignore[attr-defined]
