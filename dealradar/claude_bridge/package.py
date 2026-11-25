"""The structured analysis package: everything DealRadar knows, labelled by kind."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class ItemKind(StrEnum):
    FACT = "FACT"  # observed or computed by DealRadar from recorded data
    SELLER_CLAIM = "SELLER_CLAIM"  # stated in the listing, not verified (condition, warranty)
    ESTIMATE = "ESTIMATE"  # derived from data (medians, expected profit, days to sell)
    ASSUMPTION = "ASSUMPTION"  # configured default, not measured (return rate, thresholds)


@dataclass(frozen=True)
class PackageItem:
    key: str  # stable identifier Claude may reference in facts_disputed
    label: str
    value: str
    kind: ItemKind
    source: str


@dataclass(frozen=True)
class AnalysisPackage:
    request_id: str
    category: str
    items: tuple[PackageItem, ...]
    missing: tuple[str, ...]  # information DealRadar does not have
    evaluations: tuple[str, ...]  # deterministic engine verdicts, for context only
    untrusted_title: str
    untrusted_description: str | None = None
    notes: tuple[str, ...] = field(default=())

    def fact_keys(self) -> frozenset[str]:
        return frozenset(i.key for i in self.items)

    def by_kind(self, kind: ItemKind) -> tuple[PackageItem, ...]:
        return tuple(i for i in self.items if i.kind is kind)

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, sort_keys=True)

    def digest(self) -> str:
        return hashlib.sha256(self.to_json().encode("utf-8")).hexdigest()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AnalysisPackage:
        return cls(
            request_id=data["request_id"],
            category=data["category"],
            items=tuple(
                PackageItem(i["key"], i["label"], i["value"], ItemKind(i["kind"]), i["source"])
                for i in data["items"]
            ),
            missing=tuple(data["missing"]),
            evaluations=tuple(data["evaluations"]),
            untrusted_title=data["untrusted_title"],
            untrusted_description=data.get("untrusted_description"),
            notes=tuple(data.get("notes", ())),
        )
