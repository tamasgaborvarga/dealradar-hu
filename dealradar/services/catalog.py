"""Category-aware use of the shared database: normalize, store products, find match candidates.

One database for all categories (ADR-001). The category module decides *what* is stored and how
it matches; this service only maps validated attribute models onto the shared tables.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from dealradar.categories.registry import module_for
from dealradar.core.enums import Category, IdType, ProductOrigin
from dealradar.core.identifiers import text_key
from dealradar.db.base import Base
from dealradar.db.models import (
    ApparelAttributes,
    FoodAttributes,
    HomeAttributes,
    Product,
    ProductVariant,
    TechAttributes,
    VariantIdentifier,
)
from dealradar.db.session import Database
from dealradar.evaluation.inputs import CategoryEvaluationInputs
from dealradar.matching.cascade import match
from dealradar.matching.types import MatchOutcome, ProductCandidate, VariantCandidate
from dealradar.normalize.pipeline import normalize_listing
from dealradar.normalize.types import NormalizedListing, RawListing

ATTRIBUTE_TABLES: dict[Category, type[Base]] = {
    Category.TECH: TechAttributes,
    Category.APPAREL: ApparelAttributes,
    Category.FOOD: FoodAttributes,
    Category.HOME: HomeAttributes,
}
MAX_CANDIDATES = 200


def normalize(raw: RawListing, category: Category) -> NormalizedListing:
    return normalize_listing(raw, category, module_for(category))


def evaluation_inputs(listing: NormalizedListing) -> CategoryEvaluationInputs:
    return module_for(listing.category).evaluation_inputs(listing)


def _attr_columns(table: type[Base]) -> set[str]:
    return {c.key for c in table.__table__.columns} - {"product_id", "extra"}


def _dump(model: BaseModel | None) -> dict[str, Any]:
    return {} if model is None else model.model_dump(mode="json")


def create_product(
    session: Session, listing: NormalizedListing, created_by: ProductOrigin
) -> tuple[Product, ProductVariant]:
    """Create product + first variant + identifiers + typed attributes from a listing.

    ADR-015: the system (RULE) may only create products from listings with a global identifier.
    Listings with blocking validation errors are refused - they need review first.
    """
    if created_by is ProductOrigin.RULE and not listing.identifiers:
        raise ValueError("automatic product creation needs a GTIN / MPN / style code (ADR-015)")
    if listing.has_errors:
        codes = sorted({i.code for i in listing.issues if i.severity == "ERROR"})
        raise ValueError(f"listing has validation errors: {codes}")
    product = Product(
        category=listing.category,
        subcategory=getattr(listing.product_attrs, "kind", None),
        brand=listing.brand,
        brand_key=listing.brand_key,
        model_name=listing.model,
        model_key=listing.model_key,
        title=listing.title,
        created_by=created_by,
    )
    variant = ProductVariant(
        product=product,
        variant_key=listing.variant_key or "default",
        variant_attrs=(
            listing.variant_attrs.model_dump(mode="json", exclude_none=True) or None
            if listing.variant_attrs is not None
            else None
        ),
    )
    session.add_all([product, variant])
    session.flush()

    table = ATTRIBUTE_TABLES[listing.category]
    values = _dump(listing.product_attrs)
    unknown = set(values) - _attr_columns(table)
    if unknown:  # schema drift between category model and table: fail loudly, never drop data
        raise ValueError(f"no column for attributes {sorted(unknown)} in {table.__tablename__}")
    session.add(table(product_id=product.id, **values))
    for ident in listing.identifiers:
        session.add(
            VariantIdentifier(variant_id=variant.id, id_type=ident.id_type, value=ident.value)
        )
    session.flush()
    return product, variant


def _attrs_dict(session: Session, table: type[Base], product_id: int) -> dict[str, Any]:
    row = session.get(table, product_id)
    if row is None:
        return {}
    return {c: getattr(row, c) for c in _attr_columns(table)}


def load_candidates(session: Session, listing: NormalizedListing) -> list[ProductCandidate]:
    """Products of the listing's category sharing its brand or one of its identifiers."""
    id_values = [i.value for i in listing.identifiers]
    conditions = []
    if listing.brand_key:
        conditions.append(Product.brand_key == listing.brand_key)
    if id_values:
        conditions.append(
            Product.id.in_(
                select(ProductVariant.product_id)
                .join(VariantIdentifier)
                .where(VariantIdentifier.value.in_(id_values))
            )
        )
    if not conditions:
        return []
    products: Sequence[Product] = session.scalars(
        select(Product)
        .where(
            Product.category == listing.category,
            Product.merged_into_id.is_(None),
            or_(*conditions),
        )
        .limit(MAX_CANDIDATES)
    ).all()
    table = ATTRIBUTE_TABLES[listing.category]
    out = []
    for product in products:
        variants = tuple(
            VariantCandidate(
                variant_id=v.id,
                variant_key=v.variant_key,
                identifiers=frozenset((IdType(i.id_type), i.value) for i in v.identifiers),
                attrs=dict(v.variant_attrs or {}),
            )
            for v in product.variants
            if v.merged_into_id is None
        )
        out.append(
            ProductCandidate(
                product_id=product.id,
                category=product.category,
                brand_key=product.brand_key,
                model_key=product.model_key,
                title_key=text_key(product.title) or "",
                product_attrs=_attrs_dict(session, table, product.id),
                variants=variants,
            )
        )
    return out


def match_listing(db: Database, listing: NormalizedListing) -> MatchOutcome:
    with db.read_session() as session:
        candidates = load_candidates(session, listing)
    return match(listing, candidates, module_for(listing.category))


def dump_listing(listing: NormalizedListing) -> dict[str, Any]:
    """JSON snapshot; serialize_as_any keeps category attribute fields (declared as BaseModel)."""
    data: dict[str, Any] = listing.model_dump(mode="json", serialize_as_any=True)
    return data


def restore_listing(data: dict[str, Any]) -> NormalizedListing:
    """Inverse of dump_listing: re-validates category attributes with the category's own schemas."""
    payload = dict(data)
    module = module_for(Category(payload["category"]))
    for key, model in (
        ("product_attrs", module.product_attrs_model),
        ("variant_attrs", module.variant_attrs_model),
        ("listing_attrs", module.listing_attrs_model),
    ):
        if payload.get(key) is not None:
            payload[key] = model.model_validate(payload[key])
    return NormalizedListing.model_validate(payload)
