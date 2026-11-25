"""Manual Claude analysis workflow on the database (ADR-048).

prepare_analysis -> the user copies the prompt to claude.ai -> import_response validates and stores
the pasted answer. Nothing here changes offers, listings, products, prices or evaluations; the app
works the same whether or not this workflow is ever used.
"""

from __future__ import annotations

import json
import secrets
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from dealradar.categories.registry import module_for
from dealradar.claude_bridge.package import AnalysisPackage, ItemKind, PackageItem
from dealradar.claude_bridge.prompt import CLAUDE_URL, render
from dealradar.claude_bridge.response import MAX_RESPONSE_BYTES, parse_response
from dealradar.claude_bridge.schema import SCHEMA_VERSION, AnalysisResponse
from dealradar.core.clock import utcnow
from dealradar.core.enums import AnalysisStatus
from dealradar.db.models import (
    AiRequest,
    AiResponse,
    Listing,
    Offer,
    PriceObservation,
    Product,
    ProductVariant,
    Source,
)
from dealradar.db.session import Database
from dealradar.engines.personal import PersonalResult
from dealradar.engines.resale import ResaleResult
from dealradar.evaluation.types import ValueKind
from dealradar.pricing.types import (
    BenchmarkStatus,
    ConditionGroup,
    channel_of,
    condition_group,
)
from dealradar.services import pricing

PACKAGE_VALID_FOR = timedelta(days=7)
__all__ = ["CLAUDE_URL", "import_response", "list_offers", "prepare_analysis"]
_KIND = {
    ValueKind.FACT: ItemKind.FACT,
    ValueKind.USER_INPUT: ItemKind.FACT,
    ValueKind.ESTIMATE: ItemKind.ESTIMATE,
    ValueKind.ASSUMPTION: ItemKind.ASSUMPTION,
}


@dataclass(frozen=True)
class PreparedAnalysis:
    request_id: str
    prompt: str
    package: AnalysisPackage
    created_at: datetime
    expires_at: datetime


@dataclass(frozen=True)
class ImportOutcome:
    accepted: bool
    errors: tuple[str, ...]
    analysis: AnalysisResponse | None
    received_at: datetime


@dataclass(frozen=True)
class OfferChoice:
    offer_id: int
    label: str


def _huf(value: int | None) -> str:
    return "unknown" if value is None else f"{value:,} HUF".replace(",", " ")


def list_offers(db: Database, limit: int = 200) -> list[OfferChoice]:
    with db.read_session() as s:
        rows = s.execute(
            select(Offer.id, Listing.title, Source.name)
            .join(Listing, Offer.listing_id == Listing.id)
            .join(Source, Listing.source_id == Source.id)
            .order_by(Offer.id.desc())
            .limit(limit)
        ).all()
    return [OfferChoice(oid, f"#{oid} {title[:80]} ({source})") for oid, title, source in rows]


