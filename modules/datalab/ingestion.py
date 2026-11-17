"""Ingestion flow: fetch, validate, normalize, quality rules, versioned store, freshness (section 4.6).

A schema violation stops the run: nothing from it is stored and the previous version stays in place.
"""

import hashlib
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any
from uuid import UUID

from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from core.canonical import Batch
from core.db import system_session
from core.errors import AurexError, NotFound, ValidationFailure
from core.types import utcnow
from modules.datalab.models import (
    CalendarEvent,
    ConnectorRun,
    Dataset,
    Document,
    Entity,
    Fact,
    Instrument,
    LicenseRecord,
    Passage,
    Series,
)
from modules.datalab.quality import assess, split_passages
from modules.integration import demo, ecb, sec
from modules.logging import Severity, log

Connector = Callable[[dict[str, Any], date | None], Batch]
CONNECTORS: dict[str, Connector] = {
    "demo": demo.fetch,
    "ecb_fx": ecb.fetch_fx,
    "ecb_series": ecb.fetch_series,
    "ecb_press": ecb.fetch_press,
    "sec_index": sec.fetch_index,
    "sec_company": sec.fetch_company,
}
FULL_REFRESH = {"sec_index", "sec_company", "ecb_press"}
Screen = Callable[[str], bool]
CHUNK = 1000


@dataclass
class RunResult:
    run_id: UUID
    dataset: str
    status: str
    stored: dict[str, int] = field(default_factory=dict)
    series_ids: list[UUID] = field(default_factory=list)
    new_document_ids: list[UUID] = field(default_factory=list)
    error_code: str = ""


def _chunks(rows: list, size: int = CHUNK):
    for i in range(0, len(rows), size):
        yield rows[i : i + size]


def run_dataset(
    code: str, *, trigger: str = "schedule", params: dict[str, Any] | None = None, screen: Screen | None = None
) -> RunResult:
    """Run one connector for one dataset. ``screen`` flags instruction-like passages (injected by the caller)."""
    with system_session() as session:
        dataset = session.scalar(select(Dataset).where(Dataset.code == code))
        if dataset is None:
            raise NotFound("Dataset not found")
        if session.get(LicenseRecord, dataset.license_id) is None:
            raise ValidationFailure("A dataset without a license record is not ingested")
        connector = CONNECTORS.get(dataset.connector)
        if connector is None:
            raise ValidationFailure("Dataset has no ingestion connector")
        run = ConnectorRun(dataset_id=dataset.id, trigger=trigger)
        session.add(run)
        session.flush()
        run_id, dataset_id = run.id, dataset.id
        config = {**dataset.config, **(params or {})}
        since = None
        if dataset.connector not in FULL_REFRESH and dataset.latest_ref_time is not None:
            since = (dataset.latest_ref_time - timedelta(days=int(config.get("overlap_days", 14)))).date()
        if dataset.connector == "sec_company":
            known = session.scalars(
                select(Document.key).where(Document.dataset_id == dataset_id, Document.passage_count > 1)
            ).all()
            config["known_documents"] = set(known)

    try:
        try:
            batch = connector(config, since)
        except PydanticValidationError as exc:
            raise ValidationFailure(
                "Provider data failed schema validation", details={"issues": len(exc.errors())}
            ) from exc
        with system_session() as session:
            dataset = session.get(Dataset, dataset_id)
            result = _store(session, dataset, run_id, batch, screen)
            run = session.get(ConnectorRun, run_id)
            run.status, run.finished_at = "success", utcnow()
            run.received, run.stored, run.quality = batch.counts(), result.stored, result.quality
            dataset.status, dataset.status_detail = "ok", ""
            dataset.last_run_at = dataset.last_success_at = utcnow()
            dataset.consecutive_failures = 0
        log("datalab", "ingestion.completed", dataset=code, stored=result.stored, quality=result.quality)
        return RunResult(run_id, code, "success", result.stored, result.series_ids, result.new_document_ids)
    except AurexError as exc:
        return _fail(run_id, dataset_id, code, exc.code, exc.message)
    except Exception as exc:  # noqa: BLE001 - a connector fault must not stop the worker
        return _fail(run_id, dataset_id, code, "internal_error", type(exc).__name__)


