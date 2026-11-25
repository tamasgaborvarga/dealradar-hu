"""Figyelőlisták: target prices the Personal engine checks (a met target is notified)."""

from __future__ import annotations

import streamlit as st

from dealradar.core import hu
from dealradar.core.enums import Category, Condition
from dealradar.services import workflow
from dealradar.ui.state import get_context
from dealradar.ui.views.common import require_schema
from dealradar.ui.views.widgets import empty, notice, page, plain, section, table, unique_labels


def _create() -> None:
    db = get_context().db
    with st.form("new_watchlist", border=True, clear_on_submit=True):
        st.markdown("**Új figyelőlista**")
        c1, c2 = st.columns(2)
        name = c1.text_input("Név", placeholder="pl. Új SSD a gépbe")
        category = c2.selectbox(
            "Kategória", list(Category), format_func=lambda c: hu.label("category", c)
        )
        query = st.text_input("A hirdetés címe tartalmazza", placeholder="pl. márka és modell")
        c3, c4 = st.columns(2)
        target = c3.number_input("Célár szállítással (Ft, 0 = nincs)", min_value=0, step=100)
        maximum = c4.number_input("Maximális ár (Ft, 0 = nincs)", min_value=0, step=100)
        conditions = st.multiselect(
            "Elfogadható állapot (üres = bármilyen)",
            list(Condition),
            format_func=lambda c: hu.label("condition", c),
        )
        notify = st.toggle("Értesítést kérek, ha teljesül", value=True)
        if st.form_submit_button("Figyelőlista létrehozása", type="primary") and category:
            try:
                workflow.create_watchlist(
                    db,
                    name=name,
                    category=category,
                    query_text=query,
                    target_price_huf=int(target) or None,
                    max_price_huf=int(maximum) or None,
                    acceptable_conditions=conditions or None,
                    notify=notify,
                )
                notice("success", "Létrehozva. A következő értékeléstől érvényes.")
            except ValueError as exc:
                notice("error", plain(exc))


def _list() -> None:
    db = get_context().db
    section("Figyelőlistáid")
    rows = workflow.list_watchlists(db)
    if not rows:
        empty("Még nincs figyelőlistád.")
        return
    table(
        [
            {
                "Név": r.name,
                "Kategória": hu.label("category", r.category),
                "Mit figyel": r.target,
                "Célár": hu.huf(r.target_price_huf),
                "Maximum": hu.huf(r.max_price_huf),
                "Állapot": ", ".join(hu.label("condition", c) for c in r.acceptable_conditions)
                or "bármilyen",
                "Értesítés": "igen" if r.notify else "nem",
                "Aktív": "igen" if r.active else "szünetel",
            }
            for r in rows
        ],
        right=("Célár", "Maximum"),
    )
    labels = unique_labels(
        {r.id: f"{r.name} ({'aktív' if r.active else 'szünetel'})" for r in rows}
    )
    left, right = st.columns([4, 1], vertical_alignment="bottom")
    wid = left.selectbox("Figyelőlista", list(labels), format_func=lambda i: labels[i])
    if right.button("Szüneteltetés / folytatás", width="stretch") and wid is not None:
        current = next(r for r in rows if r.id == wid)
        workflow.set_watchlist_active(db, int(wid), not current.active)
        st.rerun()


def render() -> None:
    page(
        "Figyelőlisták",
        "Add meg, mire vársz és mennyiért. Ha egy ajánlat eléri a célárat, "
        "értesítést kapsz. A DealRadar ilyenkor sem vásárol.",
    )
    if not require_schema():
        return
    _create()
    _list()
