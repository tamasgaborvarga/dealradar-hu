"""Process-wide cached application context for Streamlit."""

from __future__ import annotations

import streamlit as st

from dealradar.core.config import get_settings
from dealradar.services.app_context import AppContext, build_app_context
from dealradar.services.schema import SchemaStatus, schema_status


@st.cache_resource(show_spinner=False)
def _context_for(data_dir: str) -> AppContext:
    return build_app_context(get_settings())


def get_context() -> AppContext:
    """Keyed by data dir so a changed DEALRADAR_DATA_DIR never reuses a stale engine."""
    return _context_for(str(get_settings().resolved_data_dir))


def get_schema_status() -> SchemaStatus:
    return schema_status(get_context().db.engine)
