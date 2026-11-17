"""Tenant-private Markets data: watchlists, alert rules, notifications and saved workspaces."""

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from core.db import Base, CreatedMixin, IdMixin, TenantMixin


class Watchlist(IdMixin, CreatedMixin, TenantMixin, Base):
    __tablename__ = "watchlists"
    __table_args__ = (UniqueConstraint("tenant_id", "user_id", "name"),)

    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), index=True)
    name: Mapped[str] = mapped_column(String(80))
    shared: Mapped[bool] = mapped_column(Boolean, default=False)  # visible to the whole organization


class WatchlistItem(IdMixin, CreatedMixin, TenantMixin, Base):
    __tablename__ = "watchlist_items"
    __table_args__ = (UniqueConstraint("watchlist_id", "instrument_id"),)

    watchlist_id: Mapped[UUID] = mapped_column(ForeignKey("watchlists.id", ondelete="CASCADE"), index=True)
    instrument_id: Mapped[UUID] = mapped_column(ForeignKey("instruments.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(Integer, default=0)
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    note: Mapped[str] = mapped_column(String(200), default="")


class AlertRule(IdMixin, CreatedMixin, TenantMixin, Base):
    __tablename__ = "alert_rules"

    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), index=True)
    series_id: Mapped[UUID] = mapped_column(ForeignKey("series.id", ondelete="CASCADE"), index=True)
    instrument_id: Mapped[UUID | None] = mapped_column(ForeignKey("instruments.id", ondelete="CASCADE"))
    condition: Mapped[str] = mapped_column(String(20))  # above, below, change_pct_above, change_pct_below
    threshold: Mapped[Decimal] = mapped_column(Numeric(28, 10))
    note: Mapped[str] = mapped_column(String(200), default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    cooldown_minutes: Mapped[int] = mapped_column(Integer, default=1440)
    last_triggered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Notification(IdMixin, CreatedMixin, TenantMixin, Base):
    __tablename__ = "notifications"

    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), index=True)
    kind: Mapped[str] = mapped_column(String(20))  # alert, thesis, document, system
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text, default="")
    link: Mapped[str] = mapped_column(String(300), default="")
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Workspace(IdMixin, CreatedMixin, TenantMixin, Base):
    __tablename__ = "workspaces"
    __table_args__ = (UniqueConstraint("tenant_id", "user_id", "name"),)

    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), index=True)
    name: Mapped[str] = mapped_column(String(80))
    layout: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
