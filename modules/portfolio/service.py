"""AUREX Portfolio: virtual portfolios, transactions, imports, analytics, exposures, limits and scenarios.

No broker connection and no orders (ADR-0012). Every record is tenant-private and every change is audited.
"""

from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from core import entitlements as ent
from core.errors import AurexError, NotFound, ValidationFailure
from core.money import normalize_currency
from core.types import Role, Scope, utcnow
from modules.datalab import access
from modules.logging import record_audit
from modules.portfolio.models import Portfolio, Transaction
from modules.processing import portfolio as calc
from modules.validation import clean_text, parse_csv

TYPES = ("buy", "sell", "deposit", "withdrawal", "dividend", "fee", "interest")
BASES = ("EUR", "USD", "GBP", "CHF")
FX_PREFIX = "ECB:EXR:"
PRESETS: dict[str, dict[str, Any]] = {
    "equity_selloff": {
        "name": "Equity sell-off",
        "description": "All equities fall 20%.",
        "shocks": [{"target_type": "type", "target": "equity", "shock_pct": -20}],
    },
    "tech_correction": {
        "name": "Technology correction",
        "description": "Information technology falls 30%, other equities 10%.",
        "shocks": [
            {"target_type": "sector", "target": "Information Technology", "shock_pct": -30},
            {"target_type": "type", "target": "equity", "shock_pct": -10},
        ],
    },
    "dollar_weakens": {
        "name": "US dollar weakens 10%",
        "description": "USD assets lose 10% against the base.",
        "shocks": [{"target_type": "currency", "target": "USD", "shock_pct": -10}],
    },
    "rates_shock": {
        "name": "Rates up 100 bp",
        "description": "Rate-sensitive sectors fall: utilities and real estate 15%, other equities 5%, "
        "financials rise 3%.",
        "shocks": [
            {"target_type": "sector", "target": "Utilities", "shock_pct": -15},
            {"target_type": "sector", "target": "Real Estate", "shock_pct": -15},
            {"target_type": "sector", "target": "Financials", "shock_pct": 3},
            {"target_type": "type", "target": "equity", "shock_pct": -5},
        ],
    },
}


# --- Portfolios -----------------------------------------------------------------------------------


def _own(session: Session, scope: Scope, portfolio_id: UUID, *, write: bool = False) -> Portfolio:
    row = session.get(Portfolio, portfolio_id)
    if row is None or row.tenant_id != scope.tenant_id:
        raise NotFound("Portfolio not found")
    if row.user_id != scope.user_id and not scope.at_least(Role.ADMIN if write else Role.VIEWER):
        raise NotFound("Portfolio not found")
    if write:
        scope.require_role(Role.ANALYST)
    return row


def _view(row: Portfolio) -> dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name,
        "description": row.description,
        "base_currency": row.base_currency,
        "benchmark_series_id": row.benchmark_series_id,
        "limits": row.limits,
        "created_at": row.created_at,
    }


def list_portfolios(session: Session, scope: Scope) -> list[dict[str, Any]]:
    scope.require(ent.PORTFOLIO)
    rows = session.scalars(
        select(Portfolio).where(Portfolio.tenant_id == scope.tenant_id).order_by(Portfolio.created_at)
    )
    return [_view(r) | {"own": r.user_id == scope.user_id} for r in rows]


