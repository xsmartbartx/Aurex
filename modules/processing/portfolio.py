"""Portfolio calculations: holdings, valuation in a base currency, time-weighted return, exposures,
concentration and scenario impact. Pure functions over values passed in by the caller.
"""

import bisect
import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from core.errors import ValidationFailure
from modules.processing import ENGINE_VERSION

CASH_TYPES = {"deposit", "withdrawal", "dividend", "fee", "interest"}
TRADE_TYPES = {"buy", "sell"}
EXTERNAL_FLOWS = {"deposit", "withdrawal"}


@dataclass(frozen=True)
class Txn:
    day: date
    type: str
    instrument: str | None  # instrument key (symbol); None for pure cash movements
    quantity: Decimal
    price: Decimal
    fees: Decimal
    currency: str


@dataclass
class Position:
    instrument: str
    quantity: Decimal = Decimal(0)
    cost: Decimal = Decimal(0)  # average-cost basis, in the trade currency
    currency: str = ""
    realized: Decimal = Decimal(0)


@dataclass
class Book:
    positions: dict[str, Position] = field(default_factory=dict)
    cash: dict[str, Decimal] = field(default_factory=lambda: defaultdict(Decimal))


def apply(book: Book, txn: Txn) -> None:
    """Apply one transaction with average-cost accounting. Selling more than is held is an error."""
    if txn.type in TRADE_TYPES:
        if not txn.instrument or txn.quantity <= 0 or txn.price < 0:
            raise ValidationFailure("A trade needs an instrument, a positive quantity and a price")
        position = book.positions.setdefault(txn.instrument, Position(txn.instrument, currency=txn.currency))
        if position.currency and position.currency != txn.currency:
            raise ValidationFailure(
                "All trades in one instrument must use the same currency", details={"instrument": txn.instrument}
            )
        position.currency = txn.currency
        gross = txn.quantity * txn.price
        if txn.type == "buy":
            position.cost += gross + txn.fees
            position.quantity += txn.quantity
            book.cash[txn.currency] -= gross + txn.fees
        else:
            if txn.quantity > position.quantity:
                raise ValidationFailure(
                    "A sale exceeds the quantity held",
                    details={"instrument": txn.instrument, "date": txn.day.isoformat()},
                )
            average = position.cost / position.quantity
            position.realized += gross - txn.fees - average * txn.quantity
            position.cost -= average * txn.quantity
            position.quantity -= txn.quantity
            book.cash[txn.currency] += gross - txn.fees
            if position.quantity == 0:
                position.cost = Decimal(0)
    elif txn.type in ("deposit", "dividend", "interest"):
        book.cash[txn.currency] += cash_amount(txn)
    elif txn.type in ("withdrawal", "fee"):
        book.cash[txn.currency] -= cash_amount(txn)
    else:
        raise ValidationFailure("Unknown transaction type", details={"type": txn.type})


def cash_amount(txn: Txn) -> Decimal:
    """Cash transactions carry their amount in ``price``; ``quantity`` is 1."""
    return txn.price * (txn.quantity or Decimal(1))


class AsOf:
    """Last known value on or before a date (prices and FX are carried forward for valuation)."""

    def __init__(self, points: Sequence[tuple[date, float]]) -> None:
        self.dates = [d for d, _ in points]
        self.values = [v for _, v in points]

    def at(self, day: date) -> float | None:
        index = bisect.bisect_right(self.dates, day) - 1
        return self.values[index] if index >= 0 else None

    def first(self) -> date | None:
        return self.dates[0] if self.dates else None


def fx_factor(currency: str, base: str, day: date, fx: Mapping[str, AsOf]) -> float | None:
    """Units of ``base`` per unit of ``currency``. ECB rates are quoted as units of a currency per EUR."""
    if currency == base:
        return 1.0
    to_eur = 1.0 if currency == "EUR" else (1 / rate if (rate := _rate(fx, currency, day)) else None)
    from_eur = 1.0 if base == "EUR" else _rate(fx, base, day)
    if to_eur is None or from_eur is None:
        return None
    return to_eur * from_eur


