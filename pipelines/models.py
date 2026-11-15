"""Job queue in PostgreSQL (ADR-0005): one queue technology, idempotent jobs, each recorded as a run."""

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Index, Integer, String, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from core.db import Base, CreatedMixin, IdMixin


class Job(IdMixin, CreatedMixin, Base):
    __tablename__ = "jobs"
    __table_args__ = (
        Index("ix_jobs_due", "status", "run_after"),
        # At most one queued or running job per dedupe key.
        Index(
            "uq_jobs_dedupe",
            "dedupe_key",
            unique=True,
            postgresql_where=text("status IN ('queued', 'running') AND dedupe_key IS NOT NULL"),
        ),
    )

    kind: Mapped[str] = mapped_column(String(60))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    dedupe_key: Mapped[str | None] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(12), default="queued")  # queued, running, done, failed
    run_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    error: Mapped[str] = mapped_column(String(300), default="")
