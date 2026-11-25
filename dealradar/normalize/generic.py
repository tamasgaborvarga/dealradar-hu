"""Category-independent normalization: price, shipping, condition, warranty, identifiers, colour.

Every field that cannot be read unambiguously becomes ``None`` plus an Issue - never a guess.
"""

from __future__ import annotations

import re

from dealradar.core.enums import Category, Condition, IdType, WarrantyType
from dealradar.core.hu_parse import ParseError, parse_price
from dealradar.core.identifiers import code_key, is_restricted_gtin, normalize_gtin, text_key
from dealradar.core.money import round_huf
from dealradar.normalize.text import clean_text
from dealradar.normalize.types import (
    MAX_ATTR_KEY,
    MAX_ATTR_VALUE,
    MAX_DESCRIPTION,
    MAX_TITLE,
    Identifier,
    Issue,
    NormalizedListing,
    RawListing,
    Severity,
    issue,
)

# Order matters: more specific phrases first.
_CONDITION_PATTERNS: tuple[tuple[re.Pattern[str], Condition], ...] = (
    (re.compile(r"alkatrész|hibás|for parts|nem működik|defekt", re.I), Condition.FOR_PARTS),
    (re.compile(r"felújított|refurb|renewed|gyárilag felújított", re.I), Condition.REFURBISHED),
    (re.compile(r"bontott|open[ -]?box|dobozsérült|kipróbált|bemutató", re.I), Condition.OPEN_BOX),
    (re.compile(r"újszerű|like new|mint az új", re.I), Condition.USED_A),
    (re.compile(r"\bhasznált\b|\bused\b|\bpre[- ]?owned\b", re.I), Condition.USED),
    (re.compile(r"\búj\b|\bnew\b|bontatlan|\bsealed\b|gyári csomagolás", re.I), Condition.NEW),
)
_FREE_SHIPPING = re.compile(r"ingyenes|díjmentes|\bfree\b|^\s*0\s*ft\.?\s*$", re.I)
_PICKUP = re.compile(r"személyes átvétel|csak személyesen|helyszíni átvétel|pickup only", re.I)
_NO_WARRANTY = re.compile(r"nincs garancia|garancia nélkül|no warranty|garancia: nincs", re.I)
_WARRANTY_PERIOD = re.compile(
    r"(\d{1,3})\s*(év|éves|year|years|yr|hónap|hónapos|hó|month|months)\b", re.I
)

COLORS: dict[str, str] = {
    "fekete": "BLACK", "black": "BLACK",
    "fehér": "WHITE", "white": "WHITE",
    "szürke": "GREY", "grey": "GREY", "gray": "GREY", "ezüst": "SILVER", "silver": "SILVER",
    "piros": "RED", "red": "RED", "vörös": "RED",
    "kék": "BLUE", "blue": "BLUE", "sötétkék": "NAVY", "navy": "NAVY",
    "zöld": "GREEN", "green": "GREEN", "khaki": "KHAKI",
    "sárga": "YELLOW", "yellow": "YELLOW",
    "narancs": "ORANGE", "narancssárga": "ORANGE", "orange": "ORANGE",
    "lila": "PURPLE", "purple": "PURPLE", "rózsaszín": "PINK", "pink": "PINK",
    "barna": "BROWN", "brown": "BROWN", "bézs": "BEIGE", "beige": "BEIGE",
    "arany": "GOLD", "gold": "GOLD", "többszínű": "MULTI", "multicolor": "MULTI",
}  # fmt: skip


def parse_condition(text: str | None) -> Condition | None:
    if not text:
        return None
    for pattern, condition in _CONDITION_PATTERNS:
        if pattern.search(text):
            return condition
    return None


def parse_shipping(text: str | None) -> tuple[int | None, bool, list[Issue]]:
    """-> (shipping_huf, pickup_only, issues). Unknown shipping stays None (never 0)."""
    if not text:
        return None, False, []
    if _PICKUP.search(text):
        return None, True, []
    if _FREE_SHIPPING.search(text):
        amounts = [re.sub(r"\D", "", n) for n in re.findall(r"\d[\d \u00a0.]*", text)]
        if any(a.strip("0") for a in amounts):  # "ingyenes 20 000 Ft felett" = conditional
            return (
                None,
                False,
                [
                    issue(
                        "shipping_conditional",
                        "shipping",
                        f"conditional: {text!r}",
                        Severity.WARNING,
                    )
                ],
            )
        return 0, False, []
    try:
        return int(round_huf(parse_price(text))), False, []
    except ParseError as exc:
        return None, False, [issue("shipping_unparsable", "shipping", str(exc), Severity.WARNING)]


