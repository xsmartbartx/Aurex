"""AUREX Markets: charts, watchlists, alerts, notifications, workspaces, correlations and screening.

Markets does not call providers and does not compute indicators itself: data comes from the DataLab
access interface and figures from the financial engine. No value is returned without freshness and source.
"""

from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.orm import Session

from core import entitlements as ent
from core.errors import AurexError, Conflict, NotFound, ValidationFailure
from core.types import Role, Scope, utcnow
from modules.datalab import access
from modules.logging import record_audit
from modules.markets.models import AlertRule, Notification, Watchlist, WatchlistItem, Workspace
from modules.processing import ENGINE_VERSION
from modules.processing import fundamentals as fnd
from modules.processing import series as calc

RANGES = {"1M": 31, "3M": 92, "6M": 183, "YTD": None, "1Y": 366, "3Y": 1096, "5Y": 1827, "10Y": 3653, "MAX": None}
INTERVALS = ("1D", "1W", "1M", "3M")
CONDITIONS = ("above", "below", "change_pct_above", "change_pct_below")


def _range_start(range_code: str, today: date) -> date | None:
    if range_code not in RANGES:
        raise ValidationFailure("Unsupported range", details={"allowed": list(RANGES)})
    if range_code == "YTD":
        return date(today.year, 1, 1)
    days = RANGES[range_code]
    return today - timedelta(days=days) if days else None


# --- Charts ---------------------------------------------------------------------------------------


def chart(
    session: Session,
    scope: Scope,
    series_ref: str | UUID,
    *,
    interval: str = "1D",
    range_code: str = "1Y",
    as_of: datetime | None = None,
    indicators: Sequence[tuple[str, int]] = (),
) -> dict[str, Any]:
    if interval not in INTERVALS:
        raise ValidationFailure("Unsupported interval", details={"allowed": list(INTERVALS)})
    today = (as_of or utcnow()).date()
    start = _range_start(range_code, today)
    # Indicators need history before the visible range.
    per_bar = {"1D": 1.5, "1W": 7, "1M": 31, "3M": 92}[interval]
    warmup = int(max((window for _, window in indicators), default=0) * per_bar) + 5
    data = access.series_data(
        session, scope, series_ref, start=start - timedelta(days=warmup) if start else None, end=today, as_of=as_of
    )
    bars = calc.resample([p.model_dump() for p in data.points], interval)
    values = [b["v"] for b in bars]
    overlays = [
        {
            "kind": kind,
            "window": window,
            "engine_version": ENGINE_VERSION,
            "lines": calc.indicator(kind, values, window),
        }
        for kind, window in indicators[:6]
    ]
    first = next((i for i, b in enumerate(bars) if start is None or b["t"].date() >= start), len(bars))
    for overlay in overlays:
        overlay["lines"] = {name: line[first:] for name, line in overlay["lines"].items()}
    bars = bars[first:]
    frequency = {"1D": data.series.frequency, "1W": "W", "1M": "M", "3M": "Q"}[interval]
    stats = calc.summary([b["v"] for b in bars], [b["t"].date() for b in bars], frequency) if bars else {}
    return {
        "series": data.series,
        "provenance": data.provenance,
        "as_of": as_of,
        "interval": interval,
        "range": range_code,
        "points": bars,
        "indicators": overlays,
        "summary": {**stats, "engine_version": ENGINE_VERSION},
        "quality": {
            "suspect": sum(1 for b in bars if b.get("q") == "suspect"),
            "demonstration": sum(1 for b in bars if b.get("q") == "demonstration"),
        },
    }


def correlations(session: Session, scope: Scope, instrument_ids: Sequence[UUID], *, days: int = 365) -> dict[str, Any]:
    if not 2 <= len(instrument_ids) <= 12:
        raise ValidationFailure("Choose between 2 and 12 instruments")
    start = utcnow().date() - timedelta(days=min(max(days, 30), 3653))
    names: dict[UUID, str] = {}
    sources = []
    for instrument_id in dict.fromkeys(instrument_ids):
        instrument = access.get_instrument(session, scope, instrument_id)
        series = access.primary_series(session, scope, instrument_id)
        names[series.id] = instrument.symbol
        _, prov = access.series_meta(session, scope, series.id)
        sources.append(
            {
                "symbol": instrument.symbol,
                "dataset": prov.dataset,
                "license_class": prov.license_class,
                "freshness_class": prov.freshness_class,
                "attribution": prov.attribution,
            }
        )
    values = access.load_values(session, scope, names, start=start)
    result = calc.correlation_matrix({names[sid]: [(d, float(v)) for d, v in pts] for sid, pts in values.items()})
    return {
        **result,
        "method": "Pearson correlation of simple returns on common dates",
        "engine_version": ENGINE_VERSION,
        "sources": sources,
    }


