"""Készlet és eredmény: ACTUAL results from recorded transactions, items, sales, costs, statuses
and reversals. Estimates never appear on this page."""

from __future__ import annotations

import streamlit as st

from dealradar.core import hu
from dealradar.core.enums import Category, Condition, ItemIntent, ItemStatus, TxType
from dealradar.services import ledger
from dealradar.ui.state import get_context
from dealradar.ui.views.common import require_schema
from dealradar.ui.views.widgets import empty, metrics, notice, page, plain, section, table

_COST_TYPES = [t for t in TxType if t not in (TxType.PURCHASE, TxType.SALE)]
_MANUAL = [
    ItemStatus.IN_STOCK,
    ItemStatus.LISTED,
    ItemStatus.RETURNED_TO_SELLER,
    ItemStatus.WRITTEN_OFF,
    ItemStatus.PERSONAL_USE,
]


def _summary() -> None:
    p = ledger.portfolio(get_context().db)
    roi = hu.pct(p.realized_roi_bp, signed=False) if p.realized_roi_bp is not None else "-"
    metrics(
        [
            (
                "Realizált haszon",
                hu.huf(p.realized_profit_huf),
                "Csak lezárt (eladott, visszaküldött, leírt) továbbértékesítési tételek.",
            ),
            ("Realizált megtérülés", roi, None),
            ("Készletben lekötött tőke", hu.huf(p.capital_in_stock_huf), None),
            ("Saját célú költés", hu.huf(p.personal_spend_huf), "Kiadás, nem haszon."),
            ("Bevétel", hu.huf(p.cash_in_huf), None),
            ("Kiadás", hu.huf(p.cash_out_huf), None),
            ("Nettó pénzmozgás", hu.huf(p.net_cash_flow_huf), None),
            ("Nyitott / lezárt tétel", f"{p.open_items} / {p.closed_items}", None),
        ],
        columns=4,
    )


def _items(rows: list[ledger.ItemRow]) -> None:
    if not rows:
        empty(
            "Még nincs tétel. Vásárlást egy ajánlat oldaláról vagy az Új vásárlás fülön "
            "rögzíthetsz."
        )
        return
    table(
        [
            {
                "Tétel": r.title,
                "Kategória": hu.label("category", r.category),
                "Cél": hu.label("intent", r.intent),
                "Állapot": hu.label("item_status", r.status),
                "Vásárolva": hu.when(r.acquired_at, with_time=False),
                "Eladó": r.seller,
                "Bekerülési érték": hu.huf(r.result.cost_basis),
                "Bevétel": hu.huf(r.result.income),
                "Realizált haszon": hu.huf(r.result.realized_profit),
            }
            for r in rows
        ],
        right=("Bekerülési érték", "Bevétel", "Realizált haszon"),
    )


def _new_purchase() -> None:
    db = get_context().db
    with st.form("manual_purchase", border=True):
        st.caption("Ajánlathoz nem kötött vásárlás rögzítése.")
        title = st.text_input("Mit vettél?")
        c1, c2 = st.columns(2)
        category = c1.selectbox(
            "Kategória", list(Category), format_func=lambda c: hu.label("category", c)
        )
        seller = c2.text_input("Eladó")
        c3, c4, c5 = st.columns(3)
        total = c3.number_input("A termékekért fizetett összeg (Ft)", min_value=1, step=100)
        shipping = c4.number_input("Szállítási díj (Ft)", min_value=0, step=100)
        units = c5.number_input("Darabszám", min_value=1, step=1, value=1)
        c6, c7 = st.columns(2)
        intent = c6.segmented_control(
            "Cél",
            list(ItemIntent),
            format_func=lambda i: hu.label("intent", i),
            default=ItemIntent.RESALE,
            required=True,
        )
        condition = c7.selectbox(
            "Állapot",
            [None, *Condition],
            format_func=lambda c: "Ismeretlen" if c is None else hu.label("condition", c),
        )
        if st.form_submit_button("Vásárlás rögzítése", type="primary") and category is not None:
            try:
                ids = ledger.record_purchase(
                    db,
                    title=title,
                    category=category,
                    seller=seller,
                    total_price_huf=int(total),
                    shipping_huf=int(shipping),
                    unit_count=int(units),
                    intent=intent or ItemIntent.RESALE,
                    condition=condition,
                )
                notice("success", f"{len(ids)} tétel rögzítve.")
            except ValueError as exc:
                notice("error", plain(exc))


