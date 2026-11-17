"""Tenant-private Intelligence data: the evidence ledger (answer records) and saved theses."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from core.db import Base, CreatedMixin, IdMixin, TenantMixin


class AnswerRecord(IdMixin, CreatedMixin, TenantMixin, Base):
    """Reproducible record of an AI answer or report: question, scope, data versions, claims and gaps."""

    __tablename__ = "answer_records"

    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), index=True)
    kind: Mapped[str] = mapped_column(String(20), default="answer")  # answer, report
    agent: Mapped[str] = mapped_column(String(40), default="research")
    title: Mapped[str] = mapped_column(String(200), default="")
    question: Mapped[str] = mapped_column(Text)
    scope: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    engine: Mapped[str] = mapped_column(String(40), default="offline")
    model_id: Mapped[str] = mapped_column(String(80), default="")
    status: Mapped[str] = mapped_column(String(20), default="complete")
    answer: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)  # blocks, claims, evidence, gaps
    data_versions: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    usage: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    shared: Mapped[bool] = mapped_column(default=False)


class Thesis(IdMixin, CreatedMixin, TenantMixin, Base):
    """A saved hypothesis with monitored conditions. New data that contradicts a condition raises a signal."""

    __tablename__ = "theses"

    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), index=True)
    title: Mapped[str] = mapped_column(String(160))
    statement: Mapped[str] = mapped_column(Text, default="")
    conditions: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    status: Mapped[str] = mapped_column(String(20), default="holding")  # holding, challenged, closed
    history: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
