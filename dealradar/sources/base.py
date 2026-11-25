"""The common source adapter interface (docs/SOURCES.md §2)."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from dealradar.core.enums import AccessMethod, Availability, Category, FetchErrorKind
from dealradar.normalize.types import RawListing
from dealradar.sources.requester import Response


@dataclass(frozen=True)
class AdapterOffer:
    """One offer in the common, source-neutral shape. Category modules normalize it further."""

    category: Category
    raw: RawListing  # untrusted text fields, as the source shows them
    availability: Availability
    fetched_at: datetime  # when the source showed this (cache hits keep the original time)


@dataclass(frozen=True)
class RecordError:
    """One record could not be read; the run continues."""

    kind: FetchErrorKind
    message: str
    external_ref: str | None = None


AdapterRecord = AdapterOffer | RecordError


class FetchContext(Protocol):
    """What the framework gives an adapter. All network access goes through ``get``, which
    enforces robots.txt, rate limits, timeouts, retries, caching and block detection."""

    def get(self, url: str) -> Response: ...


class SourceAdapter(Protocol):
    @property
    def key(self) -> str:
        """Equals sources.key in the database."""
        ...

    @property
    def name(self) -> str: ...

    @property
    def access_method(self) -> AccessMethod:
        """Must equal the access method recorded in the source's access review."""
        ...

    @property
    def categories(self) -> frozenset[Category]: ...

    @property
    def terms_note(self) -> str:
        """What permits this access; for MOCK: synthetic data."""
        ...

    @property
    def cache_ttl_s(self) -> int:
        """How long a fetched response may be reused."""
        ...

    def fetch(self, ctx: FetchContext, categories: frozenset[Category]) -> Iterator[AdapterRecord]:
        """Yield offers (and record errors) for the requested categories. Raise a SourceError
        for run-level failures. Must not catch SourceBlocked to work around it."""
        ...
