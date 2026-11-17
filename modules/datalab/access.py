"""The data access interface for all modules (section 4.4, rule 2).

License enforcement points 2 to 4 live here: every read is filtered by the caller's entitlements and
by the license record of the dataset, per channel (display, api, export, model). Nothing is returned
without provenance.
"""

from collections.abc import Iterable, Sequence
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Literal
from uuid import UUID

from sqlalchemy import Text, and_, case, cast, func, literal, or_, select, text
from sqlalchemy.orm import Session

from core.errors import EntitlementDenied, LicenseDenied, NotFound
from core.types import Scope, utcnow
from modules.datalab.models import (
    CalendarEvent,
    ConnectorRun,
    Dataset,
    Document,
    Entity,
    Fact,
    Instrument,
    LicenseRecord,
    Observation,
    Passage,
    Series,
)
from modules.datalab.schemas import (
    DatasetOut,
    DocumentOut,
    EntityOut,
    EventOut,
    FactOut,
    InstrumentOut,
    LicenseOut,
    PassageHit,
    PassageOut,
    Point,
    Provenance,
    Quote,
    RunOut,
    SeriesData,
    SeriesOut,
)

Channel = Literal["display", "api", "export", "model_external", "model_local"]
_FLAG = {
    "display": "allow_display",
    "api": "allow_api",
    "export": "allow_export",
    "model_external": "allow_model_external",
    "model_local": "allow_model_local",
}


def channel_for(scope: Scope) -> Channel:
    return "api" if scope.via_api_key else "display"


def effective_status(dataset: Dataset) -> str:
    age_limit = timedelta(minutes=dataset.stale_after_minutes)
    if dataset.status == "ok" and dataset.last_success_at and utcnow() - dataset.last_success_at > age_limit:
        return "stale"
    return dataset.status


def _refusal(scope: Scope, dataset: Dataset, lic: LicenseRecord, channel: Channel) -> Exception | None:
    if dataset.tenant_id is not None and dataset.tenant_id != scope.tenant_id:
        return NotFound("Dataset not found")
    if not scope.has(f"data.{lic.data_class}"):
        return EntitlementDenied(
            "The current plan does not include this data", details={"data_class": lic.data_class, "plan": scope.plan}
        )
    if lic.expires_at is not None and lic.expires_at <= utcnow():
        return LicenseDenied("The license for this dataset has expired", details={"dataset": dataset.code})
    if not getattr(lic, _FLAG[channel]):
        return LicenseDenied(
            "The dataset license does not permit this use", details={"dataset": dataset.code, "channel": channel}
        )
    return None


def _catalog(session: Session) -> list[tuple[Dataset, LicenseRecord]]:
    return list(
        session.execute(
            select(Dataset, LicenseRecord)
            .join(LicenseRecord, LicenseRecord.id == Dataset.license_id)
            .order_by(Dataset.name)
        ).tuples()
    )


def allowed(
    session: Session, scope: Scope, channel: Channel | None = None
) -> dict[UUID, tuple[Dataset, LicenseRecord]]:
    channel = channel or channel_for(scope)
    return {d.id: (d, lic) for d, lic in _catalog(session) if _refusal(scope, d, lic, channel) is None}


def _authorize(session: Session, scope: Scope, dataset_id: UUID, channel: Channel) -> tuple[Dataset, LicenseRecord]:
    dataset = session.get(Dataset, dataset_id)
    lic = session.get(LicenseRecord, dataset.license_id) if dataset else None
    if dataset is None or lic is None:
        raise NotFound("Dataset not found")
    if refusal := _refusal(scope, dataset, lic, channel):
        raise refusal
    return dataset, lic


