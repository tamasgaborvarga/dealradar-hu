"""Enumerations used by the data model. Stored as TEXT with CHECK constraints."""

from enum import StrEnum


class Category(StrEnum):
    TECH = "TECH"
    APPAREL = "APPAREL"
    FOOD = "FOOD"
    HOME = "HOME"


class PlatformKind(StrEnum):
    RETAILER = "RETAILER"
    MARKETPLACE = "MARKETPLACE"
    CLASSIFIEDS = "CLASSIFIEDS"
    AUCTION = "AUCTION"
    PRICE_COMPARATOR = "PRICE_COMPARATOR"
    FLYER = "FLYER"
    OTHER = "OTHER"


class AccessMethod(StrEnum):
    OFFICIAL_API = "OFFICIAL_API"
    FEED = "FEED"
    PUBLIC_HTML = "PUBLIC_HTML"
    PUBLIC_HTML_JS = "PUBLIC_HTML_JS"
    MANUAL = "MANUAL"
    MOCK = "MOCK"  # synthetic fixture data, never a real website (demo / tests only)


class SourceStatus(StrEnum):
    DISABLED = "DISABLED"
    ACTIVE = "ACTIVE"
    DEGRADED = "DEGRADED"
    BLOCKED = "BLOCKED"


class RunStatus(StrEnum):
    RUNNING = "RUNNING"
    OK = "OK"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"


class ProductOrigin(StrEnum):
    USER = "USER"
    RULE = "RULE"


class IdType(StrEnum):
    GTIN = "GTIN"
    MPN = "MPN"
    STYLE_CODE = "STYLE_CODE"
    SHOP_SKU = "SHOP_SKU"


class ListingKind(StrEnum):
    RETAIL = "RETAIL"
    MARKETPLACE = "MARKETPLACE"
    CLASSIFIED = "CLASSIFIED"
    AUCTION = "AUCTION"
    FLYER = "FLYER"


class MatchStatus(StrEnum):
    UNMATCHED = "UNMATCHED"
    PENDING_REVIEW = "PENDING_REVIEW"
    MATCHED = "MATCHED"
    REJECTED = "REJECTED"


class MatchMethod(StrEnum):
    GTIN = "GTIN"
    MPN = "MPN"
    STYLE_CODE = "STYLE_CODE"
    RULE = "RULE"
    FUZZY = "FUZZY"
    USER = "USER"
    AI_SUGGESTED = "AI_SUGGESTED"


class CandidateStatus(StrEnum):
    OPEN = "OPEN"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class SellerKind(StrEnum):
    RETAILER = "RETAILER"
    BUSINESS_SELLER = "BUSINESS_SELLER"
    PRIVATE = "PRIVATE"


class Condition(StrEnum):
    NEW = "NEW"
    OPEN_BOX = "OPEN_BOX"
    REFURBISHED = "REFURBISHED"
    USED = "USED"  # used, grade not stated (never guess a grade)
    USED_A = "USED_A"
    USED_B = "USED_B"
    USED_C = "USED_C"
    FOR_PARTS = "FOR_PARTS"


class WarrantyType(StrEnum):
    MANUFACTURER_HU = "MANUFACTURER_HU"
    MANUFACTURER_EU = "MANUFACTURER_EU"
    SELLER = "SELLER"
    NONE = "NONE"


class SizeSystem(StrEnum):
    EU = "EU"
    US = "US"
    UK = "UK"
    INT = "INT"


class CanonicalUnit(StrEnum):
    KG = "KG"
    L = "L"
    PIECE = "PIECE"
    M2 = "M2"


class Actor(StrEnum):
    USER = "USER"
    SYSTEM = "SYSTEM"


class Availability(StrEnum):
    IN_STOCK = "IN_STOCK"
    LIMITED = "LIMITED"  # "utolsó darabok", low stock
    PREORDER = "PREORDER"
    OUT_OF_STOCK = "OUT_OF_STOCK"
    UNKNOWN = "UNKNOWN"


class SaleEvidence(StrEnum):
    """How a completed sale is known (ADR-006). Asking prices are never sale evidence."""

    PLATFORM_FINAL_PRICE = "PLATFORM_FINAL_PRICE"  # platform publicly shows the final price
    USER_REPORTED = "USER_REPORTED"  # the user knows of a completed sale
    OWN_SALE = (
        "OWN_SALE"  # the user's own sale, read from the ledger (never stored in observed_sales)
    )


