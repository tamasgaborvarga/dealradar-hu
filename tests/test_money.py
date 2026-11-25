from decimal import Decimal

import pytest

from dealradar.core.money import Bp, Huf, apply_bp, bp_change, huf, round_huf


@pytest.mark.parametrize(
    ("value", "expected"),
    [("0.5", 1), ("1.4999", 1), ("2.5", 3), ("-0.5", -1), ("-2.5", -3), ("12990", 12990)],
)
def test_round_huf_half_away_from_zero(value: str, expected: int) -> None:
    assert round_huf(Decimal(value)) == expected


def test_round_huf_rejects_float() -> None:
    with pytest.raises(TypeError):
        round_huf(0.5)  # type: ignore[arg-type]


@pytest.mark.parametrize("bad", [1.0, True, "100", None])
def test_huf_rejects_non_int(bad: object) -> None:
    with pytest.raises(TypeError):
        huf(bad)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("amount", "rate", "expected"),
    [
        (12_990, 500, 650),  # 5 % of 12 990 = 649.5 -> 650
        (12_990, 0, 0),
        (100_000, 10_000, 100_000),
        (999, 1, 0),  # 0.0999 -> 0
        (5_000, 2_750, 1_375),
    ],
)
def test_apply_bp(amount: int, rate: int, expected: int) -> None:
    assert apply_bp(Huf(amount), Bp(rate)) == expected


def test_bp_change() -> None:
    assert bp_change(Huf(100_000), Huf(80_000)) == -2_000
    assert bp_change(Huf(3), Huf(2)) == -3_333
    with pytest.raises(ValueError):
        bp_change(Huf(0), Huf(1))
