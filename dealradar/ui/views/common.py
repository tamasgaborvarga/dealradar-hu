from __future__ import annotations

import streamlit as st

from dealradar.core import hu
from dealradar.ui.state import get_schema_status


def require_schema() -> bool:
    """Show a blocking message when the DB is not migrated (ADR-004). Returns True if ready."""
    status = get_schema_status()
    if status.ready:
        return True
    st.error(
        f"Az adatbázis-séma {hu.label('schema_state', status.state)} "
        f"(jelenlegi: {status.current or 'nincs'}, szükséges: {status.head}). "
        "Az app magától nem frissíti az adatbázist. Futtasd ezt a parancsot:",
        icon=":material/error:",
    )
    st.code("dealradar db upgrade", language="bash")
    st.caption("Frissítés előtt mindig készül mentés. Részletek a Rendszerállapot oldalon.")
    return False
