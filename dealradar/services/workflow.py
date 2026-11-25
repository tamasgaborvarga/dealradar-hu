"""User workflow: watchlists, decisions (incl. rejection feedback), fee/tax profiles, stored
evaluations, deal lists and offer details. Recommendations only - the app never buys."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime
from enum import Enum
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from dealradar.core import hu
from dealradar.core.clock import utcnow
from dealradar.core.enums import (
    Actor,
    CandidateStatus,
    Category,
    Condition,
    Decision,
    MatchMethod,
    MatchStatus,
    PersonalVerdict,
    RejectReason,
    ResaleVerdict,
)
from dealradar.db.models import (
    FeeProfileRecord,
    Listing,
    MatchCandidate,
    Offer,
    OfferDecision,
    PersonalEvaluation,
    PriceObservation,
    Product,
    ProductVariant,
    ResaleEvaluation,
    Source,
    Watchlist,
)
from dealradar.db.repositories import AuditLogRepository, SettingsRepository
from dealradar.db.session import Database
from dealradar.engines.personal import PersonalResult, WatchlistRelevance
from dealradar.engines.resale import ResaleResult
from dealradar.evaluation.params import FeeProfile, TaxKind, TaxProfile
from dealradar.evaluation.types import MatchInfo, WatchlistTarget
from dealradar.services import evaluation
from dealradar.services.catalog import restore_listing

__all__ = ["TaxKind"]  # re-exported for the UI (UI imports services + core only)

FEE_PROFILE_SETTING = "resale.fee_profile_id"
TAX_PROFILE_SETTING = "resale.tax_profile"


def _jsonable(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return {k: _jsonable(v) for k, v in asdict(value).items()}
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        return [_jsonable(v) for v in value]
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if value is None or isinstance(value, bool | int | float | str):
        return value
    return str(value)


# --- watchlists ---


@dataclass(frozen=True)
class WatchlistRow:
    id: int
    name: str
    category: Category
    target: str
    target_price_huf: int | None
    max_price_huf: int | None
    acceptable_conditions: tuple[str, ...]
    notify: bool
    active: bool


def create_watchlist(
    db: Database,
    *,
    name: str,
    category: Category,
    variant_id: int | None = None,
    product_id: int | None = None,
    query_text: str | None = None,
    target_price_huf: int | None = None,
    max_price_huf: int | None = None,
    acceptable_conditions: list[Condition] | None = None,
    notify: bool = True,
) -> int:
    if not name.strip():
        raise ValueError("a név kötelező")
    query = (query_text or "").strip() or None
    if variant_id is None and product_id is None and query is None:
        raise ValueError("adj meg terméket, változatot vagy keresett szöveget")
    for v in (target_price_huf, max_price_huf):
        if v is not None and v <= 0:
            raise ValueError("az árnak pozitívnak kell lennie")
    if target_price_huf and max_price_huf and target_price_huf > max_price_huf:
        raise ValueError("a célár nem lehet nagyobb a maximális árnál")
    with db.write_session() as s:
        row = Watchlist(
            name=name.strip()[:120],
            category=category,
            variant_id=variant_id,
            product_id=product_id,
            query_text=query[:200] if query else None,
            target_price_huf=target_price_huf,
            max_price_huf=max_price_huf,
            acceptable_conditions=[c.value for c in acceptable_conditions]
            if acceptable_conditions
            else None,
            notify=notify,
        )
        s.add(row)
        s.flush()
        AuditLogRepository(s).record(
            actor=Actor.USER,
            entity="watchlists",
            entity_id=str(row.id),
            action="create",
            after={"name": row.name},
        )
        return row.id


def set_watchlist_active(db: Database, watchlist_id: int, active: bool) -> None:
    with db.write_session() as s:
        row = s.get(Watchlist, watchlist_id)
        if row is None:
            raise ValueError(f"nincs ilyen figyelőlista: {watchlist_id}")
        before = row.active
        row.active = active
        AuditLogRepository(s).record(
            actor=Actor.USER,
            entity="watchlists",
            entity_id=str(row.id),
            action="active",
            before=before,
            after=active,
        )


def list_watchlists(db: Database) -> list[WatchlistRow]:
    with db.read_session() as s:
        out = []
        for w in s.scalars(select(Watchlist).order_by(Watchlist.id)).all():
            if w.variant_id:
                target = f"{w.variant_id}. változat"
            elif w.product_id:
                target = f"{w.product_id}. termék"
            else:
                target = f"szöveg: „{w.query_text}”"
            out.append(
                WatchlistRow(
                    w.id,
                    w.name,
                    w.category,
                    target,
                    w.target_price_huf,
                    w.max_price_huf,
                    tuple(w.acceptable_conditions or ()),
                    w.notify,
                    w.active,
                )
            )
        return out


def watchlist_for(
    s: Session, category: Category, title: str, product_id: int | None, variant_id: int | None
) -> Watchlist | None:
    """Most specific active watchlist matching an offer: variant > product > text."""
    rows = s.scalars(
        select(Watchlist).where(Watchlist.active.is_(True), Watchlist.category == category)
    ).all()
    lowered = title.casefold()

    def rank(w: Watchlist) -> int | None:
        if variant_id is not None and w.variant_id == variant_id:
            return 0
        if product_id is not None and w.product_id == product_id and w.variant_id is None:
            return 1
        if w.query_text is not None and w.query_text.casefold() in lowered:
            return 2
        return None

    ranked = [(r, w.id, w) for w in rows if (r := rank(w)) is not None]
    return min(ranked)[2] if ranked else None


def _target(w: Watchlist | None) -> WatchlistTarget | None:
    if w is None:
        return None
    conditions = (
        frozenset(Condition(c) for c in w.acceptable_conditions)
        if w.acceptable_conditions
        else None
    )
    return WatchlistTarget(w.target_price_huf, w.max_price_huf, conditions)


# --- decisions and rejection feedback ---


def decide(
    db: Database,
    offer_id: int,
    decision: Decision,
    *,
    reason: RejectReason | None = None,
    note: str | None = None,
) -> None:
    if decision is Decision.REJECT and reason is None:
        raise ValueError("elutasításhoz válassz okot (ez a visszajelzés)")
    if decision is Decision.BOUGHT:
        raise ValueError("a vásárlást a „Megvettem” űrlapon rögzítsd")
    with db.write_session() as s:
        if s.get(Offer, offer_id) is None:
            raise ValueError(f"nincs ilyen ajánlat: {offer_id}")
        s.add(
            OfferDecision(
                offer_id=offer_id,
                decision=decision,
                reason=reason,
                note=(note or "").strip()[:500] or None,
            )
        )


def current_decision(s: Session, offer_id: int) -> OfferDecision | None:
    return s.scalar(
        select(OfferDecision)
        .where(OfferDecision.offer_id == offer_id)
        .order_by(OfferDecision.id.desc())
        .limit(1)
    )


@dataclass(frozen=True)
class RejectedRow:
    offer_id: int
    title: str
    reason: RejectReason
    note: str | None
    decided_at: datetime


def rejected_offers(db: Database) -> list[RejectedRow]:
    with db.read_session() as s:
        latest: dict[int, OfferDecision] = {}
        for d in s.scalars(select(OfferDecision).order_by(OfferDecision.id)).all():
            latest[d.offer_id] = d
        out = []
        for offer_id, d in latest.items():
            if d.decision is Decision.REJECT and d.reason is not None:
                offer = s.get(Offer, offer_id)
                title = offer.listing.title if offer else "?"
                out.append(RejectedRow(offer_id, title, d.reason, d.note, d.decided_at))
        return sorted(out, key=lambda r: r.decided_at, reverse=True)


def feedback_summary(db: Database) -> dict[RejectReason, int]:
    return dict(Counter(r.reason for r in rejected_offers(db)))


# --- fee and tax profiles (user input) ---


@dataclass(frozen=True)
class FeeProfileRow:
    id: int
    name: str
    platform: str
    verified: bool
    active: bool
    is_default: bool
    profile: FeeProfile


def _to_profile(r: FeeProfileRecord) -> FeeProfile:
    from dealradar.core.money import Bp

    return FeeProfile(
        platform=r.platform,
        commission_bp=Bp(r.commission_bp),
        commission_min_huf=r.commission_min_huf,
        commission_cap_huf=r.commission_cap_huf,
        commission_includes_shipping=r.commission_includes_shipping,
        fixed_fee_huf=r.fixed_fee_huf,
        listing_fee_huf=r.listing_fee_huf,
        payment_fee_bp=r.payment_fee_bp,
        payment_fixed_huf=r.payment_fixed_huf,
        outbound_shipping_cost_huf=r.outbound_shipping_cost_huf,
        packaging_huf=r.packaging_huf,
        verified=r.verified,
        note=r.note or "",
    )


def save_fee_profile(
    db: Database,
    *,
    name: str,
    platform: str,
    commission_bp: int,
    commission_min_huf: int = 0,
    commission_cap_huf: int | None = None,
    commission_includes_shipping: bool = False,
    fixed_fee_huf: int = 0,
    listing_fee_huf: int = 0,
    payment_fee_bp: int = 0,
    payment_fixed_huf: int = 0,
    outbound_shipping_cost_huf: int | None = None,
    packaging_huf: int | None = None,
    verified: bool = False,
    note: str | None = None,
    make_default: bool = False,
) -> int:
    values = {
        "platform": platform.strip(),
        "commission_bp": commission_bp,
        "commission_min_huf": commission_min_huf,
        "commission_cap_huf": commission_cap_huf,
        "commission_includes_shipping": commission_includes_shipping,
        "fixed_fee_huf": fixed_fee_huf,
        "listing_fee_huf": listing_fee_huf,
        "payment_fee_bp": payment_fee_bp,
        "payment_fixed_huf": payment_fixed_huf,
        "outbound_shipping_cost_huf": outbound_shipping_cost_huf,
        "packaging_huf": packaging_huf,
        "verified": verified,
        "note": note,
    }
    if not name.strip() or not values["platform"]:
        raise ValueError("a név és a platform kötelező")
    for k, v in values.items():
        if isinstance(v, int) and not isinstance(v, bool) and v < 0:
            raise ValueError(f"{k}: nem lehet negatív")
    if commission_bp > 10_000 or payment_fee_bp > 10_000:
        raise ValueError("100 %-nál nagyobb díj nem lehetséges")
    with db.write_session() as s:
        row = s.scalar(select(FeeProfileRecord).where(FeeProfileRecord.name == name.strip()))
        before = None
        if row is None:
            row = FeeProfileRecord(name=name.strip()[:120], **values)
            s.add(row)
        else:
            before = {k: getattr(row, k) for k in values}
            for k, v in values.items():
                setattr(row, k, v)
        s.flush()
        AuditLogRepository(s).record(
            actor=Actor.USER,
            entity="fee_profiles",
            entity_id=str(row.id),
            action="save",
            before=before,
            after=values,
        )
        if make_default:
            SettingsRepository(s).set_value(FEE_PROFILE_SETTING, row.id, Actor.USER)
        return row.id


def list_fee_profiles(db: Database) -> list[FeeProfileRow]:
    with db.read_session() as s:
        default = SettingsRepository(s).get_value(FEE_PROFILE_SETTING)
        return [
            FeeProfileRow(
                r.id, r.name, r.platform, r.verified, r.active, r.id == default, _to_profile(r)
            )
            for r in s.scalars(select(FeeProfileRecord).order_by(FeeProfileRecord.id)).all()
        ]


def default_fee_profile(s: Session) -> tuple[int | None, FeeProfile | None]:
    fid = SettingsRepository(s).get_value(FEE_PROFILE_SETTING)
    row = s.get(FeeProfileRecord, fid) if isinstance(fid, int) else None
    if row is None or not row.active:
        return None, None
    return row.id, _to_profile(row)


def set_tax_profile(
    db: Database, kind: TaxKind, rate_bp: int = 0, verified: bool = False, note: str = ""
) -> None:
    if not 0 <= rate_bp <= 10_000:
        raise ValueError("a kulcs 0 és 10 000 bázispont között lehet")
    if kind in (TaxKind.NONE_SELECTED, TaxKind.NO_TAX_DECLARED) and rate_bp:
        raise ValueError(f"{hu.label('tax_kind', kind)}: ehhez nem tartozik kulcs")
    with db.write_session() as s:
        SettingsRepository(s).set_value(
            TAX_PROFILE_SETTING,
            {"kind": kind.value, "rate_bp": rate_bp, "verified": verified, "note": note[:300]},
            Actor.USER,
        )


def tax_profile(s: Session) -> TaxProfile | None:
    raw = SettingsRepository(s).get_value(TAX_PROFILE_SETTING)
    if not isinstance(raw, dict):
        return None
    return TaxProfile(
        TaxKind(raw["kind"]),
        int(raw.get("rate_bp", 0)),
        bool(raw.get("verified")),
        str(raw.get("note", "")),
    )


# --- evaluation (stored) ---


def _match_info(s: Session, listing: Listing) -> MatchInfo:
    if listing.match_status is not MatchStatus.MATCHED:
        return MatchInfo(listing.match_status)
    accepted = s.scalar(
        select(MatchCandidate).where(
            MatchCandidate.listing_id == listing.id,
            MatchCandidate.status == CandidateStatus.ACCEPTED,
        )
    )
    if accepted is None:
        return MatchInfo(MatchStatus.MATCHED, MatchMethod.USER, 100, confirmed_by_user=True)
    return MatchInfo(
        MatchStatus.MATCHED,
        accepted.method,
        accepted.confidence,
        confirmed_by_user=accepted.decided_by is Actor.USER,
    )


def evaluate_offer(
    db: Database, offer_id: int, now: datetime | None = None
) -> tuple[PersonalResult, ResaleResult] | None:
    """Run both engines (separately) on the stored listing snapshot and store both results.
    Returns None if the listing has no snapshot yet."""
    now = now or utcnow()
    with db.read_session() as s:
        offer = s.get(Offer, offer_id)
        if offer is None:
            raise ValueError(f"nincs ilyen ajánlat: {offer_id}")
        listing = offer.listing
        if listing.normalized is None:
            return None
        normalized = restore_listing(listing.normalized)
        match = _match_info(s, listing)
        variant_id = offer.variant_id
        watch = watchlist_for(s, normalized.category, listing.title, listing.product_id, variant_id)
        fee_id, fee = default_fee_profile(s)
        tax = tax_profile(s)
    p = evaluation.evaluate_personal(db, normalized, variant_id, match, _target(watch), now)
    r = evaluation.evaluate_resale(db, normalized, variant_id, match, fee, tax, now)
    with db.write_session() as s:
        s.add(
            PersonalEvaluation(
                offer_id=offer_id,
                evaluated_at=now,
                verdict=p.verdict,
                effective_price_huf=p.effective_price_huf,
                benchmark_median_huf=p.benchmark_median_huf,
                discount_vs_median_bp=p.discount_vs_median_bp,
                watchlist_relevance=p.watchlist.value,
                missing_json=list(p.missing_inputs),
                flags_json=list(p.review_flags),
                result_json=_jsonable(p),
            )
        )
        s.add(
            ResaleEvaluation(
                offer_id=offer_id,
                evaluated_at=now,
                verdict=r.verdict,
                fee_profile_id=fee_id,
                acquisition_cost_huf=r.acquisition_cost_huf,
                expected_sale_huf=r.expected_sale_huf,
                net_profit_huf=r.net_profit_huf,
                net_profit_low_huf=r.net_profit_low_huf,
                roi_bp=r.roi_bp,
                provisional=r.provisional,
                liquidity=r.liquidity.liquidity.value,
                est_days_to_sell=r.liquidity.est_days_to_sell,
                missing_json=list(r.missing_inputs),
                flags_json=list(r.review_flags),
                result_json=_jsonable(r),
            )
        )
    return p, r


def watch_target_met(p: PersonalResult) -> bool:
    return p.watchlist is WatchlistRelevance.TARGET_MET


# --- deal lists and offer detail ---


@dataclass(frozen=True)
class DealRow:
    offer_id: int
    title: str
    category: Category | None
    source: str
    price_huf: int | None  # latest asking price (item only)
    effective_price_huf: int | None  # item + delivery, from the Personal evaluation
    observed_at: datetime | None
    personal_verdict: PersonalVerdict | None
    discount_bp: int | None
    watchlist: str | None
    resale_verdict: ResaleVerdict | None
    net_profit_huf: int | None  # ESTIMATE
    roi_bp: int | None  # ESTIMATE
    provisional: bool
    decision: Decision | None


def _latest_by_offer(s: Session, model: type[Any]) -> dict[int, Any]:
    latest: dict[int, Any] = {}
    for row in s.scalars(select(model).order_by(model.id)).all():
        latest[row.offer_id] = row
    return latest


def deal_rows(
    db: Database, category: Category | None = None, include_rejected: bool = False
) -> list[DealRow]:
    with db.read_session() as s:
        personal = _latest_by_offer(s, PersonalEvaluation)
        resale = _latest_by_offer(s, ResaleEvaluation)
        decisions = _latest_by_offer(s, OfferDecision)
        latest_obs: dict[int, PriceObservation] = {}
        for o in s.scalars(select(PriceObservation).order_by(PriceObservation.observed_at)).all():
            latest_obs[o.offer_id] = o
        rows = s.execute(
            select(Offer, Listing, Source)
            .join(Listing, Offer.listing_id == Listing.id)
            .join(Source, Listing.source_id == Source.id)
        ).all()
        products = {p.id: p.category for p in s.scalars(select(Product)).all()}
        out = []
        for offer, listing, source in rows:
            cat = products.get(listing.product_id) if listing.product_id else listing.category_hint
            if category is not None and cat is not category:
                continue
            d = decisions.get(offer.id)
            if d is not None and d.decision is Decision.REJECT and not include_rejected:
                continue
            pe, re_, ob = personal.get(offer.id), resale.get(offer.id), latest_obs.get(offer.id)
            out.append(
                DealRow(
                    offer.id,
                    listing.title,
                    cat,
                    source.name,
                    ob.price_huf if ob else None,
                    pe.effective_price_huf if pe else None,
                    ob.observed_at if ob else None,
                    pe.verdict if pe else None,
                    pe.discount_vs_median_bp if pe else None,
                    pe.watchlist_relevance if pe else None,
                    re_.verdict if re_ else None,
                    re_.net_profit_huf if re_ else None,
                    re_.roi_bp if re_ else None,
                    bool(re_ and re_.provisional),
                    d.decision if d else None,
                )
            )
        return out


_PERSONAL_RANK = {
    PersonalVerdict.STRONG_DEAL: 0,
    PersonalVerdict.GOOD_DEAL: 1,
    PersonalVerdict.FAIR_PRICE: 2,
    PersonalVerdict.MANUAL_REVIEW: 3,
    PersonalVerdict.NOT_A_DEAL: 4,
}
_RESALE_RANK = {
    ResaleVerdict.PROFITABLE: 0,
    ResaleVerdict.MARGINAL: 1,
    ResaleVerdict.MANUAL_REVIEW: 2,
    ResaleVerdict.NOT_PROFITABLE: 3,
    ResaleVerdict.NOT_APPLICABLE: 4,
}


def personal_deals(rows: list[DealRow]) -> list[DealRow]:
    """Sorted by the Personal verdict, then discount. Independent of the resale list."""
    picked = [r for r in rows if r.personal_verdict is not None]
    return sorted(
        picked,
        key=lambda r: (
            _PERSONAL_RANK[r.personal_verdict],  # type: ignore[index]
            -(r.discount_bp or -(10**9)),
        ),
    )


def resale_deals(rows: list[DealRow]) -> list[DealRow]:
    """Sorted by the Resale verdict, then expected net profit (ESTIMATES)."""
    picked = [r for r in rows if r.resale_verdict not in (None, ResaleVerdict.NOT_APPLICABLE)]
    return sorted(
        picked,
        key=lambda r: (
            _RESALE_RANK[r.resale_verdict],  # type: ignore[index]
            -(r.net_profit_huf or -(10**12)),
        ),
    )


@dataclass(frozen=True)
class PricePoint:
    observed_at: datetime
    price_huf: int | None
    shipping_huf: int | None
    availability: str


@dataclass(frozen=True)
class OfferDetail:
    offer_id: int
    title: str
    url: str | None
    source: str
    listing_kind: str
    condition: str | None
    warranty: str | None
    seller_kind: str | None
    match_status: str
    product: str | None
    variant_key: str | None
    variant_id: int | None
    category: Category | None
    history: list[PricePoint]
    personal: dict[str, Any] | None
    personal_at: datetime | None
    resale: dict[str, Any] | None
    resale_at: datetime | None
    decisions: list[tuple[datetime, str, str | None, str | None]]


def offer_detail(db: Database, offer_id: int) -> OfferDetail:
    with db.read_session() as s:
        offer = s.get(Offer, offer_id)
        if offer is None:
            raise ValueError(f"nincs ilyen ajánlat: {offer_id}")
        listing = offer.listing
        source = s.get(Source, listing.source_id)
        variant = s.get(ProductVariant, offer.variant_id) if offer.variant_id else None
        product = s.get(Product, listing.product_id) if listing.product_id else None
        history = [
            PricePoint(o.observed_at, o.price_huf, o.shipping_huf, o.availability.value)
            for o in s.scalars(
                select(PriceObservation)
                .where(PriceObservation.offer_id == offer_id)
                .order_by(PriceObservation.observed_at)
            ).all()
        ]
        pe = s.scalar(
            select(PersonalEvaluation)
            .where(PersonalEvaluation.offer_id == offer_id)
            .order_by(PersonalEvaluation.id.desc())
            .limit(1)
        )
        re_ = s.scalar(
            select(ResaleEvaluation)
            .where(ResaleEvaluation.offer_id == offer_id)
            .order_by(ResaleEvaluation.id.desc())
            .limit(1)
        )
        decisions = [
            (d.decided_at, d.decision.value, d.reason.value if d.reason else None, d.note)
            for d in s.scalars(
                select(OfferDecision)
                .where(OfferDecision.offer_id == offer_id)
                .order_by(OfferDecision.id.desc())
            ).all()
        ]
        kind = (
            hu.label("warranty_type", listing.warranty_type)
            if listing.warranty_type
            else "típusa nincs megadva"
        )
        warranty = (
            f"{listing.warranty_months} hónap ({kind})"
            if listing.warranty_months is not None
            else None
        )
        return OfferDetail(
            offer_id=offer_id,
            title=listing.title,
            url=listing.url,
            source=source.name if source else "?",
            listing_kind=listing.listing_kind.value,
            condition=listing.condition.value if listing.condition else None,
            warranty=warranty,
            seller_kind=listing.seller_kind.value if listing.seller_kind else None,
            match_status=listing.match_status.value,
            product=f"{product.brand or ''} {product.model_name or product.title}".strip()
            if product
            else None,
            variant_key=variant.variant_key if variant else None,
            variant_id=variant.id if variant else None,
            category=product.category if product else listing.category_hint,
            history=history,
            personal=pe.result_json if pe else None,
            personal_at=pe.evaluated_at if pe else None,
            resale=re_.result_json if re_ else None,
            resale_at=re_.evaluated_at if re_ else None,
            decisions=decisions,
        )
