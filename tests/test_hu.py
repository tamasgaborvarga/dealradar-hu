"""Hungarian user-facing text (ADR-056): complete labels, correct number and date formats."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path

import pytest

from dealradar.claude_bridge.schema import Recommendation, RiskFlag
from dealradar.core import enums as E
from dealradar.core import hu
from dealradar.engines.personal.evaluator import WatchlistRelevance
from dealradar.engines.resale.liquidity import LiquidityClass
from dealradar.evaluation.params import TaxKind
from dealradar.evaluation.types import Level, ValueKind
from dealradar.pricing.types import BenchmarkStatus
from dealradar.services.health import Status
from dealradar.services.schema import SchemaState

DOMAINS: list[tuple[str, type[Enum]]] = [
    ("category", E.Category),
    ("category_scope", E.Category),
    ("category_variant", E.Category),
    ("personal_verdict", E.PersonalVerdict),
    ("resale_verdict", E.ResaleVerdict),
    ("decision", E.Decision),
    ("reject_reason", E.RejectReason),
    ("intent", E.ItemIntent),
    ("item_status", E.ItemStatus),
    ("tx_type", E.TxType),
    ("direction", E.Direction),
    ("condition", E.Condition),
    ("availability", E.Availability),
    ("listing_kind", E.ListingKind),
    ("seller_kind", E.SellerKind),
    ("warranty_type", E.WarrantyType),
    ("match_status", E.MatchStatus),
    ("match_method", E.MatchMethod),
    ("candidate_status", E.CandidateStatus),
    ("source_status", E.SourceStatus),
    ("run_status", E.RunStatus),
    ("fetch_error", E.FetchErrorKind),
    ("access_method", E.AccessMethod),
    ("refresh_scope", E.RefreshScope),
    ("telegram_status", E.TelegramStatus),
    ("watchlist", WatchlistRelevance),
    ("tax_kind", TaxKind),
    ("level", Level),
    ("liquidity", LiquidityClass),
    ("value_kind", ValueKind),
    ("recommendation", Recommendation),
    ("risk_flag", RiskFlag),
    ("schema_state", SchemaState),
    ("health_status", Status),
    ("benchmark_status", BenchmarkStatus),
    ("sale_evidence", E.SaleEvidence),
]
PKG = Path(__file__).resolve().parents[1] / "dealradar"


@pytest.mark.parametrize(("domain", "enum_cls"), DOMAINS)
def test_every_enum_member_has_a_hungarian_label(domain: str, enum_cls: type[Enum]) -> None:
    missing = [m.value for m in enum_cls if m.value not in hu.LABELS[domain]]
    assert missing == []
    assert all(hu.LABELS[domain][m.value].strip() for m in enum_cls)


def test_every_missing_input_and_review_flag_code_has_a_label() -> None:
    pattern = re.compile(r"(?:missing|flags)\.(?:append|insert)\((?:\d+,\s*)?\"([a-z_]+)\"")
    codes = set()
    for path in PKG.rglob("*.py"):
        codes |= set(pattern.findall(path.read_text(encoding="utf-8")))
    assert codes, "pattern found nothing"
    assert sorted(codes - set(hu.LABELS["code"])) == []


def test_money_and_percent_formats() -> None:
    nb = chr(0xA0)
    assert hu.huf(1234567) == f"1{nb}234{nb}567{nb}Ft"
    assert hu.huf(-9047) == f"-9{nb}047{nb}Ft"
    assert hu.huf(0) == f"0{nb}Ft" and hu.huf(None) == "-"
    assert hu.pct(1776) == f"+17,8{nb}%" and hu.pct(-50, signed=False) == f"-0,5{nb}%"
    assert hu.pct(None) == "-"


def test_dates_are_local_hungarian_order() -> None:
    winter = datetime(2026, 1, 15, 11, 30, tzinfo=UTC)  # CET = UTC+1
    summer = datetime(2026, 7, 15, 11, 30, tzinfo=UTC)  # CEST = UTC+2
    assert hu.when(winter) == "2026. 01. 15. 12:30"
    assert hu.when(summer) == "2026. 07. 15. 13:30"
    assert hu.when(summer, with_time=False) == "2026. 07. 15."
    assert hu.when(None) == "-"


def test_label_never_fails() -> None:
    assert hu.label("personal_verdict", E.PersonalVerdict.STRONG_DEAL) == "Kiemelkedő ajánlat"
    assert hu.label("nope", "X") == "X" and hu.label("code", None) == "-"
    assert hu.codes(["completed_sales", "unknown_code"]) == "lezárt eladások, unknown_code"
