"""The UI kit: every page is built from these pieces, so layout, wording and colours stay the same
everywhere (ADR-057).

Page anatomy: ``page()`` (title + one-line purpose) -> status notices -> one primary action ->
sections (``section()``), each a bordered card or tabs. Colours carry meaning only: green = good /
actual money, blue = action / information, orange = needs your review, red = loss / blocked,
gray = neutral.

Untrusted text (listing titles, URLs, error messages, Claude answers) goes through ``plain()``
before any Markdown-rendering widget, and is never rendered with unsafe_allow_html. The only HTML
injected is the static stylesheet below.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Literal

import streamlit as st

from dealradar.core import hu
from dealradar.core.enums import Category, PersonalVerdict, RefreshScope, ResaleVerdict
from dealradar.services.refresh import RefreshEvent, RefreshReport, refresh
from dealradar.services.workflow import DealRow
from dealradar.ui.state import get_context

Color = Literal["red", "orange", "yellow", "blue", "green", "violet", "gray"]

OFFER_KEY = "selected_offer_id"
OFFER_PAGE = "page_scripts/offer.py"

# Static stylesheet (no user data). No italics anywhere, no mid-word breaks, tabular figures.
STYLE = """<style>
html, body, [class*="st-"], [data-testid="stAppViewContainer"] { font-synthesis: none; }
em, i, cite, address, blockquote, q, dfn { font-style: normal; }
[data-testid="stMarkdownContainer"] em { font-weight: 600; }
body, p, li, td, th, label, span { overflow-wrap: normal; word-break: normal; hyphens: manual; }
[data-testid="stMetricValue"], [data-testid="stMetricDelta"] {
  font-variant-numeric: tabular-nums; white-space: nowrap;
}
[data-testid="stCaptionContainer"] p { color: #4A5563; }
h1 { letter-spacing: -0.01em; }
</style>"""

_PERSONAL_COLOR: dict[PersonalVerdict, Color] = {
    PersonalVerdict.STRONG_DEAL: "green",
    PersonalVerdict.GOOD_DEAL: "blue",
    PersonalVerdict.FAIR_PRICE: "gray",
    PersonalVerdict.NOT_A_DEAL: "red",
    PersonalVerdict.MANUAL_REVIEW: "orange",
}
_RESALE_COLOR: dict[ResaleVerdict, Color] = {
    ResaleVerdict.PROFITABLE: "green",
    ResaleVerdict.MARGINAL: "blue",
    ResaleVerdict.NOT_PROFITABLE: "red",
    ResaleVerdict.MANUAL_REVIEW: "orange",
    ResaleVerdict.NOT_APPLICABLE: "gray",
}
_NOTICE = {
    "info": (st.info, ":material/info:"),
    "success": (st.success, ":material/check_circle:"),
    "warning": (st.warning, ":material/warning:"),
    "error": (st.error, ":material/error:"),
}
_MD_SPECIAL = set("\\`*_{}[]()#+-.!|<>~$:")


def apply_style() -> None:
    st.html(STYLE)


def plain(text: object) -> str:
    """Escape Markdown for untrusted text shown in Markdown-rendering widgets (st.subheader,
    st.caption, st.write...). Without this a listing title like ``![x](http://tracker)`` would
    make the browser load an external image, and links / colour directives / LaTeX would render."""
    return "".join("\\" + ch if ch in _MD_SPECIAL else ch for ch in str(text))


def page(title: str, lead: str) -> None:
    """Every page starts the same way: a title and one sentence about what the page is for."""
    st.title(title)
    st.caption(lead)


def section(title: str, lead: str | None = None) -> None:
    st.subheader(title)
    if lead:
        st.caption(lead)


def notice(kind: str, text: str) -> None:
    fn, icon = _NOTICE[kind]
    fn(text, icon=icon)


def empty(text: str) -> None:
    """Consistent empty state."""
    st.caption(text)


def verdict_badge(verdict: PersonalVerdict | ResaleVerdict | None) -> None:
    if verdict is None:
        st.badge("Nincs értékelve", color="gray")
    elif isinstance(verdict, PersonalVerdict):
        st.badge(hu.label("personal_verdict", verdict), color=_PERSONAL_COLOR[verdict])
    else:
        st.badge(hu.label("resale_verdict", verdict), color=_RESALE_COLOR[verdict])


def pill(text: str, color: Color = "gray") -> None:
    st.badge(text, color=color)


def refresh_button(scope: RefreshScope, target: str | None, label: str, key: str) -> None:
    """The one primary action of a page: a manual refresh with progress and a clear outcome."""
    if not st.button(label, key=key, type="primary", icon=":material/refresh:"):
        return
    bar = st.progress(0.0, text="Indul...")

    def on_event(e: RefreshEvent) -> None:
        if e.total_sources:
            name = e.source_key or ""
            step = {"SOURCE_STARTED": "letöltés", "SOURCE_FINISHED": "kész"}.get(e.kind, "")
            bar.progress(min(e.done_sources / e.total_sources, 1.0), text=f"{name} {step}".strip())

    try:
        report = refresh(get_context().db, scope, target, progress=on_event)
    except ValueError as exc:
        notice("error", plain(exc))
        return
    bar.empty()
    show_report(report)


def show_report(report: RefreshReport) -> None:
    if not report.sources:
        notice("info", "Nincs aktív forrás. Forrást a Források oldalon lehet kezelni.")
        return
    new = sum(x.new_observations for x in report.sources)
    status = hu.label("run_status", report.status)
    text = f"Frissítés: {status}. {new} új áradat, {len(report.sources)} forrás."
    kind = {"OK": "success", "PARTIAL": "warning"}.get(report.status.value, "error")
    notice(kind, text)
    for x in report.sources:
        if x.error_kind is not None:
            reason = hu.label("fetch_error", x.error_kind)
            st.caption(f"{plain(x.source_key)}: {reason} - {plain(x.message)}")


def unique_labels(labels: dict[int, str]) -> dict[int, str]:
    """Selectboxes identify options by their label: two equal labels would select the wrong
    record (found in the browser check). Duplicates get their id appended."""
    seen: dict[str, int] = {}
    for text in labels.values():
        seen[text] = seen.get(text, 0) + 1
    return {k: (f"{v} (#{k})" if seen[v] > 1 else v) for k, v in labels.items()}


def open_offer(offer_id: int) -> None:
    st.session_state[OFFER_KEY] = offer_id
    st.switch_page(OFFER_PAGE)


_RIGHT = st.column_config.TextColumn(alignment="right")


def table(data: list[dict[str, Any]], right: Sequence[str] = ()) -> None:
    st.dataframe(data, hide_index=True, column_config={c: _RIGHT for c in right})


def personal_table(rows: Sequence[DealRow]) -> None:
    table(
        [
            {
                "Ajánlat": r.title,
                "Értékelés": hu.label("personal_verdict", r.personal_verdict),
                "Ár szállítással": hu.huf(r.effective_price_huf),
                "A szokásos árhoz képest": hu.pct(r.discount_bp),
                "Figyelőlista": hu.label("watchlist", r.watchlist)
                if r.watchlist and r.watchlist != "NOT_WATCHED"
                else "-",
                "Forrás": r.source,
                "Frissítve": hu.when(r.observed_at),
            }
            for r in rows
        ],
        right=("Ár szállítással", "A szokásos árhoz képest"),
    )


def resale_table(rows: Sequence[DealRow]) -> None:
    table(
        [
            {
                "Ajánlat": r.title,
                "Értékelés": hu.label("resale_verdict", r.resale_verdict),
                "Becsült nettó haszon": hu.huf(r.net_profit_huf) + (" *" if r.provisional else ""),
                "Becsült megtérülés": hu.pct(r.roi_bp),
                "Hirdetési ár": hu.huf(r.price_huf),
                "Forrás": r.source,
            }
            for r in rows
        ],
        right=("Becsült nettó haszon", "Becsült megtérülés", "Hirdetési ár"),
    )
    if any(r.provisional for r in rows):
        st.caption("* ideiglenes szám: előbb a jelzett kérdéseket kell tisztázni")


def deal_list(rows: Sequence[DealRow], kind: str, key: str, empty_text: str) -> None:
    """A deal table plus a picker that opens the offer page."""
    if not rows:
        empty(empty_text)
        return
    if kind == "personal":
        personal_table(rows)
    else:
        resale_table(rows)
    labels = unique_labels({r.offer_id: f"{r.title[:70]} ({r.source})" for r in rows})
    left, right = st.columns([4, 1], vertical_alignment="bottom")
    choice = left.selectbox(
        "Ajánlat megnyitása", list(labels), format_func=lambda i: labels[i], key=f"{key}_pick"
    )
    if (
        right.button("Részletek", key=f"{key}_open", icon=":material/open_in_new:", width="stretch")
        and choice is not None
    ):
        open_offer(int(choice))


def category_name(category: Category | None) -> str:
    return hu.label("category", category)


def metrics(items: Sequence[tuple[str, str, str | None]], columns: int = 2) -> None:
    """A grid of bordered metrics: (label, value, help)."""
    cols = st.columns(columns)
    for i, (lbl, value, help_text) in enumerate(items):
        cols[i % columns].metric(lbl, value, help=help_text, border=True)
