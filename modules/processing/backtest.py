"""Backtests with explicit costs and latency, using only data known at each simulated time.

Rules (section 3.2): a backtest does not run without cost and latency assumptions; a decision taken on
day t sees only observations published by the end of day t; it is executed at the close `latency` trading
days later; results are reported in and out of sample. Strategies are declarative definitions evaluated
here, never user code (ADR-0009).
"""

import bisect
import math
import random
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from core.errors import ValidationFailure
from modules.processing import ENGINE_VERSION
from modules.processing import series as calc

STRATEGIES = {
    "buy_and_hold": {"label": "Buy and hold", "params": {}},
    "sma_cross": {"label": "Moving-average crossover", "params": {"fast": (2, 200), "slow": (5, 400)}},
    "momentum": {"label": "Time-series momentum", "params": {"lookback": (5, 400), "threshold_pct": (-50, 50)}},
    "rsi_reversion": {
        "label": "RSI mean reversion",
        "params": {"window": (2, 100), "enter_below": (1, 50), "exit_above": (50, 99)},
    },
}


@dataclass(frozen=True)
class Version:
    ref: date
    known_at: datetime
    value: float


class PointInTime:
    """The series as it was known at each moment: revisions become visible only after they were published."""

    def __init__(self, versions: Sequence[Version]) -> None:
        self._pending = sorted(versions, key=lambda v: (v.known_at, v.ref))
        self._next = 0
        self.refs: list[date] = []
        self.values: list[float] = []

    def advance(self, moment: datetime) -> None:
        while self._next < len(self._pending) and self._pending[self._next].known_at <= moment:
            version = self._pending[self._next]
            index = bisect.bisect_left(self.refs, version.ref)
            if index < len(self.refs) and self.refs[index] == version.ref:
                self.values[index] = version.value  # a revision replaces what was known before
            else:
                self.refs.insert(index, version.ref)
                self.values.insert(index, version.value)
            self._next += 1


def _end_of(day: date) -> datetime:
    return datetime.combine(day, time(23, 59, 59), tzinfo=UTC)


def _signal(kind: str, params: dict[str, float], values: list[float], current: float) -> float:
    """Target exposure (0 or 1) from the values visible at the decision time."""
    if kind == "buy_and_hold":
        return 1.0
    if kind == "sma_cross":
        fast, slow = int(params["fast"]), int(params["slow"])
        if len(values) < slow:
            return 0.0
        return 1.0 if sum(values[-fast:]) / fast > sum(values[-slow:]) / slow else 0.0
    if kind == "momentum":
        lookback = int(params["lookback"])
        if len(values) <= lookback or values[-lookback - 1] <= 0:
            return 0.0
        change = (values[-1] / values[-lookback - 1] - 1) * 100
        return 1.0 if change > params.get("threshold_pct", 0.0) else 0.0
    if kind == "rsi_reversion":
        window = int(params["window"])
        rsi = calc.rsi(values[-(window * 4 + 1) :], window)[-1] if len(values) > window else None
        if rsi is None:
            return current
        if rsi < params["enter_below"]:
            return 1.0
        if rsi > params["exit_above"]:
            return 0.0
        return current
    raise ValidationFailure("Unknown strategy", details={"allowed": sorted(STRATEGIES)})


def validate_spec(spec: dict[str, Any]) -> None:
    kind = spec.get("strategy")
    if kind not in STRATEGIES:
        raise ValidationFailure("Unknown strategy", details={"allowed": sorted(STRATEGIES)})
    for name, (low, high) in STRATEGIES[kind]["params"].items():
        value = spec.get("params", {}).get(name)
        if value is None or not low <= float(value) <= high:
            raise ValidationFailure(f"Parameter '{name}' must be between {low} and {high}")
    if kind == "sma_cross" and spec["params"]["fast"] >= spec["params"]["slow"]:
        raise ValidationFailure("The fast average must be shorter than the slow one")
    for name, low, high in (("cost_bps", 0, 500), ("slippage_bps", 0, 500), ("latency_days", 1, 10)):
        if spec.get(name) is None:
            raise ValidationFailure(f"A backtest needs an explicit '{name}' assumption")
        if not low <= float(spec[name]) <= high:
            raise ValidationFailure(f"'{name}' must be between {low} and {high}")


def _metrics(days: Sequence[date], equity: Sequence[float], frequency: str = "B") -> dict[str, Any]:
    if len(equity) < 2:
        return {"observations": len(equity)}
    summary = calc.summary(list(equity), list(days), frequency)
    return {
        k: summary[k]
        for k in ("observations", "start", "end", "total_return", "cagr", "volatility", "sharpe", "max_drawdown")
    }


