from __future__ import annotations

from dataclasses import replace

from dealradar.categories.registry import module_for
from dealradar.categories.tech.attributes import SsdInterface, TechKind
from dealradar.categories.tech.inputs import TechEvaluationInputs
from dealradar.core.enums import Category, IdType, ListingKind, MatchMethod, SellerKind
from dealradar.matching.cascade import match
from dealradar.matching.types import OutcomeKind, VariantCandidate
from dealradar.services.catalog import evaluation_inputs
from tests.category_helpers import candidate, codes, error_codes, gtin, norm

TECH = Category.TECH
RULES = module_for(TECH)
SSD_GTIN = gtin("880609000001")


def ssd(**kw: object):  # type: ignore[no-untyped-def]
    data: dict[str, object] = {
        "brand": "Samsung",
        "model": "990 PRO",
        "mpn": "MZ-V9P2T0BW",
        "gtin": SSD_GTIN,
        "warranty_text": "5 év gyártói garancia",
    }
    data.update(kw)
    return norm(TECH, "Samsung 990 PRO 2TB NVMe PCIe 4.0 M.2 2280 SSD", **data)


# --- normalization ------------------------------------------------------------------------------


def test_ssd_attributes() -> None:
    listing = ssd()
    p, v = listing.product_attrs, listing.variant_attrs
    assert p.kind is TechKind.SSD
    assert p.ssd_interface is SsdInterface.NVME_PCIE4
    assert p.ssd_form_factor == "M.2 2280"
    assert v.capacity_gb == 2000  # storage: 1 TB = 1000 GB
    assert listing.variant_key == "2000GB"
    mpn = listing.identifier(IdType.MPN)
    assert mpn is not None and mpn.value == "samsung|MZV9P2T0BW"  # manufacturer-scoped
    assert error_codes(listing) == set()


def test_ram_kit() -> None:
    listing = norm(
        TECH, "Kingston FURY Beast 32GB (2x16GB) DDR5 6000MHz CL30 memória", brand="Kingston"
    )
    assert listing.product_attrs.kind is TechKind.RAM
    assert listing.product_attrs.ram_type == "DDR5"
    v = listing.variant_attrs
    assert (v.capacity_gb, v.modules, v.speed_mts) == (32, 2, 6000)
    assert listing.variant_key == "32GB-2X16GB"


def test_gpu_chipset_and_vram_ignore_gddr() -> None:
    listing = norm(
        TECH, "ASUS TUF Gaming GeForce RTX 4070 SUPER OC 12GB GDDR6X videokártya", brand="ASUS"
    )
    p = listing.product_attrs
    assert p.kind is TechKind.GPU
    assert p.gpu_chipset == "RTX 4070 SUPER"
    assert p.ram_type is None  # GDDR6X is VRAM, not a RAM type
    assert listing.variant_attrs.memory_gb == 12
    assert listing.variant_key == "12GB"


def test_amd_gpu_chipset() -> None:
    listing = norm(TECH, "Sapphire PULSE Radeon RX 7800 XT 16GB", brand="Sapphire")
    assert listing.product_attrs.gpu_chipset == "RX 7800 XT"


def test_cpu_socket() -> None:
    listing = norm(TECH, "AMD Ryzen 7 7800X3D 4.2GHz AM5 BOX processzor", brand="AMD")
    assert listing.product_attrs.kind is TechKind.CPU
    assert listing.product_attrs.cpu_socket == "AM5"
    intel = norm(
        TECH, "Intel Core i5-14600K processzor", brand="Intel", attributes={"Foglalat": "LGA 1700"}
    )
    assert intel.product_attrs.cpu_socket == "LGA1700"


def test_laptop_configuration_is_the_variant() -> None:
    listing = norm(
        TECH,
        "Lenovo IdeaPad Slim 5 laptop 16GB RAM 512GB SSD Ryzen 7 8845HS",
        brand="Lenovo",
        warranty_text="2 év",
    )
    assert listing.product_attrs.kind is TechKind.LAPTOP
    assert listing.variant_key == "16GB-512GB"
    assert listing.product_attrs.cpu_model == "Ryzen 7 8845HS"
    unknown = norm(TECH, "Lenovo IdeaPad Slim 5 laptop", brand="Lenovo")
    assert "config_missing" in error_codes(unknown)


def test_monitor_specs() -> None:
    listing = norm(TECH, 'LG UltraGear 27" QHD IPS 165Hz gaming monitor', brand="LG")
    p = listing.product_attrs
    assert (p.kind, p.screen_diag_tenth_in, p.resolution, p.panel, p.refresh_hz) == (
        TechKind.MONITOR, 270, "2560x1440", "IPS", 165,
    )  # fmt: skip


def test_conflicting_title_and_specs_is_an_error() -> None:
    listing = norm(
        TECH, "Corsair Vengeance 16GB DDR4 memória", brand="Corsair", attributes={"Típus": "DDR5"}
    )
    assert "conflicting_ram_type" in error_codes(listing)


