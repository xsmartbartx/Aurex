"""Time-series calculations: resampling, returns, indicators, volatility, drawdown, correlation."""

import math
from collections.abc import Sequence
from datetime import date, datetime
from typing import Any

import numpy as np

from core.errors import ValidationFailure

TRADING_DAYS = 252
PERIODS_PER_YEAR = {"D": 365, "B": TRADING_DAYS, "W": 52, "M": 12, "Q": 4, "A": 1}


def _bucket(moment: datetime | date, interval: str) -> tuple:
    if interval == "1W":
        iso = moment.isocalendar()
        return (iso[0], iso[1])
    if interval == "1M":
        return (moment.year, moment.month)
    if interval == "3M":
        return (moment.year, (moment.month - 1) // 3)
    if interval == "1Y":
        return (moment.year,)
    raise ValidationFailure("Unsupported interval", details={"interval": interval})


def resample(points: Sequence[dict[str, Any]], interval: str) -> list[dict[str, Any]]:
    """Aggregate points ``{t, v, o, h, l, vol}`` to a coarser interval. The bar carries the last timestamp."""
    if interval in ("1D", "", None):
        return list(points)
    bars: list[dict[str, Any]] = []
    current_key = None
    for p in points:
        key = _bucket(p["t"], interval)
        value = p["v"]
        if key != current_key:
            current_key = key
            bars.append(
                {
                    **p,
                    "o": p.get("o") if p.get("o") is not None else value,
                    "h": p.get("h") if p.get("h") is not None else value,
                    "l": p.get("l") if p.get("l") is not None else value,
                    "vol": p.get("vol"),
                }
            )
            continue
        bar = bars[-1]
        bar["t"], bar["v"] = p["t"], value
        bar["h"] = max(bar["h"], p.get("h") if p.get("h") is not None else value)
        bar["l"] = min(bar["l"], p.get("l") if p.get("l") is not None else value)
        if p.get("vol") is not None:
            bar["vol"] = (bar["vol"] or 0) + p["vol"]
        if p.get("q") in ("suspect", "estimated"):
            bar["q"] = p["q"]
        bar["known_at"] = p.get("known_at")
    return bars


def simple_returns(values: Sequence[float]) -> np.ndarray:
    array = np.asarray(values, dtype=float)
    if array.size < 2:
        return np.array([])
    with np.errstate(divide="ignore", invalid="ignore"):
        return array[1:] / array[:-1] - 1


def sma(values: Sequence[float], window: int) -> list[float | None]:
    array = np.asarray(values, dtype=float)
    out: list[float | None] = [None] * len(array)
    if window < 1 or len(array) < window:
        return out
    sums = np.cumsum(np.insert(array, 0, 0.0))
    means = (sums[window:] - sums[:-window]) / window
    out[window - 1 :] = [float(x) for x in means]
    return out


def ema(values: Sequence[float], window: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    if window < 1 or len(values) < window:
        return out
    alpha = 2 / (window + 1)
    level = float(np.mean(values[:window]))
    out[window - 1] = level
    for i in range(window, len(values)):
        level = alpha * values[i] + (1 - alpha) * level
        out[i] = level
    return out


def rsi(values: Sequence[float], window: int = 14) -> list[float | None]:
    """Relative strength index with Wilder smoothing."""
    out: list[float | None] = [None] * len(values)
    if len(values) <= window:
        return out
    deltas = np.diff(np.asarray(values, dtype=float))
    gain = float(np.mean(np.clip(deltas[:window], 0, None)))
    loss = float(np.mean(np.clip(-deltas[:window], 0, None)))
    out[window] = 100.0 if loss == 0 else 100 - 100 / (1 + gain / loss)
    for i in range(window, len(deltas)):
        gain = (gain * (window - 1) + max(deltas[i], 0)) / window
        loss = (loss * (window - 1) + max(-deltas[i], 0)) / window
        out[i + 1] = 100.0 if loss == 0 else 100 - 100 / (1 + gain / loss)
    return out


def bollinger(
    values: Sequence[float], window: int = 20, width: float = 2.0
) -> tuple[list[float | None], list[float | None]]:
    array = np.asarray(values, dtype=float)
    upper: list[float | None] = [None] * len(array)
    lower: list[float | None] = [None] * len(array)
    for i in range(window - 1, len(array)):
        chunk = array[i - window + 1 : i + 1]
        mean, deviation = float(chunk.mean()), float(chunk.std(ddof=0))
        upper[i], lower[i] = mean + width * deviation, mean - width * deviation
    return upper, lower


def annualized_volatility(values: Sequence[float], frequency: str = "B") -> float | None:
    returns = simple_returns(values)
    returns = returns[np.isfinite(returns)]
    if returns.size < 2:
        return None
    return float(returns.std(ddof=1) * math.sqrt(PERIODS_PER_YEAR.get(frequency, TRADING_DAYS)))


def total_return(values: Sequence[float]) -> float | None:
    if len(values) < 2 or not values[0]:
        return None
    return float(values[-1] / values[0] - 1)


def cagr(values: Sequence[float], dates: Sequence[date]) -> float | None:
    if len(values) < 2 or values[0] <= 0 or values[-1] <= 0:
        return None
    years = (dates[-1] - dates[0]).days / 365.25
    if years <= 0:
        return None
    return float((values[-1] / values[0]) ** (1 / years) - 1)


def max_drawdown(values: Sequence[float]) -> dict[str, Any]:
    """Largest peak-to-trough decline. Returns the depth and the indexes of the peak and the trough."""
    if len(values) < 2:
        return {"depth": None, "peak": None, "trough": None}
    array = np.asarray(values, dtype=float)
    peaks = np.maximum.accumulate(array)
    drawdowns = array / peaks - 1
    trough = int(np.argmin(drawdowns))
    peak = int(np.argmax(array[: trough + 1]))
    return {"depth": float(drawdowns[trough]), "peak": peak, "trough": trough}


def drawdown_series(values: Sequence[float]) -> list[float]:
    array = np.asarray(values, dtype=float)
    if array.size == 0:
        return []
    return [float(x) for x in array / np.maximum.accumulate(array) - 1]


def sharpe(values: Sequence[float], frequency: str = "B", risk_free: float = 0.0) -> float | None:
    returns = simple_returns(values)
    returns = returns[np.isfinite(returns)]
    if returns.size < 2:
        return None
    periods = PERIODS_PER_YEAR.get(frequency, TRADING_DAYS)
    deviation = returns.std(ddof=1)
    if deviation == 0:
        return None
    return float((returns.mean() - risk_free / periods) / deviation * math.sqrt(periods))


def align(series: dict[str, Sequence[tuple[date, float]]]) -> tuple[list[date], dict[str, list[float]]]:
    """Keep the dates on which every series has a value (inner join). No value is carried forward."""
    if not series:
        return [], {}
    common = set.intersection(*(set(d for d, _ in points) for points in series.values()))
    dates = sorted(common)
    lookup = {name: dict(points) for name, points in series.items()}
    return dates, {name: [float(lookup[name][d]) for d in dates] for name in series}


def correlation_matrix(series: dict[str, Sequence[tuple[date, float]]]) -> dict[str, Any]:
    """Pearson correlation of simple returns on common dates."""
    dates, values = align(series)
    names = list(values)
    if len(dates) < 3:
        return {"names": names, "matrix": [], "observations": len(dates), "start": None, "end": None}
    returns = np.array([simple_returns(values[n]) for n in names])
    returns = returns[:, np.all(np.isfinite(returns), axis=0)]
    with np.errstate(divide="ignore", invalid="ignore"):
        matrix = np.corrcoef(returns)
    matrix = np.atleast_2d(matrix)
    cells = [[None if not math.isfinite(x) else round(float(x), 4) for x in row] for row in matrix]
    return {
        "names": names,
        "matrix": cells,
        "observations": int(returns.shape[1]),
        "start": dates[0].isoformat(),
        "end": dates[-1].isoformat(),
    }


def summary(values: Sequence[float], dates: Sequence[date], frequency: str = "B") -> dict[str, Any]:
    drawdown = max_drawdown(values)
    return {
        "observations": len(values),
        "start": dates[0].isoformat() if dates else None,
        "end": dates[-1].isoformat() if dates else None,
        "first": float(values[0]) if len(values) else None,
        "last": float(values[-1]) if len(values) else None,
        "total_return": total_return(values),
        "cagr": cagr(values, dates),
        "volatility": annualized_volatility(values, frequency),
        "sharpe": sharpe(values, frequency),
        "max_drawdown": drawdown["depth"],
        "max_drawdown_peak": dates[drawdown["peak"]].isoformat() if drawdown["peak"] is not None else None,
        "max_drawdown_trough": dates[drawdown["trough"]].isoformat() if drawdown["trough"] is not None else None,
        "high": float(max(values)) if len(values) else None,
        "low": float(min(values)) if len(values) else None,
    }


INDICATORS = {"sma", "ema", "rsi", "bollinger"}


def indicator(kind: str, values: Sequence[float], window: int) -> dict[str, list[float | None]]:
    """Declarative indicators (ADR-0009): a definition evaluated by the engine, never user code."""
    if kind not in INDICATORS:
        raise ValidationFailure("Unknown indicator", details={"allowed": sorted(INDICATORS)})
    if not 2 <= window <= 400:
        raise ValidationFailure("Indicator window must be between 2 and 400")
    if kind == "sma":
        return {"value": sma(values, window)}
    if kind == "ema":
        return {"value": ema(values, window)}
    if kind == "rsi":
        return {"value": rsi(values, window)}
    upper, lower = bollinger(values, window)
    return {"upper": upper, "lower": lower, "middle": sma(values, window)}
