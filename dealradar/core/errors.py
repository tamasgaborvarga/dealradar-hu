class DealRadarError(Exception):
    """Base class for expected, user-reportable errors."""


class LockTimeoutError(DealRadarError):
    """Another process holds the single-writer lock."""


class ImmutableRowError(DealRadarError):
    """An update was attempted on an insert-only row (mutability class IMMUTABLE/LEDGER/SPAN)."""


class SchemaNotReadyError(DealRadarError):
    """The database schema is missing or not at the migration head."""
