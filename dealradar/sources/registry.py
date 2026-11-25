"""Code-side adapter registry. A source runs only if BOTH exist and agree:
an adapter here and a reviewed, ACTIVE row in the ``sources`` table with the same key and
access method (docs/SOURCES.md §1).

Real adapters are added here only after their permitted access method is verified and
documented in docs/SOURCES.md. There are none yet.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from dealradar.core.enums import AccessMethod
from dealradar.sources.base import SourceAdapter
from dealradar.sources.errors import AccessNotPermitted
from dealradar.sources.mock.adapters import MOCK_MARKET, MOCK_SHOP, MOCK_SHOP_2, MockAdapter
from dealradar.sources.mock.transport import MockTransport
from dealradar.sources.requester import Transport

ADAPTERS: dict[str, SourceAdapter] = {a.key: a for a in (MOCK_SHOP, MOCK_SHOP_2, MOCK_MARKET)}


def get_adapter(key: str) -> SourceAdapter | None:
    return ADAPTERS.get(key)


def transport_for(adapter: SourceAdapter, clock: Callable[[], datetime]) -> Transport:
    """MOCK adapters get the in-process fixture transport. No real HTTP transport exists yet:
    it is added together with the first verified real adapter (docs/SOURCES.md)."""
    if adapter.access_method is AccessMethod.MOCK and isinstance(adapter, MockAdapter):
        return MockTransport(clock=clock)
    raise AccessNotPermitted(
        f"{adapter.key}: no transport for {adapter.access_method}; real sources are not enabled yet"
    )
