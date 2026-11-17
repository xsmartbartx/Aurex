"""The offline evidence engine: answers without a language model.

It plans with fixed rules, calls the same tools as a model would and writes each statement from a
template bound to one or more evidence items. It cannot reason beyond its templates, and it says so; in
exchange nothing leaves the deployment and every statement is checkable by construction.
"""

import re
from typing import Any

from modules.analysis.engine import Draft, RunContext

Statement = tuple[str, list[str], bool]

_STOP = {
    "I",
    "A",
    "AN",
    "THE",
    "WHAT",
    "HOW",
    "WHY",
    "WHICH",
    "WHO",
    "WHEN",
    "IS",
    "ARE",
    "DOES",
    "DO",
    "COMPARE",
    "SHOW",
    "GIVE",
    "TELL",
    "AND",
    "OR",
    "VS",
    "VERSUS",
    "ON",
    "IN",
    "OF",
    "FOR",
    "TO",
    "WITH",
    "ABOUT",
    "IT",
    "ITS",
    "THEIR",
    "EU",
    "US",
    "USA",
    "AI",
    "FY",
    "Q1",
    "Q2",
    "Q3",
    "Q4",
    "ECB",
    "GDP",
    "HICP",
    "CEO",
    "CFO",
    "SEC",
    "ETF",
    "FX",
    "YTD",
    "FCF",
    "ROE",
    "EPS",
    "DEMO",
    "AUREX",
    "PLEASE",
    "CAN",
    "COULD",
    "MY",
    "ME",
    "DATA",
    "CURRENT",
    "MISSING",
    "LATEST",
    "SUMMARIZE",
    "ANALYZE",
    "EXPLAIN",
    "DESCRIBE",
    "LIST",
    "FIND",
}
_MACRO = [
    (r"deposit facility|policy rate|ecb rate|interest rates?|rate (?:cut|hike)|monetary policy", "ECBDFR"),
    (r"refinanc", "ECBMRR"),
    (r"inflation|hicp|consumer prices", "EAHICP"),
    (r"\bgdp\b|economic growth", "EAGDP"),
    (r"yield|bund|10-year|ten-year", "EUR10Y"),
    (r"€str|estr|overnight rate", "ESTR"),
    (r"dollar|\busd\b", "EURUSD"),
    (r"zloty|\bpln\b", "EURPLN"),
    (r"sterling|pound|\bgbp\b", "EURGBP"),
    (r"\byen\b|\bjpy\b", "EURJPY"),
    (r"swiss franc|\bchf\b", "EURCHF"),
]
_TOPICS = [
    ("growth", r"revenue|sales|growth|grow|top line", ["revenue", "revenue_growth"]),
    ("cash", r"cash|flow|fcf|capex|liquidity", ["operating_cash_flow", "free_cash_flow", "fcf_margin", "cash"]),
    (
        "debt",
        r"debt|leverage|borrow|interest|rates?|coverage|balance sheet|solvency",
        ["total_debt", "debt_to_equity", "net_debt", "interest_coverage"],
    ),
    (
        "margin",
        r"margin|profit|earning|income|return on",
        ["net_income", "operating_margin", "net_margin", "return_on_equity"],
    ),
]
_GRAPH_STARTS = [
    (r"inflation|hicp", "Euro area inflation (HICP)"),
    (r"deposit facility|policy rate|ecb rate", "ECB deposit facility rate"),
    (r"10.?year|long.?term yield", "Euro area 10-year government yield"),
    (r"financing cost|borrowing cost", "Corporate financing costs"),
    (r"monetary policy|ecb decision|rate (?:hike|cut|increase|decrease)", "ECB monetary policy decision"),
]
_QUESTION_WORDS = {
    "say",
    "says",
    "said",
    "about",
    "documents",
    "document",
    "files",
    "notes",
    "uploads",
    "our",
    "my",
    "does",
    "did",
    "what",
    "which",
    "there",
    "any",
    "this",
    "that",
    "these",
    "those",
    "from",
    "into",
    "compare",
    "between",
    "over",
    "last",
    "year",
    "years",
}
_DEFAULT = ["revenue", "revenue_growth", "net_margin", "free_cash_flow", "debt_to_equity", "interest_coverage"]
_RANGE = [
    (r"10.?year|decade", "10Y"),
    (r"5.?year|five.?year", "5Y"),
    (r"3.?year|three.?year", "3Y"),
    (r"6.?month|half.?year", "6M"),
    (r"3.?month|quarter", "3M"),
    (r"1.?month|\bmonth\b", "1M"),
]