# --- Screener -------------------------------------------------------------------------------------

SCREEN_METRICS = (
    "last",
    "return_1m",
    "return_3m",
    "return_1y",
    "volatility",
    "max_drawdown",
    "revenue",
    "revenue_growth",
    "net_margin",
    "debt_to_equity",
    "return_on_equity",
)


def screen(
    session: Session,
    scope: Scope,
    *,
    types: Sequence[str] = (),
    filters: dict[str, dict[str, Any]] | None = None,
    sort: str = "return_1y",
    descending: bool = True,
    limit: int = 100,
) -> dict[str, Any]:
    """Filter priced instruments by price and fundamental criteria. Metrics come from the financial engine."""
    scope.require(ent.SCREENER)
    filters = filters or {}
    if sort not in SCREEN_METRICS or any(k not in (*SCREEN_METRICS, "sector") for k in filters):
        raise ValidationFailure("Unknown screening metric", details={"allowed": list(SCREEN_METRICS)})
    instruments = access.search_instruments(session, scope, types=types, priced_only=True, limit=200)
    today = utcnow().date()
    rows = []
    for instrument in instruments:
        series = access.primary_series(session, scope, instrument.id)
        points = access.load_values(session, scope, [series.id], start=today - timedelta(days=380))[series.id]
        if len(points) < 5:
            continue
        values = [float(v) for _, v in points]
        dates = [d for d, _ in points]

        def ret(days: int, values=values, dates=dates) -> float | None:
            cutoff = today - timedelta(days=days)
            base = next((v for d, v in zip(dates, values, strict=True) if d >= cutoff), None)
            return (values[-1] / base - 1) * 100 if base else None

        volatility = calc.annualized_volatility(values, series.frequency)
        drawdown = calc.max_drawdown(values)["depth"]
        row: dict[str, Any] = {
            "instrument": instrument,
            "last": values[-1],
            "unit": series.unit,
            "as_of": dates[-1],
            "return_1m": ret(31),
            "return_3m": ret(92),
            "return_1y": ret(366),
            "volatility": volatility * 100 if volatility is not None else None,
            "max_drawdown": drawdown * 100 if drawdown is not None else None,
        }
        if instrument.entity_id:
            facts, _ = access.entity_facts(session, scope, instrument.entity_id)
            analysis = fnd.analyze([f.model_dump() for f in facts], max_years=1)
            if analysis["years"]:
                year = analysis["years"][0]
                row["sector"] = access.get_entity(session, scope, instrument.entity_id).sector
                row["fiscal_year"] = year["fiscal_year"]
                row["revenue"] = float(year["items"]["revenue"]["value"]) if "revenue" in year["items"] else None
                for name in ("revenue_growth", "net_margin", "debt_to_equity", "return_on_equity"):
                    row[name] = year["ratios"][name].output if name in year["ratios"] else None
        rows.append(row)
    for key, bounds in filters.items():
        if key == "sector":
            if bounds.get("equals"):
                rows = [r for r in rows if r.get("sector") == bounds["equals"]]
            continue
        low, high = bounds.get("min"), bounds.get("max")
        rows = [
            r
            for r in rows
            if r.get(key) is not None and (low is None or r[key] >= low) and (high is None or r[key] <= high)
        ]
    rows.sort(key=lambda r: (r.get(sort) is None, -(r.get(sort) or 0) if descending else (r.get(sort) or 0)))
    return {
        "rows": rows[:limit],
        "total": len(rows),
        "engine_version": ENGINE_VERSION,
        "note": "Returns compare the latest stored value with the first value on or after the start of "
        "the window. Instruments without a licensed price series are not screened.",
    }


# --- Watchlists -----------------------------------------------------------------------------------


