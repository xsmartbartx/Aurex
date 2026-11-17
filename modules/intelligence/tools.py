"""Tools the agents may use. Every tool is read-only, acts with the scope of the requesting user and
records what it returns on the evidence ledger. Data comes through the DataLab access interface, figures
from the financial engine.
"""

from datetime import date, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from core import entitlements as ent
from core.errors import AurexError, NotFound
from core.types import Scope, utcnow
from modules.analysis.engine import AgentSpec, RunContext, Tool
from modules.datalab import access
from modules.datalab.schemas import EntityOut, InstrumentOut, Provenance
from modules.processing import ENGINE_VERSION
from modules.processing import fundamentals as fnd
from modules.processing import series as calc

RANGE_DAYS = {"1M": 31, "3M": 92, "6M": 183, "1Y": 366, "3Y": 1096, "5Y": 1827, "10Y": 3653}
STRING = {"type": "string"}
NULLABLE = {"type": ["string", "null"]}
RATIO_LABEL = {
    "revenue_growth": "Revenue growth",
    "gross_margin": "Gross margin",
    "operating_margin": "Operating margin",
    "net_margin": "Net margin",
    "free_cash_flow": "Free cash flow",
    "fcf_margin": "Free cash flow margin",
    "total_debt": "Total debt",
    "net_debt": "Net debt",
    "debt_to_equity": "Debt to equity",
    "interest_coverage": "Interest coverage",
    "return_on_equity": "Return on equity",
    "current_ratio": "Current ratio",
}

AGENTS: dict[str, AgentSpec] = {
    "research": AgentSpec(
        "research",
        "Research Agent",
        "Collect material and write a report with cited sources.",
        (
            "find_companies",
            "get_fundamentals",
            "get_series",
            "search_documents",
            "recent_documents",
            "compare_companies",
            "correlation",
        ),
    ),
    "earnings": AgentSpec(
        "earnings",
        "Earnings Agent",
        "Analyze reported results: growth, margins, cash generation and what changed between periods.",
        ("find_companies", "get_fundamentals", "compare_companies", "search_documents", "recent_documents"),
        "Point out differences between what a filing says and what the reported figures show.",
    ),
    "macro": AgentSpec(
        "macro",
        "Macro Agent",
        "Examine relations between interest rates, inflation, currencies and markets.",
        ("find_companies", "get_series", "correlation", "search_documents", "recent_documents", "impact_paths"),
        "Describe scenarios and their conditions. A scenario is never a forecast.",
    ),
    "risk": AgentSpec(
        "risk",
        "Risk Agent",
        "Detect concentration in the user's portfolios and describe their exposures.",
        ("portfolio_overview", "get_series", "correlation", "find_companies"),
    ),
    "data_quality": AgentSpec(
        "data_quality",
        "Data Quality Agent",
        "Detect gaps, anomalies and stale data in the datasets behind the terminal.",
        ("dataset_status", "get_series", "find_companies"),
    ),
    "thesis": AgentSpec(
        "thesis",
        "Thesis Monitor",
        "Check whether new data contradicts the assumptions of a saved thesis.",
        ("thesis_status", "get_series", "search_documents", "find_companies"),
    ),
}


