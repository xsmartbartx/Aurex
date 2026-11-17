"""Fundamental analysis from reported facts. Every ratio names the facts it was computed from."""

from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import Any

from core.concepts import CONCEPTS, DURATION_ITEMS, LABELS
from modules.processing import Calculation

ANNUAL_DAYS = (340, 380)
QUARTER_DAYS = (80, 100)


def _is_annual(start: date | None, end: date) -> bool:
    return start is not None and ANNUAL_DAYS[0] <= (end - start).days <= ANNUAL_DAYS[1]


def annual_statements(facts: Sequence[dict[str, Any]], *, max_years: int = 8) -> list[dict[str, Any]]:
    """Arrange reported facts into fiscal years, newest first.

    A fiscal year is any 12-month period for which revenue or net income was reported. For each line
    item the first available concept in the preference list is used; the fact reference is kept.
    """
    by_concept: dict[str, list[dict[str, Any]]] = {}
    for fact in facts:
        by_concept.setdefault(fact["concept"], []).append(fact)

    periods: dict[date, date] = {}
    for item in ("revenue", "net_income"):
        for concept in CONCEPTS[item]:
            for fact in by_concept.get(concept, []):
                if _is_annual(fact.get("period_start"), fact["period_end"]):
                    periods.setdefault(fact["period_end"], fact["period_start"])
    years = []
    for end in sorted(periods, reverse=True)[:max_years]:
        start = periods[end]
        items: dict[str, dict[str, Any]] = {}
        for item, concepts in CONCEPTS.items():
            for concept in concepts:
                match = next(
                    (
                        f
                        for f in by_concept.get(concept, [])
                        if f["period_end"] == end
                        and (
                            (
                                item in DURATION_ITEMS
                                and _is_annual(f.get("period_start"), end)
                                and abs((f["period_start"] - start).days) <= 10
                            )
                            or (item not in DURATION_ITEMS and f.get("period_start") is None)
                        )
                    ),
                    None,
                )
                if match:
                    items[item] = {
                        "value": Decimal(match["value"]),
                        "unit": match["unit"],
                        "concept": concept,
                        "label": LABELS[item],
                        "fact_id": match["id"],
                        "accession": match["accession"],
                        "filed_at": match["filed_at"],
                    }
                    break
        years.append({"period_end": end, "period_start": start, "fiscal_year": end.year, "items": items})
    return years


def _ratio(
    name: str,
    numerator: Decimal | None,
    denominator: Decimal | None,
    *,
    unit: str,
    inputs: dict[str, Any],
    scale: int = 1,
) -> Calculation | None:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return Calculation(definition=name, inputs=inputs, output=float(numerator / denominator * scale), unit=unit)


def ratios(year: dict[str, Any], previous: dict[str, Any] | None = None) -> dict[str, Calculation]:
    """Ratios for one fiscal year. Missing inputs produce no ratio (a gap), never an estimate."""
    items = year["items"]
    prev = previous["items"] if previous else {}

    def val(name: str, source: dict = items) -> Decimal | None:
        return source[name]["value"] if name in source else None

    def refs(*names: str, source: dict = items, suffix: str = "") -> dict[str, Any]:
        return {
            f"{n}{suffix}": {
                "fact_id": source[n]["fact_id"],
                "value": float(source[n]["value"]),
                "period_end": year["period_end"].isoformat() if not suffix else previous["period_end"].isoformat(),
            }
            for n in names
            if n in source
        }

    out: dict[str, Calculation | None] = {}
    revenue, net, operating = val("revenue"), val("net_income"), val("operating_income")
    out["gross_margin"] = _ratio(
        "gross_profit / revenue",
        val("gross_profit"),
        revenue,
        unit="percent",
        inputs=refs("gross_profit", "revenue"),
        scale=100,
    )
    out["operating_margin"] = _ratio(
        "operating_income / revenue",
        operating,
        revenue,
        unit="percent",
        inputs=refs("operating_income", "revenue"),
        scale=100,
    )
    out["net_margin"] = _ratio(
        "net_income / revenue", net, revenue, unit="percent", inputs=refs("net_income", "revenue"), scale=100
    )
    if revenue is not None and val("revenue", prev):
        growth = (revenue / val("revenue", prev) - 1) * 100
        out["revenue_growth"] = Calculation(
            "revenue / previous_revenue - 1",
            {**refs("revenue"), **refs("revenue", source=prev, suffix="_previous")},
            float(growth),
            "percent",
        )
    ocf, capex = val("operating_cash_flow"), val("capex")
    if ocf is not None and capex is not None:
        fcf = ocf - capex
        out["free_cash_flow"] = Calculation(
            "operating_cash_flow - capex",
            refs("operating_cash_flow", "capex"),
            float(fcf),
            items["operating_cash_flow"]["unit"],
        )
        out["fcf_margin"] = _ratio(
            "(operating_cash_flow - capex) / revenue",
            fcf,
            revenue,
            unit="percent",
            inputs=refs("operating_cash_flow", "capex", "revenue"),
            scale=100,
        )
    debt_parts = [n for n in ("debt_long_term", "debt_current") if n in items]
    if debt_parts:
        debt = sum((items[n]["value"] for n in debt_parts), Decimal(0))
        out["total_debt"] = Calculation(
            " + ".join(debt_parts),
            refs(*debt_parts),
            float(debt),
            items[debt_parts[0]]["unit"],
            notes=() if len(debt_parts) == 2 else ("one debt component not reported",),
        )
        out["debt_to_equity"] = _ratio(
            "total_debt / equity", debt, val("equity"), unit="ratio", inputs=refs(*debt_parts, "equity")
        )
        if val("cash") is not None:
            out["net_debt"] = Calculation(
                "total_debt - cash", refs(*debt_parts, "cash"), float(debt - val("cash")), items["cash"]["unit"]
            )
    out["interest_coverage"] = _ratio(
        "operating_income / interest_expense",
        operating,
        val("interest_expense"),
        unit="ratio",
        inputs=refs("operating_income", "interest_expense"),
    )
    out["return_on_equity"] = _ratio(
        "net_income / equity", net, val("equity"), unit="percent", inputs=refs("net_income", "equity"), scale=100
    )
    out["current_ratio"] = _ratio(
        "assets_current / liabilities_current",
        val("assets_current"),
        val("liabilities_current"),
        unit="ratio",
        inputs=refs("assets_current", "liabilities_current"),
    )
    return {k: v for k, v in out.items() if v is not None}


def analyze(facts: Sequence[dict[str, Any]], *, max_years: int = 6) -> dict[str, Any]:
    """Statements and ratios per fiscal year, plus the list of line items that were not reported."""
    years = annual_statements(facts, max_years=max_years + 1)
    result = []
    for index, year in enumerate(years[:max_years]):
        previous = years[index + 1] if index + 1 < len(years) else None
        result.append({**year, "ratios": ratios(year, previous)})
    latest = result[0]["items"] if result else {}
    return {"years": result, "missing": sorted(set(CONCEPTS) - set(latest)) if result else sorted(CONCEPTS)}
