"""Enqueue and claim jobs. ``FOR UPDATE SKIP LOCKED`` lets several workers share the queue safely."""

from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from core.types import utcnow
from pipelines.models import Job

MAX_ATTEMPTS = 3
STALE_AFTER = timedelta(minutes=45)


def enqueue(
    session: Session,
    kind: str,
    payload: dict[str, Any] | None = None,
    *,
    dedupe_key: str | None = None,
    run_after: datetime | None = None,
) -> UUID | None:
    """Queue a job. Returns ``None`` when an identical job is already queued or running."""
    stmt = pg_insert(Job).values(
        kind=kind, payload=payload or {}, dedupe_key=dedupe_key, run_after=run_after or utcnow()
    )
    if dedupe_key:
        stmt = stmt.on_conflict_do_nothing(
            index_elements=["dedupe_key"],
            index_where=text("status IN ('queued', 'running') AND dedupe_key IS NOT NULL"),
        )
    return session.execute(stmt.returning(Job.id)).scalar_one_or_none()


def claim(session: Session, *, only: tuple[str, ...] = (), exclude: tuple[str, ...] = ()) -> Job | None:
    """Take the oldest due job. ``only`` and ``exclude`` give a worker lane its job kinds."""
    stmt = select(Job).where(Job.status == "queued", Job.run_after <= utcnow())
    if only:
        stmt = stmt.where(Job.kind.in_(only))
    if exclude:
        stmt = stmt.where(Job.kind.not_in(exclude))
    job = session.scalar(stmt.order_by(Job.run_after).limit(1).with_for_update(skip_locked=True))
    if job is not None:
        job.status, job.locked_at, job.attempts = "running", utcnow(), job.attempts + 1
    return job


def finish(session: Session, job_id: UUID, *, result: dict[str, Any] | None = None, error: str = "") -> None:
    job = session.get(Job, job_id)
    if job is None:
        return
    if error and job.attempts < MAX_ATTEMPTS:
        job.status, job.error = "queued", error[:300]
        job.run_after = utcnow() + timedelta(minutes=5 * job.attempts)
    else:
        job.status, job.error = ("failed" if error else "done"), error[:300]
        job.finished_at, job.result = utcnow(), result or {}


def requeue_stale(session: Session) -> int:
    """A worker that died mid-job leaves it running; hand it back to the queue."""
    return session.execute(
        update(Job)
        .where(Job.status == "running", Job.locked_at < utcnow() - STALE_AFTER)
        .values(status="queued", run_after=utcnow())
    ).rowcount
