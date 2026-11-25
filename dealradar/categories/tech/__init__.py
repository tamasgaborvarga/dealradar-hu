"""TECH category module: CPUs, GPUs, RAM, SSDs, laptops, monitors, electronics."""

from __future__ import annotations

from typing import ClassVar

from dealradar.categories.base import CategoryInfo, ComparisonBasis
from dealradar.categories.tech import identity, inputs
from dealradar.categories.tech import normalize as _normalize
from dealradar.categories.tech.attributes import (
    TechListingAttrs,
    TechProductAttrs,
    TechVariantAttrs,
)
from dealradar.core.enums import Category, IdType
from dealradar.evaluation.inputs import CategoryEvaluationInputs
from dealradar.evaluation.params import PersonalParams, ResaleParams
from dealradar.matching.types import ProductCandidate
from dealradar.normalize.types import Issue, NormalizedListing
from dealradar.pricing.types import BenchmarkPolicy

INFO = CategoryInfo(
    key=Category.TECH,
    label="Tech",
    scope="CPUs, GPUs, RAM, SSDs, laptops, monitors and electronics",
    variant_means="configuration / capacity (e.g. SSD size, RAM kit, laptop RAM+storage)",
    comparison_basis=ComparisonBasis.ITEM,
    resale_enabled_by_default=True,
)


# Prices move with launches; 90 days. (ADR-041, PROPOSED defaults)
BENCHMARK_POLICY = BenchmarkPolicy(window_days=90, stale_after_days=14)


# Engine defaults: ASSUMPTIONS, not market data.
# Electronics: few returns, defects costly (half the price).
# Overridable per user via settings (docs/ENGINE_FORMULAS.md).
PERSONAL_PARAMS = PersonalParams()
RESALE_PARAMS = ResaleParams(
    return_rate_bp=300, return_cost_huf=3_000, defect_rate_bp=200, defect_loss_bp=5_000
)


class TechModule:
    info = INFO
    product_attrs_model: ClassVar = TechProductAttrs
    variant_attrs_model: ClassVar = TechVariantAttrs
    listing_attrs_model: ClassVar = TechListingAttrs
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


MODULE = TechModule()
