"""Repositories: the only place that builds SQL queries. Services and UI never query directly."""

from dealradar.db.repositories.base import Repository
from dealradar.db.repositories.catalog import ProductRepository
from dealradar.db.repositories.offers import ListingRepository, OfferRepository
from dealradar.db.repositories.pricing import ObservedSaleRepository, PriceObservationRepository
from dealradar.db.repositories.sources import PlatformRepository, SourceRepository
from dealradar.db.repositories.system import AuditLogRepository, SettingsRepository

__all__ = [
    "AuditLogRepository",
    "ListingRepository",
    "ObservedSaleRepository",
    "OfferRepository",
    "PlatformRepository",
    "PriceObservationRepository",
    "ProductRepository",
    "Repository",
    "SettingsRepository",
    "SourceRepository",
]