class Toolbox:
    """Builds the tool set for one run, bound to a session, a scope and a data channel."""

    def __init__(
        self,
        session: Session,
        scope: Scope,
        *,
        external: bool,
        as_of: datetime | None = None,
        extra: dict[str, Tool] | None = None,
    ) -> None:
        self.session, self.scope, self.as_of = session, scope, as_of
        # License enforcement point 3: data not cleared for this kind of model is never retrieved.
        self.channel: access.Channel = "model_external" if external else "model_local"
        self.extra = extra or {}

    # --- helpers ----------------------------------------------------------------------------------

    def _resolve(self, name: str) -> tuple[InstrumentOut, EntityOut | None]:
        name = (name or "").strip()[:80]
        if not name:
            raise NotFound("Name a company or an instrument")
        try:
            instrument = access.get_instrument(self.session, self.scope, name)
        except AurexError:
            hits = access.search_instruments(self.session, self.scope, name, limit=5)
            hits = [h for h in hits if h.dataset in self._allowed_codes()]
            if not hits:
                raise NotFound(f"No instrument matches '{name}'") from None
            instrument = hits[0]
        if instrument.dataset not in self._allowed_codes():
            raise NotFound("This data is not cleared for use by the current AI engine")
        entity = access.get_entity(self.session, self.scope, instrument.entity_id) if instrument.entity_id else None
        return instrument, entity

    def _allowed_codes(self) -> set[str]:
        return {d.code for d, _ in access.allowed(self.session, self.scope, self.channel).values()}

    def _note_provenance(self, run: RunContext, what: str, prov: Provenance | None) -> dict[str, Any]:
        if prov is None:
            return {}
        if prov.license_class == "demonstration":
            run.ledger.gap(f"{what} is demonstration data generated by AUREX, not market data.")
        if prov.status in ("stale", "failed"):
            run.ledger.gap(
                f"{what}: the dataset '{prov.dataset_name}' is {prov.status}; "
                f"latest data {str(prov.latest_ref_time)[:10]}."
            )
        return {
            "dataset": prov.dataset,
            "attribution": prov.attribution,
            "license_class": prov.license_class,
            "freshness_class": prov.freshness_class,
            "status": prov.status,
        }

    # --- tools ------------------------------------------------------------------------------------

    def find_companies(self, run: RunContext, query: str) -> dict[str, Any]:
        allowed = self._allowed_codes()
        hits = [
            h for h in access.search_instruments(self.session, self.scope, query[:80], limit=8) if h.dataset in allowed
        ]
        return {
            "matches": [
                {
                    "symbol": h.symbol,
                    "name": h.name,
                    "type": h.type,
                    "has_price_data": h.has_prices,
                    "has_issuer": h.entity_id is not None,
                    "demonstration": h.license_class == "demonstration",
                }
                for h in hits
            ]
        }

    def get_fundamentals(self, run: RunContext, company: str, years: int = 3) -> dict[str, Any]:
        instrument, entity = self._resolve(company)
        if entity is None:
            run.ledger.gap(f"{instrument.symbol} has no issuer with reported financial statements.")
            return {"company": instrument.name, "fiscal_years": [], "note": "No issuer financials for this instrument."}
        as_of = self.as_of.date() if self.as_of else None
        facts, prov = access.entity_facts(self.session, self.scope, entity.id, as_of=as_of, channel=self.channel)
        source = self._note_provenance(run, f"Financial data for {entity.name}", prov)
        analysis = fnd.analyze([f.model_dump() for f in facts], max_years=max(1, min(int(years or 3), 6)))
        if not analysis["years"]:
            run.ledger.gap(
                f"No reported annual figures are loaded for {entity.name}."
                + ("" if entity.tracked else " Track the company in Intelligence to import its filings.")
            )
            return {"company": entity.name, "fiscal_years": []}
        out = []
        for year in analysis["years"]:
            fy = year["fiscal_year"]
            items, ratios = [], []
            for name, item in year["items"].items():
                evidence = run.ledger.add(
                    "fact",
                    f"{item['label']} FY{fy} — {entity.name}",
                    key=("fact", item["fact_id"]),
                    value=float(item["value"]),
                    unit=item["unit"],
                    numbers=[float(fy)],
                    source={
                        **source,
                        "fact_id": item["fact_id"],
                        "concept": item["concept"],
                        "accession": item["accession"],
                        "filed_at": item["filed_at"].isoformat(),
                        "period_end": year["period_end"].isoformat(),
                        "entity_id": str(entity.id),
                    },
                )
                items.append(
                    {
                        "id": evidence.id,
                        "item": name,
                        "label": item["label"],
                        "value": float(item["value"]),
                        "unit": item["unit"],
                    }
                )
            for name, ratio in year["ratios"].items():
                evidence = run.ledger.add(
                    "calculation",
                    f"{RATIO_LABEL.get(name, name)} FY{fy} — {entity.name}",
                    key=("ratio", str(entity.id), fy, name),
                    value=ratio.output,
                    unit=ratio.unit,
                    numbers=[float(fy)],
                    calculation=ratio.to_dict(),
                    source={**source, "period_end": year["period_end"].isoformat(), "entity_id": str(entity.id)},
                    recipe={"tool": "get_fundamentals", "input": {"company": instrument.symbol, "years": 6}},
                )
                ratios.append(
                    {
                        "id": evidence.id,
                        "ratio": name,
                        "label": RATIO_LABEL.get(name, name),
                        "value": round(ratio.output, 4),
                        "unit": ratio.unit,
                    }
                )
            out.append(
                {
                    "fiscal_year": fy,
                    "period_end": year["period_end"].isoformat(),
                    "reported": items,
                    "calculated": ratios,
                }
            )
        latest_missing = [
            m
            for m in analysis["missing"]
            if m in ("revenue", "net_income", "operating_cash_flow", "capex", "equity", "debt_long_term")
        ]
        if latest_missing:
            run.ledger.gap(
                f"{entity.name}: not reported for the latest fiscal year: "
                f"{', '.join(m.replace('_', ' ') for m in latest_missing)}."
            )
        return {
            "company": entity.name,
            "symbol": instrument.symbol,
            "sector": entity.sector,
            "engine_version": ENGINE_VERSION,
            "fiscal_years": out,
        }

    def get_series(self, run: RunContext, symbol: str, range: str = "1Y") -> dict[str, Any]:  # noqa: A002
        instrument, _ = self._resolve(symbol)
        series_list = access.instrument_series(self.session, self.scope, instrument.id)
        if not series_list:
            run.ledger.gap(f"No licensed price series is available for {instrument.symbol}.")
            return {"symbol": instrument.symbol, "note": "No licensed price data for this instrument."}
        series = series_list[0]
        code = range.upper() if range and range.upper() in RANGE_DAYS else "1Y"
        end = (self.as_of or utcnow()).date()
        start = end - timedelta(days=RANGE_DAYS[code])
        points = access.load_values(
            self.session, self.scope, [series.id], start=start, end=end, as_of=self.as_of, channel=self.channel
        )[series.id]
        _, prov = access.series_meta(self.session, self.scope, series.id, self.channel)
        source = self._note_provenance(run, f"{instrument.symbol} ({series.name})", prov) | {
            "series_id": str(series.id),
            "series_code": series.code,
            "instrument": instrument.symbol,
        }
        if len(points) < 2:
            run.ledger.gap(f"Fewer than two observations for {instrument.symbol} in the last {code}.")
            return {"symbol": instrument.symbol, "observations": len(points)}
        dates = [d for d, _ in points]
        values = [float(v) for _, v in points]
        stats = calc.summary(values, dates, series.frequency)
        recipe = {"tool": "get_series", "input": {"symbol": instrument.symbol, "range": code}}
        last = run.ledger.add(
            "observation",
            f"{instrument.symbol} latest value ({dates[-1].isoformat()})",
            key=("obs", str(series.id), dates[-1]),
            value=values[-1],
            unit=series.unit,
            source={**source, "ref_time": dates[-1].isoformat()},
        )
        evidence = [
            {
                "id": last.id,
                "measure": "latest value",
                "value": values[-1],
                "unit": series.unit,
                "date": dates[-1].isoformat(),
            }
        ]
        if series.kind in ("rate", "yield", "macro"):
            # Rates and indicators are levels: their change is in percentage points, not a return.
            stats["change"] = values[-1] - values[0]
            measures = [
                ("change", f"Change over {code} (percentage points)", 1, "percentage points"),
                ("high", f"High over {code}", 1, series.unit),
                ("low", f"Low over {code}", 1, series.unit),
            ]
        else:
            measures = [
                ("total_return", f"Return over {code}", 100, "percent"),
                ("volatility", "Annualized volatility", 100, "percent"),
                ("max_drawdown", "Maximum drawdown", 100, "percent"),
                ("high", f"High over {code}", 1, series.unit),
                ("low", f"Low over {code}", 1, series.unit),
            ]
        for name, label, factor, unit in measures:
            if stats.get(name) is None:
                continue
            item = run.ledger.add(
                "calculation",
                f"{label} — {instrument.symbol}",
                key=("stat", str(series.id), code, name, dates[-1]),
                value=stats[name] * factor,
                unit=unit,
                source=source,
                calculation={
                    "definition": name,
                    "version": ENGINE_VERSION,
                    "inputs": {
                        "series": series.code,
                        "start": dates[0].isoformat(),
                        "end": dates[-1].isoformat(),
                        "observations": len(values),
                    },
                },
                recipe=recipe,
            )
            evidence.append({"id": item.id, "measure": label, "value": round(stats[name] * factor, 4), "unit": unit})
        return {
            "symbol": instrument.symbol,
            "name": instrument.name,
            "series": series.name,
            "range": code,
            "from": dates[0].isoformat(),
            "to": dates[-1].isoformat(),
            "evidence": evidence,
        }

    def search_documents(
        self, run: RunContext, query: str, company: str | None = None, source: str = "all"
    ) -> dict[str, Any]:
        entity_ids = []
        if company:
            try:
                _, entity = self._resolve(company)
                entity_ids = [entity.id] if entity else []
            except AurexError:
                entity_ids = []
        hits = access.search_passages(
            self.session,
            self.scope,
            query[:300],
            entity_ids=entity_ids,
            limit=8,
            include_flagged=False,
            until=self.as_of,
            channel=self.channel,
            private=True if source == "organization" else None,
        )
        out, withheld = [], 0
        for hit in hits:
            if run.screen(hit.passage.text):  # screened again at the point of use
                withheld += 1
                continue
            doc = hit.document
            evidence = run.ledger.add(
                "passage",
                f"{doc.title} · {hit.passage.location}",
                key=("passage", hit.passage.id),
                text=hit.passage.text[:1500],
                source={
                    "document_id": str(doc.id),
                    "passage_id": hit.passage.id,
                    "location": hit.passage.location,
                    "published_at": doc.published_at.date().isoformat(),
                    "url": doc.url,
                    "doc_type": doc.doc_type,
                    "dataset": doc.dataset,
                    "attribution": doc.attribution,
                    "license_class": doc.license_class,
                    "private": doc.private,
                },
            )
            out.append(
                {
                    "id": evidence.id,
                    "document": doc.title,
                    "published": doc.published_at.date().isoformat(),
                    "location": hit.passage.location,
                    "text": hit.passage.text[:1500],
                }
            )
        if withheld:
            run.ledger.gap(
                f"{withheld} passage{'s were' if withheld > 1 else ' was'} withheld because the text "
                "contains instruction-like content."
            )
        if not out:
            run.ledger.gap(f"No document passage matched '{query[:80]}'" + (f" for {company}." if company else "."))
        return {"passages": out}

    def recent_documents(self, run: RunContext, company: str | None = None) -> dict[str, Any]:
        entity_id = None
        if company:
            _, entity = self._resolve(company)
            entity_id = entity.id if entity else None
        docs = access.list_documents(self.session, self.scope, entity_id=entity_id, limit=10, channel=self.channel)
        out = []
        for doc in docs:
            evidence = run.ledger.add(
                "passage",
                f"{doc.title} ({doc.doc_type})",
                key=("doc", str(doc.id)),
                text=doc.title,
                source={
                    "document_id": str(doc.id),
                    "published_at": doc.published_at.date().isoformat(),
                    "url": doc.url,
                    "doc_type": doc.doc_type,
                    "dataset": doc.dataset,
                    "attribution": doc.attribution,
                    "license_class": doc.license_class,
                },
            )
            out.append(
                {
                    "id": evidence.id,
                    "title": doc.title,
                    "type": doc.doc_type,
                    "published": doc.published_at.date().isoformat(),
                }
            )
        return {"documents": out}

    def compare_companies(self, run: RunContext, companies: list[str]) -> dict[str, Any]:
        rows = []
        for name in list(companies)[:6]:
            try:
                result = self.get_fundamentals(run, name, years=1)
            except AurexError as exc:
                rows.append({"company": name, "error": exc.message})
                continue
            year = result["fiscal_years"][0] if result.get("fiscal_years") else None
            year = year or {"fiscal_year": None, "reported": [], "calculated": []}
            rows.append(
                {
                    "company": result["company"],
                    "fiscal_year": year["fiscal_year"],
                    "reported": year["reported"],
                    "calculated": year["calculated"],
                }
            )
        return {"comparison": rows}

    def correlation(self, run: RunContext, symbols: list[str], range: str = "1Y") -> dict[str, Any]:  # noqa: A002
        code = range.upper() if range and range.upper() in RANGE_DAYS else "1Y"
        end = (self.as_of or utcnow()).date()
        start = end - timedelta(days=RANGE_DAYS[code])
        data: dict[str, list[tuple[date, float]]] = {}
        for symbol in list(symbols)[:8]:
            instrument, _ = self._resolve(symbol)
            series_list = access.instrument_series(self.session, self.scope, instrument.id)
            if not series_list:
                run.ledger.gap(f"No price series for {instrument.symbol}; it is left out of the correlation.")
                continue
            points = access.load_values(
                self.session,
                self.scope,
                [series_list[0].id],
                start=start,
                end=end,
                as_of=self.as_of,
                channel=self.channel,
            )[series_list[0].id]
            data[instrument.symbol] = [(d, float(v)) for d, v in points]
        if len(data) < 2:
            return {"note": "At least two instruments with price data are needed."}
        result = calc.correlation_matrix(data)
        pairs = []
        names = result["names"]
        for i, a in enumerate(names):
            for j in range_(i + 1, len(names)):
                value = result["matrix"][i][j] if result["matrix"] else None
                if value is None:
                    continue
                item = run.ledger.add(
                    "calculation",
                    f"Correlation of returns {a} / {names[j]} over {code}",
                    key=("corr", a, names[j], code, end),
                    value=value,
                    unit="correlation",
                    calculation={
                        "definition": "pearson correlation of simple returns on common dates",
                        "version": ENGINE_VERSION,
                        "inputs": {
                            "start": result["start"],
                            "end": result["end"],
                            "observations": result["observations"],
                        },
                    },
                    recipe={"tool": "correlation", "input": {"symbols": [a, names[j]], "range": code}},
                )
                pairs.append({"id": item.id, "a": a, "b": names[j], "value": value})
        return {"range": code, "observations": result["observations"], "pairs": pairs}

    def dataset_status(self, run: RunContext) -> dict[str, Any]:
        out = []
        for dataset in access.list_datasets(self.session, self.scope):
            runs = access.dataset_runs(self.session, self.scope, dataset.code, limit=1)
            quality = runs[0].quality if runs else {}
            flagged = sum(int(v) for k, v in quality.items() if k in ("suspect", "gaps", "jumps", "non_positive"))
            item = run.ledger.add(
                "dataset",
                f"Dataset {dataset.name}: {dataset.status}",
                key=("dataset", dataset.code),
                text=f"Status {dataset.status}. Last import {str(dataset.last_success_at)[:16]}. "
                f"Latest data {str(dataset.latest_ref_time)[:10]}. Quality flags in the last run: {flagged}.",
                value=float(flagged),
                unit="quality flags",
                source={
                    "dataset": dataset.code,
                    "status": dataset.status,
                    "freshness_class": dataset.freshness_class,
                    "license_class": dataset.license.data_class,
                },
            )
            out.append(
                {
                    "id": item.id,
                    "dataset": dataset.name,
                    "status": dataset.status,
                    "freshness": dataset.freshness_class,
                    "quality_flags": flagged,
                    "last_run_quality": quality,
                    "detail": dataset.status_detail,
                }
            )
        return {"datasets": out}

    def thesis_status(self, run: RunContext, thesis: str | None = None) -> dict[str, Any]:
        """Saved theses of the requesting user and whether each monitored condition still holds."""
        from modules.intelligence.models import Thesis  # noqa: PLC0415 - own module, imported lazily

        stmt = self.session.query(Thesis).filter(
            Thesis.tenant_id == self.scope.tenant_id, Thesis.user_id == self.scope.user_id
        )
        out, statements = [], []
        for item in stmt.order_by(Thesis.created_at.desc()).limit(10):
            if thesis and thesis.lower() not in (item.title.lower() + str(item.id)):
                continue
            for condition in item.conditions:
                series, prov = access.series_meta(self.session, self.scope, UUID(condition["series_id"]), self.channel)
                if series.latest_value is None:
                    run.ledger.gap(f"No data yet for {condition['instrument']} in thesis '{item.title}'.")
                    continue
                value = float(series.latest_value)
                holds = value > condition["value"] if condition["operator"] == "above" else value < condition["value"]
                evidence = run.ledger.add(
                    "observation",
                    f"{condition['instrument']} latest value for thesis '{item.title}'",
                    key=("obs", str(series.id), series.latest_ref_time),
                    value=value,
                    unit=series.unit,
                    numbers=[float(condition["value"])],
                    source=self._note_provenance(run, condition["instrument"], prov)
                    | {"ref_time": str(series.latest_ref_time)[:10], "series_code": series.code},
                )
                verdict = "holds" if holds else "no longer holds"
                statements.append(
                    {
                        "text": f"In thesis '{item.title}', the condition {condition['instrument']} "
                        f"{condition['operator']} {condition['value']:g} {verdict}: the latest value is {value:g} "
                        f"({str(series.latest_ref_time)[:10]}).",
                        "evidence": [evidence.id],
                    }
                )
            out.append({"title": item.title, "status": item.status, "statement": item.statement[:500]})
        if not out:
            run.ledger.gap("No saved thesis matches the request.")
        return {"theses": out, "statements": statements}

    def portfolio_overview(self, run: RunContext, portfolio: str | None = None) -> dict[str, Any]:
        """Holdings, exposures, concentration and limit breaches of the requesting user's portfolio."""
        from modules.portfolio import service as portfolios  # noqa: PLC0415 - published read interface

        items = portfolios.list_portfolios(self.session, self.scope)
        if portfolio:
            items = [p for p in items if portfolio.lower() in (p["name"].lower() + str(p["id"]))] or items
        if not items:
            run.ledger.gap("You have no portfolio yet.")
            return {"portfolios": []}
        chosen = items[0]
        result = portfolios.analytics(self.session, self.scope, chosen["id"])
        for gap in result.get("gaps", []):
            run.ledger.gap(gap)
        if result.get("empty"):
            return {"portfolio": chosen["name"], "positions": []}
        base = result["base_currency"]
        source = {"portfolio_id": str(chosen["id"]), "as_of": str(result["as_of"]), "license_class": "tenant_private"}
        statements = []

        def add(label: str, value: float | None, unit: str, text: str, key: tuple, numbers=()) -> None:
            if value is None:
                return
            item = run.ledger.add(
                "calculation",
                label,
                key=key,
                value=value,
                unit=unit,
                numbers=list(numbers),
                source=source,
                calculation={
                    "definition": label,
                    "version": result["performance"].get("engine_version", ""),
                    "inputs": {},
                },
            )
            statements.append({"text": text, "evidence": [item.id]})

        name = chosen["name"]
        add(
            f"Value of {name}",
            result["value"],
            base,
            f"The portfolio '{name}' is valued at {base} {result['value']:,.0f}.",
            ("pv", name),
        )
        perf = result["performance"]
        add(
            f"Time-weighted return of {name}",
            perf.get("total_return"),
            "percent",
            f"Its time-weighted return since inception is {perf.get('total_return', 0):.1f}%.",
            ("twr", name),
        )
        add(
            f"Maximum drawdown of {name}",
            perf.get("max_drawdown"),
            "percent",
            f"Its maximum drawdown was {perf.get('max_drawdown', 0):.1f}%.",
            ("dd", name),
        )
        concentration = result["exposures"]["concentration"]
        add(
            f"Largest position weight in {name}",
            concentration.get("largest_weight"),
            "percent",
            f"The largest position is {concentration.get('largest_weight') or 0:.1f}% of the portfolio.",
            ("lw", name),
        )
        for row in result["exposures"]["sector"][:4]:
            add(
                f"{row['name']} weight in {name}",
                row["weight"],
                "percent",
                f"{row['name']} makes up {row['weight']:.1f}% of the portfolio.",
                ("sector", name, row["name"]),
            )
        for row in result["exposures"]["currency"][:3]:
            add(
                f"{row['name']} exposure in {name}",
                row["weight"],
                "percent",
                f"Assets in {row['name']} are {row['weight']:.1f}% of the value.",
                ("ccy", name, row["name"]),
            )
        for breach in result["breaches"]:
            add(
                f"Limit {breach['limit']} for {breach['subject']}",
                breach["value"],
                "percent",
                f"{breach['subject']} at {breach['value']:.1f}% breaches the limit of {breach['threshold']:g}%.",
                ("breach", name, breach["limit"], breach["subject"]),
                numbers=[breach["threshold"]],
            )
        return {"portfolio": name, "statements": statements}

    def impact_paths(self, run: RunContext, start: str, direction: str = "rises") -> dict[str, Any]:
        """Transmission paths in the Market Impact Graph, each link with its source and confidence."""
        from modules.graph import service as graph  # noqa: PLC0415 - published read interface

        try:
            result = graph.scenario(self.session, self.scope, start, direction=1 if direction != "falls" else -1)
        except AurexError as exc:
            run.ledger.gap(f"The impact graph has no starting point for '{start[:60]}': {exc.message}")
            return {"paths": []}
        statements = []
        # Consequences for sectors, companies and currencies first; intermediate rates appear inside the chains.
        priority = {"sector": 0, "currency": 1, "company": 2}
        ranked = sorted(
            result["paths"], key=lambda p: (priority.get(p["end"]["kind"], 3), -p["confidence"], p["length"])
        )
        for path in ranked[:10]:
            ids = []
            for step in path["steps"]:
                link = step["link"]
                item = run.ledger.add(
                    "link",
                    f"{link['source']['name']} → {link['target']['name']} ({link['relation'].replace('_', ' ')})",
                    key=("link", str(link["id"])),
                    value=link["confidence"],
                    unit="confidence",
                    text=link["description"],
                    numbers=[link["confidence"]],
                    source={
                        "method": link["method"],
                        "source_ref": link["source_ref"],
                        "confidence_basis": link["confidence_basis"],
                        "license_class": "public",
                    },
                )
                ids.append(item.id)
            chain = " → ".join([result["origin"]["name"]] + [s["node"]["name"] for s in path["steps"]])
            move = "moving up" if result["direction"] == "rises" else "moving down"
            statements.append(
                {
                    "text": f"Starting from {result['origin']['name']} {move}: {path['end']['name']} "
                    f"{path['effect']}, through {chain}. Weakest link confidence {path['confidence']:.2f}.",
                    "evidence": ids,
                }
            )
        if not statements:
            run.ledger.gap("No accepted transmission path starts at this point in the impact graph.")
        run.ledger.gap(graph.SCENARIO_LABEL)
        return {"origin": result["origin"]["name"], "statements": statements}

    def build(self) -> dict[str, Tool]:
        company = {"type": "string", "description": "Ticker symbol or company name"}
        range_schema = {"type": "string", "enum": list(RANGE_DAYS), "description": "Look-back window"}
        tools = [
            Tool(
                "find_companies",
                "Find instruments and companies by symbol or name. Use it to get exact symbols.",
                {"query": STRING},
                self.find_companies,
            ),
            Tool(
                "get_fundamentals",
                "Reported annual figures and calculated ratios (growth, margins, cash flow, debt, coverage) for one "
                "company, newest fiscal year first. Each figure is an evidence item.",
                {"company": company, "years": {"type": "integer", "enum": [1, 2, 3, 4, 5, 6]}},
                self.get_fundamentals,
            ),
            Tool(
                "get_series",
                "Latest value, return, volatility, drawdown and range for a priced instrument, currency pair, "
                "interest rate or macro indicator.",
                {"symbol": company, "range": range_schema},
                self.get_series,
            ),
            Tool(
                "search_documents",
                "Full-text search over filings, news and the organization's own documents. Returns passages.",
                {
                    "query": STRING,
                    "company": {**NULLABLE, "description": "Restrict to one company, or null"},
                    "source": {
                        "type": "string",
                        "enum": ["all", "organization"],
                        "description": "'organization' searches only documents uploaded by the analyst's team",
                    },
                },
                self.search_documents,
                entitlement=ent.DOCUMENTS,
            ),
            Tool(
                "recent_documents",
                "The most recent filings and news, optionally for one company.",
                {"company": {**NULLABLE, "description": "Company, or null for all"}},
                self.recent_documents,
                entitlement=ent.DOCUMENTS,
            ),
            Tool(
                "compare_companies",
                "Latest fiscal-year figures and ratios for several companies side by side.",
                {"companies": {"type": "array", "items": STRING}},
                self.compare_companies,
            ),
            Tool(
                "correlation",
                "Correlation of returns between instruments on common dates.",
                {"symbols": {"type": "array", "items": STRING}, "range": range_schema},
                self.correlation,
            ),
            Tool(
                "dataset_status",
                "Status, freshness and quality flags of every dataset behind the terminal.",
                {},
                self.dataset_status,
                entitlement=ent.DATALAB,
            ),
            Tool(
                "portfolio_overview",
                "Value, return, drawdown, sector and currency exposure, concentration and limit breaches of the "
                "analyst's own portfolio.",
                {"portfolio": {**NULLABLE, "description": "Portfolio name, or null for the first one"}},
                self.portfolio_overview,
                entitlement=ent.PORTFOLIO,
            ),
            Tool(
                "impact_paths",
                "Possible transmission paths from a macro event or indicator to rates, currencies, sectors and "
                "companies in the Market Impact Graph. Every link has a source and a confidence.",
                {
                    "start": {"type": "string", "description": "Starting node, e.g. 'ECB monetary policy decision'"},
                    "direction": {"type": "string", "enum": ["rises", "falls"]},
                },
                self.impact_paths,
                entitlement=ent.GRAPH,
            ),
            Tool(
                "thesis_status",
                "The analyst's saved theses and whether each monitored condition still holds.",
                {"thesis": {**NULLABLE, "description": "Title of one thesis, or null for all"}},
                self.thesis_status,
                entitlement=ent.THESES,
            ),
        ]
        return {tool.name: tool for tool in tools} | self.extra


range_ = range  # the built-in, kept reachable where a parameter is named ``range``
