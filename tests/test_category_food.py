from __future__ import annotations

from datetime import date

import pytest

from dealradar.categories.food.attributes import DateKind
from dealradar.categories.food.inputs import FoodEvaluationInputs
from dealradar.categories.food.normalize import parse_date
from dealradar.categories.registry import module_for
from dealradar.core.enums import CanonicalUnit, Category, IdType, MatchMethod
from dealradar.core.hu_parse import ParseError
from dealradar.matching.cascade import match
from dealradar.matching.types import OutcomeKind
from dealradar.services.catalog import evaluation_inputs
from tests.category_helpers import candidate, codes, error_codes, gtin, norm

FOOD = Category.FOOD
RULES = module_for(FOOD)
COLA = gtin("544900000099")


def cola(**kw: object):  # type: ignore[no-untyped-def]
    data: dict[str, object] = {
        "brand": "Coca-Cola",
        "model": "Coca-Cola Zero",
        "gtin": COLA,
        "price_text": "1 299 Ft",
        "condition_text": None,
    }
    data.update(kw)
    return norm(FOOD, "Coca-Cola Zero szénsavas üdítőital 6 x 330 ml", **data)


def test_pack_size_and_unit_price() -> None:
    listing = cola()
    assert listing.variant_key == "6X330ML"
    v, la = listing.variant_attrs, listing.listing_attrs
    assert (v.pack_count, v.each_amount, v.each_unit, v.total_canonical) == (6, "330", "ML", "1.98")
    assert listing.product_attrs.canonical_unit is CanonicalUnit.L
    assert la.unit_price_chuf == 65_606  # 1 299 / 1.98 l = 656.06 Ft/l
    assert error_codes(listing) == set()


def test_explicit_pack_attribute_wins_over_title() -> None:
    listing = norm(
        FOOD,
        "Pick téliszalámi",
        brand="Pick",
        price_text="3 490 Ft",
        condition_text=None,
        attributes={"Nettó tömeg": "0,4 kg", "Vonalkód": gtin("599000000003")},
    )
    assert listing.variant_key == "400G"
    assert listing.listing_attrs.unit_price_chuf == 872_500  # 8 725,00 Ft/kg
    assert listing.identifier(IdType.GTIN) is not None


@pytest.mark.parametrize(
    ("title", "code"),
    [
        ("Milka csokoládé 100 g + 20 g ajándék", "pack_size_ambiguous"),
        ("Milka csokoládé", "pack_size_missing"),
    ],
)
def test_pack_size_errors(title: str, code: str) -> None:
    listing = norm(FOOD, title, brand="Milka", condition_text=None)
    assert code in error_codes(listing)
    assert listing.listing_attrs.unit_price_chuf is None  # never computed from a guess


def test_shop_unit_price_is_cross_checked() -> None:
    ok = cola(attributes={"Egységár": "656,06 Ft/l"})
    assert ok.listing_attrs.shelf_unit_price_chuf == 65_606
    assert "unit_price_mismatch" not in codes(ok)
    off = cola(attributes={"Egységár": "599 Ft/l"})
    assert "unit_price_mismatch" in codes(off)
    wrong_unit = cola(attributes={"Egységár": "656 Ft/kg"})
    assert "unit_mismatch" in error_codes(wrong_unit)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2026.12.31.", date(2026, 12, 31)),
        ("2026-12-31", date(2026, 12, 31)),
        ("2026. 12. 31.", date(2026, 12, 31)),
        ("Minőségét megőrzi: 2027.01.15", date(2027, 1, 15)),
        ("31.12.2026", date(2026, 12, 31)),
    ],
)
def test_parse_date(text: str, expected: date) -> None:
    assert parse_date(text) == expected


def test_parse_date_rejects_ambiguous_slash_format() -> None:
    with pytest.raises(ParseError):
        parse_date("03/04/27")


@pytest.mark.parametrize(
    ("attrs", "code", "kind"),
    [
        ({"Minőségét megőrzi": "2026.11.20."}, "past_best_before", DateKind.BEST_BEFORE),
        ({"Fogyasztható": "2026.11.23."}, "expired_use_by", DateKind.USE_BY),
        ({"Minőségét megőrzi": "2026.11.28."}, "short_dated", DateKind.BEST_BEFORE),
    ],
)
def test_dates_relative_to_observation(attrs: dict[str, str], code: str, kind: DateKind) -> None:
    listing = cola(attributes=attrs)  # observed 2026-11-24
    assert code in codes(listing)
    assert listing.listing_attrs.date_kind is kind


def test_evaluation_inputs() -> None:
    inputs = evaluation_inputs(cola(attributes={"Minőségét megőrzi": "2027.03.01"}))
    assert isinstance(inputs, FoodEvaluationInputs)
    assert inputs.unit_price_chuf == 65_606 and inputs.canonical_unit is CanonicalUnit.L
    assert inputs.days_to_date == 97
    assert inputs.resale_applicable is False  # OPEN-5: food resale not applicable
    assert "condition" not in inputs.missing_inputs
    assert not inputs.needs_manual_review
    missing = evaluation_inputs(norm(FOOD, "Milka csokoládé", brand="Milka", condition_text=None))
    assert {"package_size", "unit_price"} <= set(missing.missing_inputs)


# --- matching ----------------------------------------------------------------------------------


def test_barcode_match() -> None:
    outcome = match(cola(model="Coke Zero dobozos"), [candidate(cola())], RULES)
    assert outcome.kind is OutcomeKind.AUTO_MATCH and outcome.method is MatchMethod.GTIN


def test_same_name_other_pack_size_is_same_product_new_variant() -> None:
    stored = candidate(cola(gtin=None))
    bottle = norm(
        FOOD,
        "Coca-Cola Zero 1,75 l",
        brand="Coca-Cola",
        model="Coca-Cola Zero",
        condition_text=None,
    )
    outcome = match(bottle, [stored], RULES)
    assert outcome.kind is OutcomeKind.REVIEW  # name rule is not decisive for food
    assert outcome.candidates[0].product_id == 1


def test_unit_mismatch_is_shown_with_the_contradiction() -> None:
    stored = candidate(cola(gtin=None), product_attrs={"canonical_unit": "KG"})
    outcome = match(cola(gtin=None), [stored], RULES)
    assert outcome.kind is OutcomeKind.REVIEW
    assert "contradict" in outcome.reasons[0]
    assert "unit" in outcome.candidates[0].reason and outcome.candidates[0].confidence == 40


def test_barcode_with_unit_contradiction_is_conflict() -> None:
    stored = candidate(cola(), product_attrs={"canonical_unit": "KG"})
    assert match(cola(), [stored], RULES).kind is OutcomeKind.CONFLICT