def create_portfolio(
    session: Session,
    scope: Scope,
    *,
    name: str,
    base_currency: str = "EUR",
    description: str = "",
    benchmark: str | None = None,
    limits: dict[str, float] | None = None,
) -> Portfolio:
    scope.require(ent.PORTFOLIO)
    scope.require_role(Role.ANALYST)
    count = session.scalar(select(func.count()).select_from(Portfolio).where(Portfolio.tenant_id == scope.tenant_id))
    scope.check_limit("portfolios", count)
    base = normalize_currency(base_currency)
    if base not in BASES:
        raise ValidationFailure("Base currency is not supported", details={"allowed": list(BASES)})
    row = Portfolio(
        tenant_id=scope.tenant_id,
        user_id=scope.user_id,
        name=clean_text(name, max_len=100),
        description=clean_text(description, max_len=1000),
        base_currency=base,
        benchmark_series_id=_benchmark(session, scope, benchmark),
        limits=_limits(limits or {}),
    )
    session.add(row)
    session.flush()
    record_audit(
        session,
        action="portfolio.created",
        tenant_id=scope.tenant_id,
        actor_id=scope.user_id,
        object_type="portfolio",
        object_id=row.id,
    )
    return row


def _benchmark(session: Session, scope: Scope, symbol: str | None) -> UUID | None:
    if not symbol:
        return None
    instrument = access.get_instrument(session, scope, symbol)
    return access.primary_series(session, scope, instrument.id).id


def _limits(limits: dict[str, Any]) -> dict[str, float]:
    allowed = {"max_position_pct", "max_sector_pct", "min_cash_pct"}
    out = {}
    for key, value in limits.items():
        if key not in allowed:
            raise ValidationFailure("Unknown portfolio limit", details={"allowed": sorted(allowed)})
        if value is None or value == "":
            continue
        number = float(value)
        if not 0 <= number <= 100:
            raise ValidationFailure("Limits are percentages between 0 and 100")
        out[key] = number
    return out


def update_portfolio(
    session: Session,
    scope: Scope,
    portfolio_id: UUID,
    *,
    name: str | None = None,
    description: str | None = None,
    benchmark: str | None = None,
    limits: dict[str, Any] | None = None,
) -> Portfolio:
    row = _own(session, scope, portfolio_id, write=True)
    if name:
        row.name = clean_text(name, max_len=100)
    if description is not None:
        row.description = clean_text(description, max_len=1000)
    if benchmark is not None:
        row.benchmark_series_id = _benchmark(session, scope, benchmark) if benchmark else None
    if limits is not None:
        row.limits = _limits(limits)
    record_audit(
        session,
        action="portfolio.updated",
        tenant_id=scope.tenant_id,
        actor_id=scope.user_id,
        object_type="portfolio",
        object_id=row.id,
    )
    return row


def delete_portfolio(session: Session, scope: Scope, portfolio_id: UUID) -> None:
    row = _own(session, scope, portfolio_id, write=True)
    session.delete(row)
    record_audit(
        session,
        action="portfolio.deleted",
        tenant_id=scope.tenant_id,
        actor_id=scope.user_id,
        object_type="portfolio",
        object_id=portfolio_id,
    )


# --- Transactions ---------------------------------------------------------------------------------


def _decimal(value: Any, field: str) -> Decimal:
    try:
        number = Decimal(str(value).replace(",", "").strip() or "0")
    except InvalidOperation as exc:
        raise ValidationFailure("Not a number", details={"field": field}) from exc
    if not number.is_finite() or abs(number) > Decimal("1e15"):
        raise ValidationFailure("Number out of range", details={"field": field})
    return number


