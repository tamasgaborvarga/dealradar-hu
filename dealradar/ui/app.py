"""Streamlit entry point. Start with ``dealradar ui`` (never plain ``streamlit run``).

Pages are thin scripts in ``ui/page_scripts/`` that render views from ``ui/views``.
The folder must NOT be called ``pages/``: Streamlit auto-loads such a folder as legacy
multipage navigation and overrides ``st.navigation`` (found in the browser smoke test).
"""

from __future__ import annotations

import streamlit as st

from dealradar.ui.views.widgets import apply_style


def main() -> None:
    st.set_page_config(page_title="DealRadar HU", page_icon=":material/radar:", layout="wide")
    apply_style()
    pages = {
        "": [
            st.Page(
                "page_scripts/overview.py",
                title="Áttekintés",
                icon=":material/space_dashboard:",
                url_path="overview",
                default=True,
            )
        ],
        "Kategóriák": [
            st.Page(
                "page_scripts/tech.py",
                title="Műszaki cikkek",
                icon=":material/memory:",
                url_path="tech",
            ),
            st.Page(
                "page_scripts/apparel.py",
                title="Ruha, cipő, sport",
                icon=":material/checkroom:",
                url_path="apparel",
            ),
            st.Page(
                "page_scripts/food.py",
                title="Élelmiszer",
                icon=":material/local_grocery_store:",
                url_path="food",
            ),
            st.Page(
                "page_scripts/home.py",
                title="Otthon és háztartás",
                icon=":material/chair:",
                url_path="home",
            ),
        ],
        "Munka": [
            st.Page(
                "page_scripts/offer.py",
                title="Ajánlat részletei",
                icon=":material/sell:",
                url_path="offer",
            ),
            st.Page(
                "page_scripts/watchlists.py",
                title="Figyelőlisták",
                icon=":material/notifications_active:",
                url_path="watchlists",
            ),
            st.Page(
                "page_scripts/inventory.py",
                title="Készlet és eredmény",
                icon=":material/inventory_2:",
                url_path="inventory",
            ),
            st.Page(
                "page_scripts/feedback.py",
                title="Elutasított ajánlatok",
                icon=":material/thumb_down:",
                url_path="feedback",
            ),
            st.Page(
                "page_scripts/analysis.py",
                title="Claude-elemzés",
                icon=":material/psychology:",
                url_path="analysis",
            ),
        ],
        "Rendszer": [
            st.Page(
                "page_scripts/settings.py",
                title="Beállítások",
                icon=":material/tune:",
                url_path="settings",
            ),
            st.Page(
                "page_scripts/sources.py",
                title="Források",
                icon=":material/hub:",
                url_path="sources",
            ),
            st.Page(
                "page_scripts/health.py",
                title="Rendszerállapot",
                icon=":material/monitor_heart:",
                url_path="health",
            ),
        ],
    }
    st.navigation(pages).run()


if __name__ == "__main__":
    main()