def _watchlist(session: Session, scope: Scope, watchlist_id: UUID, *, write: bool = False) -> Watchlist:
    row = session.get(Watchlist, watchlist_id)
    if row is None or row.tenant_id != scope.tenant_id or (row.user_id != scope.user_id and not row.shared):
        raise NotFound("Watchlist not found")
    if write and row.user_id != scope.user_id and not scope.at_least(Role.ADMIN):
        raise NotFound("Watchlist not found")
    return row


def list_watchlists(session: Session, scope: Scope) -> list[dict[str, Any]]:
    rows = list(
        session.scalars(
            select(Watchlist)
            .where(
                Watchlist.tenant_id == scope.tenant_id,
                or_(Watchlist.user_id == scope.user_id, Watchlist.shared.is_(True)),
            )
            .order_by(Watchlist.created_at)
        )
    )
    if not any(r.user_id == scope.user_id for r in rows) and scope.at_least(Role.ANALYST):
        rows.append(create_watchlist(session, scope, "My watchlist"))  # every analyst starts with one list
    return [watchlist_detail(session, scope, row.id) for row in rows]


def create_watchlist(session: Session, scope: Scope, name: str, shared: bool = False) -> Watchlist:
    scope.require_role(Role.ANALYST)
    count = session.scalar(
        select(func.count())
        .select_from(Watchlist)
        .where(Watchlist.tenant_id == scope.tenant_id, Watchlist.user_id == scope.user_id)
    )
    scope.check_limit("watchlists", count)
    if session.scalar(
        select(Watchlist.id).where(
            Watchlist.tenant_id == scope.tenant_id, Watchlist.user_id == scope.user_id, Watchlist.name == name
        )
    ):
        raise Conflict("A watchlist with this name already exists")
    row = Watchlist(tenant_id=scope.tenant_id, user_id=scope.user_id, name=name, shared=shared)
    session.add(row)
    session.flush()
    record_audit(
        session,
        action="watchlist.created",
        tenant_id=scope.tenant_id,
        actor_id=scope.user_id,
        object_type="watchlist",
        object_id=row.id,
    )
    return row


def watchlist_detail(session: Session, scope: Scope, watchlist_id: UUID) -> dict[str, Any]:
    row = _watchlist(session, scope, watchlist_id)
    items = list(
        session.scalars(
            select(WatchlistItem)
            .where(WatchlistItem.watchlist_id == row.id)
            .order_by(WatchlistItem.pinned.desc(), WatchlistItem.position, WatchlistItem.created_at)
        )
    )
    quotes = access.quotes(session, scope, [i.instrument_id for i in items])
    out = []
    for item in items:
        try:
            instrument = access.get_instrument(session, scope, item.instrument_id)
        except AurexError:  # an instrument that left the tenant's entitlements is not shown
            continue
        out.append(
            {
                "id": item.id,
                "instrument": instrument,
                "quote": quotes.get(item.instrument_id),
                "pinned": item.pinned,
                "position": item.position,
                "note": item.note,
            }
        )
    return {"id": row.id, "name": row.name, "shared": row.shared, "owner": row.user_id == scope.user_id, "items": out}


def update_watchlist(
    session: Session, scope: Scope, watchlist_id: UUID, *, name: str | None = None, shared: bool | None = None
) -> None:
    row = _watchlist(session, scope, watchlist_id, write=True)
    if name:
        row.name = name
    if shared is not None:
        row.shared = shared
    record_audit(
        session,
        action="watchlist.updated",
        tenant_id=scope.tenant_id,
        actor_id=scope.user_id,
        object_type="watchlist",
        object_id=row.id,
    )


def delete_watchlist(session: Session, scope: Scope, watchlist_id: UUID) -> None:
    row = _watchlist(session, scope, watchlist_id, write=True)
    session.delete(row)
    record_audit(
        session,
        action="watchlist.deleted",
        tenant_id=scope.tenant_id,
        actor_id=scope.user_id,
        object_type="watchlist",
        object_id=watchlist_id,
    )


