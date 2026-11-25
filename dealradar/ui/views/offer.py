"""Ajánlat részletei: summary with both verdicts (separate), then tabs for price history, the two
evaluations, the user's decision / purchase and Claude analyses. Recording a purchase is the
user's own record - DealRadar never buys anything."""

from __future__ import annotations

from typing import Any

import streamlit as st

from dealradar.core import hu
from dealradar.core.enums import (
    Category,
    Condition,
    Decision,
    ItemIntent,
    PersonalVerdict,
    RejectReason,
    ResaleVerdict,
)
from dealradar.services import ledger, workflow
from dealradar.services.analysis import analyses_for_offer, list_offers
from dealradar.ui.state import get_context
from dealradar.ui.views.common import require_schema
from dealradar.ui.views.widgets import (
    OFFER_KEY,
    empty,
    metrics,
    notice,
    page,
    pill,
    plain,
    table,
    verdict_badge,
)

_SCENARIO_LINES = [
    ("sale_price", "Eladási ár", 1),
    ("buyer_shipping_charge", "A vevő által fizetett szállítás", 1),
    ("acquisition_cost", "Beszerzés (ár + szállítás)", -1),
    ("commission", "Platform jutalék", -1),
    ("payment_fee", "Fizetési díj", -1),
    ("fixed_fees", "Fix és hirdetési díjak", -1),
    ("outbound_shipping", "Kiszállítás", -1),
    ("packaging", "Csomagolás", -1),
    ("expected_return_cost", "Várható visszaküldési költség", -1),
    ("expected_defect_cost", "Várható hibás termék költsége", -1),
    ("holding_cost", "Tőkeköltség", -1),
    ("tax", "Adó", -1),
    ("net_profit", "Nettó haszon", 1),
]


def _pick_offer() -> int | None:
    offers = list_offers(get_context().db)
    if not offers:
        empty("Még nincs ajánlat. Indíts egy frissítést az Áttekintés oldalon.")
        return None
    ids = [o.offer_id for o in offers]
    labels = {o.offer_id: o.label for o in offers}
    current = st.session_state.get(OFFER_KEY)
    choice = st.selectbox(
        "Ajánlat",
        ids,
        index=ids.index(current) if current in ids else 0,
        format_func=lambda i: labels[i],
    )
    if choice is None:
        return None
    st.session_state[OFFER_KEY] = int(choice)
    return int(choice)


def _bullets(title: str, values: Any, label_codes: bool = False) -> None:
    if not values:
        return
    st.markdown(f"**{title}**")
    for v in values:
        st.markdown("- " + plain(hu.label("code", v) if label_codes else v))


def _summary(d: workflow.OfferDetail) -> None:
    st.subheader(plain(d.title))
    with st.container(horizontal=True, gap="small"):
        pill(d.source, "gray")
        pill(hu.label("listing_kind", d.listing_kind), "gray")
        pill(hu.label("condition", d.condition) if d.condition else "Állapot ismeretlen", "gray")
        pill(hu.label("match_status", d.match_status), "gray")
    personal = d.personal or {}
    resale = d.resale or {}
    left, right = st.columns(2, gap="medium")
    with left, st.container(border=True):
        st.markdown("**Saját vásárlásra**")
        verdict_badge(PersonalVerdict(personal["verdict"]) if personal else None)
        metrics(
            [
                ("Ár szállítással", hu.huf(personal.get("effective_price_huf")), None),
                (
                    "A szokásos árhoz képest",
                    hu.pct(personal.get("discount_vs_median_bp")),
                    "Pozitív szám: ennyivel olcsóbb a szokásos (medián) árnál.",
                ),
            ]
        )
    with right, st.container(border=True):
        st.markdown("**Továbbértékesítésre (becslés)**")
        verdict_badge(ResaleVerdict(resale["verdict"]) if resale else None)
        metrics(
            [
                ("Becsült nettó haszon", hu.huf(resale.get("net_profit_huf")), None),
                ("Becsült megtérülés", hu.pct(resale.get("roi_bp")), None),
            ]
        )


# Hungarian axis formats: "11. 24." dates, "160 000" amounts (Vega's default is US English).
_NUMBER_LABEL = "replace(format(datum.value, ',d'), regexp(',', 'g'), ' ')"


def _price_chart(points: list[workflow.PricePoint]) -> None:
    import altair as alt

    data = [
        {
            "t": hu.local(p.observed_at).replace(tzinfo=None).isoformat(),
            "ar": p.price_huf,
            "mikor": hu.when(p.observed_at),
            "ar_szoveg": hu.huf(p.price_huf),
        }
        for p in points
    ]
    chart = (
        alt.Chart(alt.Data(values=data))  # type: ignore[no-untyped-call]
        .mark_line(point=alt.OverlayMarkDef(size=36), interpolate="step-after", strokeWidth=2)
        .encode(
            x=alt.X(
                "t:T",
                title=None,
                axis=alt.Axis(
                    format="%m. %d.",
                    labelAngle=0,
                    labelOverlap=True,
                    tickCount={"interval": "day", "step": 1},
                ),
            ),
            y=alt.Y(
                "ar:Q",
                title="Ár (Ft)",
                scale=alt.Scale(zero=False, nice=True, padding=8),
                axis=alt.Axis(labelExpr=_NUMBER_LABEL),
            ),
            tooltip=[
                alt.Tooltip("mikor:N", title="Időpont"),
                alt.Tooltip("ar_szoveg:N", title="Ár"),
            ],
        )
        .properties(height=260)
    )
    st.altair_chart(chart)


