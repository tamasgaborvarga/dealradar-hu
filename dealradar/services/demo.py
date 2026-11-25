"""Synthetic demo data: two weeks of mock-source history, a demo fee profile and a few synthetic
completed sales. For trying the app and for UI tests - never mix with real data (use a separate
DEALRADAR_DATA_DIR). Everything created here is labelled synthetic / unverified.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select

from dealradar.core.clock import utcnow
from dealradar.core.enums import (
    Actor,
    Category,
    Condition,
    IdType,
    PlatformKind,
    RefreshScope,
    SaleEvidence,
)
from dealradar.core.identifiers import code_key, text_key
from dealradar.db.models import Offer, Platform, VariantIdentifier
from dealradar.db.session import Database
from dealradar.evaluation.params import TaxKind
from dealradar.services import evaluation, pricing, refresh, sources, workflow
from dealradar.services.refresh import ProgressFn

DEMO_SALES = (  # (brand, part number, synthetic used sale prices)
    ("Demotron", "DX900-1T", (24_000, 25_500, 23_000, 26_000, 24_500, 25_000)),
    ("Probaline", "WM8000X", (98_000, 105_000, 92_000, 101_000, 99_000, 103_000)),
)


def seed_demo(db: Database, days: int = 14, progress: ProgressFn | None = None) -> dict[str, int]:
    if not 1 <= days <= 60:
        raise ValueError("a napok száma 1 és 60 között lehet")
    sources.register_mock_sources(db)
    workflow.save_fee_profile(
        db,
        name="Demó piactér (szintetikus)",
        platform="demó piactér",
        commission_bp=800,
        commission_min_huf=150,
        payment_fee_bp=150,
        payment_fixed_huf=50,
        outbound_shipping_cost_huf=1_990,
        packaging_huf=400,
        verified=False,
        note="szintetikus demóértékek, nem valódi platform díjai",
        make_default=True,
    )
    workflow.set_tax_profile(db, TaxKind.NO_TAX_DECLARED, verified=False, note="csak demó")
    for category in (Category.TECH, Category.HOME):  # demo assumption, labelled as such
        evaluation.set_overrides(db, "resale", category, {"pickup_travel_cost_huf": 2_000})
    now = utcnow()
    sales_added = 0
    for d in range(days, -1, -1):
        when = now - timedelta(days=d, minutes=5)
        refresh.refresh(
            db,
            RefreshScope.ALL,
            now=when,
            evaluate=(d == 0),
            notify_results=(d == 0),
            progress=progress,
        )
        if d == days:
            sales_added = _demo_sales(db, now)
    with db.read_session() as s:
        offers = len(s.scalars(select(Offer.id)).all())
    return {"days": days + 1, "offers": offers, "synthetic_sales": sales_added}


def _demo_sales(db: Database, now: object) -> int:
    added = 0
    with db.write_session() as s:
        platform = s.scalar(select(Platform).where(Platform.key == "demo-auction"))
        if platform is None:
            platform = Platform(
                key="demo-auction", name="Demó aukció (szintetikus)", kind=PlatformKind.AUCTION
            )
            s.add(platform)
            s.flush()
        for brand, mpn, prices in DEMO_SALES:
            value = f"{text_key(brand)}|{code_key(mpn)}"
            ident = s.scalar(
                select(VariantIdentifier).where(
                    VariantIdentifier.id_type == IdType.MPN, VariantIdentifier.value == value
                )
            )
            if ident is None:
                continue
            for i, price in enumerate(prices):
                pricing.record_completed_sale(
                    s,
                    variant_id=ident.variant_id,
                    platform_id=platform.id,
                    evidence=SaleEvidence.USER_REPORTED,
                    condition=Condition.USED_B,
                    sale_price_huf=price,
                    buyer_shipping_huf=1_990,
                    sold_at=utcnow() - timedelta(days=3 + i * 4),
                    source_ref="szintetikus demóadat",
                    entered_by=Actor.SYSTEM,
                    days_listed=6 + i,
                )
                added += 1
    return added
