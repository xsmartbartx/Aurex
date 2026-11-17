"""Worker and scheduler in one process: ingestion runs, alert evaluation, thesis monitoring.

The pipeline layer holds no business logic. It decides when a job runs and calls the owning module.
"""

import signal
import threading
import time
from collections.abc import Callable
from datetime import timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select

from core.config import get_settings
from core.db import system_session, tenant_session
from core.types import utcnow
from modules.datalab.ingestion import RunResult, run_dataset
from modules.datalab.models import Dataset, Entity, Series
from modules.graph import seed as graph_seed
from modules.integration import sec
from modules.intelligence import service as intelligence
from modules.logging import Severity, log
from modules.markets import service as markets
from pipelines import jobs
from security import auth
from security.controls import screen_content

IDLE_SLEEP = 2.0
SCHEDULE_EVERY = 60.0
_running = True


def _screen(text: str) -> bool:
    return screen_content(text, source="ingestion").flagged


def _after_run(result: RunResult) -> dict[str, Any]:
    """Events for alerts and monitors (the last step of the ingestion flow)."""
    fired = 0
    if result.status == "success" and result.series_ids:
        with system_session() as session:
            rows = session.execute(
                select(Series.id, Series.latest_value, Series.previous_value, Series.name).where(
                    Series.id.in_(result.series_ids)
                )
            ).all()
            fired = markets.evaluate_alerts(session, {r.id: (r.latest_value, r.previous_value, r.name) for r in rows})
            intelligence.check_theses(session, series_ids=result.series_ids, notify=markets.notify)
        if result.dataset in GRAPH_SOURCES:
            with system_session() as session:
                graph_seed.refresh(session)
        for hook in AFTER_RUN_HOOKS:
            hook(result)
    return {"status": result.status, "stored": result.stored, "error_code": result.error_code, "alerts_fired": fired}


AFTER_RUN_HOOKS: list[Callable[[RunResult], None]] = []
GRAPH_SOURCES = {"demo", "ecb-rates", "ecb-fx", "ecb-macro"}


def ingest_dataset(payload: dict[str, Any]) -> dict[str, Any]:
    return _after_run(run_dataset(payload["code"], trigger=payload.get("trigger", "schedule"), screen=_screen))


def ingest_company(payload: dict[str, Any]) -> dict[str, Any]:
    return _after_run(
        run_dataset(
            "sec-companies", trigger=payload.get("trigger", "schedule"), params={"cik": payload["cik"]}, screen=_screen
        )
    )


def answer(payload: dict[str, Any]) -> dict[str, Any]:
    """Run an agent for a stored question, with the scope and model policy of the member who asked."""
    tenant_id, user_id = UUID(payload["tenant_id"]), UUID(payload["user_id"])
    with system_session() as session:
        scope = auth.scope_for(session, user_id, tenant_id)
        allow_external = auth.external_models_allowed(session, tenant_id)
    with tenant_session(tenant_id) as session:
        record = intelligence.answer_question(
            session,
            scope,
            UUID(payload["record_id"]),
            allow_external=allow_external,
            screen=lambda text: screen_content(text, source="agent_context").flagged,
        )
        return {"status": record.status, "engine": record.engine}


HANDLERS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "ingest.dataset": ingest_dataset,
    "ingest.company": ingest_company,
    "intelligence.answer": answer,
}


def schedule_due() -> int:
    """Queue a run for every enabled dataset whose interval has elapsed."""
    if not get_settings().ingest_enabled:
        return 0
    queued = 0
    now = utcnow()
    with system_session() as session:
        jobs.requeue_stale(session)
        for dataset in session.scalars(select(Dataset).where(Dataset.enabled.is_(True))):
            interval = timedelta(minutes=dataset.interval_minutes)
            if dataset.tenant_id is not None:
                continue  # customer-supplied data is imported by the tenant, not scheduled
            due = dataset.last_run_at is None or now - dataset.last_run_at >= interval
            if dataset.connector != "sec_company" and not due:
                continue
            if dataset.connector.startswith("sec") and not sec.configured():
                if dataset.status != "not_configured":
                    dataset.status = "not_configured"
                    dataset.status_detail = "Set AUREX_SEC_USER_AGENT to a name and contact address."
                continue
            if dataset.connector == "sec_company":
                tracked = set(
                    session.scalars(
                        select(Entity.cik).where(
                            Entity.tracked.is_(True),
                            Entity.cik.isnot(None),
                            (Entity.facts_synced_at.is_(None)) | (Entity.facts_synced_at < now - interval),
                        )
                    )
                )
                never = set(dataset.config.get("default_ciks", [])) - set(
                    session.scalars(select(Entity.cik).where(Entity.tracked.is_(True), Entity.cik.isnot(None)))
                )
                for cik in sorted(tracked | never):
                    queued += (
                        jobs.enqueue(session, "ingest.company", {"cik": cik}, dedupe_key=f"company:{cik}") is not None
                    )
                continue
            queued += (
                jobs.enqueue(session, "ingest.dataset", {"code": dataset.code}, dedupe_key=f"ingest:{dataset.code}")
                is not None
            )
    return queued


# Interactive jobs have their own lane, so an answer never waits behind a long import.
INTERACTIVE = ("intelligence.answer",)


def run_one(*, only: tuple[str, ...] = (), exclude: tuple[str, ...] = ()) -> bool:
    """Claim and run one job. Returns False when the queue is empty."""
    with system_session() as session:
        job = jobs.claim(session, only=only, exclude=exclude)
        if job is None:
            return False
        job_id, kind, payload = job.id, job.kind, dict(job.payload)
    handler = HANDLERS.get(kind)
    try:
        if handler is None:
            raise ValueError("unknown job kind")
        result = handler(payload)
        error = ""
    except Exception as exc:  # noqa: BLE001 - a failing job is recorded and retried, the worker continues
        result, error = {}, type(exc).__name__
        log("pipeline", "job.failed", Severity.ERROR, kind=kind, error=error)
    with system_session() as session:
        jobs.finish(session, job_id, result=result, error=error)
    return True


def _stop(*_: Any) -> None:
    global _running
    _running = False


def _lane(name: str, *, only: tuple[str, ...] = (), exclude: tuple[str, ...] = (), schedule: bool = False) -> None:
    last_schedule = 0.0
    while _running:
        if schedule and time.monotonic() - last_schedule >= SCHEDULE_EVERY:
            last_schedule = time.monotonic()
            try:
                schedule_due()
            except Exception as exc:  # noqa: BLE001
                log("pipeline", "schedule.failed", Severity.ERROR, error=type(exc).__name__)
        try:
            busy = run_one(only=only, exclude=exclude)
        except Exception as exc:  # noqa: BLE001 - a database hiccup must not end the lane
            log("pipeline", "lane.error", Severity.ERROR, lane=name, error=type(exc).__name__)
            busy = False
        if not busy:
            time.sleep(IDLE_SLEEP if not only else 0.5)


def main() -> None:
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    log("pipeline", "worker.started", lanes=["interactive", "background"])
    interactive = threading.Thread(target=_lane, args=("interactive",), kwargs={"only": INTERACTIVE}, daemon=True)
    interactive.start()
    _lane("background", exclude=INTERACTIVE, schedule=True)
    interactive.join(timeout=30)
    log("pipeline", "worker.stopped")


if __name__ == "__main__":
    main()
