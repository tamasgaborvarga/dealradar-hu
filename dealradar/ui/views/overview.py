"""Áttekintés: one refresh for everything, ACTUAL money next to (never added to) ESTIMATES, the
best offers of each engine (separately), notifications and the four categories."""

from __future__ import annotations

import streamlit as st

from dealradar.core import hu
from dealradar.core.enums import Category, RefreshScope
from dealradar.services import ledger, notify, workflow
from dealradar.services.overview import system_overview
from dealradar.services.refresh import freshness
from dealradar.ui.state import get_context
from dealradar.ui.views.common import require_schema
from dealradar.ui.views.widgets import (
    deal_list,
    empty,
    metrics,
    notice,
    page,
    plain,
    refresh_button,
    section,
    table,
)

CATEGORY_PAGES = {
    Category.TECH: "page_scripts/tech.py",
    Category.APPAREL: "page_scripts/apparel.py",
    Category.FOOD: "page_scripts/food.py",
    Category.HOME: "page_scripts/home.py",
}


def _status_notices() -> None:
    fresh = freshness(get_context().db)
    if any(f.access_method.value == "MOCK" for f in fresh):
        notice(
            "warning", "Demó mód: szintetikus források vannak bekapcsolva, az áraik nem valódiak."
        )
    blocked = [f.name for f in fresh if f.status.value == "BLOCKED"]
    if blocked:
        notice(
            "error",
            "Letiltott források (leálltak, újra kell ellenőrizni): " + plain(", ".join(blocked)),
        )
    stale = [f.name for f in fresh if f.stale]
    if stale:
        notice("warning", "Elavult adatok, frissítés szükséges: " + plain(", ".join(stale)))
    last = max((f.last_success_at for f in fresh if f.last_success_at), default=None)
    st.caption(f"Utolsó sikeres frissítés: {hu.when(last) if last else 'még nem volt'}")


def _money() -> None:
    db = get_context().db
    section(
        "Pénzügyek",
        "A tényleges eredmény és a becslések külön szerepelnek, és sosem adódnak össze.",
    )
    actual, estimate = st.columns(2, gap="medium")
    p = ledger.portfolio(db)
    with actual, st.container(border=True):
        st.markdown("**Tényleges eredmény**")
        st.caption("Csak a Készlet oldalon rögzített tranzakciókból, lezárt tételekre.")
        roi = hu.pct(p.realized_roi_bp, signed=False) if p.realized_roi_bp is not None else "-"
        metrics(
            [
                ("Realizált haszon", hu.huf(p.realized_profit_huf), None),
                ("Realizált megtérülés", roi, None),
                ("Készletben lekötött tőke", hu.huf(p.capital_in_stock_huf), None),
                ("Nyitott / lezárt tétel", f"{p.open_items} / {p.closed_items}", None),
            ]
        )
    est = ledger.estimated_opportunities(db)
    with estimate, st.container(border=True):
        st.markdown("**Becsült lehetőségek**")
        st.caption("A továbbértékesítési motor becslése lezárt eladások alapján. Nem valós pénz.")
        metrics(
            [
                ("Nyereséges ajánlat", str(est.offers), None),
                ("Becsült nettó haszon", hu.huf(est.expected_net_profit_huf), None),
                ("Szükséges tőke", hu.huf(est.capital_needed_huf), None),
            ]
        )


def _best_offers() -> None:
    section(
        "Legjobb ajánlatok",
        "A két értékelés független: egy ajánlat lehet jó vétel, de rossz továbbadásra.",
    )
    rows = workflow.deal_rows(get_context().db)
    personal, resale = st.tabs(["Saját vásárlásra", "Továbbértékesítésre"])
    with personal:
        deal_list(
            workflow.personal_deals(rows)[:8],
            "personal",
            "ov_p",
            "Még nincs értékelt ajánlat. Indíts egy frissítést.",
        )
    with resale:
        deal_list(
            workflow.resale_deals(rows)[:8],
            "resale",
            "ov_r",
            "Még nincs továbbértékesítési értékelés.",
        )


def _notifications() -> None:
    db = get_context().db
    items = notify.inbox(db, limit=15)
    unread = sum(1 for i in items if not i.read)
    section("Értesítések", "A Telegram nem kötelező: minden értesítés itt is megjelenik.")
    if not items:
        empty("Nincs értesítés.")
        return
    table(
        [
            {
                "Időpont": hu.when(i.created_at),
                "Értesítés": i.title,
                "Állapot": "Új" if not i.read else "Olvasott",
                "Kézbesítés": hu.label("telegram_status", i.telegram_status),
            }
            for i in items
        ]
    )
    if unread and st.button(f"Mind olvasottnak jelölöm ({unread})", icon=":material/done_all:"):
        notify.mark_all_read(db)
        st.rerun()


def _categories() -> None:
    section("Kategóriák")
    overview = system_overview(get_context().db)
    cols = st.columns(len(overview.categories))
    for col, cat in zip(cols, overview.categories, strict=True):
        with col, st.container(border=True):
            st.markdown(f"**{hu.label('category', cat.info.key)}**")
            st.caption(
                f"{cat.products} termék, {cat.variants} változat, "
                f"{cat.matched_listings} párosított hirdetés"
            )
            st.page_link(
                CATEGORY_PAGES[cat.info.key], label="Megnyitás", icon=":material/arrow_forward:"
            )
    st.caption(f"{overview.sources} forrás, {overview.unmatched_listings} párosítatlan hirdetés")


def render() -> None:
    page(
        "Áttekintés",
        "Minden ajánlatot két független motor értékel: saját vásárlásra és továbbértékesítésre. "
        "A DealRadar csak javasol, sosem vásárol.",
    )
    if not require_schema():
        return
    _status_notices()
    refresh_button(RefreshScope.ALL, None, "Összes forrás frissítése", key="refresh_all")
    _money()
    _best_offers()
    _notifications()
    _categories()
