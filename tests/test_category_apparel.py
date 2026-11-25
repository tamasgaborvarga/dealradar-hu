from __future__ import annotations

from dataclasses import replace

import pytest

from dealradar.categories.apparel.attributes import AuthenticityRisk, Gender, Season
from dealradar.categories.apparel.inputs import ApparelEvaluationInputs
from dealradar.categories.apparel.normalize import SizeError, parse_size
from dealradar.categories.registry import module_for
from dealradar.core.enums import Category, IdType, ListingKind, MatchMethod, SellerKind, SizeSystem
from dealradar.matching.cascade import match
from dealradar.matching.types import OutcomeKind, VariantCandidate
from dealradar.services.catalog import evaluation_inputs
from tests.category_helpers import candidate, codes, error_codes, gtin, norm

APPAREL = Category.APPAREL
RULES = module_for(APPAREL)


def sneaker(**kw: object):  # type: ignore[no-untyped-def]
    data: dict[str, object] = {
        "brand": "Nike",
        "model": "Air Max 90",
        "style_code": "DM0029-100",
        "variant_text": "42",
        "color_text": "fehér",
    }
    data.update(kw)
    return norm(APPAREL, "Nike Air Max 90 férfi sportcipő", **data)


@pytest.mark.parametrize(
    ("text", "system", "value", "inferred"),
    [
        ("42", SizeSystem.EU, "42", True),
        ("EU 42", SizeSystem.EU, "42", False),
        ("42,5 EU", SizeSystem.EU, "42.5", False),
        ("42 2/3", SizeSystem.EU, "42-2/3", True),
        ("US 9", SizeSystem.US, "9", False),
        ("9 US", SizeSystem.US, "9", False),
        ("UK 8.5", SizeSystem.UK, "8.5", False),
        ("m", SizeSystem.INT, "M", False),
        ("XXL", SizeSystem.INT, "2XL", False),
        ("2XL", SizeSystem.INT, "2XL", False),
        ("W32 L34", SizeSystem.INT, "W32L34", False),
        ("W32/L34", SizeSystem.INT, "W32L34", False),
        ("Egy méret", SizeSystem.INT, "ONESIZE", False),
    ],
)
def test_parse_size(text: str, system: SizeSystem, value: str, inferred: bool) -> None:
    size = parse_size(text)
    assert (size.system, size.value, size.inferred) == (system, value, inferred)


@pytest.mark.parametrize("text", ["9", "128", "nagy", "42-44"])
def test_parse_size_rejects_unclear(text: str) -> None:
    with pytest.raises(SizeError):
        parse_size(text)  # a bare 9 could be US, UK or kids - never guessed


def test_sneaker_attributes() -> None:
    listing = sneaker()
    p, v = listing.product_attrs, listing.variant_attrs
    assert (p.gender, p.color) == (Gender.MEN, "WHITE")
    assert (v.size, v.size_system, v.size_inferred) == ("42", SizeSystem.EU, True)
    assert listing.variant_key == "EU42"
    style = listing.identifier(IdType.STYLE_CODE)
    assert style is not None and style.value == "nike|DM0029100"
    assert "size_system_inferred" in codes(listing)
    assert error_codes(listing) == set()


def test_spec_table_fallbacks_and_season() -> None:
    listing = norm(
        APPAREL,
        "Női téli kabát",
        attributes={"Márka": "Columbia", "Méret": "M", "Szín": "fekete", "Cikkszám": "WK1234"},
    )
    assert listing.brand == "Columbia"
    assert listing.product_attrs.gender is Gender.WOMEN
    assert listing.product_attrs.season is Season.AUTUMN_WINTER
    assert listing.variant_key == "INTM"
    assert listing.product_attrs.color == "BLACK"


