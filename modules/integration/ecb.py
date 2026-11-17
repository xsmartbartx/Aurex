"""European Central Bank connectors: ECB Data Portal (SDMX 2.1, CSV) and the press feed.

Terms: free reuse with source citation; statistics are not modified. Derived series are labeled as
AUREX calculations by the caller. Figures are revised, which the versioned store records.
"""

import calendar
import csv
import io
import re
import xml.etree.ElementTree as ET  # noqa: S405 - parsed with entity declarations rejected below
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from email.utils import parsedate_to_datetime
from typing import Any

from core.canonical import Batch, DocumentIn, EntityIn, InstrumentIn, ObservationIn, SeriesIn
from core.errors import ProviderError, ValidationFailure
from core.types import InstrumentType
from modules.integration.http import fetch
from modules.validation import Lenient, validate

BASE = "https://data-api.ecb.europa.eu/service/data"
PRESS_FEED = "https://www.ecb.europa.eu/rss/press.html"
PUBLICATION_TIME = time(15, 0, tzinfo=UTC)  # reference rates are published around 16:00 CET
_QUARTER = re.compile(r"^(\d{4})-Q([1-4])$")
_CURRENCY_NAMES = {
    "USD": "US dollar",
    "GBP": "Pound sterling",
    "JPY": "Japanese yen",
    "CHF": "Swiss franc",
    "PLN": "Polish zloty",
    "SEK": "Swedish krona",
    "NOK": "Norwegian krone",
    "DKK": "Danish krone",
    "CZK": "Czech koruna",
    "HUF": "Hungarian forint",
    "CAD": "Canadian dollar",
    "AUD": "Australian dollar",
    "NZD": "New Zealand dollar",
    "CNY": "Chinese yuan",
    "INR": "Indian rupee",
    "BRL": "Brazilian real",
    "MXN": "Mexican peso",
    "ZAR": "South African rand",
    "TRY": "Turkish lira",
    "KRW": "South Korean won",
    "SGD": "Singapore dollar",
    "HKD": "Hong Kong dollar",
    "ILS": "Israeli shekel",
    "RON": "Romanian leu",
    "BGN": "Bulgarian lev",
    "ISK": "Icelandic krona",
    "IDR": "Indonesian rupiah",
    "MYR": "Malaysian ringgit",
    "PHP": "Philippine peso",
    "THB": "Thai baht",
}


class _Row(Lenient):
    KEY: str
    TIME_PERIOD: str
    OBS_VALUE: str
    OBS_STATUS: str = ""
    CURRENCY: str = ""
    TITLE: str = ""


def parse_period(value: str) -> date:
    """Map an SDMX time period to the last day it covers."""
    try:
        if len(value) == 10:
            return date.fromisoformat(value)
        if len(value) == 7 and value[4] == "-" and value[5] != "Q":
            year, month = int(value[:4]), int(value[5:])
            return date(year, month, calendar.monthrange(year, month)[1])
        if match := _QUARTER.match(value):
            year, month = int(match[1]), int(match[2]) * 3
            return date(year, month, calendar.monthrange(year, month)[1])
        if len(value) == 4:
            return date(int(value), 12, 31)
    except ValueError:
        pass
    raise ValidationFailure("Unrecognized time period in provider data", details={"period": value[:12]})


def _rows(flow: str, key: str, start: date | None) -> list[_Row]:
    params = {"format": "csvdata"}
    if start:
        params["startPeriod"] = start.isoformat()
    try:
        raw = fetch(f"{BASE}/{flow}/{key}", params=params, timeout=120.0)
    except ProviderError as exc:
        if exc.code == "provider_not_found" and start:
            return []  # no observations since the last run
        raise
    text = raw.decode("utf-8-sig", errors="strict")
    if not text.startswith("KEY,"):
        raise ValidationFailure("Unexpected response format from the ECB Data Portal")
    return [validate(_Row, row, what="ECB observation") for row in csv.DictReader(io.StringIO(text))]


# When the portal does not state a publication time, a conservative estimate is used so that point-in-time
# reads never see a value before it could have been known (docs/data-sources.md).
PUBLICATION_LAG = {
    "D": timedelta(days=1, hours=12),
    "B": timedelta(days=1, hours=12),
    "M": timedelta(days=35),
    "Q": timedelta(days=50),
    "A": timedelta(days=120),
}


