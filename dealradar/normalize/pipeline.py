"""raw listing -> generic normalization -> category normalization -> category validation."""

from __future__ import annotations

from dealradar.core.enums import Category
from dealradar.normalize.generic import normalize_generic
from dealradar.normalize.types import CategoryNormalizer, NormalizedListing, RawListing


def normalize_listing(
    raw: RawListing, category: Category, module: CategoryNormalizer
) -> NormalizedListing:
    listing = module.normalize(normalize_generic(raw, category))
    return listing.with_issues(*module.validate(listing))
