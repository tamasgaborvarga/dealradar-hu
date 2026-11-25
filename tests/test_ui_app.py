"""Streamlit smoke tests with the official headless test runner (no browser, no server)."""

from __future__ import annotations

from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from dealradar.core.config import Settings
from dealradar.db.session import Database

APP = str(Path(__file__).resolve().parents[1] / "dealradar" / "ui" / "app.py")
PAGES = [
    "overview",
    "tech",
    "apparel",
    "food",
    "home",
    "offer",
    "watchlists",
    "inventory",
    "feedback",
    "analysis",
    "settings",
    "sources",
    "health",
]


@pytest.fixture(autouse=True)
def _fresh_streamlit_cache() -> None:
    st.cache_resource.clear()


def _run(page: str | None = None) -> AppTest:
    at = AppTest.from_file(APP, default_timeout=30)
    at.run()
    if page is not None and page != "overview":
        at.switch_page(f"page_scripts/{page}.py")
        at.run()
    return at


def test_app_starts_on_migrated_db(db: Database) -> None:
    at = _run()
    assert not at.exception, at.exception
    assert at.title[0].value == "Áttekintés"
    assert len(at.metric) == 7  # 4 actual + 3 estimated money metrics


@pytest.mark.parametrize("page", PAGES)
def test_every_page_renders_without_exception(db: Database, page: str) -> None:
    at = _run(page)
    assert not at.exception, at.exception
    assert not at.error, [e.value for e in at.error]


def test_category_pages_show_two_separate_engines(db: Database) -> None:
    at = _run("food")
    assert at.title[0].value == "Élelmiszer"
    assert [t.label for t in at.tabs] == ["Saját vásárlás", "Továbbértékesítés"]
    assert any("nem alkalmazható" in i.value for i in at.info)


def test_unmigrated_db_shows_upgrade_instruction(settings: Settings) -> None:
    at = _run()
    assert not at.exception
    assert at.error and "séma" in at.error[0].value.lower()
    assert any("dealradar db upgrade" in c.value for c in at.code)


@pytest.fixture
def demo_db(db: Database) -> Database:
    from dealradar.services.demo import seed_demo

    seed_demo(db, days=3)
    return db


@pytest.mark.parametrize("page", PAGES)
def test_every_page_renders_with_demo_data(demo_db: Database, page: str) -> None:
    at = _run(page)
    assert not at.exception, at.exception
    assert not at.error, [e.value for e in at.error]


def test_overview_keeps_actual_and_estimated_money_apart(demo_db: Database) -> None:
    at = _run()
    texts = [m.value for m in at.markdown]
    assert "**Tényleges eredmény**" in texts and "**Becsült lehetőségek**" in texts
    assert any("szintetikus" in w.value for w in at.warning)  # demo mode is visible
    assert [t.label for t in at.tabs] == ["Saját vásárlásra", "Továbbértékesítésre"]


def test_category_refresh_button_runs_a_refresh(demo_db: Database) -> None:
    at = _run("tech")
    at.button(key="refresh_TECH").click().run()
    assert not at.exception, at.exception
    assert any("Frissítés: Sikeres" in s.value for s in at.success), [s.value for s in at.success]


def test_offer_page_shows_history_and_both_evaluations(demo_db: Database) -> None:
    at = _run("offer")
    assert not at.exception, at.exception
    labels = [t.label for t in at.tabs]
    assert labels[:3] == ["Árelőzmény", "Saját vásárlás", "Továbbértékesítés"]
    texts = [m.value for m in at.markdown]
    assert "**Saját vásárlásra**" in texts and "**Továbbértékesítésre (becslés)**" in texts


def test_rejection_without_reason_is_refused_in_the_ui(demo_db: Database) -> None:
    at = _run("offer")
    at.button_group[0].set_value("REJECT")
    next(b for b in at.button if b.label == "Döntés mentése").click().run()
    assert any("okot" in e.value for e in at.error), [e.value for e in at.error]


def test_everything_the_user_sees_is_hungarian(demo_db: Database) -> None:
    """No English UI words left on any page (spot check of words used before ADR-056)."""
    english = (
        "Refresh",
        "Overview",
        "Personal deals",
        "Resale deals",
        "Save",
        "Offer",
        "Settings",
        "Sources",
        "Record",
        "Open details",
        "Not evaluated",
        "Missing",
    )
    for page in PAGES:
        at = _run(page)
        shown = [x.value for x in (*at.title, *at.subheader, *at.caption, *at.markdown)]
        shown += [b.label for b in at.button] + [t.label for t in at.tabs]
        hits = [t for t in shown for w in english if w in str(t)]
        assert hits == [], (page, hits)


def test_untrusted_listing_text_is_not_rendered_as_markdown(demo_db: Database) -> None:
    """QA: a listing title with Markdown (external image, link, colour, LaTeX) is shown escaped."""
    from dealradar.db.models import Listing

    evil = "SSD ![t](http://tracker.invalid/p.png) [x](http://evil.invalid) :red[a] $x$"
    with demo_db.write_session() as s:
        listing = s.get(Listing, 1)
        assert listing is not None
        listing.title = evil
    at = AppTest.from_file(APP, default_timeout=30)
    at.session_state["selected_offer_id"] = 1
    at.run()
    at.switch_page("page_scripts/offer.py")
    at.run()
    assert not at.exception, at.exception
    shown = next(h.value for h in at.subheader if "SSD" in h.value)
    assert "![" not in shown and "](" not in shown and ":red[" not in shown
    from dealradar.ui.views.widgets import plain

    assert shown == plain(evil)


def test_details_open_the_chosen_offer_even_with_equal_titles(demo_db: Database) -> None:
    """Browser finding: two offers with the same title (same RAM in two shops) - the picker must
    still open the one chosen, not its namesake."""
    at = _run()
    picker = at.selectbox(key="ov_p_pick")
    assert len(set(picker.options)) == len(picker.options)  # every label unique
    first = picker.value
    next(b for b in at.button if b.key == "ov_p_open").click().run()
    assert at.session_state["selected_offer_id"] == first
