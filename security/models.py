"""Access model: tenants, users, roles, sessions, API keys, invitations and usage counters.

Sign-in, key resolution and invitations run in system sessions, before a tenant is known.
"""

from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from core.db import Base, CreatedMixin, IdMixin, TenantMixin


class Tenant(IdMixin, CreatedMixin, Base):
    __tablename__ = "tenants"

    name: Mapped[str] = mapped_column(String(120))
    slug: Mapped[str] = mapped_column(String(63), unique=True)
    plan: Mapped[str] = mapped_column(String(30), default="community")
    status: Mapped[str] = mapped_column(String(20), default="active")
    stripe_customer_id: Mapped[str | None] = mapped_column(String(80), unique=True)
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(80))
    # Which data classes may be sent to external model providers (section 4.7, rule 6).
    model_policy: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class User(IdMixin, CreatedMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(254), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(120), default="")
    is_platform_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Membership(CreatedMixin, Base):
    __tablename__ = "memberships"

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True)
    role: Mapped[str] = mapped_column(String(20), default="analyst")


class UserSession(IdMixin, CreatedMixin, Base):
    __tablename__ = "user_sessions"
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ApiKey(IdMixin, CreatedMixin, TenantMixin, Base):
    __tablename__ = "api_keys"

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(80))
    prefix: Mapped[str] = mapped_column(String(20))
    key_hash: Mapped[str] = mapped_column(String(64), unique=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Invite(IdMixin, CreatedMixin, TenantMixin, Base):
    __tablename__ = "invites"

    email: Mapped[str] = mapped_column(String(254))
    role: Mapped[str] = mapped_column(String(20), default="analyst")
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_by: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UsageCounter(TenantMixin, Base):
    __tablename__ = "usage_counters"
    __table_args__ = (UniqueConstraint("tenant_id", "metric", "day"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    metric: Mapped[str] = mapped_column(String(60))
    day: Mapped[date] = mapped_column(Date)
    count: Mapped[int] = mapped_column(Integer, default=0)


class BillingEvent(Base):
    """Processed payment-provider events, kept so a webhook delivered twice is applied once."""

    __tablename__ = "billing_events"

    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    type: Mapped[str] = mapped_column(String(80))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