def _fail(run_id: UUID, dataset_id: UUID, code: str, error_code: str, detail: str) -> RunResult:
    with system_session() as session:
        run = session.get(ConnectorRun, run_id)
        dataset = session.get(Dataset, dataset_id)
        run.status, run.finished_at = "failed", utcnow()
        run.error_code, run.error_detail = error_code, detail[:400]
        dataset.last_run_at = utcnow()
        dataset.status = "not_configured" if error_code == "connector_not_configured" else "failed"
        dataset.status_detail = detail[:300]
        dataset.consecutive_failures += 1
        failures = dataset.consecutive_failures
    repeated = failures >= 3 and error_code == "validation_failed"
    log(
        "datalab",
        "ingestion.failed",
        Severity.SECURITY if repeated else Severity.WARN,
        dataset=code,
        error_code=error_code,
        consecutive_failures=failures,
    )
    return RunResult(run_id, code, "failed", error_code=error_code)


@dataclass
class _Stored:
    stored: dict[str, int]
    quality: dict[str, int]
    series_ids: list[UUID]
    new_document_ids: list[UUID]


def _store(session: Session, dataset: Dataset, run_id: UUID, batch: Batch, screen: Screen | None) -> _Stored:
    stored: dict[str, int] = {}

    # Entities
    for rows in _chunks([e.model_dump() | {"dataset_id": dataset.id} for e in batch.entities]):
        stmt = pg_insert(Entity).values(rows)
        ex = stmt.excluded
        session.execute(
            stmt.on_conflict_do_update(
                index_elements=[Entity.key],
                set_={
                    "name": ex.name,
                    "ticker": func.coalesce(ex.ticker, Entity.ticker),
                    "cik": func.coalesce(ex.cik, Entity.cik),
                    "lei": func.coalesce(ex.lei, Entity.lei),
                    "country": func.coalesce(ex.country, Entity.country),
                    "sector": func.coalesce(ex.sector, Entity.sector),
                    "industry": func.coalesce(ex.industry, Entity.industry),
                    "meta": Entity.meta.op("||")(ex.meta),
                },
            )
        )
    stored["entities"] = len(batch.entities)
    entity_keys = {
        k
        for k in (
            [e.key for e in batch.entities]
            + [i.entity_key for i in batch.instruments]
            + [d.entity_key for d in batch.documents]
            + [f.entity_key for f in batch.facts]
            + [e.entity_key for e in batch.events]
        )
        if k
    }
    entity_ids: dict[str, UUID] = {}
    for keys in _chunks(sorted(entity_keys), 5000):
        entity_ids.update(session.execute(select(Entity.key, Entity.id).where(Entity.key.in_(keys))).all())

    def entity_id(key: str | None) -> UUID | None:
        if key is None:
            return None
        if key not in entity_ids:
            raise ValidationFailure("Batch refers to an unknown entity")
        return entity_ids[key]

    # Instruments
    rows = [
        {
            "symbol": i.symbol,
            "name": i.name,
            "type": i.type.value,
            "currency": i.currency,
            "venue": i.venue,
            "status": i.status,
            "entity_id": entity_id(i.entity_key),
            "external_ids": i.external_ids,
            "dataset_id": dataset.id,
            "tenant_id": dataset.tenant_id,
        }
        for i in batch.instruments
    ]
    for part in _chunks(rows):
        stmt = pg_insert(Instrument).values(part)
        ex = stmt.excluded
        session.execute(
            stmt.on_conflict_do_update(
                index_elements=[Instrument.symbol],
                set_={
                    "name": ex.name,
                    "venue": ex.venue,
                    "status": ex.status,
                    "entity_id": ex.entity_id,
                    "external_ids": ex.external_ids,
                    "currency": ex.currency,
                },
                where=Instrument.dataset_id == dataset.id,
            )
        )
    stored["instruments"] = len(rows)
    symbols = [s.instrument_symbol for s in batch.series if s.instrument_symbol]
    instrument_ids = (
        dict(session.execute(select(Instrument.symbol, Instrument.id).where(Instrument.symbol.in_(symbols))).all())
        if symbols
        else {}
    )

    # Series
    for s in batch.series:
        stmt = pg_insert(Series).values(
            code=s.code,
            name=s.name,
            kind=s.kind,
            unit=s.unit,
            currency=s.currency,
            frequency=s.frequency,
            has_ohlc=s.has_ohlc,
            instrument_id=instrument_ids.get(s.instrument_symbol),
            dataset_id=dataset.id,
            tenant_id=dataset.tenant_id,
        )
        session.execute(
            stmt.on_conflict_do_update(
                index_elements=[Series.code],
                set_={
                    "name": s.name,
                    "unit": s.unit,
                    "currency": s.currency,
                    "frequency": s.frequency,
                    "has_ohlc": s.has_ohlc,
                    "instrument_id": instrument_ids.get(s.instrument_symbol),
                },
                where=Series.dataset_id == dataset.id,
            )
        )
    stored["series"] = len(batch.series)

    # Observations: quality rules, then a new version only where a value is new or changed
    series_rows = {}
    quality: dict[str, int] = {}
    if batch.observations:
        codes = sorted({o.series_code for o in batch.observations})
        series_rows = {
            r.code: r
            for r in session.execute(
                select(Series.code, Series.id, Series.latest_value).where(
                    Series.code.in_(codes), Series.dataset_id == dataset.id
                )
            )
        }
        if missing := set(codes) - set(series_rows):
            raise ValidationFailure("Observations refer to an undeclared series", details={"count": len(missing)})
        kept, quality = assess(batch.series, batch.observations)
        stored["observations"] = _store_observations(session, run_id, dataset.tenant_id, series_rows, kept)
        ids = [r.id for r in series_rows.values()]
        session.execute(text(_REFRESH_LATEST), {"ids": ids})
        dataset.latest_ref_time = session.scalar(
            select(func.max(Series.latest_ref_time)).where(Series.dataset_id == dataset.id)
        )

    # Documents and passages
    new_documents: list[UUID] = []
    flagged = 0
    for doc in batch.documents:
        body = doc.body or doc.title
        digest = hashlib.sha256(body.encode()).hexdigest()
        existing = session.scalar(select(Document).where(Document.dataset_id == dataset.id, Document.key == doc.key))
        if existing and (existing.content_hash == digest or existing.passage_count > 1 >= body.count("\n")):
            continue  # unchanged, or a stored full text that this run did not fetch again
        row = existing or Document(dataset_id=dataset.id, key=doc.key, tenant_id=dataset.tenant_id)
        row.entity_id, row.doc_type, row.title = entity_id(doc.entity_key), doc.doc_type, doc.title
        row.url, row.published_at, row.language = doc.url, doc.published_at, doc.language
        row.content_hash, row.meta = digest, doc.meta
        session.add(row)
        session.flush()
        if existing:
            session.execute(delete(Passage).where(Passage.document_id == row.id))
        else:
            new_documents.append(row.id)
        parts = split_passages(body)
        passages = []
        for ordinal, (location, chunk) in enumerate(parts):
            bad = bool(screen and screen(chunk))
            flagged += bad
            passages.append(
                {
                    "document_id": row.id,
                    "tenant_id": dataset.tenant_id,
                    "ordinal": ordinal,
                    "location": location,
                    "text": chunk,
                    "flagged": bad,
                }
            )
        for part in _chunks(passages, 500):
            session.execute(pg_insert(Passage).values(part))
        row.passage_count = len(passages)
        row.screening = "flagged" if any(p["flagged"] for p in passages) else "clear"
        if dataset.latest_ref_time is None or doc.published_at > dataset.latest_ref_time:
            dataset.latest_ref_time = doc.published_at
    stored["documents"] = len(new_documents)
    if flagged:
        quality["flagged_passages"] = flagged

    # Facts: one row per reported value and filing; a restatement is a new row with a later filing date
    fact_rows = [
        f.model_dump(exclude={"entity_key"}) | {"entity_id": entity_id(f.entity_key), "dataset_id": dataset.id}
        for f in batch.facts
    ]
    inserted = 0
    for part in _chunks(fact_rows):
        inserted += len(session.execute(pg_insert(Fact).values(part).on_conflict_do_nothing().returning(Fact.id)).all())
    stored["facts"] = inserted
    if batch.facts:
        session.execute(
            update(Entity)
            .where(Entity.id.in_({r["entity_id"] for r in fact_rows}))
            .values(facts_synced_at=utcnow(), tracked=True)
        )

    # Calendar events
    series_by_code = {c: r.id for c, r in series_rows.items()}
    for event in batch.events:
        stmt = pg_insert(CalendarEvent).values(
            dataset_id=dataset.id,
            key=event.key,
            kind=event.kind,
            title=event.title,
            scheduled_at=event.scheduled_at,
            entity_id=entity_id(event.entity_key),
            series_id=series_by_code.get(event.series_code),
            meta=event.meta,
        )
        session.execute(
            stmt.on_conflict_do_update(
                index_elements=[CalendarEvent.dataset_id, CalendarEvent.key],
                set_={"title": event.title, "scheduled_at": event.scheduled_at, "meta": event.meta},
            )
        )
    stored["events"] = len(batch.events)
    return _Stored(stored, quality, [r.id for r in series_rows.values()], new_documents)


