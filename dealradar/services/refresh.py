"""Manual refresh workflow (docs/SOURCES.md §4): one source, one category, or all sources.

Per source: preflight (registry + access review + method + demo opt-in) -> adapter.fetch through
the PoliteRequester -> per offer: normalize, upsert listing/offer, match, record observation
(duplicates skipped), evaluate both engines (separately), notify. Every run, error and timestamp
is recorded. A blocked source is marked BLOCKED and skipped until the user re-reviews it.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from dealradar.categories.registry import module_for
from dealradar.core import hu
from dealradar.core.clock import utcnow
from dealradar.core.enums import (
    AccessMethod,
    Actor,
    Availability,
    CandidateStatus,
    Category,
    FetchErrorKind,
    IdType,
    MatchMethod,
    MatchStatus,
    PersonalVerdict,
    ProductOrigin,
    RefreshScope,
    ResaleVerdict,
    RunStatus,
    SourceStatus,
)
from dealradar.db.models import (
    Listing,
    MatchCandidate,
    Offer,
    PriceObservation,
    ProductVariant,
    RawRecord,
    RefreshJob,
    Source,
    SourceRun,
    SourceRunError,
)
from dealradar.db.repositories import SettingsRepository
from dealradar.db.session import Database
from dealradar.matching.types import OutcomeKind
from dealradar.normalize.types import NormalizedListing
from dealradar.services import catalog, notify, workflow
from dealradar.sources.base import AdapterOffer, RecordError
from dealradar.sources.errors import AccessNotPermitted, SourceBlocked, SourceError
from dealradar.sources.registry import get_adapter, transport_for
from dealradar.sources.requester import PoliteRequester, ResponseCache

log = logging.getLogger(__name__)
DEMO_SETTING = "demo.mock_sources_allowed"
BUYABLE = (Availability.IN_STOCK, Availability.LIMITED, Availability.PREORDER, Availability.UNKNOWN)

ProgressFn = Callable[["RefreshEvent"], None]


@dataclass(frozen=True)
class RefreshEvent:
    kind: str  # JOB_STARTED, SOURCE_STARTED, RECORDS, SOURCE_FINISHED, SOURCE_SKIPPED, JOB_FINISHED
    source_key: str | None = None
    done_sources: int = 0
    total_sources: int = 0
    records: int = 0
    message: str = ""


@dataclass
class SourceSummary:
    source_key: str
    status: RunStatus
    fetched: int = 0
    parsed: int = 0
    failed: int = 0
    new_observations: int = 0
    duplicates: int = 0
    retries: int = 0
    cache_hits: int = 0
    requests: int = 0
    error_kind: FetchErrorKind | None = None
    message: str = ""


@dataclass
class RefreshReport:
    job_id: int
    scope: RefreshScope
    target: str | None
    status: RunStatus
    started_at: datetime
    finished_at: datetime
    sources: list[SourceSummary] = field(default_factory=list)


# --- source selection and preflight ---


def _sources_for(s: Session, scope: RefreshScope, target: str | None) -> list[Source]:
    rows = list(s.scalars(select(Source).order_by(Source.key)).all())
    if scope is RefreshScope.SOURCE:
        picked = [r for r in rows if r.key == target]
        if not picked:
            raise ValueError(f"nincs ilyen forrás: {target}")
        return picked
    rows = [r for r in rows if r.status in (SourceStatus.ACTIVE, SourceStatus.DEGRADED)]
    if scope is RefreshScope.CATEGORY:
        category = Category(str(target))
        return [
            r for r in rows if (a := get_adapter(r.key)) is not None and category in a.categories
        ]
    return rows


def _preflight(s: Session, source: Source) -> str | None:
    """Return a refusal reason, or None if this source may run."""
    adapter = get_adapter(source.key)
    if adapter is None:
        return "ehhez a forráshoz nincs adatgyűjtő"
    if not source.access_review_ok or source.status not in (
        SourceStatus.ACTIVE,
        SourceStatus.DEGRADED,
    ):
        state = hu.label("source_status", source.status)
        return f"a forrás állapota: {state}, vagy a hozzáférés-ellenőrzés nincs kész"
    if adapter.access_method is not source.access_method:
        return (
            f"az adatgyűjtő módja ({adapter.access_method.value}) eltér az ellenőrzéskor "
            f"rögzítettől ({source.access_method.value})"
        )
    if adapter.access_method is AccessMethod.MOCK and not SettingsRepository(s).get_value(
        DEMO_SETTING
    ):
        return "a demóforrások csak a demóadatok bekapcsolása után futhatnak"
    return None


def _requests_today(s: Session, source_id: int, now: datetime) -> int:
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    runs = s.scalars(
        select(SourceRun).where(SourceRun.source_id == source_id, SourceRun.started_at >= start)
    ).all()
    return sum(r.requests for r in runs)


# --- per-offer processing ---


def _upsert(
    s: Session, source: Source, rec: AdapterOffer, listing: NormalizedListing, now: datetime
) -> Offer:
    row = s.scalar(
        select(Listing).where(
            Listing.source_id == source.id, Listing.external_id == listing.external_id
        )
    )
    attrs = (
        listing.listing_attrs.model_dump(mode="json") if listing.listing_attrs is not None else None
    )
    if row is None:
        row = Listing(
            source_id=source.id,
            external_id=listing.external_id,
            title=listing.title,
            listing_kind=listing.listing_kind,
            first_seen_at=rec.fetched_at,
            last_seen_at=rec.fetched_at,
        )
        s.add(row)
    row.title = listing.title
    row.url = rec.raw.url
    row.category_hint = rec.category
    row.condition = listing.condition
    row.warranty_months = listing.warranty_months
    row.warranty_type = listing.warranty_type
    row.seller_kind = listing.seller_kind
    row.price_is_net = rec.raw.price_is_net
    row.category_attrs = attrs
    row.normalized = catalog.dump_listing(listing)
    row.last_seen_at = max(row.last_seen_at or rec.fetched_at, rec.fetched_at)
    row.delisted_at = None
    s.flush()
    key = listing.variant_key or "default"
    offer = s.scalar(select(Offer).where(Offer.listing_id == row.id, Offer.variant_key_raw == key))
    if offer is None:
        offer = Offer(listing_id=row.id, variant_key_raw=key)
        s.add(offer)
        s.flush()
    return offer


def _match(
    s: Session, db: Database, offer: Offer, listing: NormalizedListing, now: datetime
) -> None:
    row = offer.listing
    if row.match_status is MatchStatus.MATCHED and offer.variant_id is not None:
        return
    if row.match_status is not MatchStatus.MATCHED:
        candidates = catalog.load_candidates(s, listing)
        from dealradar.matching.cascade import match

        outcome = match(listing, candidates, module_for(listing.category))
        if outcome.kind is OutcomeKind.AUTO_MATCH and outcome.product_id is not None:
            s.add(
                MatchCandidate(
                    listing_id=row.id,
                    product_id=outcome.product_id,
                    method=outcome.method,
                    confidence=outcome.confidence,
                    reason="; ".join(outcome.reasons)[:500],
                    status=CandidateStatus.ACCEPTED,
                    decided_at=now,
                    decided_by=Actor.SYSTEM,
                )
            )
            row.product_id = outcome.product_id
            row.match_status = MatchStatus.MATCHED
            offer.variant_id = outcome.variant_id
        elif outcome.kind in (OutcomeKind.REVIEW, OutcomeKind.CONFLICT):
            existing = {
                c.product_id
                for c in s.scalars(
                    select(MatchCandidate).where(
                        MatchCandidate.listing_id == row.id,
                        MatchCandidate.status == CandidateStatus.OPEN,
                    )
                )
            }
            for c in outcome.candidates:
                if c.product_id not in existing:
                    s.add(
                        MatchCandidate(
                            listing_id=row.id,
                            product_id=c.product_id,
                            method=c.method,
                            confidence=c.confidence,
                            reason=c.reason[:500],
                        )
                    )
            row.match_status = MatchStatus.PENDING_REVIEW
        elif listing.identifiers and not listing.has_errors:
            # ADR-015: the system may create a product only from a global identifier.
            product, variant = catalog.create_product(s, listing, ProductOrigin.RULE)
            s.add(
                MatchCandidate(
                    listing_id=row.id,
                    product_id=product.id,
                    method=_identifier_method(listing),
                    confidence=100,
                    reason="new product from identifier",
                    status=CandidateStatus.ACCEPTED,
                    decided_at=now,
                    decided_by=Actor.SYSTEM,
                )
            )
            row.product_id = product.id
            row.match_status = MatchStatus.MATCHED
            offer.variant_id = variant.id
    if row.match_status is MatchStatus.MATCHED and offer.variant_id is None and listing.variant_key:
        # A new variant (e.g. a new size) of a matched product: deterministic from the category's
        # variant key, not a guess.
        found = s.scalar(
            select(ProductVariant).where(
                ProductVariant.product_id == row.product_id,
                ProductVariant.variant_key == listing.variant_key,
            )
        )
        if found is None:
            attrs = (
                listing.variant_attrs.model_dump(mode="json", exclude_none=True)
                if listing.variant_attrs
                else None
            )
            found = ProductVariant(
                product_id=row.product_id,
                variant_key=listing.variant_key,
                variant_attrs=attrs or None,
            )
            s.add(found)
            s.flush()
        offer.variant_id = found.id
    s.flush()


def _identifier_method(listing: NormalizedListing) -> MatchMethod:
    first = listing.identifiers[0].id_type
    return {
        IdType.GTIN: MatchMethod.GTIN,
        IdType.MPN: MatchMethod.MPN,
        IdType.STYLE_CODE: MatchMethod.STYLE_CODE,
    }.get(first, MatchMethod.RULE)


def _observe(
    s: Session,
    offer: Offer,
    source: Source,
    rec: AdapterOffer,
    listing: NormalizedListing,
    raw_id: int,
) -> str:
    """Returns 'new', 'duplicate' or an error message."""
    if s.scalar(
        select(PriceObservation.id).where(
            PriceObservation.offer_id == offer.id, PriceObservation.observed_at == rec.fetched_at
        )
    ):
        return "duplicate"
    if (
        listing.price_huf is None
        and rec.availability in BUYABLE
        and rec.availability is not Availability.UNKNOWN
    ):
        return "nincs használható ár, pedig megvásárolható"
    price = listing.price_huf
    availability = rec.availability
    if price is None and availability is not Availability.OUT_OF_STOCK:
        availability = Availability.UNKNOWN
    s.add(
        PriceObservation(
            offer_id=offer.id,
            source_id=source.id,
            observed_at=rec.fetched_at,
            price_huf=price,
            shipping_huf=listing.shipping_huf,
            availability=availability,
            condition=listing.condition,
            listing_kind=listing.listing_kind,
            loyalty_only=offer.loyalty_only,
            min_quantity=offer.min_quantity,
            raw_record_id=raw_id,
        )
    )
    return "new"


# --- the run ---


def _no_progress(event: RefreshEvent) -> None:
    return None


def refresh(
    db: Database,
    scope: RefreshScope,
    target: str | None = None,
    *,
    progress: ProgressFn | None = None,
    now: datetime | None = None,
    sleep: Callable[[float], None] | None = None,
    evaluate: bool = True,
    notify_results: bool = True,
) -> RefreshReport:
    if scope is RefreshScope.CATEGORY and target not in {c.value for c in Category}:
        raise ValueError(f"nincs ilyen kategória: {target}")
    if scope is RefreshScope.SOURCE and not target:
        raise ValueError("egy forrás frissítéséhez add meg a forrás kulcsát")
    started = now or utcnow()

    def fixed_clock() -> datetime:
        return started

    clock: Callable[[], datetime] = fixed_clock if now is not None else utcnow
    emit: ProgressFn = progress or _no_progress
    with db.write_session() as s:
        sources = _sources_for(s, scope, target)
        job = RefreshJob(scope=scope, target=target, requested_by=Actor.USER, started_at=started)
        s.add(job)
        s.flush()
        job_id = job.id
        source_ids = [x.id for x in sources]
    report = RefreshReport(job_id, scope, target, RunStatus.RUNNING, started, started)
    categories = (
        frozenset({Category(str(target))})
        if scope is RefreshScope.CATEGORY
        else frozenset(Category)
    )
    emit(RefreshEvent("JOB_STARTED", total_sources=len(source_ids)))
    for i, source_id in enumerate(source_ids):
        summary = _run_source(
            db,
            source_id,
            job_id,
            categories,
            clock,
            sleep,
            emit,
            i,
            len(source_ids),
            evaluate,
            notify_results,
        )
        report.sources.append(summary)
        emit(
            RefreshEvent(
                "SOURCE_FINISHED",
                summary.source_key,
                i + 1,
                len(source_ids),
                summary.fetched,
                f"{summary.status.value}: {summary.message}",
            )
        )
    statuses = {x.status for x in report.sources}
    if not statuses or statuses == {RunStatus.OK}:
        final = RunStatus.OK
    elif RunStatus.OK in statuses or RunStatus.PARTIAL in statuses:
        final = RunStatus.PARTIAL
    else:
        final = RunStatus.FAILED
    finished = clock()
    with db.write_session() as s:
        job_row = s.get(RefreshJob, job_id)
        assert job_row is not None
        job_row.status = final
        job_row.finished_at = finished
    report.status, report.finished_at = final, finished
    emit(
        RefreshEvent(
            "JOB_FINISHED",
            done_sources=len(source_ids),
            total_sources=len(source_ids),
            message=final.value,
        )
    )
    return report


def _run_source(
    db: Database,
    source_id: int,
    job_id: int,
    categories: frozenset[Category],
    clock: Callable[[], datetime],
    sleep: Callable[[float], None] | None,
    emit: ProgressFn,
    index: int,
    total: int,
    evaluate: bool,
    notify_results: bool,
) -> SourceSummary:
    with db.write_session() as s:
        source = s.get(Source, source_id)
        assert source is not None
        key = source.key
        refusal = _preflight(s, source)
        run = SourceRun(source_id=source_id, refresh_job_id=job_id, started_at=clock())
        s.add(run)
        s.flush()
        run_id = run.id
        if refusal:
            s.add(
                SourceRunError(
                    source_run_id=run_id,
                    kind=FetchErrorKind.ACCESS_NOT_PERMITTED,
                    message=refusal[:500],
                    at=clock(),
                )
            )
            run.status, run.finished_at = RunStatus.FAILED, clock()
            run.error_kind, run.error_summary = FetchErrorKind.ACCESS_NOT_PERMITTED, refusal[:500]
            emit(RefreshEvent("SOURCE_SKIPPED", key, index, total, message=refusal))
            return SourceSummary(
                key,
                RunStatus.FAILED,
                error_kind=FetchErrorKind.ACCESS_NOT_PERMITTED,
                message=refusal,
            )
        adapter = get_adapter(key)
        assert adapter is not None
        requester = PoliteRequester(
            transport=transport_for(adapter, clock),
            min_interval_s=source.min_interval_s,
            daily_cap=source.daily_request_cap,
            requests_today=_requests_today(s, source_id, clock()),
            cache=ResponseCache(db.settings.resolved_data_dir / "cache" / key),
            cache_ttl_s=adapter.cache_ttl_s,
            clock=clock,
            # Mock sources never touch a network: no politeness delay needed in tests / demo.
            sleep=sleep
            or ((lambda _s: None) if adapter.access_method is AccessMethod.MOCK else time.sleep),
        )
    emit(RefreshEvent("SOURCE_STARTED", key, index, total))
    summary = SourceSummary(key, RunStatus.RUNNING)
    evaluated: list[int] = []
    error: SourceError | None = None
    try:
        for rec in adapter.fetch(requester, categories):
            summary.fetched += 1
            if isinstance(rec, RecordError):
                summary.failed += 1
                _record_error(db, run_id, rec.kind, rec.message, rec.external_ref, clock())
                continue
            if rec.category not in categories:
                continue
            outcome, offer_id = _process(db, source_id, run_id, rec, clock())
            if outcome == "new":
                summary.parsed += 1
                summary.new_observations += 1
                if offer_id is not None:
                    evaluated.append(offer_id)
            elif outcome == "duplicate":
                summary.parsed += 1
                summary.duplicates += 1
            else:
                summary.failed += 1
                _record_error(
                    db, run_id, FetchErrorKind.INVALID_RECORD, outcome, rec.raw.external_id, clock()
                )
            if summary.fetched % 10 == 0:
                emit(RefreshEvent("RECORDS", key, index, total, summary.fetched))
    except SourceError as exc:
        error = exc
    except Exception as exc:  # an adapter bug must not crash the whole refresh
        log.exception("adapter failure", extra={"source": key})
        error = SourceError(f"belső hiba: {type(exc).__name__}")
    stats = requester.stats
    summary.retries, summary.cache_hits, summary.requests = (
        stats.retries,
        stats.cache_hits,
        stats.requests,
    )
    if error is None:
        summary.status = RunStatus.OK
        summary.message = f"{summary.new_observations} új ár, {summary.duplicates} ismétlődő"
    else:
        summary.error_kind = error.kind
        summary.message = error.message
        _record_error(db, run_id, error.kind, error.message, None, clock())
        if isinstance(error, SourceBlocked):
            summary.status = RunStatus.BLOCKED
        elif isinstance(error, AccessNotPermitted):
            summary.status = RunStatus.FAILED
        else:
            summary.status = RunStatus.PARTIAL if summary.parsed else RunStatus.FAILED
    with db.write_session() as s:
        run_row = s.get(SourceRun, run_id)
        assert run_row is not None
        run_row.status = summary.status
        run_row.finished_at = clock()
        run_row.requests, run_row.fetched = summary.requests, summary.fetched
        run_row.parsed, run_row.failed = summary.parsed, summary.failed
        run_row.new_observations, run_row.duplicates = summary.new_observations, summary.duplicates
        run_row.retries, run_row.cache_hits = summary.retries, summary.cache_hits
        run_row.error_kind = summary.error_kind
        run_row.error_summary = summary.message[:500] if error else None
        if summary.status is RunStatus.BLOCKED:
            src = s.get(Source, source_id)
            assert src is not None
            src.status = SourceStatus.BLOCKED  # stays blocked until the user re-reviews access
    if summary.status in (RunStatus.BLOCKED, RunStatus.FAILED) and notify_results:
        notify.notify(
            db,
            kind="SOURCE_PROBLEM",
            title=f"{key} forrás: {hu.label('run_status', summary.status)}",
            body=summary.message,
            dedupe_key=f"source:{key}:{run_id}",
        )
    if evaluate:
        for offer_id in dict.fromkeys(evaluated):
            _evaluate_and_notify(db, offer_id, clock(), notify_results)
    return summary


def _process(
    db: Database, source_id: int, run_id: int, rec: AdapterOffer, now: datetime
) -> tuple[str, int | None]:
    listing = catalog.normalize(rec.raw, rec.category)
    with db.write_session() as s:
        source = s.get(Source, source_id)
        assert source is not None
        content = json.dumps(rec.raw.model_dump(mode="json"), sort_keys=True, ensure_ascii=False)
        raw = RawRecord(
            source_run_id=run_id,
            external_ref=rec.raw.external_id,
            url=rec.raw.url,
            fetched_at=rec.fetched_at,
            http_status=200,
            parse_status="PARSED",
            content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        )
        s.add(raw)
        offer = _upsert(s, source, rec, listing, now)
        _match(s, db, offer, listing, now)
        s.flush()
        outcome = _observe(s, offer, source, rec, listing, raw.id)
        return outcome, offer.id


def _record_error(
    db: Database, run_id: int, kind: FetchErrorKind, message: str, ref: str | None, at: datetime
) -> None:
    with db.write_session() as s:
        s.add(
            SourceRunError(
                source_run_id=run_id, kind=kind, message=message[:500], external_ref=ref, at=at
            )
        )


def _evaluate_and_notify(db: Database, offer_id: int, now: datetime, notify_results: bool) -> None:
    try:
        results = workflow.evaluate_offer(db, offer_id, now)
    except Exception:  # evaluation problems must not stop a refresh; the offer stays unevaluated
        log.exception("evaluation failed", extra={"offer_id": offer_id})
        return
    if results is None or not notify_results:
        return
    personal, resale = results
    with db.read_session() as s:
        offer = s.get(Offer, offer_id)
        title = offer.listing.title if offer else f"offer {offer_id}"
    if personal.verdict is PersonalVerdict.STRONG_DEAL:
        notify.notify(
            db,
            kind="STRONG_DEAL",
            title=f"Kiemelkedő ajánlat: {title}",
            body=f"{(personal.discount_vs_median_bp or 0) / 100:.1f} % below the typical "
            f"price, {personal.effective_price_huf} HUF incl. delivery.",
            dedupe_key=f"personal:{offer_id}:{personal.effective_price_huf}",
            offer_id=offer_id,
        )
    if workflow.watch_target_met(personal):
        notify.notify(
            db,
            kind="WATCHLIST",
            title=f"Célár elérve: {title}",
            body=f"{hu.huf(personal.effective_price_huf)} szállítással együtt.",
            dedupe_key=f"watch:{offer_id}:{personal.effective_price_huf}",
            offer_id=offer_id,
        )
    if resale.verdict is ResaleVerdict.PROFITABLE:
        notify.notify(
            db,
            kind="RESALE",
            title=f"Továbbértékesítési lehetőség (becslés): {title}",
            body=f"Várható nettó haszon: {hu.huf(resale.net_profit_huf)} (becslés, nem pénz).",
            dedupe_key=f"resale:{offer_id}:{resale.net_profit_huf}",
            offer_id=offer_id,
        )


# --- freshness ---


@dataclass(frozen=True)
class Freshness:
    source_key: str
    name: str
    status: SourceStatus
    access_method: AccessMethod
    last_success_at: datetime | None
    last_run_status: RunStatus | None
    last_error: str | None
    stale: bool
    max_age_hours: int


def freshness(db: Database, now: datetime | None = None) -> list[Freshness]:
    """A source is stale when its last successful run is older than the shortest freshness window
    of its categories (benchmark policy current_max_age_hours)."""
    now = now or utcnow()
    out = []
    with db.read_session() as s:
        for src in s.scalars(select(Source).order_by(Source.key)).all():
            adapter = get_adapter(src.key)
            cats = adapter.categories if adapter else frozenset(Category)
            max_age = min(module_for(c).benchmark_policy.current_max_age_hours for c in cats)
            last = s.scalar(
                select(SourceRun)
                .where(SourceRun.source_id == src.id)
                .order_by(SourceRun.id.desc())
                .limit(1)
            )
            ok = s.scalar(
                select(SourceRun)
                .where(
                    SourceRun.source_id == src.id,
                    SourceRun.status.in_([RunStatus.OK, RunStatus.PARTIAL]),
                )
                .order_by(SourceRun.id.desc())
                .limit(1)
            )
            last_ok = ok.finished_at if ok else None
            active = src.status in (SourceStatus.ACTIVE, SourceStatus.DEGRADED)
            stale = active and (last_ok is None or now - last_ok > timedelta(hours=max_age))
            out.append(
                Freshness(
                    src.key,
                    src.name,
                    src.status,
                    src.access_method,
                    last_ok,
                    last.status if last else None,
                    last.error_summary if last else None,
                    stale,
                    max_age,
                )
            )
    return out
