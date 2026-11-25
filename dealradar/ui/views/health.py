from __future__ import annotations

import streamlit as st

from dealradar.core import hu
from dealradar.services.health import Status, overall, run_health_checks
from dealradar.ui.state import get_context
from dealradar.ui.views.widgets import Color, notice, page, pill, table

_COLOR: dict[Status, Color] = {Status.OK: "green", Status.WARN: "orange", Status.FAIL: "red"}


def _live_ui_options() -> dict[str, object]:
    return {
        "server.address": st.get_option("server.address"),
        "browser.gatherUsageStats": st.get_option("browser.gatherUsageStats"),
    }


def render() -> None:
    page("Rendszerállapot", "Az adatbázis, a mentések, a források és a helyi futás ellenőrzése.")
    ctx = get_context()
    results = run_health_checks(ctx.settings, ctx.db, ui_options=_live_ui_options())
    status = overall(results)
    text = f"Összesítve: {hu.label('health_status', status)}"
    {
        Status.OK: lambda: notice("success", text),
        Status.WARN: lambda: notice("warning", text),
        Status.FAIL: lambda: notice("error", text),
    }[status]()
    table(
        [
            {
                "Ellenőrzés": hu.label("health_check", r.name),
                "Eredmény": hu.label("health_status", r.status),
                "Részletek": r.detail,
            }
            for r in results
        ]
    )
    with st.container(horizontal=True, gap="small"):
        for r in results:
            if r.status is not Status.OK:
                pill(hu.label("health_check", r.name), _COLOR[r.status])
    st.caption(f"Adatmappa: {ctx.settings.resolved_data_dir}")