def test_validation_rules() -> None:
    no_brand = norm(TECH, "Samsung 990 PRO 2TB NVMe SSD")
    assert "manufacturer_missing" in error_codes(no_brand)
    no_capacity = norm(TECH, "Samsung 990 PRO NVMe SSD", brand="Samsung")
    assert "capacity_missing" in error_codes(no_capacity)
    used = norm(
        TECH,
        "Samsung 990 PRO 2TB NVMe SSD",
        brand="Samsung",
        listing_kind=ListingKind.CLASSIFIED,
        seller_kind=SellerKind.PRIVATE,
        condition_text=None,
    )
    assert "condition_missing" in error_codes(used)
    assert "kind_unknown" in codes(norm(TECH, "Ismeretlen kütyü", brand="X"))


def test_brand_from_spec_table_and_ean_from_spec_table() -> None:
    listing = norm(TECH, "990 PRO 2TB NVMe SSD", attributes={"Gyártó": "Samsung", "EAN": SSD_GTIN})
    assert listing.brand == "Samsung"
    assert listing.identifier(IdType.GTIN) is not None


# --- evaluation inputs -------------------------------------------------------------------------


def test_evaluation_inputs() -> None:
    inputs = evaluation_inputs(ssd())
    assert isinstance(inputs, TechEvaluationInputs)
    assert inputs.missing_inputs == () and not inputs.needs_manual_review
    assert inputs.effective_price_huf == 10_000
    assert inputs.warranty_months == 60 and inputs.resale_applicable
    no_warranty = evaluation_inputs(ssd(warranty_text=None, shipping_text=None))
    assert set(no_warranty.missing_inputs) == {"warranty", "shipping"}
    assert no_warranty.effective_price_huf is None  # unknown shipping is never 0


# --- matching ----------------------------------------------------------------------------------


def test_gtin_match_is_automatic() -> None:
    stored = ssd()
    outcome = match(ssd(mpn=None, brand="SAMSUNG "), [candidate(stored)], RULES)
    assert outcome.kind is OutcomeKind.AUTO_MATCH and outcome.method is MatchMethod.GTIN
    assert (outcome.product_id, outcome.variant_id) == (1, 10)


def test_mpn_needs_the_same_manufacturer() -> None:
    stored = ssd(gtin=None)
    same = match(ssd(gtin=None), [candidate(stored)], RULES)
    assert same.kind is OutcomeKind.AUTO_MATCH and same.method is MatchMethod.MPN
    other_brand = match(ssd(gtin=None, brand="Kingston", model="X"), [candidate(stored)], RULES)
    assert other_brand.kind is OutcomeKind.NO_MATCH


def test_identifier_with_contradicting_specs_is_a_conflict() -> None:
    stored = candidate(ssd(), product_attrs={"kind": "SSD", "ssd_interface": "SATA"})
    outcome = match(ssd(), [stored], RULES)
    assert outcome.kind is OutcomeKind.CONFLICT
    assert any("ssd_interface" in r for r in outcome.reasons)


def test_identifiers_pointing_to_two_products_is_a_conflict() -> None:
    a = candidate(ssd(mpn=None), product_id=1)
    b = candidate(ssd(gtin=None), product_id=2, variant_id=20)
    outcome = match(ssd(), [a, b], RULES)
    assert outcome.kind is OutcomeKind.CONFLICT and len(outcome.candidates) == 2


def test_identifier_variant_must_agree_with_listing_variant() -> None:
    stored = candidate(ssd())
    one_tb = VariantCandidate(
        variant_id=10, variant_key="1000GB", identifiers=stored.variants[0].identifiers
    )
    two_tb = VariantCandidate(variant_id=11, variant_key="2000GB")
    outcome = match(ssd(), [replace(stored, variants=(one_tb, two_tb))], RULES)
    assert outcome.kind is OutcomeKind.CONFLICT


def test_rule_key_without_identifiers_needs_review() -> None:
    stored = candidate(ssd(gtin=None, mpn=None))
    outcome = match(ssd(gtin=None, mpn=None), [stored], RULES)
    assert outcome.kind is OutcomeKind.REVIEW
    assert outcome.candidates[0].method is MatchMethod.RULE


def test_fuzzy_is_never_automatic() -> None:
    stored = candidate(ssd(gtin=None, mpn=None, model=None))
    listing = norm(TECH, "Samsung 990 PRO 2TB NVMe M.2 SSD PCIe 4.0", brand="Samsung")
    outcome = match(listing, [stored], RULES)
    assert outcome.kind is OutcomeKind.REVIEW
    assert outcome.candidates[0].method is MatchMethod.FUZZY


def test_other_category_products_are_ignored() -> None:
    stored = replace(candidate(ssd()), category=Category.HOME)
    assert match(ssd(), [stored], RULES).kind is OutcomeKind.NO_MATCH
