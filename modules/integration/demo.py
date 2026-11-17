"""Demonstration dataset: fictional companies with generated prices, fundamentals and reports.

Nothing here describes a real issuer. Every value is stored with the ``demonstration`` class and is
labeled as such wherever it is shown. The generator is deterministic, so history never changes.
"""

import math
import random
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from core.canonical import Batch, DocumentIn, EntityIn, EventIn, FactIn, InstrumentIn, ObservationIn, SeriesIn
from core.types import InstrumentType, QualityStatus

START = date(2019, 1, 2)
# symbol, name, sector, start price, drift, volatility, revenue (USD m), net margin, debt/equity, rate beta
COMPANIES = [
    ("NWND", "Northwind Industrial", "Industrials", 48.0, 0.07, 0.24, 9200, 0.08, 0.9, -0.6),
    ("HLXB", "Helix Biosciences", "Health Care", 31.0, 0.11, 0.42, 2100, 0.14, 0.3, -0.2),
    ("ORCA", "Orca Semiconductor", "Information Technology", 62.0, 0.19, 0.38, 14800, 0.24, 0.2, -0.4),
    ("LUMN", "Lumen Grid Utilities", "Utilities", 27.0, 0.04, 0.16, 6400, 0.10, 1.6, -1.1),
    ("TRVX", "Travex Logistics", "Industrials", 39.0, 0.06, 0.28, 11900, 0.05, 1.1, -0.5),
    ("MERD", "Meridian Bank Group", "Financials", 22.0, 0.05, 0.27, 7300, 0.21, 0.0, 0.8),
    ("SOLR", "Solara Renewables", "Energy", 18.0, 0.09, 0.47, 3100, 0.06, 1.3, -0.9),
    ("PXLR", "Pixelar Software", "Information Technology", 85.0, 0.16, 0.34, 5200, 0.22, 0.1, -0.7),
    ("FARM", "Greenfield Foods", "Consumer Staples", 44.0, 0.05, 0.17, 8700, 0.07, 0.7, -0.3),
    ("AURM", "Aurum Mining", "Materials", 14.0, 0.03, 0.39, 4300, 0.12, 0.5, 0.1),
]


def _business_days(start: date, end: date):
    day = start
    while day <= end:
        if day.weekday() < 5:
            yield day
        day += timedelta(days=1)


def _dec(value: float, places: int = 4) -> Decimal:
    return Decimal(str(round(value, places)))


def fetch(config: dict[str, Any], since: date | None) -> Batch:
    today = datetime.now(UTC).date()
    last_complete = today - timedelta(days=1)
    batch = Batch()
    index_levels: dict[date, float] = {}
    for symbol, name, sector, price0, drift, vol, revenue, margin, leverage, rate_beta in COMPANIES:
        key = f"demo:{symbol}"
        full = f"{symbol}.DEMO"
        batch.entities.append(
            EntityIn(
                key=key,
                name=f"{name} (demonstration)",
                ticker=full,
                country="US",
                sector=sector,
                meta={"demonstration": True, "rate_beta": rate_beta, "leverage": leverage},
            )
        )
        batch.instruments.append(
            InstrumentIn(
                symbol=full,
                name=f"{name} (demonstration)",
                type=InstrumentType.EQUITY,
                currency="USD",
                venue="AUREX demonstration",
                entity_key=key,
            )
        )
        code = f"DEMO:{symbol}"
        batch.series.append(
            SeriesIn(
                code=code,
                name=f"{name} share price (demonstration)",
                kind="price",
                unit="USD",
                currency="USD",
                frequency="B",
                instrument_symbol=full,
                has_ohlc=True,
            )
        )
        rng = random.Random(f"aurex-demo-{symbol}")  # noqa: S311 - simulation, not security
        price = price0
        for day in _business_days(START, last_complete):
            shock = rng.gauss(0, 1)
            previous = price
            price = max(0.5, price * math.exp((drift - vol * vol / 2) / 252 + vol / math.sqrt(252) * shock))
            spread = abs(rng.gauss(0, vol / math.sqrt(252) / 2))
            open_ = previous * math.exp(rng.gauss(0, vol / math.sqrt(252) / 4))
            high = max(open_, price) * (1 + spread)
            low = min(open_, price) * (1 - spread)
            volume = int(rng.lognormvariate(13.5, 0.5))
            index_levels[day] = index_levels.get(day, 0.0) + price / price0 * 100 / len(COMPANIES)
            if since and day < since:
                continue
            batch.observations.append(
                ObservationIn(
                    series_code=code,
                    ref_time=datetime.combine(day, time(0, tzinfo=UTC)),
                    value=_dec(price),
                    open=_dec(open_),
                    high=_dec(high),
                    low=_dec(low),
                    volume=Decimal(volume),
                    known_at=datetime.combine(day, time(21, 30, tzinfo=UTC)),
                    quality=QualityStatus.DEMONSTRATION,
                )
            )
        batch.facts.extend(_facts(key, symbol, revenue, margin, leverage, today))
        batch.documents.extend(_reports(key, symbol, name, sector, revenue, margin, leverage, rate_beta, today))
    batch.instruments.append(
        InstrumentIn(
            symbol="DEMO10.DEMO",
            name="AUREX Demonstration 10 Index",
            type=InstrumentType.INDEX,
            currency="USD",
            venue="AUREX demonstration",
        )
    )
    batch.series.append(
        SeriesIn(
            code="DEMO:INDEX10",
            name="AUREX Demonstration 10 Index (equal weight)",
            kind="price",
            unit="index points",
            currency="USD",
            frequency="B",
            instrument_symbol="DEMO10.DEMO",
        )
    )
    for day, level in sorted(index_levels.items()):
        if since and day < since:
            continue
        batch.observations.append(
            ObservationIn(
                series_code="DEMO:INDEX10",
                ref_time=datetime.combine(day, time(0, tzinfo=UTC)),
                value=_dec(level),
                known_at=datetime.combine(day, time(21, 30, tzinfo=UTC)),
                quality=QualityStatus.DEMONSTRATION,
            )
        )
    for doc in batch.documents:
        batch.events.append(
            EventIn(
                key=f"filing:{doc.key}",
                kind="filing",
                title=doc.title[:300],
                scheduled_at=doc.published_at,
                entity_key=doc.entity_key,
                meta={"form": doc.doc_type, "demonstration": True},
            )
        )
    return batch


