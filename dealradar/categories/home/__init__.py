"""HOME category module: appliances, furniture, kitchen, garden, DIY."""

from __future__ import annotations

from typing import ClassVar

from dealradar.categories.base import CategoryInfo, ComparisonBasis
from dealradar.categories.home import identity, inputs
from dealradar.categories.home import normalize as _normalize
from dealradar.categories.home.attributes import (
    HomeListingAttrs,
    HomeProductAttrs,
    HomeVariantAttrs,
)
from dealradar.core.enums import Category, IdType
from dealradar.evaluation.inputs import CategoryEvaluationInputs
from dealradar.evaluation.params import PersonalParams, ResaleParams
from dealradar.matching.types import ProductCandidate
from dealradar.normalize.types import Issue, NormalizedListing
from dealradar.pricing.types import BenchmarkPolicy

INFO = CategoryInfo(
    key=Category.HOME,
    label="Home",
    scope="Household appliances, furniture, kitchen, garden and DIY",
    variant_means="colour where it changes the price, otherwise 'default'",
    comparison_basis=ComparisonBasis.ITEM,
    resale_enabled_by_default=True,
)


# Slow-moving prices; delivery is a large part of the cost. (ADR-041, PROPOSED defaults)
BENCHMARK_POLICY = BenchmarkPolicy(window_days=120, stale_after_days=30, landed_price_relevant=True)


# Engine defaults: ASSUMPTIONS, not market data.
# Bulky goods: delivery must be part of the comparison; returns are expensive.
# Overridable per user via settings (docs/ENGINE_FORMULAS.md).
PERSONAL_PARAMS = PersonalParams(require_landed_comparison=True)
RESALE_PARAMS = ResaleParams(
    return_rate_bp=300,
    return_cost_huf=15_000,
    defect_rate_bp=300,
    defect_loss_bp=6_000,
    max_days_to_sell=90,
)


class HomeModule:
    info = INFO
    product_attrs_model: ClassVar = HomeProductAttrs
    variant_attrs_model: ClassVar = HomeVariantAttrs
    listing_attrs_model: ClassVar = HomeListingAttrs
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


MODULE = HomeModule()
