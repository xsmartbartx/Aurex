"""AUREX DataLab endpoints: dataset catalog, freshness, lineage and the license register."""

from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import Field
from sqlalchemy import select

from core.db import system_session
from core.errors import NotFound, ValidationFailure
from core.types import Role
from interface.api.deps import AdminDep, DbDep, ScopeDep
from modules.datalab import access
from modules.datalab.models import Dataset
from modules.logging import record_audit
from modules.validation import Strict
from pipelines import jobs

router = APIRouter(prefix="/datalab", tags=["datalab"])


class DatasetUpdate(Strict):
    enabled: bool | None = None
    interval_minutes: int | None = Field(default=None, ge=15, le=60 * 24 * 30)


class TrackCompany(Strict):
    cik: str = Field(pattern=r"^\d{1,10}$")


@router.get("/datasets")
def datasets(scope: ScopeDep, db: DbDep) -> dict:
    items = access.list_datasets(db, scope)
    unlocked = set(access.allowed(db, scope))
    return {"items": [{**d.model_dump(), "accessible": d.id in unlocked} for d in items]}


@router.get("/datasets/{code}/runs")
def runs(code: str, scope: ScopeDep, db: DbDep, limit: Annotated[int, Query(ge=1, le=100)] = 20) -> dict:
    return {"items": access.dataset_runs(db, scope, code, limit)}


@router.post("/datasets/{code}/run", status_code=202)
def trigger_run(code: str, scope: AdminDep) -> dict:
    """Queue an ingestion run. Connector operations are restricted to the deployment administrator."""
    with system_session() as session:
        dataset = session.scalar(select(Dataset).where(Dataset.code == code))
        if dataset is None:
            raise NotFound("Dataset not found")
        if dataset.connector == "sec_company":
            raise ValidationFailure("This dataset is ingested per company. Track a company instead.")
        job_id = jobs.enqueue(
            session, "ingest.dataset", {"code": code, "trigger": "manual"}, dedupe_key=f"ingest:{code}"
        )
        record_audit(
            session,
            action="datalab.run_requested",
            tenant_id=scope.tenant_id,
            actor_id=scope.user_id,
            object_type="dataset",
            object_id=code,
        )
    return {"queued": job_id is not None, "detail": "Run queued" if job_id else "A run is already queued"}


@router.patch("/datasets/{code}")
def update_dataset(code: str, body: DatasetUpdate, scope: AdminDep) -> dict:
    with system_session() as session:
        dataset = session.scalar(select(Dataset).where(Dataset.code == code))
        if dataset is None:
            raise NotFound("Dataset not found")
        if body.enabled is not None:
            dataset.enabled = body.enabled
        if body.interval_minutes is not None:
            dataset.interval_minutes = body.interval_minutes
        record_audit(
            session,
            action="datalab.dataset_updated",
            tenant_id=scope.tenant_id,
            actor_id=scope.user_id,
            object_type="dataset",
            object_id=code,
            enabled=dataset.enabled,
            interval_minutes=dataset.interval_minutes,
        )
    return {"status": "ok"}


@router.post("/companies/track", status_code=202)
def track_company(body: TrackCompany, scope: ScopeDep) -> dict:
    """Ask for the filings and reported facts of one SEC registrant to be ingested."""
    scope.require_role(Role.ANALYST)
    cik = body.cik.zfill(10)
    with system_session() as session:
        job_id = jobs.enqueue(session, "ingest.company", {"cik": cik, "trigger": "manual"}, dedupe_key=f"company:{cik}")
        record_audit(
            session,
            action="datalab.company_tracked",
            tenant_id=scope.tenant_id,
            actor_id=scope.user_id,
            object_type="entity",
            object_id=f"cik:{cik}",
        )
    return {"queued": job_id is not None}


@router.get("/licenses")
def licenses(scope: ScopeDep, db: DbDep) -> dict:
    seen, items = set(), []
    for dataset in access.list_datasets(db, scope):
        if dataset.license.code not in seen:
            seen.add(dataset.license.code)
            items.append(dataset.license)
    return {"items": items}
