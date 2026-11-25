from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select

from dealradar.core.enums import SourceStatus
from dealradar.db.models import Platform, Source
from dealradar.db.repositories.base import Repository


class PlatformRepository(Repository[Platform]):
    model = Platform

    def get_by_key(self, key: str) -> Platform | None:
        return self.session.scalar(select(Platform).where(Platform.key == key))


class SourceRepository(Repository[Source]):
    model = Source

    def get_by_key(self, key: str) -> Source | None:
        return self.session.scalar(select(Source).where(Source.key == key))

    def list_with_platform(self) -> Sequence[tuple[Source, Platform]]:
        stmt = select(Source, Platform).join(Platform).order_by(Source.key)
        return [(s, p) for s, p in self.session.execute(stmt).all()]

    def list_by_status(self, status: SourceStatus) -> Sequence[Source]:
        return self.session.scalars(select(Source).where(Source.status == status)).all()