def _normalize(session: Session, scope: Scope, item: dict[str, Any]) -> dict[str, Any]:
    kind = str(item.get("type", "")).strip().lower()
    if kind not in TYPES:
        raise ValidationFailure("Unknown transaction type", details={"allowed": list(TYPES)})
    day = item["executed_on"] if isinstance(item.get("executed_on"), date) else None
    if day is None:
        try:
            day = date.fromisoformat(str(item.get("executed_on") or item.get("date") or "").strip())
        except ValueError as exc:
            raise ValidationFailure("Dates are written as YYYY-MM-DD") from exc
    if day > utcnow().date() or day < date(1970, 1, 1):
        raise ValidationFailure("The date is outside the allowed range")
    quantity = _decimal(item.get("quantity") or 1, "quantity")
    price = _decimal(item.get("price") or 0, "price")
    fees = _decimal(item.get("fees") or 0, "fees")
    if quantity < 0 or price < 0 or fees < 0:
        raise ValidationFailure("Quantity, price and fees are not negative; the type sets the direction")
    instrument_id, currency = None, item.get("currency")
    symbol = str(item.get("instrument") or item.get("symbol") or "").strip()
    if kind in calc.TRADE_TYPES:
        if not symbol:
            raise ValidationFailure("A trade names an instrument")
        instrument = access.get_instrument(session, scope, symbol)
        instrument_id = instrument.id
        currency = currency or instrument.currency
        if quantity == 0:
            raise ValidationFailure("A trade has a positive quantity")
    elif symbol:
        instrument_id = access.get_instrument(session, scope, symbol).id
    if not currency:
        raise ValidationFailure("Name the currency of the transaction")
    return {
        "type": kind,
        "executed_on": day,
        "instrument_id": instrument_id,
        "quantity": quantity,
        "price": price,
        "fees": fees,
        "currency": normalize_currency(str(currency)),
        "note": clean_text(str(item.get("note") or ""), max_len=200),
    }


def _check_book(session: Session, portfolio_id: UUID, extra: list[dict[str, Any]]) -> None:
    """Reject a change that would sell more than is held at any point."""
    rows = [
        _txn(t, symbol=str(t.instrument_id))
        for t in session.scalars(select(Transaction).where(Transaction.portfolio_id == portfolio_id))
    ]
    rows += [
        calc.Txn(
            e["executed_on"],
            e["type"],
            str(e["instrument_id"]) if e["instrument_id"] else None,
            e["quantity"],
            e["price"],
            e["fees"],
            e["currency"],
        )
        for e in extra
    ]
    book = calc.Book()
    for txn in sorted(rows, key=lambda t: (t.day, t.type == "sell")):
        calc.apply(book, txn)


def _txn(row: Transaction, symbol: str | None = None) -> calc.Txn:
    return calc.Txn(row.executed_on, row.type, symbol, row.quantity, row.price, row.fees, row.currency)


def add_transactions(
    session: Session, scope: Scope, portfolio_id: UUID, items: list[dict[str, Any]], *, source: str = "manual"
) -> int:
    return _store(session, scope, portfolio_id, [_normalize(session, scope, item) for item in items], source)


def _store(session: Session, scope: Scope, portfolio_id: UUID, clean: list[dict[str, Any]], source: str) -> int:
    portfolio = _own(session, scope, portfolio_id, write=True)
    _check_book(session, portfolio.id, clean)
    for item in clean:
        session.add(Transaction(tenant_id=scope.tenant_id, portfolio_id=portfolio.id, **item))
    session.flush()
    record_audit(
        session,
        action="portfolio.transactions_added",
        tenant_id=scope.tenant_id,
        actor_id=scope.user_id,
        object_type="portfolio",
        object_id=portfolio.id,
        count=len(clean),
        source=source,
    )
    return len(clean)


def import_csv(session: Session, scope: Scope, portfolio_id: UUID, raw: bytes, max_bytes: int) -> int:
    """Import transactions from an untrusted CSV file. One bad line rejects the whole file."""
    rows = parse_csv(
        raw,
        required={"date", "type"},
        max_bytes=max_bytes,
        max_rows=5000,
        optional={"symbol", "quantity", "price", "fees", "currency", "note", "amount"},
    )
    items = []
    for row in rows:
        if row.get("amount") and not row.get("price"):
            row["price"] = row["amount"]
        try:
            items.append(_normalize(session, scope, {**row, "executed_on": row["date"]}))
        except AurexError as exc:
            raise ValidationFailure(f"Line {row['_line']}: {exc.message}", details={"line": int(row["_line"])}) from exc
    return _store(session, scope, portfolio_id, items, "csv")


