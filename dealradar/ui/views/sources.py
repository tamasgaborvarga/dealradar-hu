"""Források: registry with freshness, refresh one source, re-enable a stopped source."""

from __future__ import annotations

import streamlit as st

from dealradar.core import hu
from dealradar.core.enums import RefreshScope
from dealradar.services.refresh import freshness
from dealradar.services.sources import reactivate_source
from dealradar.ui.state import get_context
from dealradar.ui.views.common import require_schema
from dealradar.ui.views.widgets import empty, notice, page, plain, refresh_button, section, table


def render() -> None:
    page(
        "Források",
        "Forrás csak ellenőrzött hozzáféréssel futhat (felhasználási feltételek, "
        "robots.txt). A letiltott forrás leáll; a DealRadar sosem kerüli ki a tiltást.",
    )
    if not require_schema():
        return
    db = get_context().db
    rows = freshness(db)
    if not rows:
        empty(
            "Nincs regisztrált forrás. Valódi forrás még nincs ellenőrizve; demóadatokat a "
            "Beállítások oldalon tölthetsz be."
        )
        return
    table(
        [
            {
                "Forrás": f.name,
                "Hozzáférés": hu.label("access_method", f.access_method),
                "Állapot": hu.label("source_status", f.status),
                "Utolsó sikeres frissítés": hu.when(f.last_success_at)
                if f.last_success_at
                else "még soha",
                "Utolsó futás": hu.label("run_status", f.last_run_status)
                if f.last_run_status
                else "-",
                "Friss": "elavult" if f.stale else "igen",
                "Frissességi idő": f"{f.max_age_hours} óra",
                "Utolsó hiba": f.last_error or "",
            }
            for f in rows
        ]
    )
    section("Egy forrás kezelése")
    names = {f.source_key: f.name for f in rows}
    key = st.selectbox("Forrás", list(names), format_func=lambda k: names[k])
    if key is None:
        return
    refresh_button(RefreshScope.SOURCE, key, "Forrás frissítése", key=f"refresh_src_{key}")
    current = next(f for f in rows if f.source_key == key)
    if current.status.value in ("BLOCKED", "DISABLED"):
        with st.form(f"reactivate_{key}", border=True):
            notice(
                "warning",
                "Ez a forrás le van állítva. Újraengedélyezés előtt ellenőrizd "
                "újra a felhasználási feltételeit és a robots.txt-t.",
            )
            note = st.text_area("Mit ellenőriztél?")
            if st.form_submit_button("Újraengedélyezés", type="primary"):
                try:
                    reactivate_source(db, key, note)
                    notice("success", "Újraengedélyezve.")
                except ValueError as exc:
                    notice("error", plain(exc))
