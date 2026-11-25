"""Workflow service: watchlists, decisions and rejection feedback, profiles, stored evaluations,
deal lists (two independent lists) and offer details."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import func, select

from dealradar.core.clock import utcnow
from dealradar.core.enums import (
    Category,
    Decision,
    PersonalVerdict,
    RefreshScope,
    RejectReason,
)
from dealradar.db.models import Offer, PersonalEvaluation, ResaleEvaluation
from dealradar.db.session import Database
from dealradar.evaluation.params import TaxKind
from dealradar.services import catalog, sources, workflow
from dealradar.services.refresh import refresh


@pytest.fixture
def seeded(db: Database) -> Database:
    sources.register_mock_sources(db)
    start = utcnow() - timedelta(days=6)
    for d in range(6):
        refresh(
            db,
            RefreshScope.ALL,
            now=start + timedelta(days=d),
            evaluate=False,
            notify_results=False,
        )
    refresh(db, RefreshScope.ALL, now=utcnow() - timedelta(minutes=1))
    return db


def test_listing_snapshot_round_trip(seeded: Database) -> None:
    with seeded.read_session() as s:
        offer = s.get(Offer, 1)
        assert offer is not None and offer.listing.normalized is not None
        data = offer.listing.normalized
    restored = catalog.restore_listing(data)
    assert catalog.dump_listing(restored) == data


def test_each_new_observation_is_evaluated_by_both_engines(seeded: Database) -> None:
    with seeded.read_session() as s:
        personal = s.scalar(select(func.count()).select_from(PersonalEvaluation))
        resale = s.scalar(select(func.count()).select_from(ResaleEvaluation))
    assert personal and personal == resale


def test_two_independent_lists(seeded: Database) -> None:
    rows = workflow.deal_rows(seeded)
    personal = workflow.personal_deals(rows)
    resale = workflow.resale_deals(rows)
    assert personal and "Fictiva Volt" in personal[0].title  # today's synthetic flash sale
    assert personal[0].personal_verdict in (PersonalVerdict.STRONG_DEAL, PersonalVerdict.GOOD_DEAL)
    ranks = [workflow._PERSONAL_RANK[r.personal_verdict] for r in personal]  # type: ignore[index]
    assert ranks == sorted(ranks)
    assert all(r.resale_verdict is not None for r in resale)
    tech = workflow.deal_rows(seeded, Category.TECH)
    assert tech and all(r.category is Category.TECH for r in tech)


def test_rejection_needs_a_reason_and_hides_the_offer(seeded: Database) -> None:
    with pytest.raises(ValueError):
        workflow.decide(seeded, 1, Decision.REJECT)
    with pytest.raises(ValueError):
        workflow.decide(seeded, 1, Decision.BOUGHT)
    workflow.decide(seeded, 1, Decision.REJECT, reason=RejectReason.WRONG_MATCH, note="other model")
    assert 1 not in {r.offer_id for r in workflow.deal_rows(seeded)}
    assert 1 in {r.offer_id for r in workflow.deal_rows(seeded, include_rejected=True)}
    assert workflow.feedback_summary(seeded) == {RejectReason.WRONG_MATCH: 1}
    workflow.decide(seeded, 1, Decision.RESTORE)
    assert workflow.rejected_offers(seeded) == []
    assert 1 in {r.offer_id for r in workflow.deal_rows(seeded)}


def test_watchlists(seeded: Database) -> None:
    with pytest.raises(ValueError):
        workflow.create_watchlist(seeded, name="x", category=Category.TECH)
    with pytest.raises(ValueError):
        workflow.create_watchlist(
            seeded,
            name="x",
            category=Category.TECH,
            query_text="ssd",
            target_price_huf=50_000,
            max_price_huf=40_000,
        )
    wid = workflow.create_watchlist(
        seeded,
        name="RAM",
        category=Category.TECH,
        query_text="fictiva volt",
        max_price_huf=10_000_000,
    )
    with seeded.read_session() as s:
        w = workflow.watchlist_for(s, Category.TECH, "Fictiva Volt 32GB DDR5", None, None)
        assert w is not None and w.id == wid
        assert workflow.watchlist_for(s, Category.FOOD, "Fictiva Volt", None, None) is None
    workflow.set_watchlist_active(seeded, wid, False)
    with seeded.read_session() as s:
        assert workflow.watchlist_for(s, Category.TECH, "Fictiva Volt", None, None) is None
    assert [w.active for w in workflow.list_watchlists(seeded)] == [False]


def test_fee_and_tax_profiles(seeded: Database) -> None:
    with pytest.raises(ValueError):
        workflow.save_fee_profile(seeded, name="x", platform="p", commission_bp=-1)
    with pytest.raises(ValueError):
        workflow.save_fee_profile(seeded, name="x", platform="p", commission_bp=20_000)
    fid = workflow.save_fee_profile(
        seeded, name="Mine", platform="p", commission_bp=500, make_default=True
    )
    workflow.save_fee_profile(seeded, name="Mine", platform="p", commission_bp=600)  # update
    [row] = workflow.list_fee_profiles(seeded)
    assert row.id == fid and row.is_default and row.profile.commission_bp == 600
    with pytest.raises(ValueError):
        workflow.set_tax_profile(seeded, TaxKind.NO_TAX_DECLARED, rate_bp=100)
    workflow.set_tax_profile(seeded, TaxKind.NO_TAX_DECLARED)
    with seeded.read_session() as s:
        tax = workflow.tax_profile(s)
    assert tax is not None and tax.kind is TaxKind.NO_TAX_DECLARED


def test_without_fee_profile_resale_asks_for_it(seeded: Database) -> None:
    result = workflow.evaluate_offer(seeded, 1)
    assert result is not None
    _, resale = result
    assert resale.verdict.value in ("MANUAL_REVIEW", "NOT_APPLICABLE")
    if resale.verdict.value == "MANUAL_REVIEW":
        assert resale.missing_inputs  # never a silent default


def test_offer_detail(seeded: Database) -> None:
    detail = workflow.offer_detail(seeded, 1)
    assert len(detail.history) == 7  # one observation per refresh day
    assert [p.observed_at for p in detail.history] == sorted(p.observed_at for p in detail.history)
    assert detail.personal is not None and detail.resale is not None
    with pytest.raises(ValueError):
        workflow.offer_detail(seeded, 99_999)
