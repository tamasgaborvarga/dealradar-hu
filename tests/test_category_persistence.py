"""Category modules on the shared database: schema fit, product creation, DB-backed matching."""

from __future__ import annotations

import pytest

from dealradar.categories.registry import module_for
from dealradar.core.enums import Category, ProductOrigin
from dealradar.db.models import Product, ProductVariant, VariantIdentifier
from dealradar.db.session import Database
from dealradar.matching.types import OutcomeKind
from dealradar.normalize.types import NormalizedListing
from dealradar.services.catalog import ATTRIBUTE_TABLES, create_product, match_listing
from tests.category_helpers import gtin, norm

TECH_EAN = gtin("880609000001")
SNEAKER_EAN = gtin("019400000001")
COLA = gtin("544900000099")


def listings() -> dict[Category, tuple[NormalizedListing, NormalizedListing]]:
    """(stored listing, later listing of the same item from another shop) per category."""
    return {
        Category.TECH: (
            norm(Category.TECH, "Samsung 990 PRO 2TB NVMe PCIe 4.0 SSD", brand="Samsung",
                 model="990 PRO", mpn="MZ-V9P2T0BW", gtin=TECH_EAN, warranty_text="5 év"),
            norm(Category.TECH, "SSD 2 TB Samsung 990PRO M.2", brand="SAMSUNG",
                 mpn="MZV9P2T0BW", external_id="shop-b:1"),
        ),
        Category.APPAREL: (
            norm(Category.APPAREL, "Nike Air Max 90 férfi", brand="Nike", model="Air Max 90",
                 style_code="DM0029-100", variant_text="EU 42", color_text="fehér"),
            norm(Category.APPAREL, "Air Max 90 fehér 43", brand="Nike", style_code="DM0029 100",
                 variant_text="EU 43", color_text="white", external_id="shop-b:1"),
        ),
        Category.FOOD: (
            norm(Category.FOOD, "Coca-Cola Zero 6 x 330 ml", brand="Coca-Cola",
                 model="Coca-Cola Zero", gtin=COLA, condition_text=None, price_text="1 299 Ft"),
            norm(Category.FOOD, "Coke Zero doboz 6x0,33l", gtin=COLA, condition_text=None,
                 price_text="1 199 Ft", external_id="shop-b:1"),
        ),
        Category.HOME: (
            norm(Category.HOME, "Samsung WW80T534DAW mosógép", brand="Samsung",
                 model="WW80T534DAW", warranty_text="3 év", shipping_text="4 990 Ft",
                 attributes={"Méretek (Sz x Ma x Mé)": "60 x 85 x 55 cm", "Súly": "65 kg"}),
            norm(Category.HOME, "Samsung mosógép WW80T534DAW 8kg", brand="Samsung",
                 model="WW80T534DAW", warranty_text="3 év", shipping_text="5 990 Ft",
                 external_id="shop-b:1"),
        ),
    }  # fmt: skip


@pytest.mark.parametrize("category", list(Category))
def test_every_product_attribute_has_a_column(category: Category) -> None:
    table = ATTRIBUTE_TABLES[category]
    columns = {c.key for c in table.__table__.columns}
    fields = set(module_for(category).product_attrs_model.model_fields)
    assert fields <= columns, fields - columns


@pytest.mark.parametrize("category", list(Category))
def test_store_then_match_from_another_listing(db: Database, category: Category) -> None:
    stored_listing, later = listings()[category]
    assert not stored_listing.has_errors, stored_listing.issues
    with db.write_session() as s:
        product, variant = create_product(s, stored_listing, ProductOrigin.RULE)
        product_id, variant_id = product.id, variant.id

    with db.read_session() as s:
        row = s.get(ATTRIBUTE_TABLES[category], product_id)
        assert row is not None
        stored = s.get(Product, product_id)
        assert stored is not None and stored.category is category
        assert stored.brand_key == stored_listing.brand_key

    outcome = match_listing(db, later)
    assert outcome.kind is OutcomeKind.AUTO_MATCH, outcome
    assert outcome.product_id == product_id
    if category is Category.APPAREL:
        assert outcome.variant_id is None  # EU43 is a new size of the same colourway
    else:
        assert outcome.variant_id == variant_id


def test_typed_attribute_values_round_trip(db: Database) -> None:
    listing = listings()[Category.TECH][0]
    with db.write_session() as s:
        product, variant = create_product(s, listing, ProductOrigin.USER)
        pid, vid = product.id, variant.id
    with db.read_session() as s:
        row = s.get(ATTRIBUTE_TABLES[Category.TECH], pid)
        v = s.get(ProductVariant, vid)
        assert row is not None and v is not None
        assert (row.kind, row.ssd_interface) == ("SSD", "NVME_PCIE4")
        assert v.variant_key == "2000GB" and v.variant_attrs == {"capacity_gb": 2000}


def test_same_part_number_at_two_manufacturers_can_coexist(db: Database) -> None:
    a = norm(
        Category.HOME,
        "Hűtő ABC12345",
        brand="Alpha",
        model="ABC12345",
        warranty_text="2 év",
        attributes={"Méretek (Sz x Ma x Mé)": "60 x 180 x 60 cm", "Súly": "70 kg"},
    )
    b = norm(
        Category.HOME, "Hűtő ABC12345", brand="Beta", model="ABC12345", warranty_text="2 év",
        attributes={"Méretek (Sz x Ma x Mé)": "60 x 180 x 60 cm", "Súly": "70 kg"},
    )  # fmt: skip
    with db.write_session() as s:
        create_product(s, a, ProductOrigin.USER)
        create_product(s, b, ProductOrigin.USER)
    with db.read_session() as s:
        values = sorted(v.value for v in s.query(VariantIdentifier).all())
    assert values == ["alpha|ABC12345", "beta|ABC12345"]


def test_rule_creation_requires_an_identifier(db: Database) -> None:
    listing = norm(Category.HOME, "Kanapé Oslo", brand="Butor", warranty_text="1 év")
    with pytest.raises(ValueError, match="ADR-015"), db.write_session() as s:
        create_product(s, listing, ProductOrigin.RULE)


def test_listing_with_errors_cannot_become_a_product(db: Database) -> None:
    listing = norm(Category.FOOD, "Milka csokoládé", brand="Milka", condition_text=None)
    assert listing.has_errors
    with pytest.raises(ValueError, match="pack_size_missing"), db.write_session() as s:
        create_product(s, listing, ProductOrigin.USER)


def test_candidates_are_limited_to_category(db: Database) -> None:
    tech = listings()[Category.TECH][0]
    with db.write_session() as s:
        create_product(s, tech, ProductOrigin.USER)
    home_listing = norm(Category.HOME, "Samsung 990 PRO", brand="Samsung", model="990 PRO")
    assert match_listing(db, home_listing).kind is OutcomeKind.NO_MATCH
