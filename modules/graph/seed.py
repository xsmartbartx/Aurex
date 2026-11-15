"""Curated first part of the Market Impact Graph (decision 8: shipped in Stage 3).

``seed`` creates the macro and sector nodes and the analyst-defined transmission links. ``refresh`` adds what
depends on loaded data: series attached to nodes, demonstration companies, their sector membership, the
exposures they report in their filings (with the passage as evidence) and statistical co-movement estimates.
"""

import math
import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from core import entitlements as ent
from core.errors import AurexError
from core.types import Role, Scope, utcnow
from modules.datalab import access
from modules.graph.models import GraphLink, GraphNode
from modules.processing import ENGINE_VERSION
from modules.processing import series as calc

ECB_RATES = "https://www.ecb.europa.eu/stats/policy_and_exchange_rates/key_ecb_interest_rates/html/index.en.html"
ECB_TRANSMISSION = "https://www.ecb.europa.eu/mopo/intro/transmission/html/index.en.html"
ECB_ESTR = (
    "https://www.ecb.europa.eu/stats/financial_markets_and_interest_rates/euro_short-term_rate/html/index.en.html"
)

NODES: list[dict[str, Any]] = [
    {
        "key": "event:ecb-policy",
        "kind": "policy_event",
        "name": "ECB monetary policy decision",
        "description": "A change in the key ECB interest rates decided by the Governing Council.",
    },
    {"key": "indicator:ecb-dfr", "kind": "indicator", "name": "ECB deposit facility rate", "series": "ECB:DFR"},
    {"key": "indicator:estr", "kind": "indicator", "name": "Euro short-term rate (€STR)", "series": "ECB:ESTR"},
    {"key": "indicator:eur-2y", "kind": "indicator", "name": "Euro area 2-year government yield", "series": "ECB:YC2Y"},
    {
        "key": "indicator:eur-10y",
        "kind": "indicator",
        "name": "Euro area 10-year government yield",
        "series": "ECB:YC10Y",
    },
    {"key": "indicator:hicp", "kind": "indicator", "name": "Euro area inflation (HICP)", "series": "ECB:HICP_YOY"},
    {"key": "indicator:gdp", "kind": "indicator", "name": "Euro area real GDP growth", "series": "ECB:GDP_YOY"},
    {
        "key": "currency:eurusd",
        "kind": "currency",
        "name": "EUR/USD exchange rate",
        "series": "ECB:EXR:USD",
        "description": "US dollars per euro. A higher value means a stronger euro.",
    },
    {
        "key": "indicator:financing-costs",
        "kind": "indicator",
        "name": "Corporate financing costs",
        "description": "The cost at which companies borrow, driven by market interest rates and credit spreads.",
    },
    *[
        {"key": f"sector:{name.lower().replace(' ', '-')}", "kind": "sector", "name": name}
        for name in (
            "Utilities",
            "Financials",
            "Real Estate",
            "Information Technology",
            "Industrials",
            "Consumer Staples",
            "Energy",
            "Materials",
            "Health Care",
        )
    ],
]