_REFRESH_LATEST = """
UPDATE series s SET latest_ref_time = l.ref_time, latest_value = l.value, previous_value = l.prev
FROM (
    SELECT series_id, ref_time, value, prev FROM (
        SELECT series_id, ref_time, value,
               LEAD(value) OVER (PARTITION BY series_id ORDER BY ref_time DESC) AS prev,
               ROW_NUMBER() OVER (PARTITION BY series_id ORDER BY ref_time DESC) AS rn
        FROM (
            SELECT DISTINCT ON (series_id, ref_time) series_id, ref_time, value
            FROM observations WHERE series_id = ANY(:ids)
            ORDER BY series_id, ref_time, version DESC
        ) current_values
    ) ranked WHERE rn = 1
) l WHERE s.id = l.series_id
"""

_INSERT_VERSIONS = """
INSERT INTO observations (series_id, ref_time, version, value, open, high, low, volume, known_at, quality,
                          run_id, tenant_id)
SELECT i.series_id, i.ref_time, COALESCE(cur.version, 0) + 1, i.value, i.open, i.high, i.low, i.volume,
       CASE WHEN cur.version IS NULL THEN COALESCE(i.known_at, now()) ELSE now() END, i.quality,
       %(run)s, %(tenant)s
FROM _obs_in i
LEFT JOIN LATERAL (
    SELECT version, value, open, high, low, volume FROM observations o
    WHERE o.series_id = i.series_id AND o.ref_time = i.ref_time ORDER BY version DESC LIMIT 1
) cur ON true
WHERE cur.version IS NULL OR cur.value IS DISTINCT FROM i.value OR cur.open IS DISTINCT FROM i.open
   OR cur.high IS DISTINCT FROM i.high OR cur.low IS DISTINCT FROM i.low OR cur.volume IS DISTINCT FROM i.volume
"""


def _store_observations(
    session: Session, run_id: UUID, tenant_id: UUID | None, series_rows: dict, observations: list
) -> int:
    raw = session.connection().connection.driver_connection
    with raw.cursor() as cursor:
        cursor.execute(
            "CREATE TEMP TABLE IF NOT EXISTS _obs_in (series_id uuid, ref_time timestamptz, value numeric, "
            "open numeric, high numeric, low numeric, volume numeric, known_at timestamptz, quality text) "
            "ON COMMIT DROP"
        )
        cursor.execute("TRUNCATE _obs_in")
        with cursor.copy(
            "COPY _obs_in (series_id, ref_time, value, open, high, low, volume, known_at, quality) FROM STDIN"
        ) as copy:
            for o in observations:
                copy.write_row(
                    (
                        series_rows[o.series_code].id,
                        o.ref_time,
                        o.value,
                        o.open,
                        o.high,
                        o.low,
                        o.volume,
                        o.known_at,
                        o.quality.value,
                    )
                )
        cursor.execute(_INSERT_VERSIONS, {"run": run_id, "tenant": tenant_id})
        return cursor.rowcount
