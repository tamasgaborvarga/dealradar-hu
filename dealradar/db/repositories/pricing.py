from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime

from sqlalchemy import func, select

from dealradar.db.models import ObservedSale, Offer, PriceObservation
from dealradar.db.repositories.base import Repository


class PriceObservationRepository(Repository[PriceObservation]):
    model = PriceObservation

    def for_variants(
        self, variant_ids: Iterable[int], since: datetime, until: datetime
    ) -> Sequence[tuple[PriceObservation, int]]:
        """Observations of offers currently matched to one of ``variant_ids`` (with that id).

        Offers without a resolved variant never appear - prices of different or unknown
        variants are never compared.
        """
        ids = list(variant_ids)
        if not ids:
            return []
        stmt = (
            select(PriceObservation, Offer.variant_id)
            .join(Offer, PriceObservation.offer_id == Offer.id)
            .where(
                Offer.variant_id.in_(ids),
                PriceObservation.observed_at >= since,
                PriceObservation.observed_at <= until,
            )
            .order_by(PriceObservation.observed_at)
        )
        return [(obs, vid) for obs, vid in self.session.execute(stmt).all() if vid is not None]

    def count_for_offer(self, offer_id: int) -> int:
        stmt = select(func.count()).where(PriceObservation.offer_id == offer_id)
        return int(self.session.scalar(stmt) or 0)

    def latest_for_offer(self, offer_id: int) -> PriceObservation | None:
        return self.session.scalar(
            select(PriceObservation)
            .where(PriceObservation.offer_id == offer_id)
            .order_by(PriceObservation.observed_at.desc())
            .limit(1)
        )


class ObservedSaleRepository(Repository[ObservedSale]):
    model = ObservedSale

    def for_variants(
        self, variant_ids: Iterable[int], since: datetime, until: datetime
    ) -> Sequence[ObservedSale]:
        ids = list(variant_ids)
        if not ids:
            return []
        return self.session.scalars(
            select(ObservedSale)
            .where(
                ObservedSale.variant_id.in_(ids),
                ObservedSale.sold_at >= since,
                ObservedSale.sold_at <= until,
            )
            .order_by(ObservedSale.sold_at)
        ).all()