def add_item(session: Session, scope: Scope, watchlist_id: UUID, instrument_ref: str | UUID) -> UUID:
    scope.require_role(Role.ANALYST)
    row = _watchlist(session, scope, watchlist_id, write=True)
    instrument = access.get_instrument(session, scope, instrument_ref)
    if session.scalar(
        select(WatchlistItem.id).where(
            WatchlistItem.watchlist_id == row.id, WatchlistItem.instrument_id == instrument.id
        )
    ):
        raise Conflict("The instrument is already on this watchlist")
    count = session.scalar(select(func.count()).select_from(WatchlistItem).where(WatchlistItem.watchlist_id == row.id))
    if count >= 200:
        raise ValidationFailure("A watchlist holds at most 200 instruments")
    item = WatchlistItem(tenant_id=scope.tenant_id, watchlist_id=row.id, instrument_id=instrument.id, position=count)
    session.add(item)
    session.flush()
    record_audit(
        session,
        action="watchlist.item_added",
        tenant_id=scope.tenant_id,
        actor_id=scope.user_id,
        object_type="watchlist",
        object_id=row.id,
        symbol=instrument.symbol,
    )
    return item.id


def update_item(
    session: Session,
    scope: Scope,
    watchlist_id: UUID,
    item_id: UUID,
    *,
    pinned: bool | None = None,
    position: int | None = None,
    note: str | None = None,
) -> None:
    _watchlist(session, scope, watchlist_id, write=True)
    item = session.get(WatchlistItem, item_id)
    if item is None or item.watchlist_id != watchlist_id:
        raise NotFound("Watchlist item not found")
    if pinned is not None:
        item.pinned = pinned
    if position is not None:
        item.position = position
    if note is not None:
        item.note = note
    record_audit(
        session,
        action="watchlist.item_updated",
        tenant_id=scope.tenant_id,
        actor_id=scope.user_id,
        object_type="watchlist",
        object_id=watchlist_id,
    )


def remove_item(session: Session, scope: Scope, watchlist_id: UUID, item_id: UUID) -> None:
    _watchlist(session, scope, watchlist_id, write=True)
    deleted = session.execute(
        delete(WatchlistItem).where(WatchlistItem.id == item_id, WatchlistItem.watchlist_id == watchlist_id)
    ).rowcount
    if not deleted:
        raise NotFound("Watchlist item not found")
    record_audit(
        session,
        action="watchlist.item_removed",
        tenant_id=scope.tenant_id,
        actor_id=scope.user_id,
        object_type="watchlist",
        object_id=watchlist_id,
    )


# --- Alerts and notifications ---------------------------------------------------------------------


def list_alerts(session: Session, scope: Scope) -> list[dict[str, Any]]:
    rows = session.scalars(
        select(AlertRule)
        .where(AlertRule.tenant_id == scope.tenant_id, AlertRule.user_id == scope.user_id)
        .order_by(AlertRule.created_at.desc())
    )
    out = []
    for rule in rows:
        try:
            series, prov = access.series_meta(session, scope, rule.series_id)
        except AurexError:
            continue
        out.append(
            {
                "id": rule.id,
                "series": series,
                "provenance": prov,
                "condition": rule.condition,
                "threshold": float(rule.threshold),
                "note": rule.note,
                "active": rule.active,
                "cooldown_minutes": rule.cooldown_minutes,
                "last_triggered_at": rule.last_triggered_at,
                "instrument_id": rule.instrument_id,
            }
        )
    return out


def create_alert(
    session: Session,
    scope: Scope,
    *,
    instrument_ref: str | UUID,
    condition: str,
    threshold: Decimal,
    note: str = "",
    cooldown_minutes: int = 1440,
) -> UUID:
    scope.require(ent.ALERTS)
    scope.require_role(Role.ANALYST)
    if condition not in CONDITIONS:
        raise ValidationFailure("Unknown alert condition", details={"allowed": list(CONDITIONS)})
    count = session.scalar(select(func.count()).select_from(AlertRule).where(AlertRule.tenant_id == scope.tenant_id))
    scope.check_limit("alerts", count)
    instrument = access.get_instrument(session, scope, instrument_ref)
    series = access.primary_series(session, scope, instrument.id)
    rule = AlertRule(
        tenant_id=scope.tenant_id,
        user_id=scope.user_id,
        series_id=series.id,
        instrument_id=instrument.id,
        condition=condition,
        threshold=threshold,
        note=note,
        cooldown_minutes=max(5, cooldown_minutes),
    )
    session.add(rule)
    session.flush()
    record_audit(
        session,
        action="alert.created",
        tenant_id=scope.tenant_id,
        actor_id=scope.user_id,
        object_type="alert_rule",
        object_id=rule.id,
    )
    return rule.id