def provenance(dataset: Dataset, lic: LicenseRecord) -> Provenance:
    return Provenance(
        dataset=dataset.code,
        dataset_name=dataset.name,
        provider=dataset.provider,
        license_class=lic.data_class,
        attribution=lic.attribution,
        terms_url=lic.terms_url,
        freshness_class=dataset.freshness_class,
        delay_minutes=lic.required_delay_minutes,
        status=effective_status(dataset),
        last_success_at=dataset.last_success_at,
        latest_ref_time=dataset.latest_ref_time,
        export_allowed=lic.allow_export,
    )


def count_usage(session: Session, scope: Scope, dataset_id: UUID, channel: str) -> None:
    session.execute(
        text(
            "INSERT INTO dataset_usage (dataset_id, tenant_id, day, channel, count) "
            "VALUES (:d, :t, :day, :c, 1) ON CONFLICT (dataset_id, tenant_id, day, channel) "
            "DO UPDATE SET count = dataset_usage.count + 1"
        ),
        {"d": dataset_id, "t": scope.tenant_id, "day": utcnow().date(), "c": channel[:20]},
    )


# --- Instruments and quotes -----------------------------------------------------------------------


def _instrument_out(row: Instrument, catalog: dict, has_prices: bool) -> InstrumentOut:
    dataset, lic = catalog[row.dataset_id]
    return InstrumentOut(
        id=row.id,
        symbol=row.symbol,
        name=row.name,
        type=row.type,
        currency=row.currency,
        venue=row.venue,
        status=row.status,
        entity_id=row.entity_id,
        dataset=dataset.code,
        license_class=lic.data_class,
        has_prices=has_prices,
    )


def search_instruments(
    session: Session,
    scope: Scope,
    query: str = "",
    *,
    types: Sequence[str] = (),
    priced_only: bool = False,
    limit: int = 25,
    offset: int = 0,
) -> list[InstrumentOut]:
    catalog = allowed(session, scope)
    if not catalog:
        return []
    has_prices = select(Series.id).where(Series.instrument_id == Instrument.id).exists()
    stmt = select(Instrument, has_prices.label("has_prices")).where(Instrument.dataset_id.in_(catalog))
    if types:
        stmt = stmt.where(Instrument.type.in_(types))
    if priced_only:
        stmt = stmt.where(has_prices)
    q = query.strip()
    if q:
        like = f"%{q.replace('%', '').replace('_', '')}%"
        upper = q.upper()
        stmt = stmt.where(or_(Instrument.symbol.ilike(like), Instrument.name.ilike(like)))
        rank = case(
            (Instrument.symbol == upper, 0),
            (Instrument.symbol.like(f"{upper}.%"), 1),
            (Instrument.symbol.ilike(f"{q}%"), 2),
            (Instrument.name.ilike(f"{q}%"), 3),
            else_=4,
        )
        stmt = stmt.order_by(rank, has_prices.desc(), func.length(Instrument.symbol), Instrument.symbol)
    else:
        stmt = stmt.order_by(has_prices.desc(), Instrument.type, Instrument.symbol)
    rows = session.execute(stmt.limit(min(limit, 200)).offset(offset)).all()
    return [_instrument_out(r.Instrument, catalog, r.has_prices) for r in rows]


def get_instrument(session: Session, scope: Scope, ref: str | UUID) -> InstrumentOut:
    column = Instrument.id if isinstance(ref, UUID) else Instrument.symbol
    row = session.scalar(select(Instrument).where(column == (ref if isinstance(ref, UUID) else ref.upper())))
    if row is None:
        raise NotFound("Instrument not found")
    _authorize(session, scope, row.dataset_id, channel_for(scope))
    has_prices = session.scalar(select(func.count()).select_from(Series).where(Series.instrument_id == row.id))
    return _instrument_out(row, allowed(session, scope), bool(has_prices))


def instrument_series(session: Session, scope: Scope, instrument_id: UUID) -> list[SeriesOut]:
    catalog = allowed(session, scope)
    rows = session.scalars(
        select(Series)
        .where(Series.instrument_id == instrument_id, Series.dataset_id.in_(catalog))
        .order_by(Series.created_at)
    )
    return [SeriesOut.model_validate(r) for r in rows]