ANALYST = "analyst_defined"
LINKS: list[dict[str, Any]] = [
    {
        "source": "event:ecb-policy",
        "target": "indicator:ecb-dfr",
        "relation": "transmits_to",
        "sign": 1,
        "method": "reported_fact",
        "confidence": 0.95,
        "source_ref": ECB_RATES,
        "confidence_basis": "The deposit facility rate is one of the three key rates set by the Governing Council.",
        "description": "A policy decision sets the deposit facility rate.",
    },
    {
        "source": "indicator:ecb-dfr",
        "target": "indicator:estr",
        "relation": "transmits_to",
        "sign": 1,
        "method": ANALYST,
        "confidence": 0.9,
        "source_ref": ECB_ESTR,
        "confidence_basis": "With ample liquidity, overnight unsecured rates trade close to the deposit facility rate.",
        "description": "Money-market rates follow the deposit facility rate.",
    },
    {
        "source": "indicator:ecb-dfr",
        "target": "indicator:eur-2y",
        "relation": "transmits_to",
        "sign": 1,
        "method": ANALYST,
        "confidence": 0.75,
        "source_ref": ECB_TRANSMISSION,
        "confidence_basis": "Short-dated yields price the expected path of policy rates.",
        "description": "Expected policy rates feed into short-term government yields.",
    },
    {
        "source": "indicator:eur-2y",
        "target": "indicator:eur-10y",
        "relation": "transmits_to",
        "sign": 1,
        "method": ANALYST,
        "confidence": 0.6,
        "source_ref": ECB_TRANSMISSION,
        "confidence_basis": "Long yields reflect expected short rates plus a term premium that can move independently.",
        "description": "Part of a change in short yields passes to long yields.",
    },
    {
        "source": "indicator:eur-10y",
        "target": "indicator:financing-costs",
        "relation": "transmits_to",
        "sign": 1,
        "method": ANALYST,
        "confidence": 0.6,
        "source_ref": ECB_TRANSMISSION,
        "confidence_basis": "Corporate bond and loan rates are priced over government yields; spreads add uncertainty.",
        "description": "Higher market yields raise the cost of corporate borrowing.",
    },
    {
        "source": "indicator:ecb-dfr",
        "target": "currency:eurusd",
        "relation": "transmits_to",
        "sign": 1,
        "method": ANALYST,
        "confidence": 0.4,
        "source_ref": ECB_TRANSMISSION,
        "confidence_basis": "Rate differentials affect capital flows, but exchange rates have many other drivers.",
        "description": "Higher euro rates relative to dollar rates tend to strengthen the euro.",
    },
    {
        "source": "indicator:hicp",
        "target": "event:ecb-policy",
        "relation": "transmits_to",
        "sign": 1,
        "method": ANALYST,
        "confidence": 0.55,
        "source_ref": ECB_TRANSMISSION,
        "confidence_basis": "The ECB's mandate is price stability; inflation above target argues for tighter policy.",
        "description": "Inflation above target makes a rate increase more likely.",
    },
    {
        "source": "indicator:financing-costs",
        "target": "sector:utilities",
        "relation": "exposed_to",
        "sign": -1,
        "method": ANALYST,
        "confidence": 0.6,
        "source_ref": ECB_TRANSMISSION,
        "confidence_basis": "Capital-intensive, highly leveraged businesses with regulated returns.",
        "description": "Utilities carry high debt, so higher financing costs weigh on earnings and valuations.",
    },
    {
        "source": "indicator:financing-costs",
        "target": "sector:real-estate",
        "relation": "exposed_to",
        "sign": -1,
        "method": ANALYST,
        "confidence": 0.6,
        "source_ref": ECB_TRANSMISSION,
        "confidence_basis": "Leverage and property valuations that discount future rents.",
        "description": "Real estate is financed with debt and valued on discounted rents.",
    },
    {
        "source": "indicator:financing-costs",
        "target": "sector:financials",
        "relation": "exposed_to",
        "sign": 1,
        "method": ANALYST,
        "confidence": 0.45,
        "source_ref": ECB_TRANSMISSION,
        "confidence_basis": "Wider net interest margins, offset by credit losses if borrowers come under strain.",
        "description": "Banks can earn wider lending margins when rates rise.",
    },
    {
        "source": "indicator:financing-costs",
        "target": "sector:information-technology",
        "relation": "exposed_to",
        "sign": -1,
        "method": ANALYST,
        "confidence": 0.45,
        "source_ref": ECB_TRANSMISSION,
        "confidence_basis": "Valuations depend on cash flows far in the future, which higher discount rates reduce.",
        "description": "Long-duration growth valuations are sensitive to discount rates.",
    },
]


def _system_scope() -> Scope:
    """Reads shared data for curation. Tenant-private data is never visible to it."""
    return Scope(
        tenant_id=uuid.UUID(int=0),
        user_id=uuid.UUID(int=0),
        role=Role.OWNER,
        plan="system",
        entitlements=frozenset({ent.DATA_PUBLIC, ent.DATA_DEMO, ent.DATA_LICENSED, ent.MARKETS, ent.DOCUMENTS}),
    )


def _node(session: Session, spec: dict[str, Any]) -> uuid.UUID:
    values = {k: spec.get(k) for k in ("key", "kind", "name")} | {
        "description": spec.get("description", ""),
        "meta": spec.get("meta", {}),
        "tenant_id": None,
    }
    for field in ("series_id", "entity_id", "instrument_id"):
        if spec.get(field):
            values[field] = spec[field]
    stmt = pg_insert(GraphNode).values(id=uuid.uuid4(), **values)
    update = {k: stmt.excluded[k] for k in values if k not in ("key", "tenant_id")}
    stmt = stmt.on_conflict_do_update(index_elements=["tenant_id", "key"], set_=update).returning(GraphNode.id)
    return session.execute(stmt).scalar_one()


def _link(session: Session, ids: dict[str, uuid.UUID], spec: dict[str, Any]) -> None:
    source, target = ids[spec["source"]], ids[spec["target"]]
    existing = session.scalar(
        select(GraphLink).where(
            GraphLink.tenant_id.is_(None),
            GraphLink.source_id == source,
            GraphLink.target_id == target,
            GraphLink.relation == spec["relation"],
        )
    )
    fields = {k: v for k, v in spec.items() if k not in ("source", "target")}
    if existing is None:
        existing = GraphLink(tenant_id=None, source_id=source, target_id=target, review_status="accepted", **fields)
        session.add(existing)
    else:
        for key, value in fields.items():
            setattr(existing, key, value)
    existing.last_verified_at = utcnow()


def seed(session: Session) -> None:
    ids = {spec["key"]: _node(session, spec) for spec in NODES}
    for spec in LINKS:
        _link(session, ids, spec)
    session.flush()
    refresh(session)