def _rate(fx: Mapping[str, AsOf], currency: str, day: date) -> float | None:
    series = fx.get(currency)
    return series.at(day) if series else None


def _business_days(start: date, end: date) -> list[date]:
    days, day = [], start
    while day <= end:
        if day.weekday() < 5:
            days.append(day)
        day += timedelta(days=1)
    return days


def valuation(
    txns: Sequence[Txn], prices: Mapping[str, AsOf], fx: Mapping[str, AsOf], base: str, end: date
) -> dict[str, Any]:
    """Daily value in the base currency and the time-weighted return index.

    Positions without a price are valued at cost and reported. A missing FX rate stops the calculation
    for that day rather than guessing.
    """
    if not txns:
        return {"days": [], "values": [], "flows": [], "index": [], "unpriced": [], "missing_fx": []}
    ordered = sorted(txns, key=lambda t: (t.day, t.type != "deposit"))
    book = Book()
    days = _business_days(ordered[0].day, end)
    if ordered[0].day.weekday() >= 5:
        days.insert(0, ordered[0].day)
    pointer = 0
    out_days, values, flows, index = [], [], [], []
    unpriced: set[str] = set()
    missing_fx: set[str] = set()
    level, previous = 100.0, None
    for day in days:
        flow = 0.0
        while pointer < len(ordered) and ordered[pointer].day <= day:
            txn = ordered[pointer]
            apply(book, txn)
            if txn.type in EXTERNAL_FLOWS:
                factor = fx_factor(txn.currency, base, day, fx)
                if factor is None:
                    missing_fx.add(txn.currency)
                    factor = 0.0
                amount = float(cash_amount(txn)) * factor
                flow += amount if txn.type == "deposit" else -amount
            pointer += 1
        total, complete = 0.0, True
        for position in book.positions.values():
            if position.quantity == 0:
                continue
            price = prices[position.instrument].at(day) if position.instrument in prices else None
            if price is None:
                unpriced.add(position.instrument)
                local = float(position.cost)
            else:
                local = float(position.quantity) * price
            factor = fx_factor(position.currency, base, day, fx)
            if factor is None:
                missing_fx.add(position.currency)
                complete = False
                continue
            total += local * factor
        for currency, amount in book.cash.items():
            factor = fx_factor(currency, base, day, fx)
            if factor is None:
                missing_fx.add(currency)
                complete = False
                continue
            total += float(amount) * factor
        if not complete:
            continue
        if previous is not None and previous > 0:
            level *= (total - flow) / previous
        out_days.append(day)
        values.append(total)
        flows.append(flow)
        index.append(level)
        previous = total
    return {
        "days": out_days,
        "values": values,
        "flows": flows,
        "index": index,
        "unpriced": sorted(unpriced),
        "missing_fx": sorted(missing_fx),
        "book": book,
        "engine_version": ENGINE_VERSION,
    }