def quotes(session: Session, scope: Scope, instrument_ids: Iterable[UUID]) -> dict[UUID, Quote]:
    """Latest and previous value of the primary series of each instrument, with freshness."""
    ids = list(instrument_ids)
    catalog = allowed(session, scope)
    if not ids or not catalog:
        return {}
    rows = session.scalars(
        select(Series).where(Series.instrument_id.in_(ids), Series.dataset_id.in_(catalog)).order_by(Series.created_at)
    )
    result: dict[UUID, Quote] = {}
    for s in rows:
        if s.instrument_id in result:
            continue
        dataset, lic = catalog[s.dataset_id]
        last = float(s.latest_value) if s.latest_value is not None else None
        prev = float(s.previous_value) if s.previous_value is not None else None
        change = last - prev if last is not None and prev is not None else None
        result[s.instrument_id] = Quote(
            instrument_id=s.instrument_id,
            series_id=s.id,
            series_code=s.code,
            unit=s.unit,
            currency=s.currency,
            last=last,
            previous=prev,
            change=change,
            change_pct=(change / prev * 100 if change is not None and prev else None),
            ref_time=s.latest_ref_time,
            freshness_class=dataset.freshness_class,
            status=effective_status(dataset),
            license_class=lic.data_class,
        )
    return result


# --- Series ---------------------------------------------------------------------------------------


def _series(session: Session, ref: str | UUID) -> Series:
    row = (
        session.get(Series, ref) if isinstance(ref, UUID) else session.scalar(select(Series).where(Series.code == ref))
    )
    if row is None:
        raise NotFound("Series not found")
    return row


def find_series(
    session: Session, scope: Scope, *, kinds: Sequence[str] = (), query: str = "", limit: int = 100
) -> list[SeriesOut]:
    catalog = allowed(session, scope)
    stmt = select(Series).where(Series.dataset_id.in_(catalog))
    if kinds:
        stmt = stmt.where(Series.kind.in_(kinds))
    if query.strip():
        like = f"%{query.strip()}%"
        stmt = stmt.where(or_(Series.name.ilike(like), Series.code.ilike(like)))
    return [SeriesOut.model_validate(r) for r in session.scalars(stmt.order_by(Series.name).limit(limit))]


def _bounds(start: date | None, end: date | None) -> tuple[datetime, datetime]:
    lo = datetime.combine(start or date(1900, 1, 1), time(0, tzinfo=UTC))
    hi = datetime.combine(end or date(2200, 1, 1), time(23, 59, 59, tzinfo=UTC))
    return lo, hi


def _current_points(series_id: UUID, lo: datetime, hi: datetime, as_of: datetime | None):
    """The version of each observation that was known at ``as_of`` (point-in-time read)."""
    stmt = (
        select(Observation)
        .where(Observation.series_id == series_id, Observation.ref_time >= lo, Observation.ref_time <= hi)
        .distinct(Observation.ref_time)
        .order_by(Observation.ref_time, Observation.version.desc())
    )
    if as_of is not None:
        stmt = stmt.where(Observation.known_at <= as_of)
    return stmt


def series_data(
    session: Session,
    scope: Scope,
    ref: str | UUID,
    *,
    start: date | None = None,
    end: date | None = None,
    as_of: datetime | None = None,
    channel: Channel | None = None,
) -> SeriesData:
    channel = channel or channel_for(scope)
    row = _series(session, ref)
    dataset, lic = _authorize(session, scope, row.dataset_id, channel)
    lo, hi = _bounds(start, end)
    if lic.required_delay_minutes:
        hi = min(hi, utcnow() - timedelta(minutes=lic.required_delay_minutes))
    points = [
        Point(
            t=o.ref_time,
            v=float(o.value),
            o=_f(o.open),
            h=_f(o.high),
            l=_f(o.low),
            vol=_f(o.volume),
            q=o.quality,
            known_at=o.known_at,
            version=o.version,
        )
        for o in session.scalars(_current_points(row.id, lo, hi, as_of))
    ]
    count_usage(session, scope, dataset.id, channel)
    return SeriesData(
        series=SeriesOut.model_validate(row), provenance=provenance(dataset, lic), as_of=as_of, points=points
    )


