"""Elutasított ajánlatok: rejected offers and why - feedback on where matching or evaluation
misleads."""

from __future__ import annotations

import streamlit as st

from dealradar.core import hu
from dealradar.core.enums import Decision
from dealradar.services import workflow
from dealradar.ui.state import get_context
from dealradar.ui.views.common import require_schema
from dealradar.ui.views.widgets import empty, open_offer, page, pill, section, table, unique_labels


def render() -> None:
    page(
        "Elutasított ajánlatok",
        "Minden elutasításnak van oka. Sok „Rossz termékpárosítás” "
        "a párosítás hibájára, sok „Túl drága” a kevés áradatra utal.",
    )
    if not require_schema():
        return
    db = get_context().db
    summary = workflow.feedback_summary(db)
    if not summary:
        empty("Nincs elutasított ajánlat.")
        return
    section("Okok szerint")
    with st.container(horizontal=True, gap="small"):
        for reason, count in sorted(summary.items(), key=lambda x: -x[1]):
            pill(f"{hu.label('reject_reason', reason)}: {count}", "orange")
    rows = workflow.rejected_offers(db)
    section("Elutasított ajánlatok")
    table(
        [
            {
                "Ajánlat": r.title,
                "Ok": hu.label("reject_reason", r.reason),
                "Megjegyzés": r.note or "",
                "Elutasítva": hu.when(r.decided_at),
            }
            for r in rows
        ]
    )
    labels = unique_labels({r.offer_id: r.title[:80] for r in rows})
    choice = st.selectbox("Ajánlat", list(labels), format_func=lambda i: labels[i])
    with st.container(horizontal=True, gap="small"):
        if st.button("Visszaállítás", icon=":material/undo:") and choice is not None:
            workflow.decide(db, int(choice), Decision.RESTORE)
            st.rerun()
        if st.button("Részletek", icon=":material/open_in_new:") and choice is not None:
            open_offer(int(choice))