def _money(value: float, unit: str) -> str:
    prefix = f"{unit} " if unit and len(unit) == 3 and unit.isalpha() else ""
    size = abs(value)
    if size >= 1e9:
        return f"{prefix}{value / 1e9:.2f} billion"
    if size >= 1e6:
        return f"{prefix}{value / 1e6:.1f} million"
    return f"{prefix}{value:,.0f}"


def _fmt(value: float, unit: str) -> str:
    if unit == "percent":
        return f"{value:.1f}%"
    if unit == "ratio":
        return f"{value:.2f}x"
    if unit == "correlation":
        return f"{value:.2f}"
    if unit == "percentage points":
        return f"{value:+.2f} percentage points"
    if len(unit) == 3 and unit.isalpha():
        return _money(value, unit)
    return f"{value:,.4f}".rstrip("0").rstrip(".") + (f" {unit}" if unit else "")


class OfflineEngine:
    name = "offline"
    model_id = "aurex-offline-1"
    external = False

    def draft(self, run: RunContext) -> Draft:
        question = run.question
        lowered = question.lower()
        available = {tool.name for tool in run.tools}
        sections: list[tuple[str, list[Statement]]] = []
        steps = 0

        def call(name: str, **kwargs: Any) -> dict[str, Any]:
            nonlocal steps
            if name not in available:
                return {}
            steps += 1
            return run.call(name, kwargs)

        if run.agent.name == "data_quality":
            sections.append(("Dataset status", self._datasets(call("dataset_status"))))
        for name, heading in (
            ("portfolio_overview", "Portfolio"),
            ("thesis_status", "Theses"),
            ("impact_paths", "Impact paths"),
        ):
            if name in available and name in run.agent.tools:
                result = call(name, **self._extra_input(name, run))
                statements = [(s["text"], s["evidence"], False) for s in result.get("statements", [])]
                if statements:
                    sections.append((heading, statements))

        subjects, unmatched = self._subjects(run, call)
        wanted = [items for _, pattern, items in _TOPICS if re.search(pattern, lowered)]
        metrics = list(dict.fromkeys(m for group in wanted for m in group)) or _DEFAULT
        span = next((code for pattern, code in _RANGE if re.search(pattern, lowered)), "1Y")

        compared: dict[str, dict[str, dict[str, Any]]] = {}
        for subject in subjects:
            statements: list[Statement] = []
            if subject["has_issuer"]:
                result = call("get_fundamentals", company=subject["symbol"], years=2)
                statements += self._fundamentals(result, metrics, compared)
            if subject["has_price_data"]:
                statements += self._series(call("get_series", symbol=subject["symbol"], range=span))
            if statements:
                sections.append((subject["name"], statements))

        if len(compared) >= 2:
            sections.append(("Comparison, latest fiscal year", self._comparison(compared, metrics)))
        priced = [s["symbol"] for s in subjects if s["has_price_data"]]
        if len(priced) >= 2 and re.search(r"correlat|co-?move|relationship|together", lowered):
            result = call("correlation", symbols=priced, range=span)
            pairs = [
                (
                    f"Correlation of returns between {p['a']} and {p['b']} over {result['range']} was "
                    f"{_fmt(p['value'], 'correlation')}.",
                    [p["id"]],
                    False,
                )
                for p in result.get("pairs", [])
            ]
            if pairs:
                sections.append(("Co-movement", pairs))

        documents: list[Statement] = []
        targets = [s["symbol"] for s in subjects if s["has_issuer"]] or [None]
        own = re.search(r"\b(?:my|our)\s+(?:own\s+)?(?:documents?|files?|notes?|memos?|uploads?|research)\b", lowered)
        terms = (
            " ".join(
                w
                for w in re.findall(r"[A-Za-z][A-Za-z\-]{2,}", question)
                if w.upper() not in _STOP and w.lower() not in _QUESTION_WORDS
            )
            or question
        )
        # A question about a named company that is not in the data is not answered from other companies' filings.
        if unmatched and not subjects and not own:
            targets = []
        for target in targets[:3]:
            result = call("search_documents", query=terms, company=target, source="organization" if own else "all")
            for passage in result.get("passages", [])[: 3 if target else 4]:
                excerpt = passage["text"][:320].rsplit(" ", 1)[0] if len(passage["text"]) > 320 else passage["text"]
                documents.append(
                    (
                        f"{passage['document']} ({passage['location']}, published "
                        f"{passage['published']}) states: “{excerpt}”",
                        [passage["id"]],
                        False,
                    )
                )
        if documents:
            sections.append(("What the documents say", documents))

        gaps = []
        if unmatched:
            names = ", ".join(f"'{name}'" for name in unmatched[:4])
            gaps.append(f"{names} could not be matched to any company, instrument or indicator in the loaded data.")
        if not subjects and not any(heading in ("Impact paths", "Portfolio", "Theses") for heading, _ in sections):
            gaps.append(
                "No company, instrument or indicator in the question could be matched to loaded data"
                + ("; the answer draws on document search only." if sections else ".")
            )
        gaps.append(
            "This answer was assembled by the offline evidence engine from fixed templates. It reports "
            "what the data shows and does not interpret it. Configure a language model for written analysis."
        )
        return Draft(
            title=question[:120], sections=[s for s in sections if s[1]], gaps=gaps, steps=steps, model_id=self.model_id
        )

    # --- planning ---------------------------------------------------------------------------------

    @staticmethod
    def _extra_input(name: str, run: RunContext) -> dict[str, Any]:
        if name == "impact_paths":
            lowered = run.question.lower()
            start = run.context.get("node") or next(
                (node for pattern, node in _GRAPH_STARTS if re.search(pattern, lowered)), "ECB monetary policy decision"
            )
            falls = re.search(r"\b(cut|lower|fall|falls|drop|decline|ease|easing)\b", lowered)
            return {"start": start, "direction": "falls" if falls else "rises"}
        if name == "portfolio_overview":
            return {"portfolio": run.context.get("portfolio")}
        return {"thesis": run.context.get("thesis")}

    def _subjects(self, run: RunContext, call) -> tuple[list[dict[str, Any]], list[str]]:
        question = run.question.replace("/", "")
        candidates: list[str] = []
        if run.context.get("symbol"):
            candidates.append(str(run.context["symbol"]))
        candidates += re.findall(r"\b[A-Z][A-Z0-9]{1,9}(?:\.[A-Z]{1,5})?\b", question)
        candidates += re.findall(r"\b[A-Z][a-z]{2,}(?:\s[A-Z][a-z]{2,}){0,2}\b", question)
        for pattern, symbol in _MACRO:
            if re.search(pattern, run.question.lower()):
                candidates.append(symbol)
        found: dict[str, dict[str, Any]] = {}
        unmatched: list[str] = []
        for candidate in list(dict.fromkeys(candidates))[:10]:
            if candidate.upper() in _STOP or candidate.split()[0].upper() in _STOP or len(found) >= 4:
                continue
            hit = False
            for match in call("find_companies", query=candidate).get("matches", []):
                symbol, name = match["symbol"], match["name"].lower()
                exact = symbol == candidate.upper() or symbol.startswith(candidate.upper() + ".")
                named = re.search(rf"\b{re.escape(candidate.lower())}\b", name) is not None and len(candidate) > 3
                if exact or named:
                    found.setdefault(symbol, match)
                    hit = True
                    break
            if not hit and candidate[:1].isupper() and len(candidate) > 3:
                unmatched.append(candidate)
        covered = " ".join(m["name"].lower() + " " + m["symbol"].lower() for m in found.values())
        return list(found.values()), [u for u in unmatched if u.lower() not in covered]

    # --- composition ------------------------------------------------------------------------------

    @staticmethod
    def _fundamentals(result: dict[str, Any], metrics: list[str], compared: dict) -> list[Statement]:
        years = result.get("fiscal_years") or []
        if not years:
            return []
        latest = years[0]
        fy = latest["fiscal_year"]
        values = {r["item"]: r for r in latest["reported"]} | {r["ratio"]: r for r in latest["calculated"]}
        compared[result["company"]] = values
        out: list[Statement] = []
        for metric in metrics:
            row = values.get(metric)
            if row is None:
                continue
            out.append((f"{row['label']} in fiscal {fy} was {_fmt(row['value'], row['unit'])}.", [row["id"]], False))
        if len(years) > 1:
            previous = {r["item"]: r for r in years[1]["reported"]}
            for metric in ("revenue", "net_income"):
                if metric in values and metric in previous and metric in metrics:
                    out.append(
                        (
                            f"{values[metric]['label']} in fiscal {years[1]['fiscal_year']} was "
                            f"{_fmt(previous[metric]['value'], previous[metric]['unit'])}.",
                            [previous[metric]["id"]],
                            False,
                        )
                    )
        return out

    @staticmethod
    def _series(result: dict[str, Any]) -> list[Statement]:
        evidence = result.get("evidence") or []
        if not evidence:
            return []
        by = {e["measure"]: e for e in evidence}
        last = by["latest value"]
        level = _fmt(last["value"], last["unit"])
        out: list[Statement] = [
            (f"{result['name']} ({result['symbol']}) stood at {level} on {last['date']}.", [last["id"]], False)
        ]
        for measure, item in by.items():
            if measure == "latest value":
                continue
            out.append((f"{measure}: {_fmt(item['value'], item['unit'])}.", [item["id"]], False))
        return out

    @staticmethod
    def _comparison(compared: dict[str, dict[str, dict[str, Any]]], metrics: list[str]) -> list[Statement]:
        out: list[Statement] = []
        for metric in metrics:
            rows = [(name, values[metric]) for name, values in compared.items() if metric in values]
            if len(rows) < 2:
                continue
            text = "; ".join(f"{name} {_fmt(row['value'], row['unit'])}" for name, row in rows)
            out.append((f"{rows[0][1]['label']}: {text}.", [row["id"] for _, row in rows], False))
        return out

    @staticmethod
    def _datasets(result: dict[str, Any]) -> list[Statement]:
        out: list[Statement] = []
        for item in result.get("datasets", []):
            if item["status"] == "ok" and not item["quality_flags"]:
                continue
            detail = f" {item['detail']}" if item.get("detail") else ""
            flags = f" The last run flagged {item['quality_flags']} value(s)." if item["quality_flags"] else ""
            status = item["status"].replace("_", " ")
            out.append((f"{item['dataset']} is {status}.{detail}{flags}", [item["id"]], False))
        healthy = [i for i in result.get("datasets", []) if i["status"] == "ok" and not i["quality_flags"]]
        if healthy:
            out.append(
                (
                    f"{len(healthy)} dataset(s) are current with no quality flags in the last run.",
                    [i["id"] for i in healthy][:12],
                    False,
                )
            )
        return out