def _history(d: workflow.OfferDetail) -> None:
    points = [p for p in d.history if p.price_huf is not None]
    st.caption("Hirdetési árak az ellenőrzések időpontjában. Ezek sosem számítanak eladási árnak.")
    if len(points) >= 2:
        _price_chart(points)
    elif not points:
        empty("Még nincs ár ehhez az ajánlathoz.")
    if not d.history:
        return
    table(
        [
            {
                "Időpont": hu.when(p.observed_at),
                "Ár": hu.huf(p.price_huf),
                "Szállítás": hu.huf(p.shipping_huf),
                "Készlet": hu.label("availability", p.availability),
            }
            for p in reversed(d.history)
        ],
        right=("Ár", "Szállítás"),
    )


def _personal(d: workflow.OfferDetail) -> None:
    r = d.personal
    if r is None:
        empty("Még nincs értékelve.")
        return
    metrics(
        [
            ("Ár szállítással", hu.huf(r.get("effective_price_huf")), None),
            ("Szokásos ár (medián)", hu.huf(r.get("benchmark_median_huf")), None),
            ("A szokásos árhoz képest", hu.pct(r.get("discount_vs_median_bp")), None),
            ("Figyelőlista", hu.label("watchlist", r.get("watchlist")), None),
        ],
        columns=4,
    )
    _bullets("Indoklás", r.get("reasons"))
    _bullets("Hiányzó adatok", r.get("missing_inputs"), label_codes=True)
    _bullets("Ellenőrizendő", r.get("review_flags"), label_codes=True)
    st.caption(f"Értékelve: {hu.when(d.personal_at)}")


def _resale(d: workflow.OfferDetail) -> None:
    r = d.resale
    if r is None:
        empty("Még nincs értékelve.")
        return
    liquidity = r.get("liquidity") or {}
    days = liquidity.get("est_days_to_sell")
    metrics(
        [
            ("Beszerzési költség", hu.huf(r.get("acquisition_cost_huf")), None),
            (
                "Várható eladási ár",
                hu.huf(r.get("expected_sale_huf")),
                "A lezárt eladások mediánja, sosem hirdetési ár.",
            ),
            ("Becsült nettó haszon", hu.huf(r.get("net_profit_huf")), None),
            (
                "Eladhatóság",
                hu.label("liquidity", liquidity.get("liquidity")),
                f"Várhatóan {days} nap" if days is not None else None,
            ),
        ],
        columns=4,
    )
    if r.get("provisional"):
        notice("warning", "Ideiglenes számok: a jelzett kérdések tisztázásáig nem döntésre készek.")
    _bullets("Indoklás", r.get("reasons"))
    _bullets("Hiányzó adatok", r.get("missing_inputs"), label_codes=True)
    _bullets("Ellenőrizendő", r.get("review_flags"), label_codes=True)
    scenarios = r.get("scenarios")
    if scenarios:
        st.markdown("**A számítás részletei**")
        names = (
            ("low", "Alacsony (p25)"),
            ("expected", "Várható (medián)"),
            ("high", "Magas (p75)"),
        )
        rows = []
        for key, name, sign in _SCENARIO_LINES:
            row = {"Tétel": name}
            for scenario, col in names:
                value = (scenarios.get(scenario) or {}).get(key)
                row[col] = hu.huf(value if value is None or key == "net_profit" else sign * value)
            rows.append(row)
        table(rows, right=[c for _, c in names])
    st.caption(f"Becslés, nem valós pénz. Értékelve: {hu.when(d.resale_at)}")


def _decision(offer_id: int) -> None:
    db = get_context().db
    with st.form(f"decide_{offer_id}", border=True):
        st.markdown("**Döntésed**")
        decision = st.segmented_control(
            "Döntés",
            [Decision.WATCH, Decision.REJECT, Decision.RESTORE],
            format_func=lambda x: hu.label("decision", x),
            default=Decision.WATCH,
            required=True,
        )
        reason = st.selectbox(
            "Elutasítás oka (elutasításnál kötelező)",
            [None, *RejectReason],
            format_func=lambda r: "Válassz..." if r is None else hu.label("reject_reason", r),
        )
        note = st.text_input("Megjegyzés (nem kötelező)")
        if st.form_submit_button("Döntés mentése", type="primary"):
            try:
                workflow.decide(db, offer_id, decision or Decision.WATCH, reason=reason, note=note)
                notice("success", "Mentve.")
            except ValueError as exc:
                notice("error", plain(exc))


