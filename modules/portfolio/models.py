"""Tenant-private holdings. Virtual portfolios only: no broker connection and no orders (ADR-0012)."""

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import Date, ForeignKey, Index, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from core.db import Base, CreatedMixin, IdMixin, TenantMixin

NUM = Numeric(28, 10)


class Portfolio(IdMixin, CreatedMixin, TenantMixin, Base):
    __tablename__ = "portfolios"

    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), index=True)
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text, default="")
    base_currency: Mapped[str] = mapped_column(String(3), default="EUR")
    benchmark_series_id: Mapped[UUID | None] = mapped_column(ForeignKey("series.id", ondelete="SET NULL"))
    limits: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)  # e.g. max_position_pct


class Transaction(IdMixin, CreatedMixin, TenantMixin, Base):
    __tablename__ = "transactions"
    __table_args__ = (Index("ix_transactions_portfolio_date", "portfolio_id", "executed_on"),)

    portfolio_id: Mapped[UUID] = mapped_column(ForeignKey("portfolios.id", ondelete="CASCADE"))
    instrument_id: Mapped[UUID | None] = mapped_column(ForeignKey("instruments.id"))
    type: Mapped[str] = mapped_column(String(12))  # buy, sell, deposit, withdrawal, dividend, fee
    quantity: Mapped[Decimal] = mapped_column(NUM, default=0)
    price: Mapped[Decimal] = mapped_column(NUM, default=0)  # per unit, in ``currency``
    fees: Mapped[Decimal] = mapped_column(NUM, default=0)
    currency: Mapped[str] = mapped_column(String(3))
    executed_on: Mapped[date] = mapped_column(Date)
    note: Mapped[str] = mapped_column(String(200), default="")
