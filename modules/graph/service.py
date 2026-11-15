"""AUREX Graph: entities and relationships, impact scenarios and link review (ADR-0011).

A link carries its source, method and confidence. Proposed links are hidden by default and never used in
shared views. A scenario lists paths from an event with the evidence of every link; the confidence of a
path is that of its weakest link. A scenario is never presented as a forecast.
"""

from collections import deque
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from core import entitlements as ent
from core.errors import NotFound, ValidationFailure
from core.types import Role, Scope, utcnow
from modules.datalab import access
from modules.graph.models import GraphLink, GraphNode
from modules.logging import record_audit
from modules.validation import clean_text

RELATIONS = (
    "supplies",
    "buys_from",
    "competes_with",
    "belongs_to",
    "exposed_to",
    "operates_in",
    "transmits_to",
    "co_moves_with",
)
METHODS = ("reported_fact", "statistical_estimate", "analyst_defined", "ai_extracted")
KINDS = ("company", "sector", "commodity", "currency", "country", "indicator", "policy_event", "instrument")
LOW_CONFIDENCE = 0.4
PROPAGATES = {"transmits_to", "exposed_to", "supplies", "operates_in"}
SCENARIO_LABEL = (
    "Possible transmission paths under the stated links. A scenario explores consequences; it is not a forecast."
)


def _visible(scope: Scope, include_proposed: bool):
    own = GraphLink.tenant_id == scope.tenant_id
    shared = and_(GraphLink.tenant_id.is_(None), GraphLink.review_status == "accepted")
    if include_proposed:
        return or_(shared, own)
    return or_(shared, and_(own, GraphLink.review_status == "accepted"))


def _node_view(node: GraphNode) -> dict[str, Any]:
    return {
        "id": node.id,
        "key": node.key,
        "kind": node.kind,
        "name": node.name,
        "description": node.description,
        "private": node.tenant_id is not None,
        "has_series": node.series_id is not None,
        "series_id": node.series_id,
        "entity_id": node.entity_id,
        "instrument_id": node.instrument_id,
        "meta": node.meta,
    }


def _link_view(link: GraphLink, nodes: dict[UUID, GraphNode], passages: dict[int, Any]) -> dict[str, Any]:
    passage = passages.get(link.source_passage_id) if link.source_passage_id else None
    return {
        "id": link.id,
        "source": _node_view(nodes[link.source_id]),
        "target": _node_view(nodes[link.target_id]),
        "relation": link.relation,
        "method": link.method,
        "confidence": float(link.confidence),
        "confidence_basis": link.confidence_basis,
        "source_ref": link.source_ref,
        "sign": link.sign,
        "magnitude": float(link.magnitude) if link.magnitude is not None else None,
        "estimation": link.estimation,
        "description": link.description,
        "review_status": link.review_status,
        "private": link.tenant_id is not None,
        "low_confidence": float(link.confidence) < LOW_CONFIDENCE,
        "valid_from": link.valid_from,
        "valid_to": link.valid_to,
        "last_verified_at": link.last_verified_at,
        "evidence": {
            "passage_id": passage.passage.id,
            "text": passage.passage.text[:800],
            "location": passage.passage.location,
            "document": passage.document.title,
            "url": passage.document.url,
        }
        if passage
        else None,
    }


def _nodes(session: Session, scope: Scope, ids: set[UUID]) -> dict[UUID, GraphNode]:
    rows = session.scalars(
        select(GraphNode).where(
            GraphNode.id.in_(ids), or_(GraphNode.tenant_id.is_(None), GraphNode.tenant_id == scope.tenant_id)
        )
    )
    return {row.id: row for row in rows}


def _passages(session: Session, scope: Scope, links: list[GraphLink]) -> dict[int, Any]:
    ids = [link.source_passage_id for link in links if link.source_passage_id]
    return {hit.passage.id: hit for hit in access.get_passages(session, scope, ids)} if ids else {}


def find_node(session: Session, scope: Scope, ref: str | UUID) -> GraphNode:
    visible = or_(GraphNode.tenant_id.is_(None), GraphNode.tenant_id == scope.tenant_id)
    if isinstance(ref, UUID):
        node = session.scalar(select(GraphNode).where(GraphNode.id == ref, visible))
    else:
        node = session.scalar(select(GraphNode).where(GraphNode.key == ref, visible))
        if node is None:
            like = f"%{clean_text(ref, max_len=80)}%"
            node = session.scalar(
                select(GraphNode)
                .where(visible, or_(GraphNode.name.ilike(like), GraphNode.key.ilike(like)))
                .order_by(GraphNode.kind != "policy_event", GraphNode.name)
                .limit(1)
            )
    if node is None:
        raise NotFound("Node not found")
    return node


