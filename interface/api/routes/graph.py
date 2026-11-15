"""AUREX Graph endpoints: Market Impact Graph neighborhoods, scenarios and link review."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import Field

from interface.api.deps import DbDep, ScopeDep
from modules.graph import service
from modules.validation import Strict

router = APIRouter(prefix="/graph", tags=["graph"])


class NodeIn(Strict):
    key: str = Field(min_length=2, max_length=80, pattern=r"^[A-Za-z0-9][A-Za-z0-9 _.:\-]*$")
    kind: Literal["company", "sector", "commodity", "currency", "country", "indicator", "policy_event", "instrument"]
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=1000)


class LinkIn(Strict):
    source: str = Field(min_length=1, max_length=120)
    target: str = Field(min_length=1, max_length=120)
    relation: Literal[
        "supplies",
        "buys_from",
        "competes_with",
        "belongs_to",
        "exposed_to",
        "operates_in",
        "transmits_to",
        "co_moves_with",
    ]
    method: Literal["analyst_defined", "reported_fact"] = "analyst_defined"
    confidence: float = Field(ge=0, le=1)
    confidence_basis: str = Field(min_length=3, max_length=300)
    source_ref: str = Field(min_length=3, max_length=600)
    sign: Literal[-1, 0, 1] = 0
    description: str = Field(default="", max_length=1000)


class Review(Strict):
    decision: Literal["accepted", "rejected"]


def _ref(value: str) -> str | UUID:
    try:
        return UUID(value)
    except ValueError:
        return value


@router.get("/nodes")
def nodes(
    scope: ScopeDep, db: DbDep, q: Annotated[str, Query(max_length=80)] = "", kind: Annotated[list[str], Query()] = []
) -> dict:
    return {"items": service.search_nodes(db, scope, q, kinds=kind)}


@router.post("/nodes", status_code=201)
def create_node(body: NodeIn, scope: ScopeDep, db: DbDep) -> dict:
    return {"id": service.create_node(db, scope, **body.model_dump())}


@router.get("/nodes/{ref}")
def neighborhood(ref: str, scope: ScopeDep, db: DbDep, proposed: bool = False) -> dict:
    return service.neighborhood(db, scope, _ref(ref), include_proposed=proposed)


@router.get("/scenario")
def scenario(
    scope: ScopeDep,
    db: DbDep,
    start: Annotated[str, Query(min_length=1, max_length=120)],
    direction: Literal["rises", "falls"] = "rises",
    depth: Annotated[int, Query(ge=1, le=6)] = 6,
    min_confidence: Annotated[float, Query(ge=0, le=1)] = 0.0,
) -> dict:
    return service.scenario(
        db, scope, _ref(start), direction=1 if direction == "rises" else -1, depth=depth, min_confidence=min_confidence
    )


@router.post("/links", status_code=201)
def propose(body: LinkIn, scope: ScopeDep, db: DbDep) -> dict:
    return service.propose_link(db, scope, body.model_dump())


@router.get("/links/pending")
def pending(scope: ScopeDep, db: DbDep) -> dict:
    return {"items": service.pending(db, scope)}


@router.post("/links/{link_id}/review")
def review(link_id: UUID, body: Review, scope: ScopeDep, db: DbDep) -> dict:
    service.review_link(db, scope, link_id, body.decision)
    return {"status": body.decision}
