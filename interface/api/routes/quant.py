"""AUREX Quant endpoints: backtests and simulations. Strategies are declarative; no user code runs."""

from datetime import date
from typing import Literal
from uuid import UUID

from fastapi import APIRouter
from pydantic import Field

from interface.api.deps import DbDep, ScopeDep
from modules.portfolio import service as portfolios
from modules.processing.backtest import STRATEGIES
from modules.quant import service
from modules.validation import Strict


class BacktestIn(Strict):
    name: str = Field(default="", max_length=120)
    symbol: str = Field(min_length=1, max_length=40)
    strategy: Literal["buy_and_hold", "sma_cross", "momentum", "rsi_reversion"]
    params: dict[str, float] = Field(default_factory=dict, max_length=6)
    start: date
    end: date
    in_sample_end: date | None = None
    cost_bps: float = Field(ge=0, le=500)
    slippage_bps: float = Field(ge=0, le=500)
    latency_days: int = Field(ge=1, le=10)
    initial_capital: float = Field(default=100_000, gt=0, le=1e12)


class SimulationIn(Strict):
    symbol: str | None = Field(default=None, max_length=40)
    portfolio_id: UUID | None = None
    horizon: int = Field(default=252, ge=1, le=756)
    paths: int = Field(default=2000, ge=100, le=20_000)
    method: Literal["bootstrap", "normal"] = "bootstrap"
    lookback_days: int = Field(default=756, ge=60, le=3000)
    seed: int | None = Field(default=None, ge=0, le=10**9)


router = APIRouter(prefix="/quant", tags=["quant"])


@router.get("/strategies")
def strategies(scope: ScopeDep) -> dict:
    return {
        "items": [
            {
                "name": name,
                "label": spec["label"],
                "params": {k: {"min": lo, "max": hi} for k, (lo, hi) in spec["params"].items()},
            }
            for name, spec in STRATEGIES.items()
        ]
    }


@router.post("/backtests", status_code=201)
def backtest(body: BacktestIn, scope: ScopeDep, db: DbDep) -> dict:
    spec = body.model_dump(mode="json")
    if spec["in_sample_end"] is None:
        spec.pop("in_sample_end")
    return service.run_backtest(db, scope, spec)


@router.post("/simulations", status_code=201)
def simulation(body: SimulationIn, scope: ScopeDep, db: DbDep) -> dict:
    if not body.symbol and not body.portfolio_id:
        from core.errors import ValidationFailure

        raise ValidationFailure("Choose an instrument or a portfolio")
    portfolio = portfolios.analytics(db, scope, body.portfolio_id) if body.portfolio_id else None
    return service.simulate(db, scope, body.model_dump(mode="json"), portfolio=portfolio)


@router.get("/runs")
def runs(scope: ScopeDep, db: DbDep) -> dict:
    return {"items": service.list_runs(db, scope)}


@router.get("/runs/{run_id}")
def run(run_id: UUID, scope: ScopeDep, db: DbDep) -> dict:
    return service.get_run(db, scope, run_id)


@router.post("/runs/{run_id}/reproduce")
def reproduce(run_id: UUID, scope: ScopeDep, db: DbDep) -> dict:
    return service.reproduce(db, scope, run_id)


@router.delete("/runs/{run_id}", status_code=204)
def delete(run_id: UUID, scope: ScopeDep, db: DbDep) -> None:
    service.delete_run(db, scope, run_id)
