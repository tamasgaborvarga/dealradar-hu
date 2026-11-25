"""Strict response schema (v1). Anything else is rejected - never repaired or guessed."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = "dealradar.analysis.v1"
ShortText = Annotated[str, Field(min_length=1, max_length=200)]


class Recommendation(StrEnum):
    """Advisory only. There is deliberately no BUY value: the user decides, the app never buys."""

    CONSIDER = "CONSIDER"  # worth a closer look by the user
    WAIT = "WAIT"  # better to wait / watch the price
    AVOID = "AVOID"
    NEEDS_MORE_INFO = "NEEDS_MORE_INFO"


class RiskFlag(StrEnum):
    COUNTERFEIT_RISK = "COUNTERFEIT_RISK"
    SCAM_RISK = "SCAM_RISK"
    WRONG_PRODUCT_MATCH = "WRONG_PRODUCT_MATCH"
    PRICE_ERROR_LIKELY = "PRICE_ERROR_LIKELY"
    CONDITION_CONCERN = "CONDITION_CONCERN"
    WARRANTY_CONCERN = "WARRANTY_CONCERN"
    SELLER_CONCERN = "SELLER_CONCERN"
    LISTING_INCONSISTENT = "LISTING_INCONSISTENT"
    MISSING_KEY_INFO = "MISSING_KEY_INFO"
    OTHER = "OTHER"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class RiskFinding(_Strict):
    flag: RiskFlag
    evidence: str = Field(min_length=1, max_length=300)


class DisputedFact(_Strict):
    key: str = Field(min_length=1, max_length=60)  # must be a key from the package
    reason: str = Field(min_length=1, max_length=300)


class AnalysisResponse(_Strict):
    schema_version: Literal["dealradar.analysis.v1"]
    request_id: str = Field(min_length=1, max_length=64)
    recommendation: Recommendation
    confidence: Literal["LOW", "MEDIUM", "HIGH"]
    summary: str = Field(min_length=1, max_length=600)
    risk_flags: list[RiskFinding] = Field(default_factory=list, max_length=10)
    questions_for_seller: list[ShortText] = Field(default_factory=list, max_length=5)
    missing_information: list[ShortText] = Field(default_factory=list, max_length=10)
    facts_disputed: list[DisputedFact] = Field(default_factory=list, max_length=5)


def json_schema() -> dict[str, object]:
    return AnalysisResponse.model_json_schema()