def list_transactions(session: Session, scope: Scope, portfolio_id: UUID) -> list[dict[str, Any]]:
    portfolio = _own(session, scope, portfolio_id)
    rows = list(
        session.scalars(
            select(Transaction)
            .where(Transaction.portfolio_id == portfolio.id)
            .order_by(Transaction.executed_on.desc(), Transaction.created_at.desc())
        )
    )
    symbols = _symbols(session, scope, {r.instrument_id for r in rows if r.instrument_id})
    return [
        {
            "id": r.id,
            "type": r.type,
            "executed_on": r.executed_on,
            "symbol": symbols.get(r.instrument_id),
            "quantity": float(r.quantity),
            "price": float(r.price),
            "fees": float(r.fees),
            "currency": r.currency,
            "note": r.note,
        }
        for r in rows
    ]


def delete_transaction(session: Session, scope: Scope, portfolio_id: UUID, transaction_id: UUID) -> None:
    portfolio = _own(session, scope, portfolio_id, write=True)
    row = session.get(Transaction, transaction_id)
    if row is None or row.portfolio_id != portfolio.id:
        raise NotFound("Transaction not found")
    session.delete(row)
    session.flush()
    _check_book(session, portfolio.id, [])
    record_audit(
        session,
        action="portfolio.transaction_deleted",
        tenant_id=scope.tenant_id,
        actor_id=scope.user_id,
        object_type="portfolio",
        object_id=portfolio.id,
    )


def _symbols(session: Session, scope: Scope, ids: set[UUID]) -> dict[UUID, str]:
    out = {}
    for instrument_id in ids:
        try:
            out[instrument_id] = access.get_instrument(session, scope, instrument_id).symbol
        except AurexError:
            out[instrument_id] = "unavailable"
    return out


# --- Analytics ------------------------------------------------------------------------------------


def _inputs(session: Session, scope: Scope, portfolio: Portfolio, *, as_of: date | None = None):
    rows = list(session.scalars(select(Transaction).where(Transaction.portfolio_id == portfolio.id)))
    ids = {r.instrument_id for r in rows if r.instrument_id}
    meta, prices, sources, gaps = {}, {}, {}, []
    first = min((r.executed_on for r in rows), default=utcnow().date())
    start = first - timedelta(days=10)
    for instrument_id in ids:
        try:
            instrument = access.get_instrument(session, scope, instrument_id)
        except AurexError:
            gaps.append("An instrument in this portfolio is no longer available to your plan.")
            continue
        entity = access.get_entity(session, scope, instrument.entity_id) if instrument.entity_id else None
        meta[instrument.symbol] = {
            "name": instrument.name,
            "type": instrument.type,
            "sector": entity.sector if entity else None,
            "instrument_id": instrument.id,
            "license_class": instrument.license_class,
        }
        series = access.instrument_series(session, scope, instrument.id)
        if series:
            points = access.load_values(session, scope, [series[0].id], start=start)[series[0].id]
            prices[instrument.symbol] = calc.AsOf([(d, float(v)) for d, v in points])
            _, prov = access.series_meta(session, scope, series[0].id)
            sources[prov.dataset] = prov
        else:
            gaps.append(f"{instrument.symbol} has no licensed price series; it is valued at cost.")
    by_id = {m["instrument_id"]: symbol for symbol, m in meta.items()}
    txns = [
        _txn(r, symbol=by_id.get(r.instrument_id) if r.instrument_id else None)
        for r in rows
        if not r.instrument_id or r.instrument_id in by_id
    ]
    currencies = {t.currency for t in txns} | {portfolio.base_currency}
    fx = {}
    for currency in currencies - {"EUR"}:
        try:
            series, prov = access.series_meta(session, scope, FX_PREFIX + currency)
            points = access.load_values(session, scope, [series.id], start=start)[series.id]
            fx[currency] = calc.AsOf([(d, float(v)) for d, v in points])
            sources[prov.dataset] = prov
        except AurexError:
            gaps.append(f"No exchange rate for {currency} is available; positions in it cannot be converted.")
    for prov in sources.values():
        if prov.license_class == "demonstration":
            gaps.append("Prices of demonstration instruments are generated by AUREX, not market data.")
        if prov.status in ("stale", "failed"):
            gaps.append(f"The dataset '{prov.dataset_name}' is {prov.status}.")
    return txns, prices, fx, meta, sources, list(dict.fromkeys(gaps))


