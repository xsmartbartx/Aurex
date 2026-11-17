"""Tenant-private Quant data: backtest and simulation runs with their recorded inputs."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from core.db import Base, CreatedMixin, IdMixin, TenantMixin


class QuantRun(IdMixin, CreatedMixin, TenantMixin, Base):
    """A run is reproducible: the specification, the data cut-off and the engine version are stored."""

    __tablename__ = "quant_runs"

    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), index=True)
    kind: Mapped[str] = mapped_column(String(20))  # backtest, monte_carlo, stress
    name: Mapped[str] = mapped_column(String(120), default="")
    spec: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    result: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    engine_version: Mapped[str] = mapped_column(String(20), default="")
    data_as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    family: Mapped[str] = mapped_column(String(64), default="", index=True)  # variants of one idea
