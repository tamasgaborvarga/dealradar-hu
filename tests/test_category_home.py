from __future__ import annotations

from dealradar.categories.home.attributes import DeliveryMethod
from dealradar.categories.home.inputs import HomeEvaluationInputs
from dealradar.categories.registry import module_for
from dealradar.core.enums import Category, Condition, IdType, ListingKind, MatchMethod, SellerKind
from dealradar.matching.cascade import match
from dealradar.matching.types import OutcomeKind
from dealradar.services.catalog import evaluation_inputs
from tests.category_helpers import candidate, codes, error_codes, norm

HOME = Category.HOME
RULES = module_for(HOME)


def washer(**kw: object):  # type: ignore[no-untyped-def]
    data: dict[str, object] = {
        "brand": "Samsung",
        "model": "WW80T534DAW",
        "warranty_text": "3 év gyártói garancia",
        "shipping_text": "4 990 Ft",
        "attributes": {
            "Méretek (Sz x Ma x Mé)": "60 x 85 x 55 cm",
            "Súly": "65 kg",
            "Energiaosztály": "A",
            "Zajszint": "72 dB",
            "Teljesítmény": "2,2 kW",
            "Kapacitás": "8 kg",
        },
    }
    data.update(kw)
    return norm(HOME, "Samsung WW80T534DAW elöltöltős mosógép 8 kg", **data)


def test_appliance_attributes() -> None:
    listing = washer()
    p = listing.product_attrs
    assert (p.width_mm, p.height_mm, p.depth_mm) == (600, 850, 550)
    assert (p.weight_g, p.energy_class, p.noise_db, p.power_w) == (65_000, "A", 72, 2_200)
    assert p.bulky is True  # heavier than the freight threshold
    assert p.tech_specs == {"kapacitás": "8 kg", "súly": "65 kg", "energiaosztály": "A",
                            "zajszint": "72 dB", "teljesítmény": "2,2 kW"}  # fmt: skip
    assert listing.listing_attrs.delivery_method is DeliveryMethod.FREIGHT
    assert not listing.listing_attrs.dimension_order_assumed
    mpn = listing.identifier(IdType.MPN)
    assert mpn is not None and mpn.value == "samsung|WW80T534DAW"  # model number used as MPN
    assert error_codes(listing) == set()


def test_separate_dimension_fields_and_small_parcel() -> None:
    listing = norm(
        HOME,
        "Philips HD9270 airfryer",
        brand="Philips",
        model="HD9270/90",
        warranty_text="2 év",
        attributes={
            "Szélesség": "31,5 cm",
            "Magasság": "31 cm",
            "Mélység": "43 cm",
            "Tömeg": "5,6 kg",
        },
    )
    p = listing.product_attrs
    assert (p.width_mm, p.height_mm, p.depth_mm, p.weight_g) == (315, 310, 430, 5_600)
    assert p.bulky is False
    assert listing.listing_attrs.delivery_method is DeliveryMethod.PARCEL


def test_unordered_dimensions_are_flagged() -> None:
    listing = washer(attributes={"Méretek": "60 x 85 x 55 cm", "Súly": "65 kg"})
    assert listing.listing_attrs.dimension_order_assumed
    assert "dimension_order_assumed" in codes(listing)


def test_assembly_and_built_in() -> None:
    shelf = norm(
        HOME,
        "Polc, lapra szerelt",
        brand="Ikea",
        model="Kallax",
        attributes={"Méretek": "77 x 147 x 39 cm"},
    )
    assert shelf.product_attrs.assembly_required is True
    oven = norm(HOME, "Bosch HBA534BS0 beépíthető sütő", brand="Bosch", model="HBA534BS0")
    assert oven.product_attrs.installation_required is True


def test_validation_rules() -> None:
    assert "manufacturer_missing" in error_codes(washer(brand=None, attributes={}))
    freight_no_cost = washer(shipping_text=None)
    assert "delivery_cost_unknown" in error_codes(freight_no_cost)
    assert "warranty_missing" in codes(washer(warranty_text=None))
    used = washer(
        listing_kind=ListingKind.CLASSIFIED, seller_kind=SellerKind.PRIVATE, condition_text=None
    )
    assert "condition_missing" in error_codes(used)


def test_pickup_only() -> None:
    listing = washer(shipping_text="Csak személyes átvétel", condition_text="használt")
    assert listing.listing_attrs.delivery_method is DeliveryMethod.PICKUP_ONLY
    assert listing.condition is Condition.USED
    inputs = evaluation_inputs(listing)
    assert "shipping" not in inputs.missing_inputs  # pickup: no shipping cost to know


def test_evaluation_inputs() -> None:
    inputs = evaluation_inputs(washer())
    assert isinstance(inputs, HomeEvaluationInputs)
    assert inputs.delivery_method is DeliveryMethod.FREIGHT and inputs.dimensions_known
    assert inputs.effective_price_huf == 14_990 and not inputs.needs_manual_review
    unknown = evaluation_inputs(norm(HOME, "Kanapé Oslo", brand="Butor", warranty_text="1 év"))
    assert "delivery_requirements" in unknown.missing_inputs


# --- matching ----------------------------------------------------------------------------------


def test_model_number_match() -> None:
    stored = candidate(washer())
    outcome = match(washer(attributes={}), [stored], RULES)
    assert outcome.kind is OutcomeKind.AUTO_MATCH and outcome.method is MatchMethod.MPN


def test_model_number_rule_key_is_decisive_without_mpn() -> None:
    stored = candidate(washer(), variants=())  # no stored identifiers
    outcome = match(washer(attributes={}), [stored], RULES)
    assert outcome.kind is OutcomeKind.AUTO_MATCH and outcome.method is MatchMethod.RULE


def test_descriptive_names_never_auto_match() -> None:
    sofa = norm(HOME, "Kanapé Oslo 3 személyes szürke", brand="Butor", model="Oslo kanapé")
    outcome = match(sofa, [candidate(sofa, variants=())], RULES)
    assert outcome.kind is OutcomeKind.REVIEW and outcome.candidates[0].method is MatchMethod.FUZZY


def test_dimension_difference_contradicts() -> None:
    stored = candidate(washer(), product_attrs={"width_mm": 600, "height_mm": 850, "depth_mm": 450})
    assert match(washer(), [stored], RULES).kind is OutcomeKind.CONFLICT
    within_tolerance = candidate(
        washer(), product_attrs={"width_mm": 598, "height_mm": 850, "depth_mm": 550}
    )
    assert match(washer(), [within_tolerance], RULES).kind is OutcomeKind.AUTO_MATCH
