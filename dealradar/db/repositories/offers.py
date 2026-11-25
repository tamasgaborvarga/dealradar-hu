from __future__ import annotations

from sqlalchemy import func, select

from dealradar.core.enums import Category
from dealradar.db.models import Listing, Offer, Product
from dealradar.db.repositories.base import Repository


class ListingRepository(Repository[Listing]):
    model = Listing

    def get_by_external_id(self, source_id: int, external_id: str) -> Listing | None:
        return self.session.scalar(
            select(Listing).where(
                Listing.source_id == source_id, Listing.external_id == external_id
            )
        )

    def count_matched_by_category(self) -> dict[Category, int]:
        """Matched, not delisted listings per (authoritative, product) category."""
        stmt = (
            select(Product.category, func.count(Listing.id))
            .join(Product, Listing.product_id == Product.id)
            .where(Listing.delisted_at.is_(None))
            .group_by(Product.category)
        )
        counts = {c: 0 for c in Category}
        for category, n in self.session.execute(stmt).all():
            counts[category] = int(n)
        return counts

    def count_unmatched(self) -> int:
        stmt = select(func.count()).select_from(Listing).where(Listing.product_id.is_(None))
        return int(self.session.scalar(stmt) or 0)


class OfferRepository(Repository[Offer]):
    model = Offer