def _own_alert(session: Session, scope: Scope, rule_id: UUID) -> AlertRule:
    rule = session.get(AlertRule, rule_id)
    if rule is None or rule.tenant_id != scope.tenant_id or rule.user_id != scope.user_id:
        raise NotFound("Alert not found")
    return rule


def update_alert(
    session: Session,
    scope: Scope,
    rule_id: UUID,
    *,
    active: bool | None = None,
    threshold: Decimal | None = None,
    note: str | None = None,
) -> None:
    rule = _own_alert(session, scope, rule_id)
    if active is not None:
        rule.active = active
    if threshold is not None:
        rule.threshold = threshold
    if note is not None:
        rule.note = note
    record_audit(
        session,
        action="alert.updated",
        tenant_id=scope.tenant_id,
        actor_id=scope.user_id,
        object_type="alert_rule",
        object_id=rule.id,
    )


def delete_alert(session: Session, scope: Scope, rule_id: UUID) -> None:
    session.delete(_own_alert(session, scope, rule_id))
    record_audit(
        session,
        action="alert.deleted",
        tenant_id=scope.tenant_id,
        actor_id=scope.user_id,
        object_type="alert_rule",
        object_id=rule_id,
    )


def triggered(condition: str, threshold: Decimal, last: Decimal | None, previous: Decimal | None) -> bool:
    if last is None:
        return False
    if condition == "above":
        return last > threshold
    if condition == "below":
        return last < threshold
    if previous is None or previous == 0:
        return False
    change = (last / previous - 1) * 100
    return change > abs(threshold) if condition == "change_pct_above" else change < -abs(threshold)


def evaluate_alerts(session: Session, series_values: dict[UUID, tuple[Decimal | None, Decimal | None, str]]) -> int:
    """Check active rules after an ingestion run. ``series_values`` maps series id to (last, previous, name).

    Runs in a system session across tenants; each notification is written with its rule's tenant.
    """
    if not series_values:
        return 0
    now = utcnow()
    fired = 0
    rules = session.scalars(select(AlertRule).where(AlertRule.active.is_(True), AlertRule.series_id.in_(series_values)))
    for rule in rules:
        last, previous, name = series_values[rule.series_id]
        if rule.last_triggered_at and now - rule.last_triggered_at < timedelta(minutes=rule.cooldown_minutes):
            continue
        if not triggered(rule.condition, rule.threshold, last, previous):
            continue
        rule.last_triggered_at = now
        notify(
            session,
            tenant_id=rule.tenant_id,
            user_id=rule.user_id,
            kind="alert",
            title=f"{name}: {rule.condition.replace('_', ' ')} {float(rule.threshold):g}",
            body=f"Latest value {float(last):g}." + (f" {rule.note}" if rule.note else ""),
            link=f"/app/markets?instrument={rule.instrument_id}" if rule.instrument_id else "/app/markets",
            meta={"rule_id": str(rule.id), "series_id": str(rule.series_id)},
        )
        fired += 1
    return fired


def notify(
    session: Session,
    *,
    tenant_id: UUID,
    user_id: UUID,
    kind: str,
    title: str,
    body: str = "",
    link: str = "",
    meta: dict[str, Any] | None = None,
) -> None:
    session.add(
        Notification(
            tenant_id=tenant_id,
            user_id=user_id,
            kind=kind,
            title=title[:200],
            body=body,
            link=link[:300],
            meta=meta or {},
        )
    )


def list_notifications(session: Session, scope: Scope, *, unread_only: bool = False, limit: int = 50) -> dict[str, Any]:
    mine = (Notification.tenant_id == scope.tenant_id, Notification.user_id == scope.user_id)
    unread = session.scalar(select(func.count()).select_from(Notification).where(*mine, Notification.read_at.is_(None)))
    stmt = select(Notification).where(*mine)
    if unread_only:
        stmt = stmt.where(Notification.read_at.is_(None))
    rows = session.scalars(stmt.order_by(Notification.created_at.desc()).limit(limit))
    return {
        "unread": unread,
        "items": [
            {
                "id": n.id,
                "kind": n.kind,
                "title": n.title,
                "body": n.body,
                "link": n.link,
                "created_at": n.created_at,
                "read": n.read_at is not None,
            }
            for n in rows
        ],
    }


