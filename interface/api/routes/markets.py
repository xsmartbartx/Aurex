"""AUREX Markets endpoints."""

import csv
import io
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
from pydantic import Field

from core import entitlements as ent
from core.errors import ValidationFailure
from interface.api.deps import DbDep, ScopeDep
from modules.datalab import access
from modules.logging import record_audit
from modules.markets import service
from modules.validation import Strict, clean_text

router = APIRouter(prefix="/markets", tags=["markets"])


def _ref(value: str) -> str | UUID:
    try:
        return UUID(value)
    except ValueError:
        return clean_text(value, max_len=80)


def _indicators(values: list[str]) -> list[tuple[str, int]]:
    out = []
    for value in values:
        kind, _, window = value.partition(":")
        if not window.isdigit():
            raise ValidationFailure("Indicators are written as kind:window, for example sma:50")
        out.append((kind.lower(), int(window)))
    return out


@router.get("/instruments")
def search_instruments(
    scope: ScopeDep,
    db: DbDep,
    q: Annotated[str, Query(max_length=80)] = "",
    type: Annotated[list[str], Query()] = [],  # noqa: B006
    priced: bool = False,
    limit: Annotated[int, Query(ge=1, le=200)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict:
    items = access.search_instruments(
        db, scope, clean_text(q, max_len=80), types=type, priced_only=priced, limit=limit, offset=offset
    )
    quotes = access.quotes(db, scope, [i.id for i in items if i.has_prices])
    return {"items": [{"instrument": i, "quote": quotes.get(i.id)} for i in items]}


@router.get("/instruments/{ref}")
def instrument(ref: str, scope: ScopeDep, db: DbDep) -> dict:
    item = access.get_instrument(db, scope, _ref(ref))
    series = access.instrument_series(db, scope, item.id)
    entity = access.get_entity(db, scope, item.entity_id) if item.entity_id else None
    return {
        "instrument": item,
        "series": series,
        "quote": access.quotes(db, scope, [item.id]).get(item.id),
        "entity": entity,
        "price_data": "available" if series else "not_licensed",
        "price_data_note": None
        if series
        else "No licensed price series for this instrument. Fundamentals and filings come from public sources.",
    }


@router.get("/series")
def list_series(
    scope: ScopeDep,
    db: DbDep,
    kind: Annotated[list[str], Query()] = [],  # noqa: B006
    q: Annotated[str, Query(max_length=80)] = "",
) -> dict:
    return {"items": access.find_series(db, scope, kinds=kind, query=clean_text(q, max_len=80))}


@router.get("/series/{ref}/chart")
def chart(
    ref: str,
    scope: ScopeDep,
    db: DbDep,
    interval: str = "1D",
    range: str = "1Y",  # noqa: A002
    as_of: datetime | None = None,
    indicator: Annotated[list[str], Query(max_length=6)] = [],
) -> dict:  # noqa: B006
    if as_of is not None and as_of.tzinfo is None:
        raise ValidationFailure("as_of must include a time zone")
    return service.chart(
        db,
        scope,
        _ref(ref),
        interval=interval,
        range_code=range.upper(),
        as_of=as_of,
        indicators=_indicators(indicator),
    )


@router.get("/series/{ref}/export")
def export_series(ref: str, scope: ScopeDep, db: DbDep, range: str = "MAX") -> StreamingResponse:  # noqa: A002
    """CSV export. Blocked unless the plan includes export and the dataset license permits it."""
    scope.require(ent.EXPORT)
    data = access.series_data(
        db,
        scope,
        _ref(ref),
        start=service._range_start(
            range.upper(),  # noqa: SLF001
            datetime.now().date(),
        ),
        channel="export",
    )
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([f"# {data.series.name} ({data.series.unit})"])
    writer.writerow([f"# {data.provenance.attribution}"])
    writer.writerow(
        [
            f"# freshness: {data.provenance.freshness_class}; license class: "
            f"{data.provenance.license_class}; exported {datetime.now().isoformat(timespec='seconds')}"
        ]
    )
    writer.writerow(["date", "value", "open", "high", "low", "volume", "quality", "known_at", "version"])
    for p in data.points:
        writer.writerow(
            [
                p.t.date().isoformat(),
                p.v,
                p.o,
                p.h,
                p.l,
                p.vol,
                p.q,
                p.known_at.isoformat() if p.known_at else "",
                p.version,
            ]
        )
    record_audit(
        db,
        action="export.series",
        tenant_id=scope.tenant_id,
        actor_id=scope.user_id,
        object_type="series",
        object_id=data.series.id,
        rows=len(data.points),
    )
    filename = data.series.code.replace(":", "_").lower()
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}.csv"'},
    )


