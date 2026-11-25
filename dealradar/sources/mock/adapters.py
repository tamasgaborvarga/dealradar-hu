"""Mock adapters: behave like real adapters (pagination, record errors, polite fetching) but read
the synthetic catalog through MockTransport."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from dealradar.core.enums import (
    AccessMethod,
    Availability,
    Category,
    FetchErrorKind,
    ListingKind,
    SellerKind,
)
from dealradar.normalize.types import RawListing
from dealradar.sources.base import AdapterOffer, AdapterRecord, FetchContext, RecordError
from dealradar.sources.mock.transport import MockTransport

MAX_PAGES = 20  # guard against a source that never ends


@dataclass(frozen=True)
class MockAdapter:
    key: str
    name: str
    host: str
    listing_kind: ListingKind
    seller_kind: SellerKind
    default_condition: str | None
    categories: frozenset[Category]
    access_method: AccessMethod = AccessMethod.MOCK
    terms_note: str = "synthetic fixture data; no real website is contacted"
    cache_ttl_s: int = 3_600

    def transport(self) -> MockTransport:
        return MockTransport()

    def fetch(self, ctx: FetchContext, categories: frozenset[Category]) -> Iterator[AdapterRecord]:
        for category in sorted(categories & self.categories):
            page: int | None = 1
            pages = 0
            while page is not None and pages < MAX_PAGES:
                response = ctx.get(f"mock://{self.host}/api/offers?category={category}&page={page}")
                data = response.json()
                if not isinstance(data, dict) or not isinstance(data.get("items"), list):
                    yield RecordError(
                        FetchErrorKind.PARSE_ERROR, f"unexpected page shape: page {page}"
                    )
                    break
                for item in data["items"]:
                    yield self._record(category, item, response.fetched_at)
                page = data.get("next_page")
                pages += 1

    def _record(self, category: Category, item: dict[str, Any], fetched_at: Any) -> AdapterRecord:
        ref = str(item.get("id") or "")
        try:
            raw = RawListing(
                source_key=self.key,
                external_id=f"{self.key}:{ref}",
                title=item.get("title") or "",
                listing_kind=self.listing_kind,
                observed_at=fetched_at,
                category_hint=category,
                url=f"mock://{self.host}/item/{ref}",
                brand=item.get("brand"),
                model=item.get("model"),
                price_text=item.get("price"),
                shipping_text=item.get("shipping"),
                condition_text=item.get("condition", self.default_condition),
                warranty_text=item.get("warranty"),
                seller_kind=self.seller_kind,
                gtin=item.get("gtin"),
                mpn=item.get("mpn"),
                style_code=item.get("style_code"),
                variant_text=item.get("variant"),
                color_text=item.get("color"),
                attributes=item.get("attributes") or {},
            )
            availability = Availability(item.get("stock", "UNKNOWN"))
        except (ValidationError, ValueError) as exc:
            return RecordError(FetchErrorKind.PARSE_ERROR, str(exc).splitlines()[0], ref or None)
        return AdapterOffer(category, raw, availability, fetched_at)


MOCK_SHOP = MockAdapter(
    key="mock_shop",
    name="Demó bolt (szintetikus)",
    host="mock-shop",
    listing_kind=ListingKind.RETAIL,
    seller_kind=SellerKind.RETAILER,
    default_condition="új",
    categories=frozenset(Category),
)
MOCK_MARKET = MockAdapter(
    key="mock_market",
    name="Demó apróhirdetés (szintetikus)",
    host="mock-market",
    listing_kind=ListingKind.CLASSIFIED,
    seller_kind=SellerKind.PRIVATE,
    default_condition="használt",
    categories=frozenset({Category.TECH, Category.HOME}),
)
MOCK_SHOP_2 = MockAdapter(
    key="mock_shop_2",
    name="Demó bolt 2 (szintetikus)",
    host="mock-shop-2",
    listing_kind=ListingKind.RETAIL,
    seller_kind=SellerKind.RETAILER,
    default_condition="új",
    categories=frozenset(Category),
)
