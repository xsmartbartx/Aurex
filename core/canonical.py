"""Canonical interface objects (ADR-0004). Connectors produce them; ``datalab`` is the only consumer.

Every observation and fact must carry its unit and time fields; source and license class come from
the dataset it is ingested into. A batch that fails validation is rejected as a whole.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from core.types import InstrumentType, QualityStatus

Frequency = Literal["D", "B", "W", "M", "Q", "A"]


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class EntityIn(_In):
    key: str = Field(min_length=1, max_length=80)  # stable provider key, e.g. "cik:0000320193"
    kind: Literal["company", "country", "institution"] = "company"
    name: str = Field(min_length=1, max_length=200)
    ticker: str | None = Field(default=None, max_length=32)
    cik: str | None = Field(default=None, max_length=10)
    lei: str | None = Field(default=None, max_length=20)
    country: str | None = Field(default=None, max_length=2)
    sector: str | None = Field(default=None, max_length=120)
    industry: str | None = Field(default=None, max_length=160)
    meta: dict[str, Any] = Field(default_factory=dict)


class InstrumentIn(_In):
    symbol: str = Field(min_length=1, max_length=32, pattern=r"^[A-Z0-9][A-Z0-9.\-_:/=^]*$")
    name: str = Field(min_length=1, max_length=200)
    type: InstrumentType
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    venue: str | None = Field(default=None, max_length=40)
    entity_key: str | None = None
    status: Literal["active", "delisted"] = "active"
    external_ids: dict[str, str] = Field(default_factory=dict)


class SeriesIn(_In):
    code: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=240)
    kind: Literal["price", "fx", "rate", "macro", "yield"]
    unit: str = Field(min_length=1, max_length=40)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    frequency: Frequency
    instrument_symbol: str | None = None
    has_ohlc: bool = False


class ObservationIn(_In):
    series_code: str
    ref_time: datetime
    value: Decimal
    open: Decimal | None = None
    high: Decimal | None = None
    low: Decimal | None = None
    volume: Decimal | None = None
    known_at: datetime | None = None  # publication time when the provider states it
    quality: QualityStatus | None = None

    @field_validator("value", "open", "high", "low", "volume")
    @classmethod
    def _finite(cls, v: Decimal | None) -> Decimal | None:
        if v is not None and not v.is_finite():
            raise ValueError("value must be finite")
        return v

    @field_validator("ref_time", "known_at")
    @classmethod
    def _aware(cls, v: datetime | None) -> datetime | None:
        if v is not None and v.tzinfo is None:
            raise ValueError("timestamp must be timezone-aware")
        return v


class DocumentIn(_In):
    key: str = Field(min_length=1, max_length=200)  # stable provider id, e.g. an accession number
    doc_type: str = Field(min_length=1, max_length=40)
    title: str = Field(min_length=1, max_length=400)
    url: str | None = Field(default=None, max_length=600, pattern=r"^https://")
    published_at: datetime
    language: str = Field(default="en", max_length=8)
    entity_key: str | None = None
    body: str | None = None  # plain text; passages are derived from it
    meta: dict[str, Any] = Field(default_factory=dict)


class FactIn(_In):
    entity_key: str
    concept: str = Field(min_length=1, max_length=160)
    label: str = Field(default="", max_length=300)
    unit: str = Field(min_length=1, max_length=40)
    value: Decimal
    period_start: date | None = None
    period_end: date
    fiscal_year: int | None = None
    fiscal_period: str | None = Field(default=None, max_length=4)
    form: str | None = Field(default=None, max_length=12)
    accession: str = Field(min_length=1, max_length=30)
    filed_at: date


class EventIn(_In):
    key: str = Field(min_length=1, max_length=200)
    kind: Literal["filing", "release", "policy", "earnings"]
    title: str = Field(min_length=1, max_length=300)
    scheduled_at: datetime
    entity_key: str | None = None
    series_code: str | None = None
    meta: dict[str, Any] = Field(default_factory=dict)


class Batch(_In):
    """One connector result. Stored atomically: either every part passes validation or nothing is kept."""

    entities: list[EntityIn] = Field(default_factory=list)
    instruments: list[InstrumentIn] = Field(default_factory=list)
    series: list[SeriesIn] = Field(default_factory=list)
    observations: list[ObservationIn] = Field(default_factory=list)
    documents: list[DocumentIn] = Field(default_factory=list)
    facts: list[FactIn] = Field(default_factory=list)
    events: list[EventIn] = Field(default_factory=list)

    def counts(self) -> dict[str, int]:
        return {name: len(getattr(self, name)) for name in type(self).model_fields}