def run(
    spec: dict[str, Any], versions: Sequence[Version], *, start: date, end: date, initial_capital: float = 100_000.0
) -> dict[str, Any]:
    """Simulate one long-or-flat strategy on one instrument."""
    validate_spec(spec)
    final: dict[date, float] = {}
    for version in sorted(versions, key=lambda v: v.known_at):
        final[version.ref] = version.value  # the last version is the price a trade was actually filled at
    days = [d for d in sorted(final) if start <= d <= end]
    if len(days) < 30:
        raise ValidationFailure("At least 30 trading days are needed in the chosen period")
    view = PointInTime(versions)
    cost = (float(spec["cost_bps"]) + float(spec["slippage_bps"])) / 10_000
    latency = int(spec["latency_days"])
    cash, units, exposure_target = initial_capital, 0.0, 0.0
    pending: list[tuple[int, float]] = []  # (execution index, target exposure)
    equity, trades, costs, turnover, exposure_days = [], [], 0.0, 0.0, 0
    for index, day in enumerate(days):
        price = final[day]
        # Orders decided `latency` days ago are filled at today's close.
        while pending and pending[0][0] <= index:
            _, target = pending.pop(0)
            value = cash + units * price
            target_units = (value * target) / price if price > 0 else 0.0
            if target_units > units:  # buying: size so that costs are paid from the same value
                target_units = units + (target_units - units) / (1 + cost)
            traded = target_units - units
            if abs(traded) > 1e-12:
                notional = abs(traded) * price
                fee = notional * cost
                cash -= traded * price + fee
                units = target_units
                costs += fee
                turnover += notional
                trades.append(
                    {
                        "date": day.isoformat(),
                        "side": "buy" if traded > 0 else "sell",
                        "price": price,
                        "units": abs(traded),
                        "cost": fee,
                    }
                )
        value = cash + units * price
        equity.append(value)
        exposure_days += units > 0
        # Decide after the close with what was published by then.
        view.advance(_end_of(day))
        signal = _signal(spec["strategy"], spec.get("params", {}), view.values, exposure_target)
        if signal != exposure_target:
            exposure_target = signal
            if index + latency < len(days):
                pending.append((index + latency, signal))
    split = spec.get("in_sample_end")
    split_day = date.fromisoformat(split) if split else days[int(len(days) * 0.7)]
    cut = bisect.bisect_right(days, split_day)
    bench = [initial_capital * (1 - cost) * final[d] / final[days[0]] for d in days]
    result = {
        "engine_version": ENGINE_VERSION,
        "strategy": spec["strategy"],
        "label": STRATEGIES[spec["strategy"]]["label"],
        "assumptions": {
            "cost_bps": spec["cost_bps"],
            "slippage_bps": spec["slippage_bps"],
            "latency_days": latency,
            "initial_capital": initial_capital,
            "execution": f"filled at the close {latency} trading day(s) after the decision",
            "information": "each decision sees only observations published by the end of its day",
        },
        "metrics": _metrics(days, equity),
        "benchmark": _metrics(days, bench),
        "in_sample": _metrics(days[:cut], equity[:cut]),
        "out_of_sample": _metrics(days[cut:], equity[cut:]),
        "split_date": split_day.isoformat(),
        "trades": trades[-500:],
        "trade_count": len(trades),
        "total_costs": costs,
        "turnover": turnover / initial_capital,
        "time_in_market": exposure_days / len(days),
    }
    step = max(1, len(days) // 800)
    result["curve"] = [
        {"t": d.isoformat(), "equity": e, "benchmark": b}
        for d, e, b in list(zip(days, equity, bench, strict=True))[::step]
    ]
    if result["curve"][-1]["t"] != days[-1].isoformat():
        result["curve"].append({"t": days[-1].isoformat(), "equity": equity[-1], "benchmark": bench[-1]})
    return result


def monte_carlo(
    returns: Sequence[float], *, horizon: int, paths: int, method: str, seed: int, start_value: float = 100.0
) -> dict[str, Any]:
    """Distribution of future values from historical daily returns (bootstrap or normal). Seeded, so reproducible."""
    clean = [r for r in returns if math.isfinite(r)]
    if len(clean) < 60:
        raise ValidationFailure("At least 60 historical returns are needed")
    if not 1 <= horizon <= 756 or not 100 <= paths <= 20_000:
        raise ValidationFailure("Horizon is 1 to 756 trading days and paths 100 to 20,000")
    rng = random.Random(seed)  # noqa: S311 - simulation, not security
    mean = sum(clean) / len(clean)
    deviation = math.sqrt(sum((r - mean) ** 2 for r in clean) / (len(clean) - 1))
    checkpoints = sorted({max(1, round(horizon * k / 40)) for k in range(1, 41)})
    at_checkpoint: dict[int, list[float]] = {c: [] for c in checkpoints}
    terminal = []
    for _ in range(paths):
        value = start_value
        for step in range(1, horizon + 1):
            r = rng.choice(clean) if method == "bootstrap" else rng.gauss(mean, deviation)
            value *= 1 + r
            if step in at_checkpoint:
                at_checkpoint[step].append(value)
        terminal.append(value)

    def pct(values: list[float], q: float) -> float:
        ordered = sorted(values)
        return ordered[min(len(ordered) - 1, max(0, int(q * (len(ordered) - 1))))]

    returns_terminal = sorted(v / start_value - 1 for v in terminal)
    var_index = int(0.05 * (len(returns_terminal) - 1))
    tail = returns_terminal[: var_index + 1]
    return {
        "engine_version": ENGINE_VERSION,
        "method": method,
        "seed": seed,
        "paths": paths,
        "horizon": horizon,
        "history": {"observations": len(clean), "mean_daily": mean, "volatility_daily": deviation},
        "fan": [
            {"step": c, **{f"p{int(q * 100)}": pct(at_checkpoint[c], q) for q in (0.05, 0.25, 0.5, 0.75, 0.95)}}
            for c in checkpoints
        ],
        "terminal": {
            "p5": pct(terminal, 0.05),
            "p50": pct(terminal, 0.5),
            "p95": pct(terminal, 0.95),
            "mean": sum(terminal) / len(terminal),
            "probability_of_loss": sum(1 for v in terminal if v < start_value) / len(terminal),
            "var_95": -returns_terminal[var_index] * 100,
            "expected_shortfall_95": -sum(tail) / len(tail) * 100,
        },
        "label": "Simulated from historical returns. A range of outcomes under stated assumptions, not a forecast.",
    }


def business_days_after(day: date, count: int) -> date:
    while count > 0:
        day += timedelta(days=1)
        if day.weekday() < 5:
            count -= 1
    return day
