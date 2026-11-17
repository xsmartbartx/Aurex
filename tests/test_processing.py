"""Financial engine against independently computed reference values."""

from datetime import date, datetime
from decimal import Decimal

import pytest

from core.errors import ValidationFailure
from modules.processing import fundamentals as fnd
from modules.processing import series as calc

PRICES = [100.0, 102.0, 101.0, 105.0, 103.0, 108.0, 110.0, 107.0, 111.0, 115.0]


def test_returns_and_total_return():
    returns = calc.simple_returns(PRICES)
    assert returns[0] == pytest.approx(0.02)
    assert calc.total_return(PRICES) == pytest.approx(0.15)
    # Aggregation invariant: compounding period returns reproduces the total return.
    compounded = 1.0
    for r in returns:
        compounded *= 1 + r
    assert compounded - 1 == pytest.approx(calc.total_return(PRICES))


def test_moving_averages_reference_values():
    assert calc.sma(PRICES, 3)[:4] == [None, None, pytest.approx(101.0), pytest.approx(308 / 3)]
    ema = calc.ema(PRICES, 3)
    assert ema[2] == pytest.approx(101.0)
    assert ema[3] == pytest.approx(0.5 * 105 + 0.5 * 101)


def test_rsi_bounds_and_monotonic_series():
    assert calc.rsi([float(i) for i in range(1, 30)], 14)[-1] == 100.0
    values = calc.rsi(PRICES + PRICES[::-1], 5)
    assert all(v is None or 0 <= v <= 100 for v in values)


def test_volatility_reference():
    # Returns of [100, 110, 99]: +10%, -10%; sample standard deviation = 0.141421...
    assert calc.annualized_volatility([100, 110, 99], "A") == pytest.approx(0.1414213562, rel=1e-6)


def test_max_drawdown_reference():
    result = calc.max_drawdown([100, 120, 90, 95, 130, 117])
    assert result["depth"] == pytest.approx(-0.25)
    assert (result["peak"], result["trough"]) == (1, 2)
    assert calc.drawdown_series([100, 120, 90])[-1] == pytest.approx(-0.25)


def test_cagr_reference():
    assert calc.cagr([100, 121], [date(2020, 1, 1), date(2022, 1, 1)]) == pytest.approx(0.1, abs=2e-4)


def test_correlation_uses_common_dates_only():
    a = [(date(2024, 1, d), float(v)) for d, v in zip(range(1, 7), [10, 11, 12, 11, 13, 14], strict=True)]
    b = [(d, v * 2) for d, v in a]
    c = [(d, 100 - v) for d, v in a[:-1]]  # one date missing
    result = calc.correlation_matrix({"A": a, "B": b, "C": c})
    assert result["observations"] == 4
    assert result["matrix"][0][1] == pytest.approx(1.0)
    assert result["matrix"][0][2] < 0


def test_resample_weekly_ohlc():
    points = [
        {"t": datetime(2024, 1, d), "v": float(v), "o": None, "h": None, "l": None, "vol": 10.0}
        for d, v in [(1, 10), (2, 12), (3, 9), (8, 11), (9, 14)]
    ]
    bars = calc.resample(points, "1W")
    assert len(bars) == 2
    assert (bars[0]["o"], bars[0]["h"], bars[0]["l"], bars[0]["v"], bars[0]["vol"]) == (10, 12, 9, 9, 30)
    assert bars[1]["t"] == datetime(2024, 1, 9)


def test_indicator_rejects_unknown_definition():
    with pytest.raises(ValidationFailure):
        calc.indicator("exec", PRICES, 5)
    with pytest.raises(ValidationFailure):
        calc.indicator("sma", PRICES, 100000)


def _fact(i, concept, value, start, end, filed="2025-02-01", accession="A-1"):
    return {
        "id": i,
        "concept": concept,
        "unit": "USD",
        "value": Decimal(value),
        "period_start": date.fromisoformat(start) if start else None,
        "period_end": date.fromisoformat(end),
        "accession": accession,
        "filed_at": date.fromisoformat(filed),
    }


FACTS = [
    _fact(1, "Revenues", "1000", "2024-01-01", "2024-12-31"),
    _fact(2, "Revenues", "800", "2023-01-01", "2023-12-31"),
    _fact(3, "NetIncomeLoss", "150", "2024-01-01", "2024-12-31"),
    _fact(4, "OperatingIncomeLoss", "200", "2024-01-01", "2024-12-31"),
    _fact(5, "InterestExpense", "25", "2024-01-01", "2024-12-31"),
    _fact(6, "NetCashProvidedByUsedInOperatingActivities", "260", "2024-01-01", "2024-12-31"),
    _fact(7, "PaymentsToAcquirePropertyPlantAndEquipment", "60", "2024-01-01", "2024-12-31"),
    _fact(8, "StockholdersEquity", "500", None, "2024-12-31"),
    _fact(9, "LongTermDebtNoncurrent", "300", None, "2024-12-31"),
    _fact(10, "LongTermDebtCurrent", "100", None, "2024-12-31"),
    _fact(11, "CashAndCashEquivalentsAtCarryingValue", "90", None, "2024-12-31"),
    _fact(12, "Revenues", "260", "2024-10-01", "2024-12-31"),  # a quarter must not be read as a year
]


def test_fundamental_ratios_reference_values():
    analysis = fnd.analyze(FACTS)
    year = analysis["years"][0]
    assert year["fiscal_year"] == 2024 and year["items"]["revenue"]["value"] == Decimal("1000")
    ratios = year["ratios"]
    assert ratios["revenue_growth"].output == pytest.approx(25.0)
    assert ratios["net_margin"].output == pytest.approx(15.0)
    assert ratios["operating_margin"].output == pytest.approx(20.0)
    assert ratios["free_cash_flow"].output == pytest.approx(200.0)
    assert ratios["debt_to_equity"].output == pytest.approx(0.8)
    assert ratios["net_debt"].output == pytest.approx(310.0)
    assert ratios["interest_coverage"].output == pytest.approx(8.0)
    assert ratios["return_on_equity"].output == pytest.approx(30.0)


def test_every_ratio_names_its_inputs_and_gaps_are_reported():
    analysis = fnd.analyze(FACTS)
    for ratio in analysis["years"][0]["ratios"].values():
        assert ratio.inputs and all("fact_id" in ref for ref in ratio.inputs.values())
        assert ratio.version
    assert "gross_profit" in analysis["missing"]  # not reported, so no gross margin is invented
    assert "gross_margin" not in analysis["years"][0]["ratios"]
