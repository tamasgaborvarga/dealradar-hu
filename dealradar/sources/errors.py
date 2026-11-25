"""Run-level source errors. Each maps to one FetchErrorKind and a retry policy."""

from __future__ import annotations

from dealradar.core.enums import FetchErrorKind


class SourceError(Exception):
    kind: FetchErrorKind = FetchErrorKind.INTERNAL
    retryable: bool = False

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class AccessNotPermitted(SourceError):
    kind = FetchErrorKind.ACCESS_NOT_PERMITTED


class RobotsDisallowed(SourceError):
    kind = FetchErrorKind.ROBOTS_DISALLOWED


class SourceBlocked(SourceError):
    """The site refuses us. We stop - no retry, no workaround (ADR-008)."""

    kind = FetchErrorKind.BLOCKED


class RateLimited(SourceError):
    kind = FetchErrorKind.RATE_LIMITED

    def __init__(self, message: str, retry_after_s: float | None = None) -> None:
        super().__init__(message)
        self.retry_after_s = retry_after_s


class SourceTimeout(SourceError):
    kind = FetchErrorKind.TIMEOUT
    retryable = True


class SourceUnavailable(SourceError):
    kind = FetchErrorKind.UNAVAILABLE
    retryable = True


class ClientError(SourceError):
    kind = FetchErrorKind.CLIENT_ERROR


class DailyCapReached(SourceError):
    kind = FetchErrorKind.DAILY_CAP_REACHED
