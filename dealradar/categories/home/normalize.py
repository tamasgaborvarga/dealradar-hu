"""HOME normalization and validation: model number, dimensions, specs, delivery requirements."""

from __future__ import annotations

import re
from decimal import Decimal

from dealradar.categories.base import add_identifier, brand_from, scope_identifiers, search_text
from dealradar.categories.home.attributes import (
    DeliveryMethod,
    HomeListingAttrs,
    HomeProductAttrs,
    HomeVariantAttrs,
)
from dealradar.core.enums import IdType, ListingKind
from dealradar.core.hu_parse import ParseError, parse_hu_number
from dealradar.core.identifiers import text_key
from dealradar.normalize.types import Issue, NormalizedListing, Severity, issue

SCOPED_IDS = frozenset({IdType.MPN})
# Classification thresholds for "needs freight delivery" (documented heuristics, ADR-029).
FREIGHT_WEIGHT_G = 30_000
FREIGHT_LONGEST_SIDE_MM = 1_200

_MM = {"mm": Decimal(1), "cm": Decimal(10), "m": Decimal(1000)}
_NUM = r"\d+(?:[.,]\d+)?"
_TRIPLE = re.compile(
    rf"({_NUM})\s*[x\u00d7*]\s*({_NUM})\s*[x\u00d7*]\s*({_NUM})\s*(mm|cm|m)\b", re.I
)
_ORDER_HINT = re.compile(
    r"sz\s*[x\u00d7]\s*ma\s*[x\u00d7]\s*mé|w\s*[x\u00d7]\s*h\s*[x\u00d7]\s*d|szélesség\s*[x\u00d7]\s*magasság",
    re.I,
)
_LENGTH = re.compile(rf"({_NUM})\s*(mm|cm|m)\b", re.I)
_WEIGHT = re.compile(rf"({_NUM})\s*(kg|g)\b", re.I)
_POWER = re.compile(rf"({_NUM})\s*(kw|w)\b", re.I)
_NOISE = re.compile(r"(\d{2,3})\s*db\b", re.I)
_ENERGY = re.compile(r"(?<![A-Za-z])([A-G](?:\+{1,3})?)(?![A-Za-z+])")
_MODEL_CODE = re.compile(r"^(?=.*\d)(?=.*[A-Za-z])[A-Za-z0-9][A-Za-z0-9\-/.]{3,}$")
_ASSEMBLY_YES = re.compile(
    r"összeszerelendő|lapra szerelt|szerelést igényel|assembly required|önszerelős", re.I
)
_ASSEMBLY_NO = re.compile(r"összeszerelt állapotban|szerelt állapotban|fully assembled", re.I)
_BUILT_IN = re.compile(r"beépíthető|beépített|built[- ]?in|integrálható", re.I)
_DIM_ATTRS = (
    "méretek",
    "méret",
    "befoglaló méret",
    "dimensions",
    "méretek (sz x ma x mé)",
    "méret (sz x ma x mé)",
)
_USED_KEYS = {"gyártó", "márka", "brand", "manufacturer", "modell", "model", "típusszám", "típus"}


def _mm(amount: str, unit: str) -> int:
    return int((parse_hu_number(amount) * _MM[unit.lower()]).to_integral_value())


def _dimensions(listing: NormalizedListing) -> tuple[dict[str, int], bool, list[Issue]]:
    separate = {
        "width_mm": listing.attr("szélesség", "width"),
        "height_mm": listing.attr("magasság", "height"),
        "depth_mm": listing.attr("mélység", "depth"),
    }
    out: dict[str, int] = {}
    try:
        for field, text in separate.items():
            if text and (m := _LENGTH.search(text)):
                out[field] = _mm(m.group(1), m.group(2))
        if len(out) == 3:
            return out, False, []
        for key in _DIM_ATTRS:
            text = listing.attributes.get(key)
            if not text:
                continue
            m = _TRIPLE.search(text)
            if m:
                unit = m.group(4)
                w, h, d = (_mm(m.group(i), unit) for i in (1, 2, 3))
                ordered = bool(_ORDER_HINT.search(key) or _ORDER_HINT.search(text))
                return {"width_mm": w, "height_mm": h, "depth_mm": d}, not ordered, []
    except ParseError as exc:
        return {}, False, [issue("dimensions_unparsable", "dimensions", str(exc), Severity.WARNING)]
    return out, False, []


def _number_attr(
    listing: NormalizedListing, pattern: re.Pattern[str], *names: str
) -> re.Match[str] | None:
    text = listing.attr(*names)
    return pattern.search(text) if text else None


