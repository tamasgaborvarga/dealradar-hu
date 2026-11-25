from __future__ import annotations

from sqlalchemy import func, select

from dealradar.core.enums import Category, IdType
from dealradar.db.models import Product, ProductVariant, VariantIdentifier
from dealradar.db.repositories.base import Repository


class ProductRepository(Repository[Product]):
    model = Product

    def count_by_category(self) -> dict[Category, int]:
        """Active (not merged) products per category; every category present, zero if empty."""
        stmt = (
            select(Product.category, func.count())
            .where(Product.merged_into_id.is_(None))
            .group_by(Product.category)
        )
        counts = {c: 0 for c in Category}
        for category, n in self.session.execute(stmt).all():
            counts[category] = int(n)
        return counts

    def count_variants_by_category(self) -> dict[Category, int]:
        stmt = (
            select(Product.category, func.count(ProductVariant.id))
            .join(ProductVariant, ProductVariant.product_id == Product.id)
            .where(Product.merged_into_id.is_(None), ProductVariant.merged_into_id.is_(None))
            .group_by(Product.category)
        )
        counts = {c: 0 for c in Category}
        for category, n in self.session.execute(stmt).all():
            counts[category] = int(n)
        return counts

    def find_variant_by_identifier(
        self, id_type: IdType, value: str, source_id: int | None = None
    ) -> ProductVariant | None:
        """Exact identifier lookup. SHOP_SKU needs ``source_id``; global ids must not pass one."""
        if (id_type is IdType.SHOP_SKU) != (source_id is not None):
            raise ValueError("SHOP_SKU lookups need source_id; other identifier types must not")
        stmt = (
            select(ProductVariant)
            .join(VariantIdentifier)
            .where(VariantIdentifier.id_type == id_type, VariantIdentifier.value == value)
        )
        if source_id is None:
            stmt = stmt.where(VariantIdentifier.source_id.is_(None))
        else:
            stmt = stmt.where(VariantIdentifier.source_id == source_id)
        return self.session.scalar(stmt)
