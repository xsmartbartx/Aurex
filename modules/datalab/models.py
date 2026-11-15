"""Shared data owned by DataLab: license register, dataset catalog, lineage and the canonical store.

Point in time (section 4.5, rule 1): observations and facts keep the time they refer to and the time
they became known. A correction adds a version; nothing is overwritten.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    Computed,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from core.db import Base, CreatedMixin, IdMixin

NUM = Numeric(28, 10)


class LicenseRecord(IdMixin, CreatedMixin, Base):
    """Terms for a dataset (section 4.11). Enforced at ingestion, retrieval, AI context and output."""

    __tablename__ = "license_records"

    code: Mapped[str] = mapped_column(String(60), unique=True)
    provider: Mapped[str] = mapped_column(String(120))
    data_class: Mapped[str] = mapped_column(String(20))
    agreement_ref: Mapped[str] = mapped_column(String(200), default="")
    terms_url: Mapped[str] = mapped_column(String(400), default="")
    attribution: Mapped[str] = mapped_column(String(400), default="")
    allow_display: Mapped[bool] = mapped_column(Boolean, default=True)
    allow_export: Mapped[bool] = mapped_column(Boolean, default=False)
    allow_api: Mapped[bool] = mapped_column(Boolean, default=False)
    allow_derived: Mapped[bool] = mapped_column(Boolean, default=True)
    allow_model_external: Mapped[bool] = mapped_column(Boolean, default=False)
    allow_model_local: Mapped[bool] = mapped_column(Boolean, default=True)
    required_delay_minutes: Mapped[int] = mapped_column(Integer, default=0)
    retention_days: Mapped[int | None] = mapped_column(Integer)
    territories: Mapped[str] = mapped_column(String(200), default="worldwide")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str] = mapped_column(Text, default="")


class Dataset(IdMixin, CreatedMixin, Base):
    __tablename__ = "datasets"
    __table_args__ = {"info": {"rls": "shared"}}

    code: Mapped[str] = mapped_column(String(60), unique=True)
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text, default="")
    provider: Mapped[str] = mapped_column(String(120))
    connector: Mapped[str] = mapped_column(String(40))
    license_id: Mapped[UUID] = mapped_column(ForeignKey("license_records.id"))  # no dataset without a license
    tenant_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), index=True)  # customer-supplied data
    freshness_class: Mapped[str] = mapped_column(String(20))
    interval_minutes: Mapped[int] = mapped_column(Integer, default=1440)
    stale_after_minutes: Mapped[int] = mapped_column(Integer, default=4320)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(20), default="never_run")
    status_detail: Mapped[str] = mapped_column(String(300), default="")
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    latest_ref_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)


class ConnectorRun(IdMixin, Base):
    __tablename__ = "connector_runs"

    dataset_id: Mapped[UUID] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="running")
    trigger: Mapped[str] = mapped_column(String(20), default="schedule")
    received: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    stored: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    quality: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    error_code: Mapped[str] = mapped_column(String(60), default="")
    error_detail: Mapped[str] = mapped_column(String(400), default="")


class Entity(IdMixin, CreatedMixin, Base):
    __tablename__ = "entities"

    key: Mapped[str] = mapped_column(String(80), unique=True)
    kind: Mapped[str] = mapped_column(String(20), default="company")
    name: Mapped[str] = mapped_column(String(200))
    ticker: Mapped[str | None] = mapped_column(String(32), index=True)
    cik: Mapped[str | None] = mapped_column(String(10), index=True)
    lei: Mapped[str | None] = mapped_column(String(20))
    country: Mapped[str | None] = mapped_column(String(2))
    sector: Mapped[str | None] = mapped_column(String(120))
    industry: Mapped[str | None] = mapped_column(String(160))
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    dataset_id: Mapped[UUID] = mapped_column(ForeignKey("datasets.id"))
    tracked: Mapped[bool] = mapped_column(Boolean, default=False)  # fundamentals and filings are ingested
    facts_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Instrument(IdMixin, CreatedMixin, Base):
    __tablename__ = "instruments"
    __table_args__ = (
        Index("ix_instruments_name_trgm", "name", postgresql_using="gin", postgresql_ops={"name": "gin_trgm_ops"}),
        {"info": {"rls": "shared"}},
    )

    tenant_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), index=True)
    symbol: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    type: Mapped[str] = mapped_column(String(20), index=True)
    currency: Mapped[str | None] = mapped_column(String(3))
    venue: Mapped[str | None] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20), default="active")
    entity_id: Mapped[UUID | None] = mapped_column(ForeignKey("entities.id"), index=True)
    external_ids: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    dataset_id: Mapped[UUID] = mapped_column(ForeignKey("datasets.id"), index=True)


class Series(IdMixin, CreatedMixin, Base):
    __tablename__ = "series"
    __table_args__ = {"info": {"rls": "shared"}}

    tenant_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), index=True)
    code: Mapped[str] = mapped_column(String(80), unique=True)
    name: Mapped[str] = mapped_column(String(240))
    kind: Mapped[str] = mapped_column(String(20))
    unit: Mapped[str] = mapped_column(String(40))
    currency: Mapped[str | None] = mapped_column(String(3))
    frequency: Mapped[str] = mapped_column(String(2))
    has_ohlc: Mapped[bool] = mapped_column(Boolean, default=False)
    instrument_id: Mapped[UUID | None] = mapped_column(ForeignKey("instruments.id"), index=True)
    dataset_id: Mapped[UUID] = mapped_column(ForeignKey("datasets.id"), index=True)
    latest_ref_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    latest_value: Mapped[Decimal | None] = mapped_column(NUM)
    previous_value: Mapped[Decimal | None] = mapped_column(NUM)


class Observation(Base):
    __tablename__ = "observations"
    __table_args__ = (
        Index("ix_observations_series_known", "series_id", "known_at"),
        {"info": {"rls": "shared"}},
    )

    tenant_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))  # set for customer-supplied data
    series_id: Mapped[UUID] = mapped_column(ForeignKey("series.id", ondelete="CASCADE"), primary_key=True)
    ref_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    value: Mapped[Decimal] = mapped_column(NUM)
    open: Mapped[Decimal | None] = mapped_column(NUM)
    high: Mapped[Decimal | None] = mapped_column(NUM)
    low: Mapped[Decimal | None] = mapped_column(NUM)
    volume: Mapped[Decimal | None] = mapped_column(NUM)
    known_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    quality: Mapped[str] = mapped_column(String(20), default="validated")
    run_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))


class Document(IdMixin, Base):
    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint("dataset_id", "key"),
        Index("ix_documents_published", "published_at"),
        {"info": {"rls": "shared"}},
    )

    tenant_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), index=True)
    dataset_id: Mapped[UUID] = mapped_column(ForeignKey("datasets.id"), index=True)
    key: Mapped[str] = mapped_column(String(200))
    entity_id: Mapped[UUID | None] = mapped_column(ForeignKey("entities.id"), index=True)
    doc_type: Mapped[str] = mapped_column(String(40), index=True)
    title: Mapped[str] = mapped_column(String(400))
    url: Mapped[str | None] = mapped_column(String(600))
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    language: Mapped[str] = mapped_column(String(8), default="en")
    content_hash: Mapped[str] = mapped_column(String(64), default="")
    passage_count: Mapped[int] = mapped_column(Integer, default=0)
    screening: Mapped[str] = mapped_column(String(20), default="clear")
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class Passage(Base):
    __tablename__ = "passages"
    __table_args__ = (
        Index("ix_passages_tsv", "tsv", postgresql_using="gin"),
        UniqueConstraint("document_id", "ordinal"),
        {"info": {"rls": "shared"}},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    tenant_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), index=True)
    ordinal: Mapped[int] = mapped_column(Integer)
    location: Mapped[str] = mapped_column(String(200), default="")
    text: Mapped[str] = mapped_column(Text)
    flagged: Mapped[bool] = mapped_column(Boolean, default=False)  # instruction-like content
    tsv: Mapped[Any] = mapped_column(TSVECTOR, Computed("to_tsvector('english', text)", persisted=True))


class Fact(Base):
    __tablename__ = "facts"
    __table_args__ = (
        UniqueConstraint(
            "entity_id",
            "concept",
            "unit",
            "period_start",
            "period_end",
            "accession",
            postgresql_nulls_not_distinct=True,
        ),
        Index("ix_facts_entity_concept", "entity_id", "concept", "period_end"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    entity_id: Mapped[UUID] = mapped_column(ForeignKey("entities.id", ondelete="CASCADE"))
    dataset_id: Mapped[UUID] = mapped_column(ForeignKey("datasets.id"))
    concept: Mapped[str] = mapped_column(String(160))
    label: Mapped[str] = mapped_column(String(300), default="")
    unit: Mapped[str] = mapped_column(String(40))
    value: Mapped[Decimal] = mapped_column(Numeric(30, 6))
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    fiscal_year: Mapped[int | None] = mapped_column(Integer)
    fiscal_period: Mapped[str | None] = mapped_column(String(4))
    form: Mapped[str | None] = mapped_column(String(12))
    accession: Mapped[str] = mapped_column(String(30))
    filed_at: Mapped[date] = mapped_column(Date)  # the date the value became known
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CalendarEvent(IdMixin, Base):
    __tablename__ = "calendar_events"
    __table_args__ = (UniqueConstraint("dataset_id", "key"), Index("ix_calendar_events_at", "scheduled_at"))

    dataset_id: Mapped[UUID] = mapped_column(ForeignKey("datasets.id"))
    key: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(20))
    title: Mapped[str] = mapped_column(String(300))
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    entity_id: Mapped[UUID | None] = mapped_column(ForeignKey("entities.id"))
    series_id: Mapped[UUID | None] = mapped_column(ForeignKey("series.id"))
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class DatasetUsage(Base):
    """Usage per dataset and tenant, counted for reporting to licensors."""

    __tablename__ = "dataset_usage"
    dataset_id: Mapped[UUID] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    channel: Mapped[str] = mapped_column(String(20), primary_key=True)  # display, api, export, model
    count: Mapped[int] = mapped_column(Integer, default=0)
