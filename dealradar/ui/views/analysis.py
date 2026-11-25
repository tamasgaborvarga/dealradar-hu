"""Claude-elemzés (manual, optional). Everything else in DealRadar works without it."""

from __future__ import annotations

import streamlit as st

from dealradar.core import hu
from dealradar.services.analysis import (
    CLAUDE_URL,
    analyses_for_offer,
    import_response,
    list_offers,
    prepare_analysis,
)
from dealradar.ui.state import get_context
from dealradar.ui.views.common import require_schema
from dealradar.ui.views.widgets import OFFER_KEY, empty, notice, page, plain, section

_STATE = "analysis_request"


def _history(offer_id: int) -> None:
    section("Mentett elemzések ehhez az ajánlathoz")
    history = [h for h in analyses_for_offer(get_context().db, offer_id) if h.analysis]
    if not history:
        empty("Még nincs.")
    for item in history:
        a = item.analysis
        assert a is not None
        title = (
            f"{hu.when(item.received_at)}: {hu.label('recommendation', a.recommendation)} "
            f"({hu.label('level', a.confidence)} bizonyosság)"
        )
        with st.expander(title):
            st.write(plain(a.summary))
            for r in a.risk_flags:
                st.markdown(f"- **{hu.label('risk_flag', r.flag)}**: {plain(r.evidence)}")
            if a.missing_information:
                st.markdown(
                    "**Hiányzó információ:** " + "; ".join(plain(m) for m in a.missing_information)
                )
            if a.questions_for_seller:
                st.markdown(
                    "**Kérdések az eladónak:** "
                    + "; ".join(plain(q) for q in a.questions_for_seller)
                )
            for d in a.facts_disputed:
                st.markdown(f"- Vitatott adat ({plain(d.key)}): {plain(d.reason)}")


def render() -> None:
    page(
        "Claude-elemzés",
        "Nem kötelező második vélemény. Nincs API-kulcs, semmi nem megy ki "
        "automatikusan: a kérdést te másolod át a claude.ai-ba, a választ te "
        "illeszted vissza. Csak tanács, árat, párosítást, értékelést nem módosít.",
    )
    if not require_schema():
        return
    db = get_context().db
    offers = list_offers(db)
    if not offers:
        empty("Még nincs ajánlat. Indíts egy frissítést az Áttekintés oldalon.")
        return
    ids = [o.offer_id for o in offers]
    labels = {o.offer_id: o.label for o in offers}
    current = st.session_state.get(OFFER_KEY)
    offer_id = st.selectbox(
        "Ajánlat",
        ids,
        index=ids.index(current) if current in ids else 0,
        format_func=lambda i: labels[i],
    )
    assert offer_id is not None

    if st.button("Elemzési csomag készítése", type="primary", icon=":material/description:"):
        prepared = prepare_analysis(db, int(offer_id))
        st.session_state[_STATE] = (offer_id, prepared.request_id, prepared.prompt)

    state = st.session_state.get(_STATE)
    if state and state[0] == offer_id:
        _, request_id, prompt = state
        with st.container(border=True):
            section(
                "1. Másold ki a kérdést",
                f"Azonosító: {request_id}. A doboz jobb felső sarkában van a másolás gomb.",
            )
            st.code(prompt, language="markdown", wrap_lines=True)
            st.download_button(
                "Kérdés letöltése (.md)",
                prompt,
                file_name=f"{request_id}.md",
                icon=":material/download:",
            )
        with st.container(border=True):
            section(
                "2. Kérdezd meg Claude-ot",
                "Illeszd be egy új beszélgetésbe. Ha Claude épp nem elérhető, az sem baj.",
            )
            st.link_button(
                "Claude megnyitása (claude.ai)", CLAUDE_URL, icon=":material/open_in_new:"
            )
        with st.container(border=True):
            section("3. Illeszd be Claude válaszát")
            answer = st.text_area("Claude JSON-válasza", key=f"answer_{request_id}", height=220)
            if st.button("Ellenőrzés és mentés", key=f"save_{request_id}", type="primary"):
                outcome = import_response(db, request_id, answer)
                if outcome.accepted and outcome.analysis is not None:
                    a = outcome.analysis
                    notice(
                        "success",
                        f"Mentve ({hu.when(outcome.received_at)}): "
                        f"{hu.label('recommendation', a.recommendation)}, "
                        f"{hu.label('level', a.confidence)} bizonyosság.",
                    )
                else:
                    notice("error", "Elutasítva: a válasz érvénytelenként mentve, nem használjuk.")
                    for err in outcome.errors:
                        st.markdown("- " + plain(err))
    _history(int(offer_id))