@pytest.mark.parametrize(
    ("overrides", "risk"),
    [
        ({}, AuthenticityRisk.LOW),
        (
            {"listing_kind": ListingKind.MARKETPLACE, "seller_kind": SellerKind.BUSINESS_SELLER},
            AuthenticityRisk.MEDIUM,
        ),
        (
            {"listing_kind": ListingKind.CLASSIFIED, "seller_kind": SellerKind.PRIVATE},
            AuthenticityRisk.MEDIUM,
        ),
        ({"seller_kind": None}, AuthenticityRisk.UNKNOWN),
        ({"description": "Prémium replika, 1:1 minőség"}, AuthenticityRisk.HIGH),
    ],
)
def test_authenticity_risk(overrides: dict[str, object], risk: AuthenticityRisk) -> None:
    listing = sneaker(**overrides)
    assert listing.listing_attrs.authenticity_risk is risk
    if risk is AuthenticityRisk.HIGH:
        assert "authenticity_high" in error_codes(listing)


def test_validation_rules() -> None:
    assert "size_missing" in error_codes(sneaker(variant_text=None))
    assert "brand_missing" in error_codes(sneaker(brand=None))
    assert "size_unrecognized" in error_codes(sneaker(variant_text="9"))


def test_evaluation_inputs() -> None:
    inputs = evaluation_inputs(sneaker(variant_text="EU 42"))
    assert isinstance(inputs, ApparelEvaluationInputs)
    assert inputs.size == "42" and inputs.authenticity_risk is AuthenticityRisk.LOW
    assert not inputs.needs_manual_review
    risky = evaluation_inputs(sneaker(seller_kind=None))
    assert "authenticity_unknown" in risky.review_flags
    inferred = evaluation_inputs(sneaker())
    assert "size_system_inferred" in inferred.review_flags


# --- matching ----------------------------------------------------------------------------------


def test_style_code_match_resolves_size_variant() -> None:
    stored = candidate(sneaker(variant_text="EU 42"))
    other_size = VariantCandidate(variant_id=11, variant_key="EU43")
    outcome = match(
        sneaker(variant_text="EU 43"),
        [replace(stored, variants=(*stored.variants, other_size))],
        RULES,
    )
    assert outcome.kind is OutcomeKind.AUTO_MATCH
    assert outcome.method is MatchMethod.STYLE_CODE and outcome.variant_id == 11


def test_new_size_matches_product_but_reports_unknown_variant() -> None:
    outcome = match(
        sneaker(variant_text="EU 44"), [candidate(sneaker(variant_text="EU 42"))], RULES
    )
    assert outcome.kind is OutcomeKind.AUTO_MATCH and outcome.variant_id is None
    assert any("EU44" in r for r in outcome.reasons)


def test_gtin_pins_one_size() -> None:
    code = gtin("019400000001")
    stored = candidate(sneaker(style_code=None, gtin=code, variant_text="EU 42"))
    outcome = match(sneaker(style_code=None, gtin=code, variant_text="EU 42"), [stored], RULES)
    assert outcome.kind is OutcomeKind.AUTO_MATCH and outcome.method is MatchMethod.GTIN


def test_different_colour_contradicts() -> None:
    stored = candidate(sneaker())
    outcome = match(sneaker(color_text="fekete"), [stored], RULES)
    assert outcome.kind is OutcomeKind.CONFLICT


def test_unisex_compatible_but_kids_not() -> None:
    stored = candidate(sneaker(), product_attrs={"gender": "UNISEX", "color": "WHITE"})
    assert match(sneaker(), [stored], RULES).kind is OutcomeKind.AUTO_MATCH
    kids = candidate(sneaker(), product_attrs={"gender": "KIDS", "color": "WHITE"})
    assert match(sneaker(), [kids], RULES).kind is OutcomeKind.CONFLICT


def test_brand_model_colour_needs_review() -> None:
    stored = candidate(sneaker(style_code=None))
    outcome = match(sneaker(style_code=None), [stored], RULES)
    assert outcome.kind is OutcomeKind.REVIEW
