"""The suite-wide guard in conftest.py: tests cannot reach the network or real credentials."""

from __future__ import annotations

import socket

import pytest

from dealradar.core.config import get_settings, reset_settings_cache


def test_outbound_connections_are_refused() -> None:
    with pytest.raises(AssertionError, match="DNS lookup"):
        socket.create_connection(("192.0.2.1", 443), timeout=1)  # TEST-NET-1, never routed
    with socket.socket() as raw, pytest.raises(AssertionError, match="network access"):
        raw.connect(("192.0.2.1", 443))
    with pytest.raises(AssertionError, match="DNS lookup"):
        socket.getaddrinfo("api.telegram.org", 443)


def test_real_telegram_credentials_are_never_used() -> None:
    reset_settings_cache()
    try:
        assert not get_settings().telegram_enabled
    finally:
        reset_settings_cache()
