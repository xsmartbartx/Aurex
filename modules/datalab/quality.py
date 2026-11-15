"""Quality rules (section 4.6, flow 1). A rule never rejects data: it sets the status shown with the value."""

import re
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from core.canonical import ObservationIn, SeriesIn
from core.types import QualityStatus

JUMP_LIMIT = {"fx": Decimal("0.15"), "price": Decimal("0.40")}
POSITIVE_KINDS = {"fx", "price"}
_ITEM = re.compile(r"^(item\s+\d+[a-c]?)\b[.:\s—-]*(.*)$", re.IGNORECASE)


def assess(
    series: list[SeriesIn], observations: list[ObservationIn], last_values: dict[str, Decimal] | None = None
) -> tuple[list[ObservationIn], dict[str, int]]:
    """Deduplicate and classify observations. Returns the kept observations and a summary for the run."""
    kinds = {s.code: s for s in series}
    by_series: dict[str, dict] = defaultdict(dict)
    duplicates = 0
    for obs in observations:
        if obs.ref_time in by_series[obs.series_code]:
            duplicates += 1
        by_series[obs.series_code][obs.ref_time] = obs  # the last occurrence wins
    summary = {"duplicates": duplicates, "suspect": 0, "gaps": 0, "non_positive": 0, "jumps": 0, "ohlc_inconsistent": 0}
    kept: list[ObservationIn] = []
    for code, points in by_series.items():
        meta = kinds.get(code)
        kind = meta.kind if meta else ""
        previous = (last_values or {}).get(code)
        previous_time = None
        for ref_time in sorted(points):
            obs = points[ref_time]
            status = obs.quality or QualityStatus.VALIDATED
            reasons = 0
            if kind in POSITIVE_KINDS and obs.value <= 0:
                summary["non_positive"] += 1
                reasons += 1
            limit = JUMP_LIMIT.get(kind)
            if limit and previous and previous > 0 and abs(obs.value / previous - 1) > limit:
                summary["jumps"] += 1
                reasons += 1
            if (
                obs.high is not None
                and obs.low is not None
                and not (obs.low <= obs.value <= obs.high and (obs.open is None or obs.low <= obs.open <= obs.high))
            ):
                summary["ohlc_inconsistent"] += 1
                reasons += 1
            if reasons and status != QualityStatus.DEMONSTRATION:
                status = QualityStatus.SUSPECT
                summary["suspect"] += 1
            if meta and meta.frequency in ("D", "B") and previous_time and ref_time - previous_time > timedelta(days=6):
                summary["gaps"] += 1
            kept.append(obs.model_copy(update={"quality": status}))
            previous, previous_time = obs.value, ref_time
    return kept, summary


def split_passages(body: str, *, max_chars: int = 1200, max_passages: int = 1500) -> list[tuple[str, str]]:
    """Split document text into addressable passages: ``(location, text)``."""
    passages: list[tuple[str, str]] = []
    section, buffer, size = "", [], 0

    def flush() -> None:
        nonlocal buffer, size
        if buffer and len(passages) < max_passages:
            number = len(passages) + 1
            passages.append((f"{section} · ¶{number}" if section else f"¶{number}", " ".join(buffer)))
        buffer, size = [], 0

    for line in body.split("\n"):
        line = line.strip()
        if not line:
            continue
        heading = _ITEM.match(line) if len(line) < 160 else None
        if heading:
            flush()
            section = f"{heading[1].title()} {heading[2]}".strip()[:80]
        while len(line) > max_chars:  # a very long paragraph is cut at a sentence or word boundary
            cut = max(line.rfind(". ", 0, max_chars) + 1, line.rfind(" ", 0, max_chars), max_chars // 2)
            flush()
            buffer, size = [line[:cut].strip()], cut
            flush()
            line = line[cut:].strip()
        if size + len(line) > max_chars:
            flush()
        if line:
            buffer.append(line)
            size += len(line) + 1
    flush()
    return passages
