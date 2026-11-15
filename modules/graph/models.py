"""Market Impact Graph (ADR-0011). A link cannot exist without source, method and confidence."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, Numeric, SmallInteger, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from core.db import Base, CreatedMixin, IdMixin


class GraphNode(IdMixin, CreatedMixin, Base):
    __tablename__ = "graph_nodes"
    __table_args__ = (
        Index("uq_graph_nodes_key", "tenant_id", "key", unique=True, postgresql_nulls_not_distinct=True),
        {"info": {"rls": "shared"}},
    )

    tenant_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), index=True)
    key: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(20))  # company, sector, commodity, currency, country, indicator,
    name: Mapped[str] = mapped_column(String(200))  # policy_event, instrument
    description: Mapped[str] = mapped_column(Text, default="")
    entity_id: Mapped[UUID | None] = mapped_column(ForeignKey("entities.id", ondelete="SET NULL"))
    instrument_id: Mapped[UUID | None] = mapped_column(ForeignKey("instruments.id", ondelete="SET NULL"))
    series_id: Mapped[UUID | None] = mapped_column(ForeignKey("series.id", ondelete="SET NULL"))
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class GraphLink(IdMixin, CreatedMixin, Base):
    __tablename__ = "graph_links"
    __table_args__ = (
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
        CheckConstraint("source_ref <> ''", name="source_required"),
        {"info": {"rls": "shared"}},
    )

    tenant_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), index=True)
    source_id: Mapped[UUID] = mapped_column(ForeignKey("graph_nodes.id", ondelete="CASCADE"), index=True)
    target_id: Mapped[UUID] = mapped_column(ForeignKey("graph_nodes.id", ondelete="CASCADE"), index=True)
    relation: Mapped[str] = mapped_column(String(30))
    method: Mapped[str] = mapped_column(String(30))  # reported_fact, statistical_estimate, analyst_defined,
    confidence: Mapped[Decimal] = mapped_column(Numeric(4, 3))  # ai_extracted
    confidence_basis: Mapped[str] = mapped_column(String(300))
    source_ref: Mapped[str] = mapped_column(String(600))
    source_passage_id: Mapped[int | None] = mapped_column(ForeignKey("passages.id", ondelete="SET NULL"))
    description: Mapped[str] = mapped_column(Text, default="")
    sign: Mapped[int] = mapped_column(SmallInteger, default=0)  # +1 same direction, -1 opposite, 0 undirected
    magnitude: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    estimation: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)  # window, error measure
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_status: Mapped[str] = mapped_column(String(12), default="proposed")  # proposed, accepted, rejected
    created_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    reviewed_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
