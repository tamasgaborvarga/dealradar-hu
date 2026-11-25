from __future__ import annotations

from collections.abc import Sequence
from typing import Any, ClassVar

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from dealradar.db.base import Base


class Repository[M: Base]:
    """Generic CRUD helpers. Subclasses set ``model`` and add query methods."""

    model: ClassVar[type[Any]]

    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, pk: Any) -> M | None:
        obj: M | None = self.session.get(self.model, pk)
        return obj

    def add(self, obj: M) -> M:
        self.session.add(obj)
        self.session.flush()
        return obj

    def count(self) -> int:
        return int(self.session.scalar(select(func.count()).select_from(self.model)) or 0)

    def list(self, limit: int = 100, offset: int = 0) -> Sequence[M]:
        if limit < 1 or limit > 1000:
            raise ValueError("limit must be within 1..1000")
        stmt = select(self.model).order_by(self.model.__mapper__.primary_key[0])
        return self.session.scalars(stmt.limit(limit).offset(offset)).all()