def holdings_table(
    book: Book,
    prices: Mapping[str, AsOf],
    fx: Mapping[str, AsOf],
    base: str,
    day: date,
    meta: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Current positions with market value, weight and unrealized result, all in the base currency."""
    rows, total = [], 0.0
    for position in book.positions.values():
        if position.quantity == 0 and position.realized == 0:
            continue
        price = prices[position.instrument].at(day) if position.instrument in prices else None
        factor = fx_factor(position.currency, base, day, fx) or 0.0
        local = float(position.quantity) * price if price is not None else float(position.cost)
        value = local * factor
        cost = float(position.cost) * factor
        rows.append(
            {
                "instrument": position.instrument,
                "quantity": float(position.quantity),
                "currency": position.currency,
                "price": price,
                "priced": price is not None,
                "value": value,
                "cost": cost,
                "unrealized": value - cost if price is not None else 0.0,
                "unrealized_pct": (value / cost - 1) * 100 if cost and price is not None else None,
                "realized": float(position.realized) * factor,
                **dict(meta.get(position.instrument, {})),
            }
        )
        total += value if position.quantity else 0.0
    cash_rows = []
    for currency, amount in sorted(book.cash.items()):
        if amount == 0:
            continue
        factor = fx_factor(currency, base, day, fx) or 0.0
        cash_rows.append({"currency": currency, "amount": float(amount), "value": float(amount) * factor})
        total += float(amount) * factor
    for row in rows:
        row["weight"] = row["value"] / total * 100 if total and row["quantity"] else 0.0
    rows.sort(key=lambda r: -r["value"])
    return {"positions": rows, "cash": cash_rows, "total": total}


def exposures(
    positions: Sequence[Mapping[str, Any]], cash: Sequence[Mapping[str, Any]], total: float
) -> dict[str, Any]:
    """Weights by sector, currency and asset type, plus concentration measures."""
    groups: dict[str, dict[str, float]] = {
        "sector": defaultdict(float),
        "currency": defaultdict(float),
        "type": defaultdict(float),
    }
    for row in positions:
        if not row["quantity"]:
            continue
        groups["sector"][row.get("sector") or "Unclassified"] += row["value"]
        groups["currency"][row["currency"]] += row["value"]
        groups["type"][row.get("type") or "other"] += row["value"]
    for row in cash:
        groups["sector"]["Cash"] += row["value"]
        groups["currency"][row["currency"]] += row["value"]
        groups["type"]["cash"] += row["value"]
    out = {
        name: sorted(
            (
                {"name": key, "value": value, "weight": value / total * 100 if total else 0.0}
                for key, value in group.items()
            ),
            key=lambda r: -r["value"],
        )
        for name, group in groups.items()
    }
    weights = [row["value"] / total for row in positions if row["quantity"] and total]
    hhi = sum(w * w for w in weights)
    out["concentration"] = {
        "hhi": hhi,
        "effective_positions": 1 / hhi if hhi else None,
        "largest_weight": max(weights) * 100 if weights else None,
        "top5_weight": sum(sorted(weights, reverse=True)[:5]) * 100 if weights else None,
        "positions": len(weights),
        "definition": "Herfindahl-Hirschman index of position weights",
    }
    return out


def check_limits(
    positions: Sequence[Mapping[str, Any]], exposure: Mapping[str, Any], limits: Mapping[str, float]
) -> list[dict[str, Any]]:
    """Breaches of portfolio limits: largest position, sector weight, minimum cash."""
    breaches = []
    max_position = limits.get("max_position_pct")
    if max_position:
        for row in positions:
            if row.get("weight", 0) > max_position:
                breaches.append(
                    {
                        "limit": "max_position_pct",
                        "subject": row["instrument"],
                        "value": row["weight"],
                        "threshold": max_position,
                    }
                )
    max_sector = limits.get("max_sector_pct")
    if max_sector:
        for row in exposure.get("sector", []):
            if row["name"] != "Cash" and row["weight"] > max_sector:
                breaches.append(
                    {"limit": "max_sector_pct", "subject": row["name"], "value": row["weight"], "threshold": max_sector}
                )
    min_cash = limits.get("min_cash_pct")
    if min_cash is not None:
        cash = next((row["weight"] for row in exposure.get("type", []) if row["name"] == "cash"), 0.0)
        if cash < min_cash:
            breaches.append({"limit": "min_cash_pct", "subject": "cash", "value": cash, "threshold": min_cash})
    return breaches


def performance(days: Sequence[date], index: Sequence[float], benchmark: AsOf | None = None) -> dict[str, Any]:
    """Return, risk and benchmark-relative measures from a return index."""
    if len(index) < 2:
        return {"observations": len(index)}
    returns = [index[i] / index[i - 1] - 1 for i in range(1, len(index))]
    mean = sum(returns) / len(returns)
    variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1) if len(returns) > 1 else 0.0
    volatility = math.sqrt(variance) * math.sqrt(252)
    years = (days[-1] - days[0]).days / 365.25
    total = index[-1] / index[0] - 1
    peak, worst = index[0], 0.0
    for level in index:
        peak = max(peak, level)
        worst = min(worst, level / peak - 1)
    result: dict[str, Any] = {
        "observations": len(index),
        "start": days[0].isoformat(),
        "end": days[-1].isoformat(),
        "total_return": total * 100,
        "annualized_return": ((1 + total) ** (1 / years) - 1) * 100 if years > 0.25 and total > -1 else None,
        "volatility": volatility * 100,
        "max_drawdown": worst * 100,
        "sharpe": (mean / math.sqrt(variance) * math.sqrt(252)) if variance > 0 else None,
        "engine_version": ENGINE_VERSION,
        "method": "time-weighted return; external deposits and withdrawals are excluded",
    }
    if benchmark is not None:
        levels = [benchmark.at(day) for day in days]
        if all(level is not None for level in levels) and levels[0]:
            bench_returns = [levels[i] / levels[i - 1] - 1 for i in range(1, len(levels))]
            bench_total = levels[-1] / levels[0] - 1
            bench_mean = sum(bench_returns) / len(bench_returns)
            bench_var = sum((r - bench_mean) ** 2 for r in bench_returns) / max(len(bench_returns) - 1, 1)
            cov = sum((a - mean) * (b - bench_mean) for a, b in zip(returns, bench_returns, strict=True)) / max(
                len(returns) - 1, 1
            )
            result["benchmark"] = {
                "total_return": bench_total * 100,
                "excess_return": (total - bench_total) * 100,
                "beta": cov / bench_var if bench_var > 0 else None,
                "correlation": cov / math.sqrt(variance * bench_var) if variance > 0 and bench_var > 0 else None,
                "index": [level / levels[0] * 100 for level in levels],
            }
        else:
            result["benchmark"] = {"note": "The benchmark has no data for the whole period."}
    return result


SCENARIO_TARGETS = ("instrument", "sector", "type", "currency", "all")


def scenario(
    positions: Sequence[Mapping[str, Any]],
    cash: Sequence[Mapping[str, Any]],
    base: str,
    shocks: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Apply price shocks (most specific target wins) and currency shocks against the base currency.

    A scenario is a what-if calculation on current holdings, not a forecast.
    """

    def price_shock(row: Mapping[str, Any]) -> tuple[float, str]:
        for target in ("instrument", "sector", "type", "all"):
            for shock in shocks:
                if shock["target_type"] != target:
                    continue
                key = {
                    "instrument": row["instrument"],
                    "sector": row.get("sector"),
                    "type": row.get("type"),
                    "all": None,
                }[target]
                if target == "all" or str(shock.get("target", "")).lower() == str(key or "").lower():
                    return float(shock["shock_pct"]) / 100, f"{target}:{shock.get('target') or 'all'}"
        return 0.0, ""

    def currency_shock(currency: str) -> float:
        if currency == base:
            return 0.0
        for shock in shocks:
            if shock["target_type"] == "currency" and str(shock.get("target", "")).upper() == currency:
                return float(shock["shock_pct"]) / 100
        return 0.0

    rows, total_before, total_after = [], 0.0, 0.0
    for row in positions:
        if not row["quantity"]:
            continue
        p_shock, rule = price_shock(row)
        c_shock = currency_shock(row["currency"])
        after = row["value"] * (1 + p_shock) * (1 + c_shock)
        rows.append(
            {
                "instrument": row["instrument"],
                "before": row["value"],
                "after": after,
                "impact": after - row["value"],
                "price_shock_pct": p_shock * 100,
                "currency_shock_pct": c_shock * 100,
                "rule": rule,
            }
        )
        total_before += row["value"]
        total_after += after
    for row in cash:
        c_shock = currency_shock(row["currency"])
        after = row["value"] * (1 + c_shock)
        if c_shock:
            rows.append(
                {
                    "instrument": f"Cash {row['currency']}",
                    "before": row["value"],
                    "after": after,
                    "impact": after - row["value"],
                    "price_shock_pct": 0.0,
                    "currency_shock_pct": c_shock * 100,
                    "rule": f"currency:{row['currency']}",
                }
            )
        total_before += row["value"]
        total_after += after
    rows.sort(key=lambda r: r["impact"])
    return {
        "positions": rows,
        "before": total_before,
        "after": total_after,
        "impact": total_after - total_before,
        "impact_pct": (total_after / total_before - 1) * 100 if total_before else None,
        "engine_version": ENGINE_VERSION,
        "label": "Scenario on current holdings. Not a forecast.",
    }