def search_nodes(
    session: Session, scope: Scope, query: str = "", *, kinds: list[str] | None = None, limit: int = 60
) -> list[dict[str, Any]]:
    scope.require(ent.GRAPH)
    stmt = select(GraphNode).where(or_(GraphNode.tenant_id.is_(None), GraphNode.tenant_id == scope.tenant_id))
    if query.strip():
        like = f"%{clean_text(query, max_len=80)}%"
        stmt = stmt.where(or_(GraphNode.name.ilike(like), GraphNode.key.ilike(like)))
    if kinds:
        stmt = stmt.where(GraphNode.kind.in_(kinds))
    return [_node_view(n) for n in session.scalars(stmt.order_by(GraphNode.kind, GraphNode.name).limit(limit))]


def neighborhood(session: Session, scope: Scope, ref: str | UUID, *, include_proposed: bool = False) -> dict[str, Any]:
    scope.require(ent.GRAPH)
    node = find_node(session, scope, ref)
    links = list(
        session.scalars(
            select(GraphLink).where(
                or_(GraphLink.source_id == node.id, GraphLink.target_id == node.id), _visible(scope, include_proposed)
            )
        )
    )
    nodes = _nodes(session, scope, {node.id} | {lk.source_id for lk in links} | {lk.target_id for lk in links})
    links = [lk for lk in links if lk.source_id in nodes and lk.target_id in nodes]
    passages = _passages(session, scope, links)
    links.sort(key=lambda lk: (-float(lk.confidence), lk.relation))
    return {
        "node": _node_view(node),
        "links": [_link_view(lk, nodes, passages) for lk in links],
        "low_confidence_threshold": LOW_CONFIDENCE,
    }


def scenario(
    session: Session,
    scope: Scope,
    start: str | UUID,
    *,
    direction: int = 1,
    depth: int = 6,
    min_confidence: float = 0.0,
    limit: int = 60,
) -> dict[str, Any]:
    """Paths of consequences from a starting node. Proposed and statistical links are not used."""
    scope.require(ent.GRAPH)
    if direction not in (1, -1) or not 1 <= depth <= 6:
        raise ValidationFailure("Direction is +1 or -1 and depth between 1 and 6")
    origin = find_node(session, scope, start)
    links = list(session.scalars(select(GraphLink).where(_visible(scope, False))))
    outgoing: dict[UUID, list[tuple[GraphLink, UUID, int]]] = {}
    for link in links:
        if link.relation in PROPAGATES:
            outgoing.setdefault(link.source_id, []).append((link, link.target_id, link.sign or 1))
        elif link.relation == "belongs_to":  # what reaches a sector reaches its members
            outgoing.setdefault(link.target_id, []).append((link, link.source_id, 1))
    paths: list[dict[str, Any]] = []
    queue: deque[tuple[UUID, list[tuple[GraphLink, UUID, int]]]] = deque([(origin.id, [])])
    while queue and len(paths) < limit * 4:
        current, path = queue.popleft()
        if len(path) >= depth:
            continue
        seen = {origin.id} | {step[1] for step in path}
        for link, target, sign in outgoing.get(current, []):
            if target in seen or float(link.confidence) < min_confidence:
                continue
            extended = [*path, (link, target, sign)]
            paths.append({"steps": extended})
            queue.append((target, extended))
    used = {step[0].id for p in paths for step in p["steps"]}
    used_links = [lk for lk in links if lk.id in used]
    nodes = _nodes(
        session, scope, {origin.id} | {lk.source_id for lk in used_links} | {lk.target_id for lk in used_links}
    )
    passages = _passages(session, scope, used_links)
    out = []
    for path in paths:
        if any(step[1] not in nodes for step in path["steps"]):
            continue
        effect = direction
        steps = []
        for link, target, sign in path["steps"]:
            effect *= sign
            steps.append(
                {
                    "link": _link_view(link, nodes, passages),
                    "node": _node_view(nodes[target]),
                    "effect": "rises" if effect > 0 else "falls",
                }
            )
        confidence = min(float(step[0].confidence) for step in path["steps"])
        out.append(
            {
                "end": steps[-1]["node"],
                "effect": steps[-1]["effect"],
                "confidence": confidence,
                "length": len(steps),
                "steps": steps,
                "weakest_link": min(steps, key=lambda s: s["link"]["confidence"])["link"]["description"],
            }
        )
    out.sort(key=lambda p: (-p["confidence"], p["length"]))
    return {
        "origin": _node_view(origin),
        "direction": "rises" if direction > 0 else "falls",
        "paths": out[:limit],
        "label": SCENARIO_LABEL,
        "method": "Breadth-first search over accepted transmission and exposure links; path confidence is "
        "the confidence of its weakest link.",
    }