def build_package(
    s: Session,
    db: Database,
    offer_id: int,
    request_id: str,
    *,
    personal: PersonalResult | None,
    resale: ResaleResult | None,
    description: str | None,
    now: datetime,
) -> AnalysisPackage:
    offer = s.get(Offer, offer_id)
    if offer is None:
        raise ValueError(f"unknown offer {offer_id}")
    listing = offer.listing
    source = s.get(Source, listing.source_id)
    variant = s.get(ProductVariant, offer.variant_id) if offer.variant_id else None
    product = s.get(Product, variant.product_id) if variant else None
    obs = s.scalar(
        select(PriceObservation)
        .where(PriceObservation.offer_id == offer.id)
        .order_by(PriceObservation.observed_at.desc())
        .limit(1)
    )
    items: list[PackageItem] = []
    missing: list[str] = []

    def add(key: str, label: str, value: str, kind: ItemKind, src: str) -> None:
        items.append(PackageItem(key, label, value, kind, src))

    category = product.category if product else listing.category_hint
    add("source", "Source", source.name if source else "unknown", ItemKind.FACT, "source registry")
    add("listing_kind", "Listing type", listing.listing_kind.value, ItemKind.FACT, "source")
    if obs is None:
        missing.append("no recorded price observation for this offer")
    else:
        add(
            "price",
            "Price (item)",
            _huf(obs.price_huf),
            ItemKind.FACT,
            f"observed {obs.observed_at:%Y-%m-%d %H:%M} UTC",
        )
        add("delivery", "Delivery cost", _huf(obs.shipping_huf), ItemKind.FACT, "same observation")
        add(
            "availability",
            "Availability",
            obs.availability.value,
            ItemKind.FACT,
            "same observation",
        )
        if obs.shipping_huf is None:
            missing.append("delivery cost is unknown (it is NOT assumed to be free)")
    if product and variant:
        add(
            "product",
            "Matched product",
            f"{product.category.value}: {product.brand or '?'} "
            f"{product.model_name or product.title}",
            ItemKind.FACT,
            f"match status {listing.match_status.value}",
        )
        add("variant", "Variant", variant.variant_key, ItemKind.FACT, "category variant rules")
    else:
        missing.append("offer is not matched to a known product variant")
    if listing.condition is not None:
        add("condition", "Condition", listing.condition.value, ItemKind.SELLER_CLAIM, "listing")
    else:
        missing.append("condition not stated")
    if listing.warranty_months is not None:
        add(
            "warranty",
            "Warranty",
            f"{listing.warranty_months} months ({listing.warranty_type or 'type not stated'})",
            ItemKind.SELLER_CLAIM,
            "listing",
        )
    if listing.seller_kind is not None:
        add("seller", "Seller type", listing.seller_kind.value, ItemKind.SELLER_CLAIM, "listing")

    # benchmarks (estimates) - only for a matched variant
    if variant is not None and category is not None:
        policy = module_for(category).benchmark_policy
        group = (
            condition_group(listing.condition)
            if policy.condition_relevant
            else ConditionGroup.NOT_APPLICABLE
        )
        if group is not None:
            adv = pricing.advertised_benchmark(
                db, variant.id, group, channel_of(listing.listing_kind), now
            )
            if adv.item is not None and adv.status in (BenchmarkStatus.OK, BenchmarkStatus.STALE):
                add(
                    "benchmark_median",
                    "Typical advertised price (trimmed median)",
                    _huf(adv.item.trimmed_median),
                    ItemKind.ESTIMATE,
                    f"{adv.n_samples} offer-days, {adv.n_sources} sources, confidence "
                    f"{adv.confidence.value}, status {adv.status.value}",
                )
                add(
                    "benchmark_min",
                    "Lowest advertised price in the window",
                    _huf(adv.item.min),
                    ItemKind.FACT,
                    f"last {policy.window_days} days, outliers excluded",
                )
            else:
                missing.append(f"no reliable price history ({adv.status.value})")
            if group is not ConditionGroup.NOT_APPLICABLE:
                sold = pricing.sold_benchmark(db, variant.id, group, now)
                if sold.sale_price is not None:
                    add(
                        "sold_median",
                        "Typical completed-sale price",
                        _huf(sold.sale_price.trimmed_median),
                        ItemKind.ESTIMATE,
                        f"{sold.n_sales} completed sales, {sold.confidence.value}",
                    )
                else:
                    missing.append(f"no reliable completed-sale data ({sold.status.value})")

    evaluations: list[str] = []
    for name, result in (("Personal", personal), ("Resale", resale)):
        if result is None:
            evaluations.append(f"{name} engine: not evaluated in this view")
            continue
        evaluations.append(f"{name} engine verdict: {result.verdict.value}")
        missing += [f"{name.lower()} engine needs: {m}" for m in result.missing_inputs]
        evaluations += [f"{name.lower()} review flag: {f}" for f in result.review_flags]
        for a in result.assumptions:
            key = f"{name.lower()}_{a.name.replace(' ', '_').replace('/', '')}"[:60]
            add(key, f"{name}: {a.name}", a.value, _KIND[a.kind], a.source)
    if personal is not None and personal.discount_vs_median_bp is not None:
        add(
            "personal_discount",
            "Below typical price",
            f"{personal.discount_vs_median_bp / 100:.1f} % ({personal.comparison_basis})",
            ItemKind.ESTIMATE,
            "personal engine",
        )
    if resale is not None and resale.net_profit_huf is not None:
        add(
            "resale_net_profit",
            "Expected resale net profit",
            f"{_huf(resale.net_profit_huf)} (low {_huf(resale.net_profit_low_huf)}, high "
            f"{_huf(resale.net_profit_high_huf)}){' PROVISIONAL' if resale.provisional else ''}",
            ItemKind.ESTIMATE,
            "resale engine, completed sales only",
        )

    return AnalysisPackage(
        request_id=request_id,
        category=category.value if category else "UNKNOWN",
        items=tuple(items),
        missing=tuple(dict.fromkeys(missing)),
        evaluations=tuple(evaluations),
        untrusted_title=listing.title,
        untrusted_description=description,
    )


