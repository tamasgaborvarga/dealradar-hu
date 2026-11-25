"""Read models for the dashboard pages."""

from __future__ import annotations

from dataclasses import dataclass

from dealradar.categories.base import CategoryInfo
from dealradar.categories.registry import all_categories, category_info
from dealradar.core.enums import Category
from dealradar.db.repositories import ListingRepository, ProductRepository, SourceRepository
from dealradar.db.session import Database

__all__ = ["CategoryInfo", "CategoryOverview", "SystemOverview", "all_categories", "category_info"]


@dataclass(frozen=True)
class CategoryOverview:
    info: CategoryInfo
    products: int
    variants: int
    matched_listings: int


@dataclass(frozen=True)
class SystemOverview:
    categories: tuple[CategoryOverview, ...]
    sources: int
    unmatched_listings: int


def system_overview(db: Database) -> SystemOverview:
    with db.read_session() as s:
        products = ProductRepository(s).count_by_category()
        variants = ProductRepository(s).count_variants_by_category()
        listings = ListingRepository(s)
        matched = listings.count_matched_by_category()
        unmatched = listings.count_unmatched()
        sources = SourceRepository(s).count()
    cats = tuple(
        CategoryOverview(
            info=info,
            products=products[info.key],
            variants=variants[info.key],
            matched_listings=matched[info.key],
        )
        for info in all_categories()
    )
    return SystemOverview(categories=cats, sources=sources, unmatched_listings=unmatched)


def category_overview(db: Database, category: Category) -> CategoryOverview:
    for item in system_overview(db).categories:
        if item.info.key is category:
            return item
    raise KeyError(category)