@router.get("/correlations")
def correlations(
    scope: ScopeDep,
    db: DbDep,
    instrument: Annotated[list[UUID], Query()],
    days: Annotated[int, Query(ge=30, le=3653)] = 365,
) -> dict:
    return service.correlations(db, scope, instrument, days=days)


class ScreenRequest(Strict):
    types: list[str] = Field(default_factory=list, max_length=10)
    filters: dict[str, dict[str, Any]] = Field(default_factory=dict)
    sort: str = "return_1y"
    descending: bool = True
    limit: int = Field(default=100, ge=1, le=200)


@router.post("/screener")
def screener(body: ScreenRequest, scope: ScopeDep, db: DbDep) -> dict:
    return service.screen(
        db, scope, types=body.types, filters=body.filters, sort=body.sort, descending=body.descending, limit=body.limit
    )


@router.get("/calendar")
def calendar(
    scope: ScopeDep,
    db: DbDep,
    days_back: Annotated[int, Query(ge=0, le=365)] = 30,
    days_ahead: Annotated[int, Query(ge=0, le=365)] = 30,
    kind: Annotated[list[str], Query()] = [],
) -> dict:  # noqa: B006
    return {"items": service.calendar(db, scope, days_back=days_back, days_ahead=days_ahead, kinds=kind)}


# --- Watchlists -----------------------------------------------------------------------------------


class WatchlistCreate(Strict):
    name: str = Field(min_length=1, max_length=80)
    shared: bool = False


class WatchlistUpdate(Strict):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    shared: bool | None = None


class ItemAdd(Strict):
    instrument: str = Field(min_length=1, max_length=80)


class ItemUpdate(Strict):
    pinned: bool | None = None
    position: int | None = Field(default=None, ge=0, le=1000)
    note: str | None = Field(default=None, max_length=200)


@router.get("/watchlists")
def watchlists(scope: ScopeDep, db: DbDep) -> dict:
    return {"items": service.list_watchlists(db, scope)}


@router.post("/watchlists", status_code=201)
def create_watchlist(body: WatchlistCreate, scope: ScopeDep, db: DbDep) -> dict:
    row = service.create_watchlist(db, scope, clean_text(body.name, max_len=80), body.shared)
    return service.watchlist_detail(db, scope, row.id)


@router.get("/watchlists/{watchlist_id}")
def watchlist(watchlist_id: UUID, scope: ScopeDep, db: DbDep) -> dict:
    return service.watchlist_detail(db, scope, watchlist_id)


@router.patch("/watchlists/{watchlist_id}")
def update_watchlist(watchlist_id: UUID, body: WatchlistUpdate, scope: ScopeDep, db: DbDep) -> dict:
    service.update_watchlist(db, scope, watchlist_id, name=body.name, shared=body.shared)
    return service.watchlist_detail(db, scope, watchlist_id)


@router.delete("/watchlists/{watchlist_id}", status_code=204)
def delete_watchlist(watchlist_id: UUID, scope: ScopeDep, db: DbDep) -> None:
    service.delete_watchlist(db, scope, watchlist_id)


@router.post("/watchlists/{watchlist_id}/items", status_code=201)
def add_item(watchlist_id: UUID, body: ItemAdd, scope: ScopeDep, db: DbDep) -> dict:
    service.add_item(db, scope, watchlist_id, _ref(body.instrument))
    return service.watchlist_detail(db, scope, watchlist_id)


