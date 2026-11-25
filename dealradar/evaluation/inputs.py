"""Base class for category-specific evaluation inputs.

Each category module builds its own subclass from a NormalizedListing. ``missing_inputs`` and
``review_flags`` feed the MANUAL_REVIEW rule (ADR-005) once the engines exist.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from dealradar.core.enums import Category, Condition, SellerKind


class CategoryEvaluationInputs(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    category: Category
    price_huf: int | None
    shipping_huf: int | None
    condition: Condition | None
    seller_kind: SellerKind | None
    resale_applicable: bool
    missing_inputs: tuple[str, ...] = ()
    review_flags: tuple[str, ...] = ()

    @property
    def needs_manual_review(self) -> bool:
        return bool(self.missing_inputs or self.review_flags)

    @property
    def effective_price_huf(self) -> int | None:
        """Price including inbound shipping; None when either is unknown (never assume 0)."""
        if self.price_huf is None or self.shipping_huf is None:
            return None
        return self.price_huf + self.shipping_huf