def _purchase(d: workflow.OfferDetail) -> None:
    db = get_context().db
    price = d.history[-1].price_huf if d.history else None
    with st.form(f"buy_{d.offer_id}", border=True):
        st.markdown("**Megvettem: vásárlás rögzítése**")
        st.caption("A ténylegesen kifizetett összeget rögzíti. A DealRadar maga sosem vásárol.")
        c1, c2 = st.columns(2)
        seller = c1.text_input("Eladó")
        total = c2.number_input(
            "A termékekért fizetett összeg (Ft)", min_value=1, step=100, value=price or 1
        )
        c3, c4 = st.columns(2)
        shipping = c3.number_input("Szállítási díj (Ft)", min_value=0, step=100)
        units = c4.number_input("Darabszám", min_value=1, step=1, value=1)
        c5, c6 = st.columns(2)
        intent = c5.segmented_control(
            "Cél",
            list(ItemIntent),
            format_func=lambda i: hu.label("intent", i),
            default=ItemIntent.RESALE,
            required=True,
        )
        condition = c6.selectbox(
            "Állapot",
            [None, *Condition],
            format_func=lambda c: "Ismeretlen" if c is None else hu.label("condition", c),
        )
        if st.form_submit_button("Vásárlás rögzítése", type="primary"):
            try:
                ids = ledger.record_purchase(
                    db,
                    title=d.title,
                    category=d.category or Category.TECH,
                    seller=seller,
                    total_price_huf=int(total),
                    shipping_huf=int(shipping),
                    unit_count=int(units),
                    intent=intent or ItemIntent.RESALE,
                    condition=condition,
                    variant_id=d.variant_id,
                    offer_id=d.offer_id,
                )
                notice("success", f"{len(ids)} tétel rögzítve. Lásd: Készlet és eredmény.")
            except ValueError as exc:
                notice("error", plain(exc))


def _decisions_and_purchase(d: workflow.OfferDetail) -> None:
    left, right = st.columns(2, gap="medium")
    with left:
        _decision(d.offer_id)
    with right:
        _purchase(d)
    if d.decisions:
        st.markdown("**Korábbi döntések**")
        table(
            [
                {
                    "Időpont": hu.when(at),
                    "Döntés": hu.label("decision", dec),
                    "Ok": hu.label("reject_reason", r) if r else "-",
                    "Megjegyzés": n or "",
                }
                for at, dec, r, n in d.decisions
            ]
        )


def _claude(offer_id: int) -> None:
    history = [h for h in analyses_for_offer(get_context().db, offer_id) if h.analysis]
    st.caption(
        "Nem kötelező második vélemény. Csak tanács: árat, párosítást, értékelést nem módosít."
    )
    if not history:
        empty("Ehhez az ajánlathoz még nincs Claude-elemzés.")
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
    st.page_link(
        "page_scripts/analysis.py",
        label="Új Claude-elemzés készítése",
        icon=":material/psychology:",
    )


def _facts(d: workflow.OfferDetail) -> None:
    table(
        [
            {"Adat": "Forrás", "Érték": d.source},
            {"Adat": "Hirdetés típusa", "Érték": hu.label("listing_kind", d.listing_kind)},
            {
                "Adat": "Állapot",
                "Érték": hu.label("condition", d.condition) if d.condition else "ismeretlen",
            },
            {"Adat": "Garancia", "Érték": d.warranty or "nincs megadva"},
            {
                "Adat": "Eladó",
                "Érték": hu.label("seller_kind", d.seller_kind) if d.seller_kind else "ismeretlen",
            },
            {"Adat": "Párosítás", "Érték": hu.label("match_status", d.match_status)},
            {"Adat": "Termék", "Érték": d.product or "-"},
            {"Adat": "Változat", "Érték": d.variant_key or "-"},
            {"Adat": "Kategória", "Érték": hu.label("category", d.category)},
            {"Adat": "Link", "Érték": d.url or "-"},
        ]
    )
    st.caption("A linket másold ki, ha meg szeretnéd nyitni; az app nem nyit meg külső oldalt.")


def render() -> None:
    page(
        "Ajánlat részletei",
        "Árelőzmény, a két független értékelés, a döntésed és a vásárlás rögzítése egy helyen.",
    )
    if not require_schema():
        return
    offer_id = _pick_offer()
    if offer_id is None:
        return
    db = get_context().db
    d = workflow.offer_detail(db, offer_id)
    _summary(d)
    if st.button("Újraértékelés most", icon=":material/autorenew:"):
        workflow.evaluate_offer(db, offer_id)
        st.rerun()
    tabs = st.tabs(
        [
            "Árelőzmény",
            "Saját vásárlás",
            "Továbbértékesítés",
            "Döntés és vásárlás",
            "Claude-elemzések",
            "Adatok",
        ]
    )
    with tabs[0]:
        _history(d)
    with tabs[1]:
        _personal(d)
    with tabs[2]:
        _resale(d)
    with tabs[3]:
        _decisions_and_purchase(d)
    with tabs[4]:
        _claude(offer_id)
    with tabs[5]:
        _facts(d)