def parse_warranty(text: str | None) -> tuple[int | None, WarrantyType | None, list[Issue]]:
    if not text:
        return None, None, []
    if _NO_WARRANTY.search(text):
        return 0, WarrantyType.NONE, []
    periods = {
        int(n) * (12 if unit.lower().startswith(("év", "year", "yr")) else 1)
        for n, unit in _WARRANTY_PERIOD.findall(text)
    }
    if len(periods) != 1:
        msg = "no warranty period found" if not periods else f"several periods: {sorted(periods)}"
        return None, None, [issue("warranty_unclear", "warranty", msg, Severity.WARNING)]
    months = periods.pop()
    wtype: WarrantyType | None = None
    lowered = text.lower()
    if "gyártói" in lowered or "manufacturer" in lowered:
        if re.search(r"magyar|hungar|\bhu\b", lowered):
            wtype = WarrantyType.MANUFACTURER_HU
        elif re.search(r"\beu\b|európai|european", lowered):
            wtype = WarrantyType.MANUFACTURER_EU
    elif "kereskedői" in lowered or "eladó" in lowered or "seller" in lowered:
        wtype = WarrantyType.SELLER
    return months, wtype, []


def parse_color(text: str | None) -> tuple[str | None, list[Issue]]:
    if not text:
        return None, []
    words = re.findall(r"[a-zá-űA-ZÁ-Ű]+", text.casefold())
    found = {COLORS[w] for w in words if w in COLORS}
    if len(found) == 1:
        return found.pop(), []
    if len(found) > 1:
        return "MULTI", []
    raw = clean_text(text, 40)
    return (raw.upper() if raw else None), [
        issue("color_unrecognized", "color", f"colour kept as written: {text!r}", Severity.WARNING)
    ]


def parse_identifiers(raw: RawListing) -> tuple[tuple[Identifier, ...], list[Issue]]:
    ids: list[Identifier] = []
    issues: list[Issue] = []
    if raw.gtin:
        try:
            value = normalize_gtin(raw.gtin)
        except ParseError as exc:
            issues.append(issue("gtin_invalid", "gtin", str(exc)))
        else:
            if is_restricted_gtin(raw.gtin):
                issues.append(
                    issue(
                        "gtin_restricted",
                        "gtin",
                        "store-internal / variable-weight barcode; not used as a global identifier",
                        Severity.WARNING,
                    )
                )
            else:
                ids.append(Identifier(id_type=IdType.GTIN, value=value, raw=raw.gtin))
    for id_type, text in ((IdType.MPN, raw.mpn), (IdType.STYLE_CODE, raw.style_code)):
        if not text:
            continue
        try:
            ids.append(Identifier(id_type=id_type, value=code_key(text), raw=text))
        except ParseError as exc:
            issues.append(issue(f"{id_type.lower()}_invalid", id_type.lower(), str(exc)))
    return tuple(ids), issues


def normalize_generic(raw: RawListing, category: Category) -> NormalizedListing:
    """Fields every category shares. Category modules refine the result."""
    issues: list[Issue] = []
    title = clean_text(raw.title, MAX_TITLE) or ""

    price_huf: int | None = None
    if raw.price_text is None:
        issues.append(issue("price_missing", "price", "no price on the listing"))
    else:
        try:
            price_huf = int(round_huf(parse_price(raw.price_text)))
        except ParseError as exc:
            issues.append(issue("price_unparsable", "price", str(exc)))
    if raw.price_is_net:
        issues.append(
            issue("price_is_net", "price", "net (VAT-exclusive) price; gross price unknown")
        )
        price_huf = None

    shipping, pickup_only, ship_issues = parse_shipping(raw.shipping_text)
    issues += ship_issues
    months, wtype, w_issues = parse_warranty(raw.warranty_text)
    issues += w_issues
    color, c_issues = parse_color(raw.color_text)
    issues += c_issues
    identifiers, id_issues = parse_identifiers(raw)
    issues += id_issues

    condition = parse_condition(raw.condition_text)
    if raw.condition_text and condition is None:
        issues.append(
            issue(
                "condition_unrecognized", "condition", f"unknown condition: {raw.condition_text!r}"
            )
        )

    attributes: dict[str, str] = {}
    for key, value in raw.attributes.items():
        k = clean_text(key, MAX_ATTR_KEY)
        v = clean_text(value, MAX_ATTR_VALUE)
        if k and v:
            attributes[k.casefold().rstrip(":")] = v

    brand = clean_text(raw.brand, 100)
    model = clean_text(raw.model, 200)
    return NormalizedListing(
        source_key=raw.source_key,
        external_id=raw.external_id,
        category=category,
        listing_kind=raw.listing_kind,
        observed_at=raw.observed_at,
        title=title,
        title_key=text_key(title) or "",
        description=clean_text(raw.description, MAX_DESCRIPTION),
        brand=brand,
        brand_key=text_key(brand),
        model=model,
        model_key=text_key(model),
        price_huf=price_huf,
        shipping_huf=shipping,
        pickup_only=pickup_only,
        condition=condition,
        warranty_months=months,
        warranty_type=wtype,
        seller_kind=raw.seller_kind,
        color=color,
        variant_text=clean_text(raw.variant_text, 100),
        identifiers=identifiers,
        attributes=attributes,
        variant_key=None,
        issues=tuple(issues),
    )
