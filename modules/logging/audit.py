"""Append-only audit trail. A database trigger rejects UPDATE and DELETE on ``audit_events``."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, Session, mapped_column

from core.db import Base, IdMixin
from modules.logging.log import Severity, log, sanitize


class AuditEvent(IdMixin, Base):
    __tablename__ = "audit_events"

    tenant_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), index=True)
    actor_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    action: Mapped[str] = mapped_column(String(80), index=True)
    object_type: Mapped[str] = mapped_column(String(60), default="")
    object_id: Mapped[str] = mapped_column(String(80), default="")
    outcome: Mapped[str] = mapped_column(String(20), default="success")
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


def record_audit(
    session: Session,
    *,
    action: str,
    tenant_id: UUID | None = None,
    actor_id: UUID | None = None,
    object_type: str = "",
    object_id: object = "",
    outcome: str = "success",
    **details: Any,
) -> None:
    """Record a security-relevant action in the caller's transaction and mirror it to the log."""
    session.add(
        AuditEvent(
            tenant_id=tenant_id,
            actor_id=actor_id,
            action=action,
            object_type=object_type,
            object_id=str(object_id or ""),
            outcome=outcome,
            details=sanitize(details),
        )
    )
    severity = Severity.SECURITY if outcome in ("denied", "failure") else Severity.INFO
    log(
        "audit",
        action,
        severity,
        tenant=str(tenant_id or ""),
        actor=str(actor_id or ""),
        object_type=object_type,
        object_id=str(object_id or ""),
        outcome=outcome,
    )