def prepare_analysis(
    db: Database,
    offer_id: int,
    *,
    personal: PersonalResult | None = None,
    resale: ResaleResult | None = None,
    description: str | None = None,
    now: datetime | None = None,
) -> PreparedAnalysis:
    now = now or utcnow()
    request_id = f"dr-{secrets.token_hex(6)}"
    with db.read_session() as s:
        package = build_package(
            s,
            db,
            offer_id,
            request_id,
            personal=personal,
            resale=resale,
            description=description,
            now=now,
        )
    prompt = render(package)
    expires = now + PACKAGE_VALID_FOR
    with db.write_session() as s:
        s.add(
            AiRequest(
                request_id=request_id,
                offer_id=offer_id,
                schema_version=SCHEMA_VERSION,
                mode="CLIPBOARD",
                package_json=asdict(package),
                prompt_text=prompt,
                prompt_sha256=package.digest(),
                status=AnalysisStatus.PREPARED,
                created_at=now,
                expires_at=expires,
            )
        )
    return PreparedAnalysis(request_id, prompt, package, now, expires)


def import_response(
    db: Database, request_id: str, pasted: str, now: datetime | None = None
) -> ImportOutcome:
    """Validate a pasted answer and store it (valid or not) with its timestamp."""
    now = now or utcnow()
    raw = pasted.encode("utf-8")[:MAX_RESPONSE_BYTES].decode("utf-8", errors="ignore")
    with db.write_session() as s:
        request = s.scalar(select(AiRequest).where(AiRequest.request_id == request_id))
        if request is None:
            raise ValueError(f"unknown analysis request {request_id!r}")
        if now > request.expires_at:
            if request.status is AnalysisStatus.PREPARED:
                request.status = AnalysisStatus.EXPIRED
            errors: tuple[str, ...] = ("analysis package expired; prepare a new one",)
            result_ok, parsed = False, None
        else:
            outcome = parse_response(pasted, AnalysisPackage.from_dict(request.package_json))
            errors, result_ok, parsed = outcome.errors, outcome.accepted, outcome.response
        s.add(
            AiResponse(
                ai_request_id=request.id,
                received_at=now,
                raw_text=raw,
                valid=result_ok,
                errors=list(errors) or None,
                parsed_json=parsed.model_dump(mode="json") if parsed else None,
            )
        )
        if result_ok:
            request.status = AnalysisStatus.ANSWERED
    return ImportOutcome(result_ok, errors, parsed, now)


@dataclass(frozen=True)
class StoredAnalysis:
    request_id: str
    created_at: datetime
    status: AnalysisStatus
    received_at: datetime | None
    analysis: AnalysisResponse | None


def analyses_for_offer(db: Database, offer_id: int) -> list[StoredAnalysis]:
    """Latest valid answer per request, newest request first."""
    out: list[StoredAnalysis] = []
    with db.read_session() as s:
        requests = s.scalars(
            select(AiRequest).where(AiRequest.offer_id == offer_id).order_by(AiRequest.id.desc())
        ).all()
        for r in requests:
            valid = s.scalar(
                select(AiResponse)
                .where(AiResponse.ai_request_id == r.id, AiResponse.valid.is_(True))
                .order_by(AiResponse.received_at.desc())
                .limit(1)
            )
            parsed = (
                AnalysisResponse.model_validate_json(json.dumps(valid.parsed_json))
                if valid and valid.parsed_json
                else None
            )
            out.append(
                StoredAnalysis(
                    r.request_id,
                    r.created_at,
                    r.status,
                    valid.received_at if valid else None,
                    parsed,
                )
            )
    return out