def _f(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None


def load_values(
    session: Session,
    scope: Scope,
    series_ids: Iterable[UUID],
    *,
    start: date | None = None,
    end: date | None = None,
    as_of: datetime | None = None,
    channel: Channel | None = None,
) -> dict[UUID, list[tuple[date, Decimal]]]:
    """Decimal values for calculations. Each series is authorized; only data known at ``as_of`` is used."""
    channel = channel or channel_for(scope)
    lo, hi = _bounds(start, end)
    out: dict[UUID, list[tuple[date, Decimal]]] = {}
    for series_id in dict.fromkeys(series_ids):
        row = _series(session, series_id)
        _authorize(session, scope, row.dataset_id, channel)
        out[series_id] = [(o.ref_time.date(), o.value) for o in session.scalars(_current_points(row.id, lo, hi, as_of))]
    return out


def series_versions(
    session: Session,
    scope: Scope,
    ref: str | UUID,
    *,
    start: date | None = None,
    end: date | None = None,
    known_by: datetime | None = None,
    channel: Channel | None = None,
) -> list[tuple[date, datetime, Decimal]]:
    """Every stored version of a series with the time it became known, for point-in-time simulation."""
    row = _series(session, ref)
    dataset, _ = _authorize(session, scope, row.dataset_id, channel or channel_for(scope))
    lo, hi = _bounds(start, end)
    stmt = (
        select(Observation.ref_time, Observation.known_at, Observation.value)
        .where(Observation.series_id == row.id, Observation.ref_time >= lo, Observation.ref_time <= hi)
        .order_by(Observation.ref_time, Observation.version)
    )
    if known_by is not None:
        stmt = stmt.where(Observation.known_at <= known_by)
    count_usage(session, scope, dataset.id, channel or channel_for(scope))
    return [(r.ref_time.date(), r.known_at, r.value) for r in session.execute(stmt)]


def series_meta(
    session: Session, scope: Scope, ref: str | UUID, channel: Channel | None = None
) -> tuple[SeriesOut, Provenance]:
    row = _series(session, ref)
    dataset, lic = _authorize(session, scope, row.dataset_id, channel or channel_for(scope))
    return SeriesOut.model_validate(row), provenance(dataset, lic)


def primary_series(session: Session, scope: Scope, instrument_id: UUID) -> SeriesOut:
    rows = instrument_series(session, scope, instrument_id)
    if not rows:
        raise NotFound("No price series is available for this instrument", details={"reason": "no_licensed_price_data"})
    return rows[0]


def latest_values(session: Session, series_ids: Sequence[UUID]) -> dict[UUID, Decimal | None]:
    """Latest stored value per series, for monitors that run after ingestion. Values only, no tenant data."""
    if not series_ids:
        return {}
    return dict(session.execute(select(Series.id, Series.latest_value).where(Series.id.in_(series_ids))).all())


# --- Entities and facts ---------------------------------------------------------------------------


def get_entity(session: Session, scope: Scope, entity_id: UUID) -> EntityOut:
    row = session.get(Entity, entity_id)
    if row is None or row.dataset_id not in allowed(session, scope):
        raise NotFound("Company not found")
    return EntityOut.model_validate(row)


def find_entities(
    session: Session, scope: Scope, *, tracked: bool | None = None, query: str = "", limit: int = 50
) -> list[EntityOut]:
    stmt = select(Entity).where(Entity.dataset_id.in_(allowed(session, scope)))
    if tracked is not None:
        stmt = stmt.where(Entity.tracked == tracked)
    if query.strip():
        like = f"%{query.strip()}%"
        stmt = stmt.where(or_(Entity.name.ilike(like), Entity.ticker.ilike(like)))
    return [EntityOut.model_validate(r) for r in session.scalars(stmt.order_by(Entity.name).limit(limit))]


def entity_facts(
    session: Session, scope: Scope, entity_id: UUID, *, as_of: date | None = None, channel: Channel | None = None
) -> tuple[list[FactOut], Provenance | None]:
    """Reported facts as known on ``as_of``: for each concept and period, the most recently filed value."""
    channel = channel or channel_for(scope)
    catalog = allowed(session, scope, channel)
    stmt = (
        select(Fact)
        .where(Fact.entity_id == entity_id, Fact.dataset_id.in_(catalog))
        .distinct(Fact.concept, Fact.unit, Fact.period_start, Fact.period_end)
        .order_by(Fact.concept, Fact.unit, Fact.period_start, Fact.period_end, Fact.filed_at.desc())
    )
    if as_of is not None:
        stmt = stmt.where(Fact.filed_at <= as_of)
    rows = list(session.scalars(stmt))
    if not rows:
        return [], None
    dataset, lic = catalog[rows[0].dataset_id]
    count_usage(session, scope, dataset.id, channel)
    return [FactOut.model_validate(r) for r in rows], provenance(dataset, lic)


# --- Documents ------------------------------------------------------------------------------------


def _document_out(doc: Document, catalog: dict, entity_name: str | None = None) -> DocumentOut:
    dataset, lic = catalog[doc.dataset_id]
    return DocumentOut(
        id=doc.id,
        doc_type=doc.doc_type,
        title=doc.title,
        url=doc.url,
        published_at=doc.published_at,
        language=doc.language,
        entity_id=doc.entity_id,
        entity_name=entity_name,
        passage_count=doc.passage_count,
        screening=doc.screening,
        private=doc.tenant_id is not None,
        dataset=dataset.code,
        license_class=lic.data_class,
        attribution=lic.attribution,
        meta=doc.meta,
    )


def _visible(scope: Scope, catalog: dict):
    return and_(
        Document.dataset_id.in_(catalog), or_(Document.tenant_id.is_(None), Document.tenant_id == scope.tenant_id)
    )


def list_documents(
    session: Session,
    scope: Scope,
    *,
    entity_id: UUID | None = None,
    doc_types: Sequence[str] = (),
    since: datetime | None = None,
    private: bool | None = None,
    limit: int = 50,
    offset: int = 0,
    channel: Channel | None = None,
) -> list[DocumentOut]:
    catalog = allowed(session, scope, channel)
    stmt = (
        select(Document, Entity.name).outerjoin(Entity, Entity.id == Document.entity_id).where(_visible(scope, catalog))
    )
    if entity_id:
        stmt = stmt.where(Document.entity_id == entity_id)
    if doc_types:
        stmt = stmt.where(Document.doc_type.in_(doc_types))
    if since:
        stmt = stmt.where(Document.published_at >= since)
    if private is not None:
        stmt = stmt.where(Document.tenant_id.isnot(None) if private else Document.tenant_id.is_(None))
    rows = session.execute(stmt.order_by(Document.published_at.desc()).limit(min(limit, 200)).offset(offset))
    return [_document_out(doc, catalog, name) for doc, name in rows]


def get_document(
    session: Session, scope: Scope, document_id: UUID, *, channel: Channel | None = None
) -> tuple[DocumentOut, list[PassageOut]]:
    catalog = allowed(session, scope, channel)
    row = session.execute(
        select(Document, Entity.name)
        .outerjoin(Entity, Entity.id == Document.entity_id)
        .where(Document.id == document_id, _visible(scope, catalog))
    ).first()
    if row is None:
        raise NotFound("Document not found")
    passages = session.scalars(
        select(Passage).where(Passage.document_id == document_id).order_by(Passage.ordinal).limit(2000)
    )
    count_usage(session, scope, row.Document.dataset_id, channel or channel_for(scope))
    return _document_out(row.Document, catalog, row.name), [PassageOut.model_validate(p) for p in passages]


def search_passages(
    session: Session,
    scope: Scope,
    query: str,
    *,
    entity_ids: Sequence[UUID] = (),
    doc_types: Sequence[str] = (),
    until: datetime | None = None,
    limit: int = 20,
    include_flagged: bool = True,
    private: bool | None = None,
    channel: Channel | None = None,
) -> list[PassageHit]:
    """Full-text search. Tenant, license and date filters are applied inside the query."""
    catalog = allowed(session, scope, channel)
    if not query.strip() or not catalog:
        return []
    strict = func.websearch_to_tsquery("english", query)
    # Fall back to any-term matching so a natural-language question still finds evidence.
    loose = func.to_tsquery("english", func.replace(cast(func.plainto_tsquery("english", query), Text), "&", "|"))

    def run(tsq):
        rank = func.ts_rank_cd(Passage.tsv, tsq)
        stmt = (
            select(
                Passage,
                Document,
                Entity.name,
                rank.label("rank"),
                func.ts_headline(
                    "english", Passage.text, tsq, literal("MaxWords=40, MinWords=15, StartSel=«, StopSel=»")
                ).label("headline"),
            )
            .join(Document, Document.id == Passage.document_id)
            .outerjoin(Entity, Entity.id == Document.entity_id)
            .where(Passage.tsv.op("@@")(tsq), _visible(scope, catalog))
        )
        if entity_ids:
            stmt = stmt.where(Document.entity_id.in_(entity_ids))
        if doc_types:
            stmt = stmt.where(Document.doc_type.in_(doc_types))
        if until:
            stmt = stmt.where(Document.published_at <= until)
        if not include_flagged:
            stmt = stmt.where(Passage.flagged.is_(False))
        if private is not None:
            stmt = stmt.where(Document.tenant_id.isnot(None) if private else Document.tenant_id.is_(None))
        return session.execute(stmt.order_by(rank.desc(), Document.published_at.desc()).limit(min(limit, 100))).all()

    rows = run(strict) or run(loose)
    return [
        PassageHit(
            passage=PassageOut.model_validate(p),
            document=_document_out(d, catalog, name),
            rank=float(rank or 0),
            headline=headline,
        )
        for p, d, name, rank, headline in rows
    ]


def get_passages(
    session: Session, scope: Scope, passage_ids: Sequence[int], *, channel: Channel | None = None
) -> list[PassageHit]:
    catalog = allowed(session, scope, channel)
    if not passage_ids:
        return []
    rows = session.execute(
        select(Passage, Document, Entity.name)
        .join(Document, Document.id == Passage.document_id)
        .outerjoin(Entity, Entity.id == Document.entity_id)
        .where(Passage.id.in_(passage_ids), _visible(scope, catalog))
    )
    return [
        PassageHit(passage=PassageOut.model_validate(p), document=_document_out(d, catalog, name))
        for p, d, name in rows
    ]


# --- Catalog --------------------------------------------------------------------------------------


def list_datasets(session: Session, scope: Scope) -> list[DatasetOut]:
    """Every dataset the tenant may know about, including ones the plan does not unlock (shown as locked)."""
    out = []
    for dataset, lic in _catalog(session):
        if dataset.tenant_id is not None and dataset.tenant_id != scope.tenant_id:
            continue
        counts = {
            "instruments": session.scalar(
                select(func.count()).select_from(Instrument).where(Instrument.dataset_id == dataset.id)
            ),
            "series": session.scalar(select(func.count()).select_from(Series).where(Series.dataset_id == dataset.id)),
            "documents": session.scalar(
                select(func.count()).select_from(Document).where(Document.dataset_id == dataset.id)
            ),
        }
        item = DatasetOut.model_validate(
            {
                **{c.name: getattr(dataset, c.name) for c in Dataset.__table__.columns},
                "license": LicenseOut.model_validate(lic),
                "private": dataset.tenant_id is not None,
                "counts": counts,
            }
        )
        item.status = effective_status(dataset)
        out.append(item)
    return out


def dataset_runs(session: Session, scope: Scope, code: str, limit: int = 20) -> list[RunOut]:
    dataset = session.scalar(select(Dataset).where(Dataset.code == code))
    if dataset is None or (dataset.tenant_id is not None and dataset.tenant_id != scope.tenant_id):
        raise NotFound("Dataset not found")
    rows = session.scalars(
        select(ConnectorRun)
        .where(ConnectorRun.dataset_id == dataset.id)
        .order_by(ConnectorRun.started_at.desc())
        .limit(limit)
    )
    return [RunOut.model_validate(r) for r in rows]


def calendar(
    session: Session,
    scope: Scope,
    *,
    start: datetime,
    end: datetime,
    kinds: Sequence[str] = (),
    entity_ids: Sequence[UUID] = (),
    limit: int = 200,
) -> list[EventOut]:
    stmt = select(CalendarEvent).where(
        CalendarEvent.dataset_id.in_(allowed(session, scope)),
        CalendarEvent.scheduled_at >= start,
        CalendarEvent.scheduled_at <= end,
    )
    if kinds:
        stmt = stmt.where(CalendarEvent.kind.in_(kinds))
    if entity_ids:
        stmt = stmt.where(CalendarEvent.entity_id.in_(entity_ids))
    rows = session.scalars(stmt.order_by(CalendarEvent.scheduled_at.desc()).limit(limit))
    return [EventOut.model_validate(r) for r in rows]


# --- Tenant-private documents ---------------------------------------------------------------------


def private_dataset(session: Session, scope: Scope) -> Dataset:
    """The dataset that holds one tenant's own documents. Created on first use with the tenant license."""
    code = f"uploads-{scope.tenant_id.hex[:12]}"
    dataset = session.scalar(select(Dataset).where(Dataset.code == code))
    if dataset is None:
        license_id = session.scalar(select(LicenseRecord.id).where(LicenseRecord.code == "tenant-supplied"))
        dataset = Dataset(
            code=code,
            name="Your organization's documents",
            provider="Customer",
            connector="upload",
            license_id=license_id,
            tenant_id=scope.tenant_id,
            freshness_class="historical",
            status="ok",
            enabled=False,
            description="Documents uploaded by members of your organization. Private to the tenant.",
        )
        session.add(dataset)
        session.flush()
    dataset.last_success_at = dataset.latest_ref_time = utcnow()
    return dataset


def store_private_document(
    session: Session,
    scope: Scope,
    *,
    key: str,
    title: str,
    content_hash: str,
    passages: Sequence[tuple[str, str, bool]],
    meta: dict | None = None,
) -> UUID:
    """Store a tenant-private document as ``(location, text, flagged)`` passages."""
    dataset = private_dataset(session, scope)
    doc = Document(
        dataset_id=dataset.id,
        tenant_id=scope.tenant_id,
        key=key,
        doc_type="upload",
        title=title,
        published_at=utcnow(),
        content_hash=content_hash,
        meta=meta or {},
        passage_count=len(passages),
        screening="flagged" if any(flagged for _, _, flagged in passages) else "clear",
    )
    session.add(doc)
    session.flush()
    for ordinal, (location, text_value, flagged) in enumerate(passages):
        session.add(
            Passage(
                document_id=doc.id,
                tenant_id=scope.tenant_id,
                ordinal=ordinal,
                location=location,
                text=text_value,
                flagged=flagged,
            )
        )
    return doc.id


def delete_private_document(session: Session, scope: Scope, document_id: UUID) -> None:
    doc = session.get(Document, document_id)
    if doc is None or doc.tenant_id != scope.tenant_id:
        raise NotFound("Document not found")
    session.delete(doc)
