"""docs/ENGINE_FORMULAS.md must describe what the code does (requirement: document every formula
and default threshold)."""

from __future__ import annotations

import dataclasses
from pathlib import Path

from dealradar.categories.registry import module_for
from dealradar.core.enums import Category
from dealradar.evaluation.params import FeeProfile, PersonalParams, ResaleParams, TaxKind
from tests.engine_fixtures import resale_inputs

DOC = (Path(__file__).resolve().parents[1] / "docs" / "ENGINE_FORMULAS.md").read_text(
    encoding="utf-8"
)


def _fmt(n: int) -> str:
    return f"{n:,}".replace(",", " ")


def test_every_parameter_is_documented() -> None:
    for cls in (PersonalParams, ResaleParams, FeeProfile):
        for f in dataclasses.fields(cls):
            if f.name in ("source", "note", "platform"):
                continue
            assert f.name in DOC, f"{cls.__name__}.{f.name} undocumented"
    for kind in TaxKind:
        assert kind.value in DOC


def test_documented_base_defaults_match_code() -> None:
    p, r = PersonalParams(), ResaleParams()
    for name, value in (
        ("strong_discount_bp", p.strong_discount_bp),
        ("good_discount_bp", p.good_discount_bp),
        ("fair_tolerance_bp", p.fair_tolerance_bp),
        ("suspicious_discount_bp", p.suspicious_discount_bp),
        ("min_net_profit_huf", r.min_net_profit_huf),
        ("min_roi_bp", r.min_roi_bp),
        ("return_cost_huf", r.return_cost_huf),
        ("capital_cost_bp_per_year", r.capital_cost_bp_per_year),
    ):
        row = next(line for line in DOC.splitlines() if line.startswith(f"| {name} |"))
        assert _fmt(value) in row, (name, row)


def test_documented_category_overrides_match_code() -> None:
    def row(name: str) -> list[str]:
        line = next(x for x in DOC.splitlines() if x.startswith(f"| {name} |"))
        return [c.strip().strip("*") for c in line.strip("|").split("|")]

    cols = {Category.TECH: 2, Category.APPAREL: 3, Category.HOME: 5}
    for name in ("return_rate_bp", "return_cost_huf", "defect_rate_bp", "defect_loss_bp"):
        cells = row(name)
        for category, col in cols.items():
            assert cells[col] == _fmt(getattr(module_for(category).resale_params, name)), (
                name,
                category,
            )
    assert row("require_landed_comparison")[5] == "true"
    assert module_for(Category.HOME).personal_params.require_landed_comparison


def test_worked_example_in_the_doc_is_what_the_engine_computes() -> None:
    from dealradar.engines.resale import evaluate

    r = evaluate(resale_inputs())
    assert r.net_profit_huf == 9_570 and r.roi_bp == 2_393
    assert "net 9 570 HUF, ROI 2 393 bp" in DOC
