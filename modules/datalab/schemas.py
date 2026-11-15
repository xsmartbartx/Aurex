"""Objects returned by the DataLab access interface. No value leaves without its provenance."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Provenance(Out):
    dataset: str
    dataset_name: str
    provider: str
    license_class: str
    attribution: str
    terms_url: str = ""
    freshness_class: str
    delay_minutes: int = 0
    status: str  # ok, stale, failed, never_run, not_configured
    last_success_at: datetime | None = None
    latest_ref_time: datetime | None = None
    export_allowed: bool = False


class InstrumentOut(Out):
    id: UUID
    symbol: str
    name: str
    type: str
    currency: str | None = None
    venue: str | None = None
    status: str = "active"
    entity_id: UUID | None = None
    dataset: str = ""
    license_class: str = ""
    has_prices: bool = False


class Quote(Out):
    instrument_id: UUID
    series_id: UUID
    series_code: str
    unit: str
    currency: str | None = None
    last: float | None = None
    previous: float | None = None
    change: float | None = None
    change_pct: float | None = None
    ref_time: datetime | None = None
    freshness_class: str = ""
    status: str = ""
    license_class: str = ""


class SeriesOut(Out):
    id: UUID
    code: str
    name: str
    kind: str
    unit: str
    currency: str | None = None
    frequency: str
    has_ohlc: bool = False
    instrument_id: UUID | None = None
    latest_ref_time: datetime | None = None
    latest_value: float | None = None


class Point(Out):
    t: datetime
    v: float
    o: float | None = None
    h: float | None = None
    l: float | None = None  # noqa: E741 - conventional OHLC key
    vol: float | None = None
    q: str = "validated"
    known_at: datetime | None = None
    version: int = 1


class SeriesData(Out):
    series: SeriesOut
    provenance: Provenance
    as_of: datetime | None = None
    points: list[Point]


class EntityOut(Out):
    id: UUID
    key: str
    kind: str
    name: str
    ticker: str | None = None
    cik: str | None = None
    country: str | None = None
    sector: str | None = None
    industry: str | None = None
    tracked: bool = False
    facts_synced_at: datetime | None = None
    meta: dict[str, Any] = {}


class FactOut(Out):
    id: int
    concept: str
    label: str = ""
    unit: str
    value: Decimal
    period_start: date | None = None
    period_end: date
    fiscal_year: int | None = None
    fiscal_period: str | None = None
    form: str | None = None
    accession: str
    filed_at: date


class DocumentOut(Out):
    id: UUID
    doc_type: str
    title: str
    url: str | None = None
    published_at: datetime
    language: str = "en"
    entity_id: UUID | None = None
    entity_name: str | None = None
    passage_count: int = 0
    screening: str = "clear"
    private: bool = False
    dataset: str = ""
    license_class: str = ""
    attribution: str = ""
    meta: dict[str, Any] = {}


class PassageOut(Out):
    id: int
    document_id: UUID
    ordinal: int
    location: str
    text: str
    flagged: bool = False


class PassageHit(Out):
    passage: PassageOut
    document: DocumentOut
    rank: float = 0.0
    headline: str = ""


class DatasetOut(Out):
    id: UUID
    code: str
    name: str
    description: str = ""
    provider: str
    connector: str
    freshness_class: str
    interval_minutes: int
    enabled: bool
    status: str
    status_detail: str = ""
    last_run_at: datetime | None = None
    last_success_at: datetime | None = None
    latest_ref_time: datetime | None = None
    private: bool = False
    license: "LicenseOut"
    counts: dict[str, int] = {}


class LicenseOut(Out):
    code: str
    provider: str
    data_class: str
    agreement_ref: str = ""
    terms_url: str = ""
    attribution: str = ""
    allow_display: bool
    allow_export: bool
    allow_api: bool
    allow_derived: bool
    allow_model_external: bool
    allow_model_local: bool
    required_delay_minutes: int = 0
    territories: str = ""
    expires_at: datetime | None = None
    notes: str = ""


class RunOut(Out):
    id: UUID
    started_at: datetime
    finished_at: datetime | None = None
    status: str
    trigger: str
    received: dict[str, Any] = {}
    stored: dict[str, Any] = {}
    quality: dict[str, Any] = {}
    error_code: str = ""
    error_detail: str = ""


class EventOut(Out):
    id: UUID
    kind: str
    title: str
    scheduled_at: datetime
    entity_id: UUID | None = None
    meta: dict[str, Any] = {}


DatasetOut.model_rebuild()
