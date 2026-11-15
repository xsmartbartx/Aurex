"""AUREX Portfolio endpoints. Virtual portfolios only: no broker connection and no orders."""

from datetime import date
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, File, UploadFile
from pydantic import Field

from core.config import get_settings
from interface.api.deps import DbDep, ScopeDep
from modules.portfolio import service
from modules.validation import Strict

router = APIRouter(prefix="/portfolios", tags=["portfolio"])


class Limits(Strict):
    max_position_pct: float | None = Field(default=None, ge=0, le=100)
    max_sector_pct: float | None = Field(default=None, ge=0, le=100)
    min_cash_pct: float | None = Field(default=None, ge=0, le=100)


class PortfolioCreate(Strict):
    name: str = Field(min_length=1, max_length=100)
    base_currency: Literal["EUR", "USD", "GBP", "CHF"] = "EUR"
    description: str = Field(default="", max_length=1000)
    benchmark: str | None = Field(default=None, max_length=40)
    limits: Limits = Field(default_factory=Limits)


class PortfolioUpdate(Strict):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=1000)
    benchmark: str | None = Field(default=None, max_length=40)
    limits: Limits | None = None


class TransactionIn(Strict):
    type: Literal["buy", "sell", "deposit", "withdrawal", "dividend", "fee", "interest"]
    executed_on: date
    instrument: str | None = Field(default=None, max_length=40)
    quantity: Decimal = Field(default=Decimal(1), ge=0)
    price: Decimal = Field(ge=0)
    fees: Decimal = Field(default=Decimal(0), ge=0)
    currency: str | None = Field(default=None, pattern=r"^[A-Za-z]{3}$")
    note: str = Field(default="", max_length=200)


class Shock(Strict):
    target_type: Literal["instrument", "sector", "type", "currency", "all"]
    target: str = Field(default="", max_length=80)
    shock_pct: float = Field(ge=-100, le=500)


class ScenarioIn(Strict):
    shocks: list[Shock] = Field(min_length=1, max_length=20)


def _limits(limits: Limits | None) -> dict | None:
    return None if limits is None else {k: v for k, v in limits.model_dump().items() if v is not None}


@router.get("")
def portfolios(scope: ScopeDep, db: DbDep) -> dict:
    return {"items": service.list_portfolios(db, scope), "presets": service.PRESETS}


@router.post("", status_code=201)
def create(body: PortfolioCreate, scope: ScopeDep, db: DbDep) -> dict:
    row = service.create_portfolio(
        db,
        scope,
        name=body.name,
        base_currency=body.base_currency,
        description=body.description,
        benchmark=body.benchmark,
        limits=_limits(body.limits),
    )
    return {"id": row.id}


@router.post("/demo", status_code=201)
def create_demo(scope: ScopeDep, db: DbDep) -> dict:
    return {"id": service.create_demo(db, scope).id}


@router.patch("/{portfolio_id}")
def update(portfolio_id: UUID, body: PortfolioUpdate, scope: ScopeDep, db: DbDep) -> dict:
    service.update_portfolio(
        db,
        scope,
        portfolio_id,
        name=body.name,
        description=body.description,
        benchmark=body.benchmark,
        limits=_limits(body.limits),
    )
    return {"status": "ok"}


@router.delete("/{portfolio_id}", status_code=204)
def delete(portfolio_id: UUID, scope: ScopeDep, db: DbDep) -> None:
    service.delete_portfolio(db, scope, portfolio_id)


@router.get("/{portfolio_id}/analytics")
def analytics(portfolio_id: UUID, scope: ScopeDep, db: DbDep) -> dict:
    return service.analytics(db, scope, portfolio_id)


@router.get("/{portfolio_id}/transactions")
def transactions(portfolio_id: UUID, scope: ScopeDep, db: DbDep) -> dict:
    return {"items": service.list_transactions(db, scope, portfolio_id)}


@router.post("/{portfolio_id}/transactions", status_code=201)
def add_transaction(portfolio_id: UUID, body: TransactionIn, scope: ScopeDep, db: DbDep) -> dict:
    return {"added": service.add_transactions(db, scope, portfolio_id, [body.model_dump()])}


@router.delete("/{portfolio_id}/transactions/{transaction_id}", status_code=204)
def delete_transaction(portfolio_id: UUID, transaction_id: UUID, scope: ScopeDep, db: DbDep) -> None:
    service.delete_transaction(db, scope, portfolio_id, transaction_id)


@router.post("/{portfolio_id}/import", status_code=201)
async def import_csv(portfolio_id: UUID, scope: ScopeDep, db: DbDep, file: Annotated[UploadFile, File()]) -> dict:
    """CSV columns: date, type, symbol, quantity, price, fees, currency, note (amount for cash rows)."""
    limit = get_settings().max_upload_bytes
    raw = await file.read(limit + 1)
    return {"added": service.import_csv(db, scope, portfolio_id, raw, limit)}


@router.post("/{portfolio_id}/scenario")
def scenario(portfolio_id: UUID, body: ScenarioIn, scope: ScopeDep, db: DbDep) -> dict:
    return service.run_scenario(db, scope, portfolio_id, [s.model_dump() for s in body.shocks])