def _item_actions(rows: list[ledger.ItemRow]) -> None:
    if not rows:
        empty("Előbb rögzíts egy vásárlást.")
        return
    db = get_context().db
    labels = {
        r.id: f"{r.id}. tétel: {r.title[:60]} ({hu.label('item_status', r.status)})" for r in rows
    }
    item_id = st.selectbox("Tétel", list(labels), format_func=lambda i: labels[i])
    if item_id is None:
        return
    sale, cost, status = st.tabs(["Eladás rögzítése", "Költség vagy bevétel", "Állapot módosítása"])
    with sale, st.form("sale", border=False):
        c1, c2 = st.columns(2)
        price = c1.number_input("Eladási ár (Ft)", min_value=1, step=100)
        platform = c2.text_input("Hol adtad el?")
        c3, c4, c5 = st.columns(3)
        buyer_ship = c3.number_input("A vevő által fizetett szállítás", min_value=0, step=100)
        fee = c4.number_input("Platformdíj", min_value=0, step=10)
        pay = c5.number_input("Fizetési díj", min_value=0, step=10)
        c6, c7, c8 = st.columns(3)
        out = c6.number_input("Kiszállítás költsége", min_value=0, step=100)
        pack = c7.number_input("Csomagolás", min_value=0, step=10)
        tax = c8.number_input("Adó", min_value=0, step=10)
        if st.form_submit_button("Eladás rögzítése", type="primary"):
            try:
                ledger.record_sale(
                    db,
                    int(item_id),
                    sale_price_huf=int(price),
                    platform=platform,
                    buyer_shipping_charged_huf=int(buyer_ship),
                    platform_fee_huf=int(fee),
                    payment_fee_huf=int(pay),
                    outbound_shipping_huf=int(out),
                    packaging_huf=int(pack),
                    tax_huf=int(tax),
                )
                notice("success", "Eladás rögzítve.")
            except ValueError as exc:
                notice("error", plain(exc))
    with cost, st.form("cost", border=False):
        c1, c2 = st.columns(2)
        kind = c1.selectbox("Típus", _COST_TYPES, format_func=lambda t: hu.label("tx_type", t))
        amount = c2.number_input("Összeg (Ft)", min_value=1, step=10)
        note = st.text_input("Megjegyzés")
        if st.form_submit_button("Hozzáadás", type="primary") and kind is not None:
            try:
                ledger.record_item_transaction(
                    db, int(item_id), kind, int(amount), note=note or None
                )
                notice("success", "Hozzáadva.")
            except ValueError as exc:
                notice("error", plain(exc))
    with status, st.form("status", border=False):
        new = st.selectbox("Új állapot", _MANUAL, format_func=lambda s: hu.label("item_status", s))
        st.caption("Eladott állapotot az Eladás rögzítése fül állít be.")
        if st.form_submit_button("Állapot mentése", type="primary") and new is not None:
            try:
                ledger.set_status(db, int(item_id), new)
                notice("success", "Állapot módosítva.")
            except ValueError as exc:
                notice("error", plain(exc))


def _transactions() -> None:
    db = get_context().db
    rows = ledger.transactions(db)
    if not rows:
        empty("Még nincs tranzakció.")
        return
    table(
        [
            {
                "Dátum": hu.when(t.occurred_at, with_time=False),
                "Típus": hu.label("tx_type", t.type),
                "Összeg": ("+" if t.direction.value == "IN" else "-") + hu.huf(t.amount_huf),
                "Tétel": t.item_id or "-",
                "Rendelés": t.acquisition_id or "-",
                "Platform": t.platform or "",
                "Megjegyzés": t.note or "",
                "Állapot": "stornózva" if t.reversed else ("stornó" if t.is_reversal else ""),
            }
            for t in rows
        ],
        right=("Összeg",),
    )
    reversible = {
        t.id: f"{t.id}. {hu.when(t.occurred_at, with_time=False)} {hu.label('tx_type', t.type)} "
        f"{hu.huf(t.amount_huf)}"
        for t in rows
        if not t.reversed and not t.is_reversal
    }
    if not reversible:
        return
    with st.form("reverse", border=True):
        st.markdown("**Hibás tétel stornózása**")
        st.caption("Tranzakciót nem lehet szerkeszteni vagy törölni: a javítás egy ellentétel.")
        tx_id = st.selectbox(
            "Stornózandó tétel", list(reversible), format_func=lambda i: reversible[i]
        )
        why = st.text_input("Miért?")
        if st.form_submit_button("Stornózás") and tx_id is not None:
            try:
                ledger.reverse_transaction(db, int(tx_id), why or "javítás")
                notice("success", "Stornózva.")
            except ValueError as exc:
                notice("error", plain(exc))


def render() -> None:
    page(
        "Készlet és eredmény",
        "Amit megvettél és eladtál, valós összegekkel. Itt csak "
        "tényleges pénz szerepel, becslés soha.",
    )
    if not require_schema():
        return
    section("Tényleges eredmény")
    _summary()
    rows = ledger.items(get_context().db)
    tabs = st.tabs(["Tételek", "Eladás és költségek", "Új vásárlás", "Tranzakciók"])
    with tabs[0]:
        _items(rows)
    with tabs[1]:
        _item_actions(rows)
    with tabs[2]:
        _new_purchase()
    with tabs[3]:
        _transactions()