class RefreshScope(StrEnum):
    SOURCE = "SOURCE"
    CATEGORY = "CATEGORY"
    ALL = "ALL"


class FetchErrorKind(StrEnum):
    """Clear, stable error states for source runs (docs/SOURCES.md)."""

    ACCESS_NOT_PERMITTED = "ACCESS_NOT_PERMITTED"  # no access review / not ACTIVE / wrong method
    ROBOTS_DISALLOWED = "ROBOTS_DISALLOWED"
    BLOCKED = "BLOCKED"  # 401/403/407 or a challenge page - never retried, never bypassed
    RATE_LIMITED = "RATE_LIMITED"  # 429 with a wait longer than we accept
    TIMEOUT = "TIMEOUT"
    UNAVAILABLE = "UNAVAILABLE"  # 5xx after retries
    CLIENT_ERROR = "CLIENT_ERROR"  # other 4xx
    DAILY_CAP_REACHED = "DAILY_CAP_REACHED"
    PARSE_ERROR = "PARSE_ERROR"  # one record could not be read
    INVALID_RECORD = "INVALID_RECORD"  # record readable but unusable (e.g. no price while in stock)
    INTERNAL = "INTERNAL"


class AnalysisStatus(StrEnum):
    PREPARED = "PREPARED"  # prompt generated, waiting for the user's pasted answer
    ANSWERED = "ANSWERED"  # a valid answer was stored
    EXPIRED = "EXPIRED"  # package too old; prepare a new one


class PersonalVerdict(StrEnum):
    STRONG_DEAL = "STRONG_DEAL"
    GOOD_DEAL = "GOOD_DEAL"
    FAIR_PRICE = "FAIR_PRICE"
    NOT_A_DEAL = "NOT_A_DEAL"
    MANUAL_REVIEW = "MANUAL_REVIEW"


class ResaleVerdict(StrEnum):
    PROFITABLE = "PROFITABLE"
    MARGINAL = "MARGINAL"
    NOT_PROFITABLE = "NOT_PROFITABLE"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class Decision(StrEnum):
    """User decisions on an offer. Recording a purchase records what the USER did; the app
    never buys."""

    WATCH = "WATCH"
    REJECT = "REJECT"
    RESTORE = "RESTORE"  # undo a rejection
    BOUGHT = "BOUGHT"


class RejectReason(StrEnum):
    TOO_EXPENSIVE = "TOO_EXPENSIVE"
    WRONG_MATCH = "WRONG_MATCH"
    BAD_CONDITION = "BAD_CONDITION"
    SUSPECTED_SCAM = "SUSPECTED_SCAM"
    NOT_INTERESTED = "NOT_INTERESTED"
    OUT_OF_STOCK = "OUT_OF_STOCK"
    OTHER = "OTHER"


class ItemIntent(StrEnum):
    RESALE = "RESALE"
    PERSONAL = "PERSONAL"


class ItemStatus(StrEnum):
    IN_STOCK = "IN_STOCK"
    LISTED = "LISTED"
    SOLD = "SOLD"
    RETURNED_TO_SELLER = "RETURNED_TO_SELLER"
    WRITTEN_OFF = "WRITTEN_OFF"
    PERSONAL_USE = "PERSONAL_USE"


CLOSED_ITEM_STATUSES = frozenset(
    {ItemStatus.SOLD, ItemStatus.RETURNED_TO_SELLER, ItemStatus.WRITTEN_OFF}
)


class TxType(StrEnum):
    PURCHASE = "PURCHASE"
    INBOUND_SHIPPING = "INBOUND_SHIPPING"
    SALE = "SALE"
    PLATFORM_FEE = "PLATFORM_FEE"
    PAYMENT_FEE = "PAYMENT_FEE"
    OUTBOUND_SHIPPING = "OUTBOUND_SHIPPING"
    PACKAGING = "PACKAGING"
    REFUND_GIVEN = "REFUND_GIVEN"
    REFUND_RECEIVED = "REFUND_RECEIVED"
    TAX = "TAX"
    OTHER_COST = "OTHER_COST"
    OTHER_INCOME = "OTHER_INCOME"


INCOME_TYPES = frozenset({TxType.SALE, TxType.REFUND_RECEIVED, TxType.OTHER_INCOME})


class Direction(StrEnum):
    IN = "IN"
    OUT = "OUT"


class TelegramStatus(StrEnum):
    NOT_CONFIGURED = "NOT_CONFIGURED"
    SENT = "SENT"
    FAILED = "FAILED"
