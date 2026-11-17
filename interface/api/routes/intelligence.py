"""AUREX Intelligence endpoints: questions with evidence, documents, company fundamentals, theses."""

from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, File, Form, Query, UploadFile
from pydantic import Field

from core import entitlements as ent
from core.config import get_settings
from core.db import system_session, tenant_session
from core.errors import ValidationFailure
from interface.api.deps import DbDep, ScopeDep
from modules.datalab import access
from modules.intelligence import service
from modules.intelligence.tools import AGENTS
from modules.validation import Strict, clean_text
from pipelines import jobs
from security.controls import consume, screen_content

router = APIRouter(prefix="/intelligence", tags=["intelligence"])
TEXT_TYPES = {"text/plain", "text/markdown", "text/x-markdown", "application/octet-stream", ""}


class Ask(Strict):
    question: str = Field(min_length=3, max_length=2000)
    agent: Literal["research", "earnings", "macro", "risk", "data_quality", "thesis"] = "research"
    kind: Literal["answer", "report"] = "answer"
    context: dict[str, str] = Field(default_factory=dict, max_length=4)


class Share(Strict):
    shared: bool


class ThesisCondition(Strict):
    instrument: str = Field(min_length=1, max_length=40)
    operator: Literal["above", "below"]
    value: float
    description: str = Field(default="", max_length=200)


class ThesisSave(Strict):
    title: str = Field(min_length=1, max_length=160)
    statement: str = Field(default="", max_length=4000)
    conditions: list[ThesisCondition] = Field(min_length=1, max_length=8)


@router.get("/agents")
def agents(scope: ScopeDep) -> dict:
    return {
        "items": [
            {"name": a.name, "title": a.title, "purpose": a.purpose, "tools": list(a.tools)} for a in AGENTS.values()
        ],
        "engine": "anthropic" if get_settings().anthropic_api_key else "offline",
    }


@router.post("/questions", status_code=202)
def ask(body: Ask, scope: ScopeDep) -> dict:
    """Store the question and queue the run. The answer is read back from its record when complete."""
    with tenant_session(scope.tenant_id) as session:
        record = service.open_question(
            session, scope, question=body.question, agent=body.agent, context=body.context, kind=body.kind
        )
        consume(session, scope, "ai_questions", "ai_questions_per_day")
        record_id = record.id
    with system_session() as session:
        jobs.enqueue(
            session,
            "intelligence.answer",
            {"record_id": str(record_id), "tenant_id": str(scope.tenant_id), "user_id": str(scope.user_id)},
            dedupe_key=f"answer:{record_id}",
        )
    return {"id": record_id, "status": "running"}


@router.get("/questions")
def history(scope: ScopeDep, db: DbDep) -> dict:
    return {"items": service.list_records(db, scope)}


@router.get("/questions/{record_id}")
def answer(record_id: UUID, scope: ScopeDep, db: DbDep) -> dict:
    return service.get_record(db, scope, record_id)


@router.post("/questions/{record_id}/share")
def share(record_id: UUID, body: Share, scope: ScopeDep, db: DbDep) -> dict:
    service.share_record(db, scope, record_id, body.shared)
    return {"status": "ok"}


@router.post("/questions/{record_id}/reproduce")
def reproduce(record_id: UUID, scope: ScopeDep, db: DbDep) -> dict:
    return service.reproduce(db, scope, record_id)


@router.delete("/questions/{record_id}", status_code=204)
def delete_answer(record_id: UUID, scope: ScopeDep, db: DbDep) -> None:
    service.delete_record(db, scope, record_id)


# --- Documents ------------------------------------------------------------------------------------


@router.get("/documents")
def documents(
    scope: ScopeDep,
    db: DbDep,
    entity: UUID | None = None,
    type: Annotated[list[str], Query()] = [],  # noqa: A002, B006
    private: bool | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict:
    scope.require(ent.DOCUMENTS)
    return {
        "items": access.list_documents(
            db, scope, entity_id=entity, doc_types=type, private=private, limit=limit, offset=offset
        )
    }


@router.get("/documents/{document_id}")
def document(document_id: UUID, scope: ScopeDep, db: DbDep) -> dict:
    scope.require(ent.DOCUMENTS)
    doc, passages = access.get_document(db, scope, document_id)
    return {"document": doc, "passages": passages}


@router.get("/search")
def search(
    scope: ScopeDep,
    db: DbDep,
    q: Annotated[str, Query(min_length=2, max_length=300)],
    entity: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> dict:
    return {"items": service.search(db, scope, q, entity_id=entity, limit=limit)}


@router.post("/documents", status_code=201)
async def upload(
    scope: ScopeDep, title: Annotated[str, Form(min_length=1, max_length=200)], file: Annotated[UploadFile, File()]
) -> dict:
    """Upload a plain-text or Markdown document. It stays private to the organization."""
    limit = get_settings().max_upload_bytes
    if (file.content_type or "") not in TEXT_TYPES or not (file.filename or "").lower().endswith((".txt", ".md")):
        raise ValidationFailure("Upload a plain-text (.txt) or Markdown (.md) file")
    raw = await file.read(limit + 1)
    if len(raw) > limit:
        raise ValidationFailure("The file is too large", details={"max_bytes": limit})
    try:
        body = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValidationFailure("The file must be UTF-8 text") from exc
    with tenant_session(scope.tenant_id) as session:
        document_id = service.upload_document(
            session,
            scope,
            title=clean_text(title, max_len=200),
            body=body,
            screen=lambda text: screen_content(text, source="upload").flagged,
        )
        doc, passages = access.get_document(session, scope, document_id)
    return {"document": doc, "flagged_passages": sum(1 for p in passages if p.flagged)}


@router.delete("/documents/{document_id}", status_code=204)
def delete_document(document_id: UUID, scope: ScopeDep, db: DbDep) -> None:
    service.delete_document(db, scope, document_id)


# --- Companies ------------------------------------------------------------------------------------


@router.get("/companies")
def companies(
    scope: ScopeDep,
    db: DbDep,
    q: Annotated[str, Query(max_length=80)] = "",
    tracked: bool | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 40,
) -> dict:
    return {"items": access.find_entities(db, scope, tracked=tracked, query=clean_text(q, max_len=80), limit=limit)}


@router.get("/companies/{entity_id}/fundamentals")
def fundamentals(
    entity_id: UUID, scope: ScopeDep, db: DbDep, years: Annotated[int, Query(ge=1, le=10)] = 5
) -> dict[str, Any]:
    return service.company_fundamentals(db, scope, entity_id, years=years)


# --- Theses ---------------------------------------------------------------------------------------


@router.get("/theses")
def theses(scope: ScopeDep, db: DbDep) -> dict:
    return {"items": service.list_theses(db, scope)}


@router.post("/theses", status_code=201)
def create_thesis(body: ThesisSave, scope: ScopeDep, db: DbDep) -> dict:
    return service.save_thesis(
        db,
        scope,
        thesis_id=None,
        title=body.title,
        statement=body.statement,
        conditions=[c.model_dump() for c in body.conditions],
    )


@router.put("/theses/{thesis_id}")
def update_thesis(thesis_id: UUID, body: ThesisSave, scope: ScopeDep, db: DbDep) -> dict:
    return service.save_thesis(
        db,
        scope,
        thesis_id=thesis_id,
        title=body.title,
        statement=body.statement,
        conditions=[c.model_dump() for c in body.conditions],
    )


@router.delete("/theses/{thesis_id}", status_code=204)
def delete_thesis(thesis_id: UUID, scope: ScopeDep, db: DbDep) -> None:
    service.delete_thesis(db, scope, thesis_id)