@router.patch("/watchlists/{watchlist_id}/items/{item_id}")
def update_item(watchlist_id: UUID, item_id: UUID, body: ItemUpdate, scope: ScopeDep, db: DbDep) -> dict:
    service.update_item(db, scope, watchlist_id, item_id, pinned=body.pinned, position=body.position, note=body.note)
    return service.watchlist_detail(db, scope, watchlist_id)


@router.delete("/watchlists/{watchlist_id}/items/{item_id}")
def remove_item(watchlist_id: UUID, item_id: UUID, scope: ScopeDep, db: DbDep) -> dict:
    service.remove_item(db, scope, watchlist_id, item_id)
    return service.watchlist_detail(db, scope, watchlist_id)


# --- Alerts and notifications ---------------------------------------------------------------------


class AlertCreate(Strict):
    instrument: str = Field(min_length=1, max_length=80)
    condition: str
    threshold: Decimal
    note: str = Field(default="", max_length=200)
    cooldown_minutes: int = Field(default=1440, ge=5, le=43200)


class AlertUpdate(Strict):
    active: bool | None = None
    threshold: Decimal | None = None
    note: str | None = Field(default=None, max_length=200)


class NotificationsRead(Strict):
    ids: list[UUID] | None = Field(default=None, max_length=200)


@router.get("/alerts")
def alerts(scope: ScopeDep, db: DbDep) -> dict:
    return {"items": service.list_alerts(db, scope)}


@router.post("/alerts", status_code=201)
def create_alert(body: AlertCreate, scope: ScopeDep, db: DbDep) -> dict:
    rule_id = service.create_alert(
        db,
        scope,
        instrument_ref=_ref(body.instrument),
        condition=body.condition,
        threshold=body.threshold,
        note=body.note,
        cooldown_minutes=body.cooldown_minutes,
    )
    return {"id": rule_id}


@router.patch("/alerts/{rule_id}")
def update_alert(rule_id: UUID, body: AlertUpdate, scope: ScopeDep, db: DbDep) -> dict:
    service.update_alert(db, scope, rule_id, active=body.active, threshold=body.threshold, note=body.note)
    return {"status": "ok"}


@router.delete("/alerts/{rule_id}", status_code=204)
def delete_alert(rule_id: UUID, scope: ScopeDep, db: DbDep) -> None:
    service.delete_alert(db, scope, rule_id)


@router.get("/notifications")
def notifications(scope: ScopeDep, db: DbDep, unread: bool = False) -> dict:
    return service.list_notifications(db, scope, unread_only=unread)


@router.post("/notifications/read")
def read_notifications(body: NotificationsRead, scope: ScopeDep, db: DbDep) -> dict:
    return {"updated": service.mark_notifications_read(db, scope, body.ids)}


# --- Workspaces -----------------------------------------------------------------------------------


class WorkspaceSave(Strict):
    name: str = Field(min_length=1, max_length=80)
    layout: dict[str, Any]
    is_default: bool = False


def _workspace(row) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "layout": row.layout,
        "is_default": row.is_default,
        "updated_at": row.updated_at,
    }


@router.get("/workspaces")
def workspaces(scope: ScopeDep, db: DbDep) -> dict:
    return {
        "items": [_workspace(w) for w in service.list_workspaces(db, scope)],
        "panel_types": service.PANEL_TYPES,
        "presets": service.PRESETS,
    }


@router.post("/workspaces", status_code=201)
def create_workspace(body: WorkspaceSave, scope: ScopeDep, db: DbDep) -> dict:
    return _workspace(
        service.save_workspace(
            db, scope, workspace_id=None, name=body.name, layout=body.layout, is_default=body.is_default
        )
    )


@router.put("/workspaces/{workspace_id}")
def save_workspace(workspace_id: UUID, body: WorkspaceSave, scope: ScopeDep, db: DbDep) -> dict:
    return _workspace(
        service.save_workspace(
            db, scope, workspace_id=workspace_id, name=body.name, layout=body.layout, is_default=body.is_default
        )
    )


@router.delete("/workspaces/{workspace_id}", status_code=204)
def delete_workspace(workspace_id: UUID, scope: ScopeDep, db: DbDep) -> None:
    service.delete_workspace(db, scope, workspace_id)