def create_node(session: Session, scope: Scope, *, key: str, kind: str, name: str, description: str = "") -> UUID:
    scope.require(ent.GRAPH_EDIT)
    scope.require_role(Role.ANALYST)
    if kind not in KINDS:
        raise ValidationFailure("Unknown node kind", details={"allowed": list(KINDS)})
    node = GraphNode(
        tenant_id=scope.tenant_id,
        key=f"custom:{clean_text(key, max_len=80).lower()}",
        kind=kind,
        name=clean_text(name, max_len=200),
        description=clean_text(description, max_len=1000),
    )
    session.add(node)
    session.flush()
    record_audit(
        session,
        action="graph.node_created",
        tenant_id=scope.tenant_id,
        actor_id=scope.user_id,
        object_type="graph_node",
        object_id=node.id,
    )
    return node.id


def propose_link(session: Session, scope: Scope, data: dict[str, Any]) -> dict[str, Any]:
    """A link defined by a member. It is private to the organization and starts as proposed."""
    scope.require(ent.GRAPH_EDIT)
    scope.require_role(Role.ANALYST)
    if data["relation"] not in RELATIONS or data["method"] not in ("analyst_defined", "reported_fact"):
        raise ValidationFailure("Unknown relation or method", details={"relations": list(RELATIONS)})
    source_ref = clean_text(str(data.get("source_ref", "")), max_len=600)
    basis = clean_text(str(data.get("confidence_basis", "")), max_len=300)
    if not source_ref or not basis:
        raise ValidationFailure("A link needs a source and a basis for its confidence")
    confidence = float(data["confidence"])
    if not 0 <= confidence <= 1:
        raise ValidationFailure("Confidence is between 0 and 1")
    source = find_node(session, scope, data["source"])
    target = find_node(session, scope, data["target"])
    if source.id == target.id:
        raise ValidationFailure("A link connects two different nodes")
    link = GraphLink(
        tenant_id=scope.tenant_id,
        source_id=source.id,
        target_id=target.id,
        relation=data["relation"],
        method=data["method"],
        confidence=Decimal(str(confidence)),
        confidence_basis=basis,
        source_ref=source_ref,
        sign=int(data.get("sign", 0)),
        description=clean_text(str(data.get("description", "")), max_len=1000),
        review_status="proposed",
        created_by=scope.user_id,
        last_verified_at=utcnow(),
    )
    session.add(link)
    session.flush()
    record_audit(
        session,
        action="graph.link_proposed",
        tenant_id=scope.tenant_id,
        actor_id=scope.user_id,
        object_type="graph_link",
        object_id=link.id,
    )
    return _link_view(link, _nodes(session, scope, {source.id, target.id}), {})


def review_link(session: Session, scope: Scope, link_id: UUID, decision: str) -> None:
    """Accept or reject an organization's own link. The author does not review their own proposal."""
    scope.require(ent.GRAPH_EDIT)
    scope.require_role(Role.ADMIN)
    link = session.get(GraphLink, link_id)
    if link is None or link.tenant_id != scope.tenant_id:
        raise NotFound("Link not found")
    if decision not in ("accepted", "rejected"):
        raise ValidationFailure("A review accepts or rejects")
    if link.created_by == scope.user_id and decision == "accepted" and scope.role != Role.OWNER:
        raise ValidationFailure("Another administrator reviews this link")
    link.review_status, link.reviewed_by, link.last_verified_at = decision, scope.user_id, utcnow()
    record_audit(
        session,
        action=f"graph.link_{decision}",
        tenant_id=scope.tenant_id,
        actor_id=scope.user_id,
        object_type="graph_link",
        object_id=link.id,
    )


def pending(session: Session, scope: Scope) -> list[dict[str, Any]]:
    scope.require(ent.GRAPH)
    links = list(
        session.scalars(
            select(GraphLink).where(GraphLink.tenant_id == scope.tenant_id, GraphLink.review_status == "proposed")
        )
    )
    nodes = _nodes(session, scope, {lk.source_id for lk in links} | {lk.target_id for lk in links})
    return [_link_view(lk, nodes, {}) for lk in links]