def mark_notifications_read(session: Session, scope: Scope, ids: Sequence[UUID] | None = None) -> int:
    stmt = update(Notification).where(
        Notification.tenant_id == scope.tenant_id, Notification.user_id == scope.user_id, Notification.read_at.is_(None)
    )
    if ids:
        stmt = stmt.where(Notification.id.in_(ids))
    return session.execute(stmt.values(read_at=utcnow())).rowcount


# --- Workspaces -----------------------------------------------------------------------------------

PANEL_TYPES = (
    "chart",
    "watchlist",
    "quote",
    "movers",
    "calendar",
    "documents",
    "assistant",
    "fundamentals",
    "datasets",
    "notifications",
)
PRESETS = ("single", "columns", "rows", "two-one", "one-two", "grid")
DEFAULT_LAYOUT = {
    "preset": "two-one",
    "panels": [
        {"type": "chart", "config": {}},
        {"type": "watchlist", "config": {}},
        {"type": "documents", "config": {}},
    ],
}


def _check_layout(layout: dict[str, Any]) -> dict[str, Any]:
    panels = layout.get("panels")
    if not isinstance(panels, list) or not 1 <= len(panels) <= 6:
        raise ValidationFailure("A workspace has between 1 and 6 panels")
    clean = []
    for panel in panels:
        if not isinstance(panel, dict) or panel.get("type") not in PANEL_TYPES:
            raise ValidationFailure("Unknown panel type", details={"allowed": list(PANEL_TYPES)})
        config = panel.get("config") or {}
        if not isinstance(config, dict) or len(str(config)) > 2000:
            raise ValidationFailure("Panel configuration is too large")
        clean.append({"type": panel["type"], "config": config})
    preset = layout.get("preset", "grid")
    if preset not in PRESETS:
        raise ValidationFailure("Unknown layout preset", details={"allowed": list(PRESETS)})
    return {"preset": preset, "panels": clean}


def list_workspaces(session: Session, scope: Scope) -> list[Workspace]:
    rows = list(
        session.scalars(
            select(Workspace)
            .where(Workspace.tenant_id == scope.tenant_id, Workspace.user_id == scope.user_id)
            .order_by(Workspace.is_default.desc(), Workspace.created_at)
        )
    )
    if not rows:
        row = Workspace(
            tenant_id=scope.tenant_id, user_id=scope.user_id, name="Overview", layout=DEFAULT_LAYOUT, is_default=True
        )
        session.add(row)
        session.flush()
        rows = [row]
    return rows


def save_workspace(
    session: Session,
    scope: Scope,
    *,
    workspace_id: UUID | None,
    name: str,
    layout: dict[str, Any],
    is_default: bool = False,
) -> Workspace:
    scope.require(ent.WORKSPACES)
    layout = _check_layout(layout)
    mine = (Workspace.tenant_id == scope.tenant_id, Workspace.user_id == scope.user_id)
    if workspace_id:
        row = session.get(Workspace, workspace_id)
        if row is None or row.tenant_id != scope.tenant_id or row.user_id != scope.user_id:
            raise NotFound("Workspace not found")
        row.name, row.layout = name, layout
    else:
        scope.check_limit("workspaces", session.scalar(select(func.count()).select_from(Workspace).where(*mine)))
        if session.scalar(select(Workspace.id).where(*mine, Workspace.name == name)):
            raise Conflict("A workspace with this name already exists")
        row = Workspace(tenant_id=scope.tenant_id, user_id=scope.user_id, name=name, layout=layout)
        session.add(row)
    if is_default:
        session.execute(update(Workspace).where(*mine).values(is_default=False))
        row.is_default = True
    session.flush()
    return row


def delete_workspace(session: Session, scope: Scope, workspace_id: UUID) -> None:
    row = session.get(Workspace, workspace_id)
    if row is None or row.tenant_id != scope.tenant_id or row.user_id != scope.user_id:
        raise NotFound("Workspace not found")
    session.delete(row)


def calendar(
    session: Session, scope: Scope, *, days_back: int = 30, days_ahead: int = 30, kinds: Sequence[str] = ()
) -> list[Any]:
    now = datetime.now(UTC)
    return access.calendar(
        session,
        scope,
        start=now - timedelta(days=min(days_back, 365)),
        end=now + timedelta(days=min(days_ahead, 365)),
        kinds=kinds,
    )