def refresh(session: Session) -> int:
    """Attach loaded data and recompute estimates. Safe to run after every import."""
    scope = _system_scope()
    ids = {row.key: row.id for row in session.scalars(select(GraphNode).where(GraphNode.tenant_id.is_(None)))}
    for spec in NODES:
        if spec.get("series"):
            try:
                series, _ = access.series_meta(session, scope, spec["series"])
                session.get(GraphNode, ids[spec["key"]]).series_id = series.id
            except AurexError:
                continue
    created = 0
    index_series = None
    try:
        index = access.get_instrument(session, scope, "DEMO10.DEMO")
        index_series = access.primary_series(session, scope, index.id)
        ids["instrument:DEMO10.DEMO"] = _node(
            session,
            {
                "key": "instrument:DEMO10.DEMO",
                "kind": "instrument",
                "name": index.name,
                "instrument_id": index.id,
                "series_id": index_series.id,
            },
        )
    except AurexError:
        pass
    for entity in access.find_entities(session, scope, query="(demonstration)", limit=50):
        if not entity.meta.get("demonstration"):
            continue
        instruments = access.search_instruments(session, scope, entity.ticker or "", limit=1)
        instrument = instruments[0] if instruments else None
        series = access.primary_series(session, scope, instrument.id) if instrument and instrument.has_prices else None
        key = f"company:{entity.key}"
        ids[key] = _node(
            session,
            {
                "key": key,
                "kind": "company",
                "name": entity.name,
                "entity_id": entity.id,
                "instrument_id": instrument.id if instrument else None,
                "series_id": series.id if series else None,
                "meta": {"ticker": entity.ticker, "demonstration": True},
            },
        )
        sector_key = f"sector:{(entity.sector or '').lower().replace(' ', '-')}"
        if sector_key in ids:
            _link(
                session,
                ids,
                {
                    "source": key,
                    "target": sector_key,
                    "relation": "belongs_to",
                    "sign": 1,
                    "method": "reported_fact",
                    "confidence": 1.0,
                    "source_ref": "AUREX demonstration classification",
                    "confidence_basis": "Sector assigned in the company's classification record.",
                    "description": f"{entity.name} is classified in {entity.sector}.",
                },
            )
            created += 1
        created += _reported_exposures(session, scope, ids, entity, key)
        if series and index_series:
            created += _co_movement(session, scope, ids, key, series.id, index_series.id)
    session.flush()
    return created


def _reported_exposures(session: Session, scope: Scope, ids: dict[str, uuid.UUID], entity, key: str) -> int:
    """Exposures the company states in its own filing, with the passage as evidence."""
    created = 0
    for query, target, relation_text in (
        ("interest rate risk financing costs", "indicator:financing-costs", "financing costs"),
        ("currency risk stronger dollar revenue", "currency:eurusd", "the EUR/USD exchange rate"),
    ):
        hits = access.search_passages(session, scope, query, entity_ids=[entity.id], limit=1, include_flagged=False)
        if not hits:
            continue
        text = hits[0].passage.text.lower()
        if target == "indicator:financing-costs":
            if "limited direct sensitivity" in text:
                continue
            sign = 1 if "benefit from higher interest rates" in text else -1
        else:
            sign = 1  # a stronger euro (higher EUR/USD) raises the dollar value of euro revenue
        _link(
            session,
            ids,
            {
                "source": target,
                "target": key,
                "relation": "exposed_to",
                "sign": sign,
                "method": "reported_fact",
                "confidence": 0.8,
                "source_ref": hits[0].document.title,
                "source_passage_id": hits[0].passage.id,
                "confidence_basis": "Stated by the company in its annual report.",
                "description": f"{entity.name} reports exposure to {relation_text}.",
            },
        )
        created += 1
    return created


def _co_movement(session: Session, scope: Scope, ids: dict[str, uuid.UUID], key: str, series_id, index_id) -> int:
    end = utcnow().date()
    start = end - timedelta(days=366)
    values = access.load_values(session, scope, [series_id, index_id], start=start, end=end)
    result = calc.correlation_matrix(
        {"a": [(d, float(v)) for d, v in values[series_id]], "b": [(d, float(v)) for d, v in values[index_id]]}
    )
    if not result["matrix"] or result["matrix"][0][1] is None:
        return 0
    r, n = result["matrix"][0][1], result["observations"]
    error = (1 - r * r) / math.sqrt(max(n - 1, 1))
    _link(
        session,
        ids,
        {
            "source": key,
            "target": "instrument:DEMO10.DEMO",
            "relation": "co_moves_with",
            "sign": 1 if r >= 0 else -1,
            "method": "statistical_estimate",
            "confidence": round(max(0.0, min(1.0, abs(r) - 2 * error)), 3),
            "magnitude": round(r, 6),
            "source_ref": f"AUREX financial engine {ENGINE_VERSION}",
            "confidence_basis": "Absolute correlation less two standard errors.",
            "estimation": {
                "measure": "pearson correlation of daily returns",
                "window": [result["start"], result["end"]],
                "observations": n,
                "standard_error": round(error, 6),
            },
            "valid_from": start,
            "valid_to": end,
            "description": "Statistical co-movement. Not evidence of cause and effect.",
        },
    )
    return 1
