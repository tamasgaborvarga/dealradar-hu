"""CLOTHING_SHOES_SPORT category module: clothing, sneakers, sportswear, sports equipment."""

from __future__ import annotations

from typing import ClassVar

from dealradar.categories.apparel import identity, inputs
from dealradar.categories.apparel import normalize as _normalize
from dealradar.categories.apparel.attributes import (
    ApparelListingAttrs,
    ApparelProductAttrs,
    ApparelVariantAttrs,
)
from dealradar.categories.base import CategoryInfo, ComparisonBasis
from dealradar.core.enums import Category, IdType
from dealradar.evaluation.inputs import CategoryEvaluationInputs
from dealradar.evaluation.params import PersonalParams, ResaleParams
from dealradar.matching.types import ProductCandidate
from dealradar.normalize.types import Issue, NormalizedListing
from dealradar.pricing.types import BenchmarkPolicy

INFO = CategoryInfo(
    key=Category.APPAREL,
    label="Clothing, shoes & sport",
    scope="Clothing, sneakers, sportswear and sports equipment",
    variant_means="size (product = brand + model + colourway)",
    comparison_basis=ComparisonBasis.ITEM_PER_SIZE,
    resale_enabled_by_default=True,
)


# Seasonal; per-size data is sparse. (ADR-041, PROPOSED defaults)
BENCHMARK_POLICY = BenchmarkPolicy(window_days=60, stale_after_days=21, min_samples=4)


# Engine defaults: ASSUMPTIONS, not market data.
# Fit-related returns are frequent; items are cheap to ship.
# Overridable per user via settings (docs/ENGINE_FORMULAS.md).
PERSONAL_PARAMS = PersonalParams()
RESALE_PARAMS = ResaleParams(
    return_rate_bp=1_000,
    return_cost_huf=2_500,
    defect_rate_bp=100,
    defect_loss_bp=3_000,
    min_net_profit_huf=3_000,
)


class ApparelModule:
    info = INFO
    product_attrs_model: ClassVar = ApparelProductAttrs
    variant_attrs_model: ClassVar = ApparelVariantAttrs
    listing_attrs_model: ClassVar = ApparelListingAttrs
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


MODULE = ApparelModule()