def _fiscal_years(today: date) -> list[int]:
    return list(range(2019, today.year if today >= date(today.year, 3, 1) else today.year - 1))


def _facts(key: str, symbol: str, revenue: float, margin: float, leverage: float, today: date) -> list[FactIn]:
    rng = random.Random(f"aurex-demo-facts-{symbol}")  # noqa: S311
    facts: list[FactIn] = []
    level = revenue * 1_000_000
    for year in _fiscal_years(today):
        level *= 1 + rng.uniform(-0.04, 0.16)
        net = level * margin * rng.uniform(0.8, 1.2)
        equity = level * 0.55
        debt = equity * leverage
        values = {
            "Revenues": level,
            "GrossProfit": level * rng.uniform(0.32, 0.48),
            "OperatingIncomeLoss": net * 1.35,
            "NetIncomeLoss": net,
            "NetCashProvidedByUsedInOperatingActivities": net * rng.uniform(1.1, 1.5),
            "PaymentsToAcquirePropertyPlantAndEquipment": level * rng.uniform(0.03, 0.09),
            "InterestExpense": debt * rng.uniform(0.03, 0.055),
        }
        balance = {
            "Assets": equity + debt + level * 0.25,
            "Liabilities": debt + level * 0.25,
            "StockholdersEquity": equity,
            "CashAndCashEquivalentsAtCarryingValue": level * rng.uniform(0.05, 0.18),
            "LongTermDebtNoncurrent": debt * 0.85,
            "LongTermDebtCurrent": debt * 0.15,
        }
        end, filed, accession = date(year, 12, 31), date(year + 1, 2, 20), f"DEMO-{symbol}-{year}-10K"
        for concept, value in values.items():
            facts.append(
                FactIn(
                    entity_key=key,
                    concept=concept,
                    label=concept,
                    unit="USD",
                    value=Decimal(round(value)),
                    period_start=date(year, 1, 1),
                    period_end=end,
                    fiscal_year=year,
                    fiscal_period="FY",
                    form="10-K",
                    accession=accession,
                    filed_at=filed,
                )
            )
        for concept, value in balance.items():
            facts.append(
                FactIn(
                    entity_key=key,
                    concept=concept,
                    label=concept,
                    unit="USD",
                    value=Decimal(round(value)),
                    period_end=end,
                    fiscal_year=year,
                    fiscal_period="FY",
                    form="10-K",
                    accession=accession,
                    filed_at=filed,
                )
            )
    return facts


def _reports(
    key: str,
    symbol: str,
    name: str,
    sector: str,
    revenue: float,
    margin: float,
    leverage: float,
    rate_beta: float,
    today: date,
) -> list[DocumentIn]:
    docs: list[DocumentIn] = []
    sensitivity = (
        "Higher policy rates raise our financing costs and reduce demand for our products."
        if rate_beta < -0.5
        else "Our earnings benefit from higher interest rates through wider lending margins."
        if rate_beta > 0.5
        else "Our results have limited direct sensitivity to interest rates."
    )
    debt_text = (
        "The company has no long-term borrowings."
        if leverage == 0
        else f"Long-term borrowings are approximately {leverage:.1f} times shareholders' equity, "
        f"{'mostly at floating rates' if leverage > 1 else 'mostly at fixed rates'}."
    )
    for year in _fiscal_years(today)[-3:]:
        body = "\n".join(
            [
                f"Item 1. Business\n{name} is a fictional {sector.lower()} company created for AUREX "
                "demonstration data. It does not exist and its figures are generated.",
                f"Item 1A. Risk Factors\nInterest rate risk. {sensitivity} {debt_text}",
                "Currency risk. A portion of revenue is earned outside the United States, mainly in euro, "
                "so a stronger US dollar reduces reported revenue.",
                f"Item 7. Management's Discussion and Analysis\nIn fiscal {year} demand in the {sector.lower()} "
                f"market was the main driver of revenue. Net margin was close to {margin * 100:.0f} percent.",
                "Liquidity and capital resources. Operating cash flow covered capital expenditure and "
                "scheduled debt repayments during the year.",
            ]
        )
        docs.append(
            DocumentIn(
                key=f"DEMO-{symbol}-{year}-10K",
                doc_type="10-K",
                title=f"{name} (demonstration) — annual report {year}",
                published_at=datetime(year + 1, 2, 20, 21, 0, tzinfo=UTC),
                entity_key=key,
                body=body,
                meta={"demonstration": True, "fiscal_year": year},
            )
        )
    return docs