def _observation(code: str, row: _Row, *, intraday_publication: bool, frequency: str = "D") -> ObservationIn | None:
    if row.OBS_VALUE == "":
        return None  # the provider marks a missing value; the gap is counted by the quality rules
    try:
        value = Decimal(row.OBS_VALUE)
    except InvalidOperation as exc:
        raise ValidationFailure("Non-numeric value in provider data", details={"series": code}) from exc
    day = parse_period(row.TIME_PERIOD)
    ref = datetime.combine(day, time(0, tzinfo=UTC))
    known = (
        datetime.combine(day, PUBLICATION_TIME)
        if intraday_publication
        else ref + PUBLICATION_LAG.get(frequency, timedelta(days=1))
    )
    return ObservationIn(series_code=code, ref_time=ref, value=value, known_at=known)


def fetch_fx(config: dict[str, Any], since: date | None) -> Batch:
    """Euro foreign exchange reference rates for every published currency."""
    start = since or date.fromisoformat(config.get("start", "2010-01-01"))
    batch = Batch()
    seen: set[str] = set()
    for row in _rows("EXR", "D..EUR.SP00.A", start):
        currency = row.CURRENCY.upper()
        if len(currency) != 3 or not currency.isalpha():
            raise ValidationFailure("Invalid currency code in provider data")
        code = f"ECB:EXR:{currency}"
        if code not in seen:
            seen.add(code)
            name = _CURRENCY_NAMES.get(currency, currency)
            symbol = f"EUR{currency}"
            batch.instruments.append(
                InstrumentIn(
                    symbol=symbol,
                    name=f"Euro / {name}",
                    type=InstrumentType.FX,
                    currency=currency,
                    venue="ECB reference rate",
                    external_ids={"ecb": row.KEY},
                )
            )
            batch.series.append(
                SeriesIn(
                    code=code,
                    name=f"EUR/{currency} ECB reference rate",
                    kind="fx",
                    unit=f"{currency} per EUR",
                    currency=currency,
                    frequency="B",
                    instrument_symbol=symbol,
                )
            )
        if obs := _observation(code, row, intraday_publication=True):
            batch.observations.append(obs)
    return batch


def fetch_series(config: dict[str, Any], since: date | None) -> Batch:
    """Configured statistical series. Each entry: flow, key, code, symbol, name, kind, unit, frequency."""
    batch = Batch()
    for item in config.get("series", []):
        start = since or date.fromisoformat(item.get("start", config.get("start", "2000-01-01")))
        code, symbol = item["code"], item["symbol"]
        kind = item["kind"]
        batch.instruments.append(
            InstrumentIn(
                symbol=symbol,
                name=item["name"],
                type=InstrumentType.RATE if kind in ("rate", "yield") else InstrumentType.MACRO,
                currency=item.get("currency"),
                venue="ECB Data Portal",
                external_ids={"ecb": f"{item['flow']}.{item['key']}"},
            )
        )
        batch.series.append(
            SeriesIn(
                code=code,
                name=item["name"],
                kind=kind,
                unit=item["unit"],
                currency=item.get("currency"),
                frequency=item["frequency"],
                instrument_symbol=symbol,
            )
        )
        for row in _rows(item["flow"], item["key"], start):
            if obs := _observation(code, row, intraday_publication=False, frequency=item["frequency"]):
                batch.observations.append(obs)
    return batch


def fetch_press(config: dict[str, Any], since: date | None) -> Batch:
    """Titles and links of ECB press releases, speeches and interviews."""
    raw = fetch(PRESS_FEED, timeout=60.0, max_bytes=5 * 1024 * 1024)
    if b"<!DOCTYPE" in raw or b"<!ENTITY" in raw:
        raise ValidationFailure("Feed contains a document type declaration")
    try:
        root = ET.fromstring(raw)  # noqa: S314 - declarations rejected above; expat does not fetch externals
    except ET.ParseError as exc:
        raise ValidationFailure("Press feed is not well-formed XML") from exc
    batch = Batch(entities=[EntityIn(key="institution:ecb", kind="institution", name="European Central Bank")])
    for item in root.iter("item"):
        title = " ".join((item.findtext("title") or "").split())
        link = (item.findtext("link") or "").strip().replace("europa.eu//", "europa.eu/")
        published = item.findtext("pubDate") or ""
        if not title or not link.startswith("https://www.ecb.europa.eu/"):
            continue
        try:
            when = parsedate_to_datetime(published).astimezone(UTC)
        except (TypeError, ValueError) as exc:
            raise ValidationFailure("Invalid publication date in press feed") from exc
        kind = "speech" if "/press/key/" in link else "interview" if "/press/inter/" in link else "release"
        batch.documents.append(
            DocumentIn(
                key=link.rsplit("/", 1)[-1][:200],
                doc_type=kind,
                title=title[:400],
                url=link,
                published_at=when,
                entity_key="institution:ecb",
                body=title,
                meta={"publisher": "European Central Bank"},
            )
        )
    return batch
