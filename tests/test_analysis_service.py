"""Manual Claude workflow on the database, plus the UI page."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from dealradar.claude_bridge.package import ItemKind
from dealradar.claude_bridge.schema import SCHEMA_VERSION
from dealradar.core.clock import utcnow
from dealradar.core.enums import AnalysisStatus, Availability, Category, Condition, MatchStatus
from dealradar.db.models import AiRequest, AiResponse, Listing, Offer, PriceObservation
from dealradar.db.session import Database
from dealradar.engines import personal, resale
from dealradar.services import analysis, pricing
from tests import factories as f
from tests.engine_fixtures import personal_inputs, resale_inputs
from tests.test_pricing_service import observe_days, offer, product

APP = str(Path(__file__).resolve().parents[1] / "dealradar" / "ui" / "app.py")


def _offer_with_history(db: Database) -> int:
    with db.write_session() as s:
        variant = product(s, Category.TECH, "default")["default"]
        a, b = f.source(s, "a"), f.source(s, "b")
        for i, src in enumerate((a, b, a, b)):
            observe_days(s, offer(s, src, variant, f"o{i}"), [40_000, 40_000, 40_000])
        target = offer(s, a, variant, "target")
        pricing.record_observation(s, target.id, observed_at=utcnow() - timedelta(minutes=5),
                                   price_huf=32_990, shipping_huf=None,
                                   availability=Availability.IN_STOCK)  # fmt: skip
        return target.id


def _answer(request_id: str, **kw: object) -> str:
    data: dict[str, object] = {
        "schema_version": SCHEMA_VERSION, "request_id": request_id, "recommendation": "WAIT",
        "confidence": "MEDIUM", "summary": "Delivery cost unknown; ask the seller first.",
        "risk_flags": [], "questions_for_seller": [], "missing_information": [],
        "facts_disputed": [],
    }  # fmt: skip
    data.update(kw)
    return json.dumps(data)


def test_prepare_builds_labelled_package_and_stores_request(db: Database) -> None:
    offer_id = _offer_with_history(db)
    prepared = analysis.prepare_analysis(db, offer_id)
    pkg = prepared.package
    kinds = {i.key: i.kind for i in pkg.items}
    assert kinds["price"] is ItemKind.FACT and kinds["benchmark_median"] is ItemKind.ESTIMATE
    assert kinds["condition"] is ItemKind.SELLER_CLAIM
    assert any("delivery cost is unknown" in m for m in pkg.missing)
    assert "32 990 HUF" in prepared.prompt and "40 000 HUF" in prepared.prompt
    assert prepared.request_id in prepared.prompt
    with db.read_session() as s:
        row = s.query(AiRequest).one()
        assert row.status is AnalysisStatus.PREPARED and row.offer_id == offer_id
        assert row.created_at == prepared.created_at and row.expires_at > row.created_at
        assert row.prompt_sha256 == pkg.digest()


def test_engine_results_are_included_when_available(db: Database) -> None:
    offer_id = _offer_with_history(db)
    p = personal.evaluate(personal_inputs(80_000))
    r = resale.evaluate(resale_inputs())
    prepared = analysis.prepare_analysis(db, offer_id, personal=p, resale=r)
    assert "Personal engine verdict: STRONG_DEAL" in prepared.prompt
    assert "Resale engine verdict: PROFITABLE" in prepared.prompt
    keys = {i.key: i for i in prepared.package.items}
    assert keys["resale_net_profit"].kind is ItemKind.ESTIMATE
    assert any(i.kind is ItemKind.ASSUMPTION for i in prepared.package.items)


def test_valid_answer_saved_with_timestamp(db: Database) -> None:
    offer_id = _offer_with_history(db)
    prepared = analysis.prepare_analysis(db, offer_id)
    outcome = analysis.import_response(db, prepared.request_id, _answer(prepared.request_id))
    assert outcome.accepted and outcome.analysis is not None
    with db.read_session() as s:
        assert s.query(AiRequest).one().status is AnalysisStatus.ANSWERED
        stored = s.query(AiResponse).one()
        assert stored.valid and stored.received_at == outcome.received_at
        assert stored.parsed_json is not None and stored.parsed_json["recommendation"] == "WAIT"
    history = analysis.analyses_for_offer(db, offer_id)
    assert history[0].analysis is not None and history[0].received_at == outcome.received_at


def test_invalid_answer_stored_as_invalid_and_request_stays_open(db: Database) -> None:
    prepared = analysis.prepare_analysis(db, _offer_with_history(db))
    outcome = analysis.import_response(
        db, prepared.request_id, _answer(prepared.request_id, recommendation="BUY")
    )
    assert not outcome.accepted and outcome.errors
    with db.read_session() as s:
        stored = s.query(AiResponse).one()
        assert not stored.valid and stored.parsed_json is None and stored.errors
        assert s.query(AiRequest).one().status is AnalysisStatus.PREPARED  # user may paste again
    retry = analysis.import_response(db, prepared.request_id, _answer(prepared.request_id))
    assert retry.accepted


def test_expired_package_rejected(db: Database) -> None:
    prepared = analysis.prepare_analysis(db, _offer_with_history(db))
    later = utcnow() + timedelta(days=8)
    outcome = analysis.import_response(
        db, prepared.request_id, _answer(prepared.request_id), now=later
    )
    assert not outcome.accepted and "expired" in outcome.errors[0]
    with db.read_session() as s:
        assert s.query(AiRequest).one().status is AnalysisStatus.EXPIRED


def test_unknown_request_and_offer(db: Database) -> None:
    with pytest.raises(ValueError):
        analysis.import_response(db, "dr-nope", "{}")
    with pytest.raises(ValueError):
        analysis.prepare_analysis(db, 999)


def test_analysis_changes_nothing_else(db: Database) -> None:
    """Advisory only: a CONSIDER answer must not touch offers, listings, matches or prices."""
    offer_id = _offer_with_history(db)

    def snapshot() -> tuple[object, ...]:
        with db.read_session() as s:
            listing = s.get(Offer, offer_id).listing  # type: ignore[union-attr]
            return (s.query(PriceObservation).count(), listing.match_status, listing.product_id,
                    listing.condition, s.query(Listing).count())  # fmt: skip

    before = snapshot()
    prepared = analysis.prepare_analysis(db, offer_id)
    disputed = [{"key": "price", "reason": "Seems implausibly low."}]
    answer = _answer(prepared.request_id, recommendation="CONSIDER", facts_disputed=disputed)
    assert analysis.import_response(db, prepared.request_id, answer).accepted
    assert snapshot() == before
    assert before[1] is MatchStatus.UNMATCHED and before[3] is Condition.NEW  # as created


def test_workflow_needs_no_network_or_key(db: Database, monkeypatch: pytest.MonkeyPatch) -> None:
    """Claude unavailable: everything except the user's own copy/paste still works."""
    import socket

    def no_network(*args: object, **kwargs: object) -> None:
        raise AssertionError("network access attempted")

    monkeypatch.setattr(socket, "create_connection", no_network)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    prepared = analysis.prepare_analysis(db, _offer_with_history(db))
    assert analysis.import_response(db, prepared.request_id, _answer(prepared.request_id)).accepted


# --- UI ---


def test_ui_page_without_offers(db: Database) -> None:
    st.cache_resource.clear()
    at = AppTest.from_file(APP, default_timeout=30)
    at.run()
    at.switch_page("page_scripts/analysis.py")
    at.run()
    assert not at.exception
    assert any("Még nincs ajánlat" in c.value for c in at.caption)


def test_ui_prepare_paste_and_save(db: Database) -> None:
    _offer_with_history(db)
    st.cache_resource.clear()
    at = AppTest.from_file(APP, default_timeout=30)
    at.run()
    at.switch_page("page_scripts/analysis.py")
    at.run()
    next(b for b in at.button if b.label == "Elemzési csomag készítése").click().run()
    assert not at.exception
    assert at.code and "request_id:" in at.code[0].value
    request_id = at.session_state["analysis_request"][1]
    at.text_area[0].input(_answer(request_id)).run()
    next(b for b in at.button if b.label == "Ellenőrzés és mentés").click().run()
    assert not at.exception
    assert at.success and "Érdemes várni" in at.success[0].value