def analytics(session: Session, scope: Scope, portfolio_id: UUID) -> dict[str, Any]:
    portfolio = _own(session, scope, portfolio_id)
    txns, prices, fx, meta, sources, gaps = _inputs(session, scope, portfolio)
    today = utcnow().date()
    base = portfolio.base_currency
    if not txns:
        return {"portfolio": _view(portfolio), "empty": True, "gaps": ["Add transactions to see analytics."]}
    valued = calc.valuation(txns, prices, fx, base, today)
    if not valued["days"]:
        return {
            "portfolio": _view(portfolio),
            "empty": True,
            "gaps": gaps + ["The portfolio could not be valued on any day; exchange rates are missing."],
        }
    day = valued["days"][-1]
    table = calc.holdings_table(valued["book"], prices, fx, base, day, meta)
    exposure = calc.exposures(table["positions"], table["cash"], table["total"])
    benchmark = None
    if portfolio.benchmark_series_id:
        try:
            series, prov = access.series_meta(session, scope, portfolio.benchmark_series_id)
            points = access.load_values(session, scope, [series.id], start=valued["days"][0])[series.id]
            benchmark = calc.AsOf([(d, float(v)) for d, v in points])
            sources[prov.dataset] = prov
        except AurexError:
            gaps.append("The benchmark is not available to your plan.")
    perf = calc.performance(valued["days"], valued["index"], benchmark)
    flows = sum(valued["flows"])
    invested = sum(
        float(calc.cash_amount(t))
        * (calc.fx_factor(t.currency, base, t.day, fx) or 0)
        * (1 if t.type == "deposit" else -1)
        for t in txns
        if t.type in calc.EXTERNAL_FLOWS
    )
    for symbol in valued["unpriced"]:
        gaps.append(f"{symbol} is valued at cost because no price is available.")
    for currency in valued["missing_fx"]:
        gaps.append(f"Days without a {currency} exchange rate are left out of the history.")
    cash_negative = [c for c in table["cash"] if c["amount"] < 0]
    if cash_negative:
        gaps.append(
            "Cash is negative in "
            + ", ".join(c["currency"] for c in cash_negative)
            + ". Record the deposits that funded the purchases."
        )
    step = max(1, len(valued["days"]) // 600)  # at most ~600 points for the chart
    history = [
        {"t": d.isoformat(), "value": v, "index": i}
        for d, v, i in list(zip(valued["days"], valued["values"], valued["index"], strict=True))[::step]
    ]
    if history and history[-1]["t"] != valued["days"][-1].isoformat():
        history.append(
            {"t": valued["days"][-1].isoformat(), "value": valued["values"][-1], "index": valued["index"][-1]}
        )
    bench_index = perf.get("benchmark", {}).pop("index", None)
    if bench_index:
        sampled = bench_index[::step]
        if len(sampled) < len(history):
            sampled.append(bench_index[-1])
        for point, level in zip(history, sampled, strict=False):
            point["benchmark"] = level
    return {
        "portfolio": _view(portfolio),
        "empty": False,
        "as_of": day,
        "base_currency": base,
        "value": table["total"],
        "net_invested": invested,
        "result": table["total"] - invested,
        "performance": perf,
        "positions": table["positions"],
        "cash": table["cash"],
        "exposures": exposure,
        "limits": portfolio.limits,
        "breaches": calc.check_limits(table["positions"], exposure, portfolio.limits),
        "history": history,
        "gaps": list(dict.fromkeys(gaps)),
        "external_flows": flows,
        "sources": [
            {
                "dataset": p.dataset,
                "attribution": p.attribution,
                "freshness_class": p.freshness_class,
                "license_class": p.license_class,
                "status": p.status,
            }
            for p in sources.values()
        ],
    }


def run_scenario(session: Session, scope: Scope, portfolio_id: UUID, shocks: list[dict[str, Any]]) -> dict[str, Any]:
    scope.require(ent.PORTFOLIO_SCENARIOS)
    if not 1 <= len(shocks) <= 20:
        raise ValidationFailure("A scenario has between 1 and 20 shocks")
    for shock in shocks:
        if shock.get("target_type") not in calc.SCENARIO_TARGETS:
            raise ValidationFailure("Unknown shock target", details={"allowed": list(calc.SCENARIO_TARGETS)})
        if not -100 <= float(shock.get("shock_pct", 0)) <= 500:
            raise ValidationFailure("A shock is between -100% and +500%")
    result = analytics(session, scope, portfolio_id)
    if result.get("empty"):
        raise ValidationFailure("The portfolio has no holdings to shock")
    outcome = calc.scenario(result["positions"], result["cash"], result["base_currency"], shocks)
    record_audit(
        session,
        action="portfolio.scenario_run",
        tenant_id=scope.tenant_id,
        actor_id=scope.user_id,
        object_type="portfolio",
        object_id=portfolio_id,
        shocks=len(shocks),
    )
    return outcome | {"shocks": shocks, "base_currency": result["base_currency"]}


# --- Demonstration portfolio ----------------------------------------------------------------------


def create_demo(session: Session, scope: Scope) -> Portfolio:
    """A sample portfolio of demonstration instruments, so every analytic can be tried at once."""
    portfolio = create_portfolio(
        session,
        scope,
        name="Demonstration portfolio",
        base_currency="EUR",
        description="Fictional companies with generated prices.",
        benchmark="DEMO10.DEMO",
        limits={"max_position_pct": 25, "max_sector_pct": 40},
    )
    start = utcnow().date() - timedelta(days=730)
    start -= timedelta(days=max(0, start.weekday() - 4))
    items: list[dict[str, Any]] = [
        {"type": "deposit", "executed_on": start, "price": 100000, "currency": "USD", "note": "Initial funding"}
    ]
    funding = Decimal(100000)
    # Target weights leave about 5% in cash; quantities are whole shares at the first available price.
    for symbol, weight in (
        ("ORCA.DEMO", "0.20"),
        ("PXLR.DEMO", "0.15"),
        ("NWND.DEMO", "0.15"),
        ("LUMN.DEMO", "0.15"),
        ("MERD.DEMO", "0.15"),
        ("FARM.DEMO", "0.15"),
    ):
        instrument = access.get_instrument(session, scope, symbol)
        series = access.primary_series(session, scope, instrument.id)
        points = access.load_values(session, scope, [series.id], start=start, end=start + timedelta(days=10))[series.id]
        if not points:
            continue
        price = points[0][1].quantize(Decimal("0.01"))
        quantity = int(funding * Decimal(weight) / price)
        if quantity:
            items.append(
                {
                    "type": "buy",
                    "executed_on": points[0][0],
                    "instrument": symbol,
                    "quantity": quantity,
                    "price": price,
                    "fees": 5,
                    "currency": "USD",
                }
            )
    add_transactions(session, scope, portfolio.id, items, source="demo")
    return portfolio


def delete_all_transactions(session: Session, scope: Scope, portfolio_id: UUID) -> int:
    portfolio = _own(session, scope, portfolio_id, write=True)
    count = session.execute(delete(Transaction).where(Transaction.portfolio_id == portfolio.id)).rowcount
    record_audit(
        session,
        action="portfolio.transactions_cleared",
        tenant_id=scope.tenant_id,
        actor_id=scope.user_id,
        object_type="portfolio",
        object_id=portfolio.id,
        count=count,
    )
    return count
