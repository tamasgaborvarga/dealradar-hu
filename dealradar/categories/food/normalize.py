"""FOOD normalization and validation: barcode, pack size, unit price, best-before / use-by."""

from __future__ import annotations

import re
from datetime import date

from dealradar.categories.base import add_identifier, brand_from
from dealradar.categories.food.attributes import (
    DateKind,
    FoodListingAttrs,
    FoodProductAttrs,
    FoodVariantAttrs,
)
from dealradar.core.enums import IdType
from dealradar.core.hu_parse import ParseError
from dealradar.core.identifiers import text_key
from dealradar.core.money import Huf
from dealradar.core.units import (
    PackSize,
    find_pack_sizes,
    parse_pack_size,
    parse_unit_price_chuf,
    unit_price_chuf,
)
from dealradar.normalize.types import Issue, NormalizedListing, Severity, issue

SHORT_DATED_DAYS = 7
UNIT_PRICE_TOLERANCE_BP = 100  # 1 % difference between shop label and computed unit price

_PACK_ATTRS = (
    "kiszerelés",
    "nettó tömeg",
    "nettó mennyiség",
    "net weight",
    "tömeg",
    "űrtartalom",
    "mennyiség",
)
_BB_ATTRS = (
    "minőségét megőrzi",
    "minőség megőrzési idő",
    "min. megőrzési idő",
    "best before",
    "lejárat",
)
_UB_ATTRS = ("fogyasztható", "use by", "felhasználható")
_DATE = re.compile(
    r"\b(?P<y>20\d{2})[.\-/]\s?(?P<m>\d{1,2})[.\-/]\s?(?P<d>\d{1,2})\.?"
    r"|\b(?P<d2>\d{1,2})\.\s?(?P<m2>\d{1,2})\.\s?(?P<y2>20\d{2})\b"
)


def parse_date(text: str) -> date:
    """'2026.12.31.', '2026-12-31', '2026. 12. 31.', '31.12.2026'. Slash D/M forms are ambiguous."""
    m = _DATE.search(text)
    if not m:
        raise ParseError(f"no date in {text!r}")
    if m["y"]:
        return date(int(m["y"]), int(m["m"]), int(m["d"]))
    return date(int(m["y2"]), int(m["m2"]), int(m["d2"]))


def _pack(listing: NormalizedListing) -> tuple[PackSize | None, list[Issue]]:
    explicit = listing.variant_text or listing.attr(*_PACK_ATTRS)
    if explicit:
        try:
            return parse_pack_size(explicit), []
        except ParseError:
            found = find_pack_sizes(explicit)
            if len(found) == 1:
                return found[0], []
            return None, [
                issue("pack_size_unparsable", "package_size", f"cannot read {explicit!r}")
            ]
    found = find_pack_sizes(listing.title)
    if len(found) == 1:
        return found[0], []
    if len(found) > 1:
        sizes = ", ".join(p.key() for p in found)
        return None, [
            issue("pack_size_ambiguous", "package_size", f"several sizes in title: {sizes}")
        ]
    return None, [issue("pack_size_missing", "package_size", "package size unknown")]


def _dates(listing: NormalizedListing) -> tuple[date | None, DateKind | None, list[Issue]]:
    for names, kind in ((_UB_ATTRS, DateKind.USE_BY), (_BB_ATTRS, DateKind.BEST_BEFORE)):
        text = listing.attr(*names)
        if text:
            try:
                return parse_date(text), kind, []
            except (ParseError, ValueError) as exc:
                return (
                    None,
                    None,
                    [issue("date_unparsable", "best_before", str(exc), Severity.WARNING)],
                )
    return None, None, []


def normalize(listing: NormalizedListing) -> NormalizedListing:
    issues: list[Issue] = []
    updates = brand_from(listing, "márka", "gyártó", "brand", "manufacturer")
    name = listing.model or listing.attr("terméknév", "megnevezés", "product name")
    if name and not listing.model:
        updates |= {"model": name, "model_key": text_key(name)}

    ids, id_issues = add_identifier(
        listing, IdType.GTIN, listing.attr("vonalkód", "ean", "ean kód", "gtin", "barcode")
    )
    issues += id_issues

    pack, pack_issues = _pack(listing)
    issues += pack_issues

    computed: int | None = None
    if pack is not None and listing.price_huf is not None:
        computed = unit_price_chuf(Huf(listing.price_huf), pack)
    shelf: int | None = None
    shelf_text = listing.attr("egységár", "unit price", "kilogrammonkénti ár", "literenkénti ár")
    if shelf_text:
        try:
            shelf, shelf_unit = parse_unit_price_chuf(shelf_text)
            if pack is not None and shelf_unit is not pack.canonical_unit:
                issues.append(
                    issue(
                        "unit_mismatch",
                        "unit_price",
                        f"shop unit {shelf_unit} vs pack {pack.canonical_unit}",
                    )
                )
                shelf = None
        except ParseError as exc:
            issues.append(issue("unit_price_unparsable", "unit_price", str(exc), Severity.WARNING))

    best_before, date_kind, date_issues = _dates(listing)
    issues += date_issues

    variant = FoodVariantAttrs(
        pack_count=pack.count if pack else None,
        each_amount=format(pack.each.amount, "f") if pack else None,
        each_unit=pack.each.unit.value if pack else None,
        total_canonical=format(pack.total_canonical.normalize(), "f") if pack else None,
    )
    listing = listing.model_copy(
        update={
            **updates,
            "identifiers": ids,
            "product_attrs": FoodProductAttrs(canonical_unit=pack.canonical_unit if pack else None),
            "variant_attrs": variant,
            "listing_attrs": FoodListingAttrs(
                unit_price_chuf=computed,
                shelf_unit_price_chuf=shelf,
                best_before=best_before,
                date_kind=date_kind,
            ),
            "variant_key": pack.key() if pack else None,
        }
    )
    return listing.with_issues(*issues)


def validate(listing: NormalizedListing) -> list[Issue]:
    la = listing.listing_attrs
    assert isinstance(la, FoodListingAttrs)
    out: list[Issue] = []
    warn = Severity.WARNING
    if not listing.brand:
        out.append(issue("brand_missing", "brand", "brand unknown", warn))
    if listing.identifier(IdType.GTIN) is None and not (listing.brand and listing.model):
        out.append(issue("no_identity", "identity", "no barcode and no brand + product name"))
    if la.unit_price_chuf is not None and la.shelf_unit_price_chuf is not None:
        diff = abs(la.unit_price_chuf - la.shelf_unit_price_chuf) * 10_000
        if diff > UNIT_PRICE_TOLERANCE_BP * la.shelf_unit_price_chuf:
            out.append(
                issue(
                    "unit_price_mismatch",
                    "unit_price",
                    f"computed {la.unit_price_chuf / 100:.2f} vs "
                    f"shop {la.shelf_unit_price_chuf / 100:.2f} HUF",
                    warn,
                )
            )
    if la.best_before is not None:
        days = (la.best_before - listing.observed_at.date()).days
        if days < 0:
            code = "expired_use_by" if la.date_kind is DateKind.USE_BY else "past_best_before"
            out.append(issue(code, "best_before", f"date {la.best_before} is {-days} days ago"))
        elif days <= SHORT_DATED_DAYS:
            out.append(issue("short_dated", "best_before", f"{days} days left", warn))
    return out
