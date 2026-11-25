"""All ORM models. Importing this package registers every table on ``Base.metadata``.

Scope: sources, catalog (identity), category attributes, listings/offers, pricing
(observations, observed sales), system.
Evaluations, fees, sales evidence and the ledger arrive with their phases via new migrations.
"""

from dealradar.db.models.analysis import AiRequest, AiResponse
from dealradar.db.models.catalog import Product, ProductVariant, VariantIdentifier
from dealradar.db.models.category_attrs import (
    ApparelAttributes,
    FoodAttributes,
    HomeAttributes,
    TechAttributes,
)
from dealradar.db.models.ledger import Acquisition, InventoryItem, LedgerTransaction
from dealradar.db.models.offers import Listing, MatchCandidate, Offer
from dealradar.db.models.pricing import ObservedSale, PriceObservation
from dealradar.db.models.sources import (
    Platform,
    RawRecord,
    RefreshJob,
    Source,
    SourceRun,
    SourceRunError,
)
from dealradar.db.models.system import AuditLog, Setting
from dealradar.db.models.workflow import (
    FeeProfileRecord,
    Notification,
    OfferDecision,
    PersonalEvaluation,
    ResaleEvaluation,
    Watchlist,
)

__all__ = [
    "Acquisition",
    "AiRequest",
    "AiResponse",
    "ApparelAttributes",
    "AuditLog",
    "FeeProfileRecord",
    "FoodAttributes",
    "HomeAttributes",
    "InventoryItem",
    "LedgerTransaction",
    "Listing",
    "MatchCandidate",
    "Notification",
    "ObservedSale",
    "Offer",
    "OfferDecision",
    "PersonalEvaluation",
    "Platform",
    "PriceObservation",
    "Product",
    "ProductVariant",
    "RawRecord",
    "RefreshJob",
    "ResaleEvaluation",
    "Setting",
    "Source",
    "SourceRun",
    "SourceRunError",
    "TechAttributes",
    "VariantIdentifier",
    "Watchlist",
]
