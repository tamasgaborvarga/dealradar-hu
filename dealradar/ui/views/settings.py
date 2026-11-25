"""Beállítások: resale fee and tax profiles (user input, never built in), Telegram, demo data."""

from __future__ import annotations

import streamlit as st

from dealradar.core import hu
from dealradar.services import notify, sources, workflow
from dealradar.services.workflow import TaxKind
from dealradar.ui.state import get_context
from dealradar.ui.views.common import require_schema
from dealradar.ui.views.widgets import empty, notice, page, plain, table


def _fees() -> None:
    db = get_context().db
    st.caption(
        "Annak a platformnak a díjai, ahol eladnál, a platform aktuális díjtáblázatából. "
        "A DealRadar nem ismer beépített díjakat. Ellenőrizetlen profillal az eredmény "
        "ideiglenes marad."
    )
    rows = workflow.list_fee_profiles(db)
    if rows:
        table(
            [
                {
                    "Név": r.name,
                    "Platform": r.platform,
                    "Alapértelmezett": "igen" if r.is_default else "",
                    "Ellenőrizve": "igen" if r.verified else "nem",
                    "Jutalék": hu.pct(r.profile.commission_bp, signed=False),
                    "Fizetési díj": hu.pct(r.profile.payment_fee_bp, signed=False),
                    "Kiszállítás": hu.huf(r.profile.outbound_shipping_cost_huf),
                    "Csomagolás": hu.huf(r.profile.packaging_huf),
                }
                for r in rows
            ],
            right=("Jutalék", "Fizetési díj", "Kiszállítás", "Csomagolás"),
        )
    else:
        empty("Még nincs díjprofil. Nélküle a továbbértékesítési értékelés kézi ellenőrzést kér.")
    with st.form("fee_profile", border=True):
        st.markdown("**Díjprofil mentése** (azonos névvel felülírja)")
        c1, c2 = st.columns(2)
        name = c1.text_input("Profil neve")
        platform = c2.text_input("Platform")
        c3, c4, c5 = st.columns(3)
        commission = c3.number_input("Jutalék (%)", 0.0, 100.0, step=0.1, format="%.2f")
        commission_min = c4.number_input("Minimális jutalék (Ft)", min_value=0, step=10)
        fixed = c5.number_input("Fix díj eladásonként (Ft)", min_value=0, step=10)
        c6, c7, c8 = st.columns(3)
        payment = c6.number_input("Fizetési díj (%)", 0.0, 100.0, step=0.1, format="%.2f")
        payment_fixed = c7.number_input("Fizetési fix díj (Ft)", min_value=0, step=10)
        listing = c8.number_input("Hirdetési díj (Ft)", min_value=0, step=10)
        c9, c10 = st.columns(2)
        shipping = c9.number_input("Kiszállítás költsége eladásonként (Ft)", min_value=0, step=10)
        packaging = c10.number_input("Csomagolás eladásonként (Ft)", min_value=0, step=10)
        verified = st.toggle("Ellenőriztem a platform aktuális díjtáblázatában")
        default = st.toggle("Legyen ez az alapértelmezett", value=True)
        if st.form_submit_button("Díjprofil mentése", type="primary"):
            try:
                workflow.save_fee_profile(
                    db,
                    name=name,
                    platform=platform,
                    commission_bp=round(commission * 100),
                    commission_min_huf=int(commission_min),
                    fixed_fee_huf=int(fixed),
                    payment_fee_bp=round(payment * 100),
                    payment_fixed_huf=int(payment_fixed),
                    listing_fee_huf=int(listing),
                    outbound_shipping_cost_huf=int(shipping),
                    packaging_huf=int(packaging),
                    verified=verified,
                    make_default=default,
                )
                notice("success", "Mentve. Az ajánlatok újraértékelésekor érvényesül.")
            except ValueError as exc:
                notice("error", plain(exc))


def _tax() -> None:
    db = get_context().db
    st.caption(
        "A DealRadar nem ismeri az adózási helyzetedet. Válaszd ki, ami rád vonatkozik; "
        "ha bizonytalan vagy, kérdezz könyvelőt."
    )
    with db.read_session() as s:
        current = workflow.tax_profile(s)
    st.markdown(
        "**Jelenlegi:** "
        + (
            hu.label("tax_kind", current.kind)
            if current
            else "nincs beállítva (a továbbértékesítés kézi ellenőrzést kér)"
        )
    )
    with st.form("tax", border=True):
        kind = st.selectbox(
            "Adózás módja", list(TaxKind), format_func=lambda k: hu.label("tax_kind", k)
        )
        rate = st.number_input("Kulcs (%, ha van)", 0.0, 100.0, step=0.5, format="%.2f")
        verified = st.toggle("Megerősítve (pl. könyvelővel)")
        if st.form_submit_button("Adóprofil mentése", type="primary") and kind is not None:
            try:
                workflow.set_tax_profile(db, kind, round(rate * 100), verified)
                notice("success", "Mentve.")
            except ValueError as exc:
                notice("error", plain(exc))


def _telegram() -> None:
    ctx = get_context()
    st.caption("Minden értesítés megjelenik az Áttekintés oldalon. A Telegram nem kötelező.")
    if not ctx.settings.telegram_enabled:
        notice(
            "info",
            "A Telegram nincs beállítva. Bekapcsoláshoz add meg a "
            "DEALRADAR_TELEGRAM_BOT_TOKEN és DEALRADAR_TELEGRAM_CHAT_ID értékét a "
            ".env fájlban, majd indítsd újra az appot.",
        )
        return
    notice("success", "A Telegram be van állítva (a tokent az app sosem jeleníti meg).")
    if st.button("Tesztüzenet küldése", icon=":material/send:"):
        ok, error = notify.send_test_message(ctx.db)
        if ok:
            notice("success", "Elküldve.")
        else:
            notice("error", "Sikertelen: " + plain(error))


def _demo() -> None:
    db = get_context().db
    if sources.mock_sources_present(db):
        notice("warning", "Ebben az adatbázisban szintetikus demóforrások vannak.")
        return
    st.caption(
        "Három kitalált boltot regisztrál szintetikus árakkal, hogy kipróbálhasd az appot. "
        "Soha ne a valódi döntésekhez használt adatbázisban tedd: indítsd az appot külön "
        "DEALRADAR_DATA_DIR mappával."
    )
    ok = st.checkbox("Értem, hogy ezek az árak kitaláltak, nem valódiak")
    if st.button("Demóadatok betöltése", disabled=not ok, icon=":material/science:"):
        from dealradar.services.demo import seed_demo

        with st.spinner("Két hét szintetikus előzmény készül..."):
            result = seed_demo(db)
        notice("success", f"Kész: {result['offers']} ajánlat, {result['days']} nap előzmény.")


def render() -> None:
    page(
        "Beállítások",
        "A díj- és adóprofil nélkül a továbbértékesítési motor nem mond "
        "nyereséget. Mindkettőt te adod meg; beépített érték nincs.",
    )
    if not require_schema():
        return
    tabs = st.tabs(["Díjprofilok", "Adóprofil", "Értesítések", "Demóadatok"])
    with tabs[0]:
        _fees()
    with tabs[1]:
        _tax()
    with tabs[2]:
        _telegram()
    with tabs[3]:
        _demo()