def normalize(listing: NormalizedListing) -> NormalizedListing:
    issues: list[Issue] = []
    updates = brand_from(listing, "gyártó", "márka", "manufacturer", "brand")
    brand_key = updates.get("brand_key", listing.brand_key)
    model = listing.model or listing.attr("típusszám", "modell", "model", "típus")
    if model and not listing.model:
        updates |= {"model": model, "model_key": text_key(model)}

    ids, id_issues = add_identifier(listing, IdType.GTIN, listing.attr("ean", "vonalkód", "gtin"))
    listing = listing.model_copy(update={"identifiers": ids})
    mpn_text = listing.attr("gyártói cikkszám", "cikkszám", "mpn")
    if mpn_text is None and model and _MODEL_CODE.fullmatch(model.replace(" ", "")):
        mpn_text = model  # appliance model numbers (e.g. "WW80T534DAW") are part numbers
    ids, mpn_issues = add_identifier(listing, IdType.MPN, mpn_text)
    issues += id_issues + mpn_issues

    dims, order_assumed, dim_issues = _dimensions(listing)
    issues += dim_issues
    product: dict[str, object] = dict(dims)
    try:
        if w := _number_attr(listing, _WEIGHT, "súly", "tömeg", "nettó súly", "weight"):
            factor = Decimal(1000) if w.group(2).lower() == "kg" else Decimal(1)
            product["weight_g"] = int(parse_hu_number(w.group(1)) * factor)
        if p := _number_attr(listing, _POWER, "teljesítmény", "power", "névleges teljesítmény"):
            factor = Decimal(1000) if p.group(2).lower() == "kw" else Decimal(1)
            product["power_w"] = int(parse_hu_number(p.group(1)) * factor)
    except ParseError as exc:
        issues.append(issue("spec_unparsable", "specs", str(exc), Severity.WARNING))
    if n := _number_attr(listing, _NOISE, "zajszint", "noise", "zajszint (db)"):
        product["noise_db"] = int(n.group(1))
    energy_text = listing.attr("energiaosztály", "energiahatékonysági osztály", "energy class")
    if energy_text and (e := _ENERGY.search(energy_text)):
        product["energy_class"] = e.group(1)
    product["kind"] = listing.attr("termékcsoport", "kategória", "category", "termék típusa")

    text = search_text(listing) + " " + (listing.description or "")
    if _ASSEMBLY_YES.search(text):
        product["assembly_required"] = True
    elif _ASSEMBLY_NO.search(text):
        product["assembly_required"] = False
    if _BUILT_IN.search(text):
        product["installation_required"] = True

    sides = [dims[k] for k in ("width_mm", "height_mm", "depth_mm") if k in dims]
    weight = product.get("weight_g")
    if (isinstance(weight, int) and weight >= FREIGHT_WEIGHT_G) or (
        sides and max(sides) >= FREIGHT_LONGEST_SIDE_MM
    ):
        product["bulky"] = True
    elif len(sides) == 3 and isinstance(weight, int):
        product["bulky"] = False

    product["tech_specs"] = {
        k: v for k, v in listing.attributes.items() if k not in _USED_KEYS and k not in _DIM_ATTRS
    }
    attrs = HomeProductAttrs.model_validate({k: v for k, v in product.items() if v is not None})

    if listing.pickup_only:
        delivery = DeliveryMethod.PICKUP_ONLY
    elif attrs.bulky:
        delivery = DeliveryMethod.FREIGHT
    elif attrs.bulky is False:
        delivery = DeliveryMethod.PARCEL
    else:
        delivery = DeliveryMethod.UNKNOWN

    listing = listing.model_copy(
        update={
            **updates,
            "identifiers": scope_identifiers(ids, brand_key, SCOPED_IDS),
            "product_attrs": attrs,
            "variant_attrs": HomeVariantAttrs(color=listing.color),
            "listing_attrs": HomeListingAttrs(
                delivery_method=delivery, dimension_order_assumed=order_assumed
            ),
            "variant_key": listing.color or "default",
        }
    )
    return listing.with_issues(*issues)


def validate(listing: NormalizedListing) -> list[Issue]:
    p, la = listing.product_attrs, listing.listing_attrs
    assert isinstance(p, HomeProductAttrs) and isinstance(la, HomeListingAttrs)
    out: list[Issue] = []
    warn = Severity.WARNING
    if not listing.brand:
        out.append(issue("manufacturer_missing", "manufacturer", "manufacturer unknown"))
    if not listing.model and not listing.identifiers:
        out.append(issue("no_identity", "identity", "no model number, EAN or MPN"))
    if not (p.width_mm and p.height_mm and p.depth_mm):
        out.append(issue("dimensions_missing", "dimensions", "dimensions unknown", warn))
    elif la.dimension_order_assumed:
        out.append(
            issue("dimension_order_assumed", "dimensions", "read as width x height x depth", warn)
        )
    if listing.warranty_months is None:
        out.append(issue("warranty_missing", "warranty", "warranty not stated", warn))
    if la.delivery_method is DeliveryMethod.FREIGHT and listing.shipping_huf is None:
        out.append(
            issue("delivery_cost_unknown", "delivery", "bulky item and delivery cost unknown")
        )
    if listing.listing_kind is not ListingKind.RETAIL and listing.condition is None:
        out.append(issue("condition_missing", "condition", "second-hand listing without condition"))
    return out
