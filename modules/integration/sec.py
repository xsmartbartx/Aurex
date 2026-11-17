"""SEC EDGAR connector: company index, filings and XBRL company facts.

Terms: free access, at most 10 requests per second, and automated clients declare a User-Agent with
contact details. The operator supplies it in ``AUREX_SEC_USER_AGENT``; without it the connector is
not configured and makes no request.
"""

import json
import re
from datetime import UTC, date, datetime, time
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from typing import Any

from core.canonical import Batch, DocumentIn, EntityIn, EventIn, FactIn, InstrumentIn
from core.concepts import CONCEPTS
from core.config import get_settings
from core.errors import ProviderError, ValidationFailure
from core.types import InstrumentType
from modules.integration.http import fetch
from modules.validation import Lenient, validate

FORMS = {"10-K", "10-Q", "8-K", "20-F", "40-F", "6-K", "10-K/A", "10-Q/A"}
BODY_FORMS = {"10-K", "10-Q", "20-F"}
_WANTED = {name for names in CONCEPTS.values() for name in names}
_BLOCK = {"p", "div", "tr", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6", "table", "section"}
_SKIP = {"script", "style", "head", "ix:header", "ix:hidden"}


def configured() -> bool:
    agent = get_settings().sec_user_agent.strip()
    return bool(agent) and "@" in agent


def _get(url: str, **kwargs: Any) -> bytes:
    if not configured():
        raise ProviderError(
            "SEC connector needs AUREX_SEC_USER_AGENT with a contact address", code="connector_not_configured"
        )
    return fetch(url, headers={"User-Agent": get_settings().sec_user_agent.strip()}, **kwargs)


def _json(url: str) -> Any:
    try:
        return json.loads(_get(url))
    except json.JSONDecodeError as exc:
        raise ValidationFailure("SEC response is not valid JSON") from exc


def cik10(cik: str | int) -> str:
    digits = str(cik).strip().lstrip("0") or "0"
    if not digits.isdigit() or len(digits) > 10:
        raise ValidationFailure("Invalid CIK")
    return digits.zfill(10)


class _Index(Lenient):
    fields: list[str]
    data: list[list[Any]]


def fetch_index(config: dict[str, Any], since: date | None) -> Batch:
    """Every company with a ticker: entities and equity instruments. Prices are not part of EDGAR."""
    index = validate(_Index, _json("https://www.sec.gov/files/company_tickers_exchange.json"), what="SEC index")
    if index.fields[:4] != ["cik", "name", "ticker", "exchange"]:
        raise ValidationFailure("SEC company index changed its layout")
    batch = Batch()
    seen_entities: set[str] = set()
    seen_symbols: set[str] = set()
    pattern = re.compile(r"^[A-Z0-9][A-Z0-9.\-]*$")
    for row in index.data:
        cik, name, ticker, exchange = row[0], str(row[1] or "").strip(), str(row[2] or "").upper(), row[3]
        if not name or not pattern.match(ticker) or ticker in seen_symbols:
            continue
        key = f"cik:{cik10(cik)}"
        seen_symbols.add(ticker)
        if key not in seen_entities:
            seen_entities.add(key)
            batch.entities.append(EntityIn(key=key, name=name[:200], ticker=ticker[:32], cik=cik10(cik), country="US"))
        batch.instruments.append(
            InstrumentIn(
                symbol=ticker[:32],
                name=name[:200],
                type=InstrumentType.EQUITY,
                currency="USD",
                venue=(str(exchange)[:40] if exchange else None),
                entity_key=key,
                external_ids={"cik": cik10(cik)},
            )
        )
    return batch


class _Recent(Lenient):
    accessionNumber: list[str]
    filingDate: list[str]
    form: list[str]
    primaryDocument: list[str]
    primaryDocDescription: list[str] = []
    acceptanceDateTime: list[str] = []
    reportDate: list[str] = []
    items: list[str] = []


class _Filings(Lenient):
    recent: _Recent


class _Submissions(Lenient):
    cik: str | int
    name: str
    sic: str = ""
    sicDescription: str = ""
    tickers: list[str] = []
    exchanges: list[str | None] = []
    filings: _Filings


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP:
            self._skip += 1
        elif tag in _BLOCK:
            self.parts.append("\n")
        elif tag == "td":
            self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP:
            self._skip = max(0, self._skip - 1)
        elif tag in _BLOCK:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.parts.append(data)


def html_to_text(raw: bytes) -> str:
    parser = _TextExtractor()
    parser.feed(raw.decode("utf-8", errors="replace"))
    lines = (" ".join(line.split()) for line in "".join(parser.parts).replace("\xa0", " ").split("\n"))
    return "\n".join(line for line in lines if line)


def _when(accepted: str, filed: str) -> datetime:
    try:
        return datetime.fromisoformat(accepted.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return datetime.combine(date.fromisoformat(filed), time(0, tzinfo=UTC))


def fetch_company(config: dict[str, Any], since: date | None) -> Batch:
    """Profile, recent filings and reported facts for one company (``config['cik']``)."""
    cik = cik10(config["cik"])
    key = f"cik:{cik}"
    sub = validate(_Submissions, _json(f"https://data.sec.gov/submissions/CIK{cik}.json"), what="SEC submissions")
    recent = sub.filings.recent
    ticker = sub.tickers[0].upper() if sub.tickers else None
    batch = Batch(
        entities=[
            EntityIn(
                key=key,
                name=sub.name[:200],
                ticker=ticker,
                cik=cik,
                country="US",
                industry=sub.sicDescription[:160] or None,
                meta={"sic": sub.sic},
            )
        ]
    )
    max_filings = int(config.get("max_filings", 40))
    max_bodies = int(config.get("max_bodies", 3))
    known = config.get("known_documents") or set()
    candidates = 0
    for i, accession in enumerate(recent.accessionNumber):
        form = recent.form[i]
        if form not in FORMS or len(batch.documents) >= max_filings:
            continue
        filed = recent.filingDate[i]
        published = _when(recent.acceptanceDateTime[i] if i < len(recent.acceptanceDateTime) else "", filed)
        if since and published.date() < since:
            continue
        primary = recent.primaryDocument[i]
        description = recent.primaryDocDescription[i] if i < len(recent.primaryDocDescription) else ""
        report = recent.reportDate[i] if i < len(recent.reportDate) else ""
        url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}/{primary}"
        body = None
        if form in BODY_FORMS and primary.lower().endswith((".htm", ".html")):
            candidates += 1  # full text is kept for the most recent reports only
            if candidates <= max_bodies and accession not in known:
                body = html_to_text(_get(url, max_bytes=60 * 1024 * 1024, timeout=120.0))
        title = f"{sub.name} — {form}" + (f" for period ending {report}" if report else "")
        batch.documents.append(
            DocumentIn(
                key=accession,
                doc_type=form,
                title=title[:400],
                url=url,
                published_at=published,
                entity_key=key,
                body=body or f"{title}. {description}".strip(),
                meta={"accession": accession, "report_date": report, "description": description[:200]},
            )
        )
        batch.events.append(
            EventIn(
                key=f"filing:{accession}",
                kind="filing",
                title=title[:300],
                scheduled_at=published,
                entity_key=key,
                meta={"form": form},
            )
        )
    batch.facts = _facts(cik, key)
    return batch


def _facts(cik: str, key: str) -> list[FactIn]:
    payload = _json(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json")
    gaap = (payload.get("facts") or {}).get("us-gaap") if isinstance(payload, dict) else None
    if not isinstance(gaap, dict):
        return []
    facts: list[FactIn] = []
    seen: set[tuple] = set()
    for concept, body in gaap.items():
        if concept not in _WANTED or not isinstance(body, dict):
            continue
        for unit, rows in (body.get("units") or {}).items():
            for row in rows:
                try:
                    fact = FactIn(
                        entity_key=key,
                        concept=concept,
                        label=str(body.get("label") or "")[:300],
                        unit=str(unit)[:40],
                        value=Decimal(str(row["val"])),
                        period_start=date.fromisoformat(row["start"]) if row.get("start") else None,
                        period_end=date.fromisoformat(row["end"]),
                        fiscal_year=row.get("fy"),
                        fiscal_period=row.get("fp"),
                        form=(row.get("form") or "")[:12] or None,
                        accession=row["accn"],
                        filed_at=date.fromisoformat(row["filed"]),
                    )
                except (KeyError, ValueError, InvalidOperation) as exc:
                    raise ValidationFailure(
                        "Malformed fact in SEC company facts", details={"concept": concept}
                    ) from exc
                identity = (concept, fact.unit, fact.period_start, fact.period_end, fact.accession)
                if identity not in seen:
                    seen.add(identity)
                    facts.append(fact)
    return facts
