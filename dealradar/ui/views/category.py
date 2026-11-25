"""One dashboard per category. Personal and Resale are separate tabs, never merged (ADR-002)."""

from __future__ import annotations

import streamlit as st

from dealradar.core import hu
from dealradar.core.enums import Category, RefreshScope
from dealradar.services import workflow
from dealradar.services.overview import category_overview
from dealradar.ui.state import get_context
from dealradar.ui.views.common import require_schema
from dealradar.ui.views.widgets import deal_list, metrics, notice, page, refresh_button


def render_category(category: Category) -> None:
    name = hu.label("category", category)
    page(name, hu.label("category_scope", category))
    if not require_schema():
        return
    db = get_context().db
    overview = category_overview(db, category)
    refresh_button(
        RefreshScope.CATEGORY, category.value, f"{name} frissítése", key=f"refresh_{category.value}"
    )
    metrics(
        [
            ("Termékek", str(overview.products), None),
            (
                "Változatok",
                str(overview.variants),
                "Változat: " + hu.label("category_variant", category),
            ),
            ("Párosított hirdetések", str(overview.matched_listings), None),
        ],
        columns=3,
    )
    rows = workflow.deal_rows(db, category)
    personal, resale = st.tabs(["Saját vásárlás", "Továbbértékesítés"])
    with personal:
        deal_list(
            workflow.personal_deals(rows),
            "personal",
            f"{category.value}_p",
            "Még nincs értékelt ajánlat ebben a kategóriában. Indíts egy frissítést.",
        )
    with resale:
        if not overview.info.resale_enabled_by_default:
            notice("info", "Ebben a kategóriában a továbbértékesítés alapból nem alkalmazható.")
        else:
            st.caption("A becslés csak lezárt eladásokon alapul, sosem hirdetési árakon.")
            deal_list(
                workflow.resale_deals(rows),
                "resale",
                f"{category.value}_r",
                "Még nincs továbbértékesítési értékelés ebben a kategóriában.",
            )


def render_tech() -> None:
    render_category(Category.TECH)


def render_apparel() -> None:
    render_category(Category.APPAREL)


def render_food() -> None:
    render_category(Category.FOOD)


def render_home() -> None:
    render_category(Category.HOME)
