"""Backtest integrity: point-in-time access, mandatory costs, reproduction. Simulations are seeded."""

from datetime import UTC, date, datetime, time, timedelta

import pytest

from core.errors import ValidationFailure
from modules.processing import backtest as bt


def versions(values, start=date(2023, 1, 2), lag=timedelta(hours=20)):
    out, day = [], start
    for value in values:
        while day.weekday() >= 5:
            day += timedelta(days=1)
        out.append(bt.Version(day, datetime.combine(day, time(0), tzinfo=UTC) + lag, float(value)))
        day += timedelta(days=1)
    return out


SPEC = {"strategy": "buy_and_hold", "params": {}, "cost_bps": 10, "slippage_bps": 5, "latency_days": 1}


def test_costs_and_latency_are_mandatory():
    for missing in ("cost_bps", "slippage_bps", "latency_days"):
        with pytest.raises(ValidationFailure):
            bt.validate_spec({k: v for k, v in SPEC.items() if k != missing})
    with pytest.raises(ValidationFailure):
        bt.validate_spec({**SPEC, "latency_days": 0})  # same-close execution is not allowed


def test_buy_and_hold_reference():
    data = versions([100 + i for i in range(60)])
    result = bt.run(SPEC, data, start=data[0].ref, end=data[-1].ref, initial_capital=10_000)
    # Decided on day 1, filled at day 2's close (101) with 15 bp of cost; held to 159.
    units = 10_000 / 101 / (1 + 0.0015)
    expected = units * 159 + (10_000 - units * 101 * (1 + 0.0015))
    assert result["curve"][-1]["equity"] == pytest.approx(expected)
    assert result["trade_count"] == 1 and result["total_costs"] == pytest.approx(units * 101 * 0.0015)


def test_decisions_see_only_published_data():
    """A value published late cannot drive an earlier decision (no look-ahead)."""
    calm = [100.0] * 80
    data = versions(calm)
    spike_day = data[50].ref
    late = [
        bt.Version(
            v.ref,
            v.known_at + (timedelta(days=30) if v.ref == spike_day else timedelta()),
            200.0 if v.ref == spike_day else v.value,
        )
        for v in data
    ]
    spec = {**SPEC, "strategy": "momentum", "params": {"lookback": 5, "threshold_pct": 50}}
    result = bt.run(spec, late, start=data[0].ref, end=data[-1].ref)
    trade_days = [t["date"] for t in result["trades"]]
    assert all(date.fromisoformat(d) >= spike_day + timedelta(days=30) for d in trade_days)


def test_revisions_become_visible_only_after_publication():
    view = bt.PointInTime(
        [
            bt.Version(date(2024, 1, 1), datetime(2024, 1, 2, tzinfo=UTC), 1.0),
            bt.Version(date(2024, 1, 1), datetime(2024, 3, 1, tzinfo=UTC), 2.0),
        ]
    )
    view.advance(datetime(2024, 2, 1, tzinfo=UTC))
    assert view.values == [1.0]
    view.advance(datetime(2024, 3, 2, tzinfo=UTC))
    assert view.values == [2.0]


def test_monte_carlo_is_seeded():
    returns = [0.001 * ((i % 7) - 3) for i in range(300)]
    a = bt.monte_carlo(returns, horizon=20, paths=200, method="bootstrap", seed=7)
    b = bt.monte_carlo(returns, horizon=20, paths=200, method="bootstrap", seed=7)
    assert a["terminal"] == b["terminal"] and a["terminal"]["p5"] <= a["terminal"]["p50"] <= a["terminal"]["p95"]
    assert a["label"].endswith("not a forecast.")


def test_backtest_api_records_variants_and_reproduces(make_account):
    account = make_account(plan="quant")
    end = date.today() - timedelta(days=3)
    body = {
        "symbol": "ORCA.DEMO",
        "strategy": "sma_cross",
        "params": {"fast": 20, "slow": 100},
        "start": (end - timedelta(days=900)).isoformat(),
        "end": end.isoformat(),
        "cost_bps": 10,
        "slippage_bps": 5,
        "latency_days": 1,
    }
    first = account.post("/quant/backtests", body)
    assert first.status_code == 201, first.text
    run = first.json()
    assert run["result"]["variants_tried"] == 1 and run["result"]["out_of_sample"]["observations"] > 50
    assert run["result"]["data"]["license_class"] == "demonstration"
    for fast in (10, 15, 25, 30, 35):
        account.post("/quant/backtests", {**body, "params": {"fast": fast, "slow": 100}})
    latest = account.post("/quant/backtests", {**body, "params": {"fast": 40, "slow": 100}}).json()
    assert latest["result"]["variants_tried"] == 7 and any("variants" in w for w in latest["result"]["warnings"])
    assert account.post(f"/quant/runs/{run['id']}/reproduce").json()["identical"] is True
    assert account.post("/quant/backtests", {k: v for k, v in body.items() if k != "cost_bps"}).status_code == 422
    assert make_account(plan="pro").post("/quant/backtests", body).status_code == 403


def test_simulation_api(make_account):
    account = make_account(plan="pro")
    result = account.post("/quant/simulations", {"symbol": "EURUSD", "horizon": 60, "paths": 300, "seed": 1})
    assert result.status_code == 201, result.text
    assert result.json()["result"]["terminal"]["p50"] > 0
    assert account.post("/quant/simulations", {"horizon": 60}).status_code == 422
