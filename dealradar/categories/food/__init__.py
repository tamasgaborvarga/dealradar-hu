"""FOOD category module: packaged food, groceries, bulk offers, unit-price comparison."""

from __future__ import annotations

from typing import ClassVar

from dealradar.categories.base import CategoryInfo, ComparisonBasis
from dealradar.categories.food import identity, inputs
from dealradar.categories.food import normalize as _normalize
from dealradar.categories.food.attributes import (
    FoodListingAttrs,
    FoodProductAttrs,
    FoodVariantAttrs,
)
from dealradar.core.enums import Category, IdType
from dealradar.evaluation.inputs import CategoryEvaluationInputs
from dealradar.evaluation.params import PersonalParams, ResaleParams
from dealradar.matching.types import ProductCandidate
from dealradar.normalize.types import Issue, NormalizedListing
from dealradar.pricing.types import BenchmarkPolicy

INFO = CategoryInfo(
    key=Category.FOOD,
    label="Food",
    scope="Packaged food, groceries, bulk offers",
    variant_means="pack size (e.g. 500G, 6X330ML)",
    comparison_basis=ComparisonBasis.UNIT_PRICE,
    resale_enabled_by_default=False,  # OPEN-5
)


# Promotions rotate weekly; condition is not an input; unit price is the basis.
# (ADR-041, PROPOSED defaults)
BENCHMARK_POLICY = BenchmarkPolicy(
    window_days=30,
    stale_after_days=7,
    current_max_age_hours=24,
    condition_relevant=False,
    unit_price_basis=True,
    cross_variant_unit_price=True,
)


# Engine defaults: ASSUMPTIONS, not market data.
# Resale is NOT_APPLICABLE for food (OPEN-5); resale params exist for completeness.
# Overridable per user via settings (docs/ENGINE_FORMULAS.md).
PERSONAL_PARAMS = PersonalParams()
RESALE_PARAMS = ResaleParams()


class FoodModule:
    info = INFO
    product_attrs_model: ClassVar = FoodProductAttrs
    variant_attrs_model: ClassVar = FoodVariantAttrs
    listing_attrs_model: ClassVar = FoodListingAttrs
    fuzzy_threshold = identity.FUZZY_THRESHOLD
    rule_key_decisive = identity.RULE_KEY_DECISIVE
    benchmark_policy = BENCHMARK_POLICY
    personal_params = PERSONAL_PARAMS
    resale_params = RESALE_PARAMS

    def normalize(self, listing: NormalizedListing) -> NormalizedListing:
        return _normalize.normalize(listing)

    def validate(self, listing: NormalizedListing) -> list[Issue]:
        return _normalize.validate(listing)

    def identifier_requires_brand(self, id_type: IdType) -> bool:
        return identity.identifier_requires_brand(id_type)

    def identifier_pins_variant(self, id_type: IdType) -> bool:
        return identity.identifier_pins_variant(id_type)

    def rule_key(self, listing: NormalizedListing) -> str | None:
        return identity.rule_key(listing)

    def product_rule_key(self, product: ProductCandidate) -> str | None:
        return identity.product_rule_key(product)

    def contradictions(self, listing: NormalizedListing, product: ProductCandidate) -> list[str]:
        return identity.contradictions(listing, product)

    def evaluation_inputs(self, listing: NormalizedListing) -> CategoryEvaluationInputs:
        return inputs.build(listing)


MODULE = FoodModule()
