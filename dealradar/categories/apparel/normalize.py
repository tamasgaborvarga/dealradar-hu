"""CLOTHING_SHOES_SPORT normalization/validation: size, colour, gender, season, authenticity."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

from dealradar.categories.apparel.attributes import (
    ApparelListingAttrs,
    ApparelProductAttrs,
    ApparelVariantAttrs,
    AuthenticityRisk,
    Gender,
    Season,
)
from dealradar.categories.base import add_identifier, brand_from, scope_identifiers
from dealradar.core.enums import IdType, ListingKind, SellerKind, SizeSystem
from dealradar.core.identifiers import text_key
from dealradar.normalize.generic import parse_color
from dealradar.normalize.types import Issue, NormalizedListing, Severity, issue

SCOPED_IDS = frozenset({IdType.MPN, IdType.STYLE_CODE})

_LETTER = {"XXS": "2XS", "XS": "XS", "S": "S", "M": "M", "L": "L", "XL": "XL", "XXL": "2XL",
           "2XL": "2XL", "XXXL": "3XL", "3XL": "3XL", "4XL": "4XL", "5XL": "5XL"}  # fmt: skip
_COUNTERFEIT_WORDS = re.compile(
    r"replik|replica|\b1:1\b|\baaa\+?\b|utángyártott|nem eredeti|\bfake\b|mirror quality|hasonmás",
    re.I,
)
_GENDER = (
    (re.compile(r"\b(gyerek|junior|kids?|youth|gs|ps|td)\b", re.I), Gender.KIDS),
    (re.compile(r"\bunisex\b", re.I), Gender.UNISEX),
    (re.compile(r"\b(női|noi|women'?s?|wmns|lady|ladies)\b", re.I), Gender.WOMEN),
    (re.compile(r"\b(férfi|ferfi|men'?s?)\b", re.I), Gender.MEN),
)
_SEASON = (
    (re.compile(r"egész éves|all[- ]season|négy évszak", re.I), Season.ALL_SEASON),
    (re.compile(r"tavaszi|nyári|spring|summer", re.I), Season.SPRING_SUMMER),
    (re.compile(r"őszi|téli|autumn|fall|winter", re.I), Season.AUTUMN_WINTER),
)


@dataclass(frozen=True)
class Size:
    system: SizeSystem
    value: str
    inferred: bool = False

    @property
    def key(self) -> str:
        return f"{self.system}{self.value}"


class SizeError(ValueError):
    pass


def parse_size(text: str) -> Size:
    """'42', 'EU 42,5', '42 2/3', 'US 9', 'UK 8', 'M', 'XXL', 'W32 L34', 'egy méret'."""
    s = re.sub(r"\s+", " ", text.strip()).upper().replace(",", ".")
    if re.fullmatch(r"(EGY ?MÉRET|ONE ?SIZE|OS|UNI)", s):
        return Size(SizeSystem.INT, "ONESIZE")
    m = re.fullmatch(r"W ?(\d{2}) ?[/ ]? ?L ?(\d{2})", s)
    if m:
        return Size(SizeSystem.INT, f"W{m.group(1)}L{m.group(2)}")
    if s in _LETTER:
        return Size(SizeSystem.INT, _LETTER[s])
    m = re.fullmatch(r"(?:(EU|US|UK)\s?)?(\d{1,2}(?:\.5)?)(?:\s?(\d)/(3))?(?:\s?(EU|US|UK))?", s)
    if m:
        system_text = m.group(1) or m.group(5)
        number = m.group(2)
        frac = f"-{m.group(3)}/3" if m.group(3) else ""
        if system_text:
            return Size(SizeSystem(system_text), number + frac)
        if 30 <= Decimal(number) <= 50:
            return Size(SizeSystem.EU, number + frac, inferred=True)
        raise SizeError(f"size system unclear for {text!r}")
    raise SizeError(f"unrecognized size {text!r}")


def authenticity(listing: NormalizedListing) -> ApparelListingAttrs:
    text = f"{listing.title} {listing.description or ''}"
    if _COUNTERFEIT_WORDS.search(text):
        return ApparelListingAttrs(
            authenticity_risk=AuthenticityRisk.HIGH,
            authenticity_reasons=("listing text mentions replica / non-original",),
        )
    if listing.listing_kind is ListingKind.RETAIL and listing.seller_kind is SellerKind.RETAILER:
        return ApparelListingAttrs(
            authenticity_risk=AuthenticityRisk.LOW, authenticity_reasons=("sold by the retailer",)
        )
    if listing.seller_kind in (
        SellerKind.PRIVATE,
        SellerKind.BUSINESS_SELLER,
    ) or listing.listing_kind in (
        ListingKind.MARKETPLACE,
        ListingKind.CLASSIFIED,
        ListingKind.AUCTION,
    ):
        return ApparelListingAttrs(
            authenticity_risk=AuthenticityRisk.MEDIUM,
            authenticity_reasons=("third-party or private seller; authenticity not verifiable",),
        )
    return ApparelListingAttrs(
        authenticity_risk=AuthenticityRisk.UNKNOWN, authenticity_reasons=("seller type unknown",)
    )


def _first[T](patterns: tuple[tuple[re.Pattern[str], T], ...], text: str) -> T | None:
    for pattern, value in patterns:
        if pattern.search(text):
            return value
    return None


def normalize(listing: NormalizedListing) -> NormalizedListing:
    issues: list[Issue] = []
    updates = brand_from(listing, "márka", "brand", "gyártó")
    brand_key = updates.get("brand_key", listing.brand_key)
    model = listing.model or listing.attr("modell", "model", "terméknév")
    if model and not listing.model:
        updates |= {"model": model, "model_key": text_key(model)}

    ids, id_issues = add_identifier(listing, IdType.GTIN, listing.attr("ean", "vonalkód", "gtin"))
    listing = listing.model_copy(update={"identifiers": ids})
    ids, sc_issues = add_identifier(
        listing,
        IdType.STYLE_CODE,
        listing.attr("cikkszám", "termékkód", "style code", "style", "modellszám", "sku"),
    )
    issues += id_issues + sc_issues

    color = listing.color
    if color is None:
        color, c_issues = parse_color(listing.attr("szín", "color", "colour", "színárnyalat"))
        issues += c_issues

    gender_text = listing.attr("nem", "gender", "célcsoport") or listing.title
    season_text = listing.attr("évszak", "szezon", "season") or listing.title
    gender = _first(_GENDER, gender_text)
    season = _first(_SEASON, season_text)

    size: Size | None = None
    raw_variant = listing.variant_text or listing.attr("méret", "size", "cipőméret")
    if raw_variant:
        try:
            size = parse_size(raw_variant)
        except SizeError as exc:
            issues.append(issue("size_unrecognized", "size", str(exc)))
    product = ApparelProductAttrs(
        gender=gender,
        fit=listing.attr("fazon", "szabás", "fit"),
        color=color,
        season=season,
        material=listing.attr("anyag", "material", "anyagösszetétel"),
        size_system=size.system if size else None,
    )
    listing = listing.model_copy(
        update={
            **updates,
            "color": color,
            "identifiers": scope_identifiers(ids, brand_key, SCOPED_IDS),
            "product_attrs": product,
            "variant_attrs": ApparelVariantAttrs(
                size=size.value if size else None,
                size_system=size.system if size else None,
                size_inferred=size.inferred if size else False,
            ),
            "listing_attrs": authenticity(listing),
            "variant_key": size.key if size else None,
        }
    )
    return listing.with_issues(*issues)


def validate(listing: NormalizedListing) -> list[Issue]:
    p, v, la = listing.product_attrs, listing.variant_attrs, listing.listing_attrs
    assert isinstance(p, ApparelProductAttrs) and isinstance(v, ApparelVariantAttrs)
    assert isinstance(la, ApparelListingAttrs)
    out: list[Issue] = []
    warn = Severity.WARNING
    if not listing.brand:
        out.append(issue("brand_missing", "brand", "brand unknown"))
    if v.size is None:
        out.append(issue("size_missing", "size", "size unknown; prices are compared per size"))
    elif v.size_inferred:
        out.append(issue("size_system_inferred", "size", f"bare size {v.size} read as EU", warn))
    if p.color is None:
        out.append(issue("color_missing", "color", "colour unknown", warn))
    if p.gender is None:
        out.append(issue("gender_missing", "gender", "gender / fit group unknown", warn))
    if la.authenticity_risk is AuthenticityRisk.HIGH:
        out.append(issue("authenticity_high", "authenticity", "; ".join(la.authenticity_reasons)))
    if listing.listing_kind is not ListingKind.RETAIL and listing.condition is None:
        out.append(issue("condition_missing", "condition", "second-hand listing without condition"))
    return out
