"""Usage limits, rate limiting and content screening for AI context (threats T-03, T-11)."""

import re
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from core.errors import QuotaExceeded, RateLimited
from core.types import Scope, utcnow
from modules.logging import Severity, log


class RateLimiter:
    """Sliding window per key, per process. Run one API process per deployment or front it with a proxy limit."""

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str, limit: int, window_seconds: int = 60) -> None:
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            while hits and hits[0] <= now - window_seconds:
                hits.popleft()
            if len(hits) >= limit:
                retry = int(window_seconds - (now - hits[0])) + 1
                raise RateLimited("Too many requests", details={"retry_after_seconds": retry})
            hits.append(now)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


rate_limiter = RateLimiter()


def consume(session: Session, scope: Scope, metric: str, limit_name: str, amount: int = 1) -> int:
    """Count metered usage for today and refuse when the plan limit is reached. Atomic per tenant and day."""
    allowed = scope.limits.get(limit_name, 0)
    used = session.execute(
        text(
            "INSERT INTO usage_counters (tenant_id, metric, day, count) VALUES (:t, :m, :d, :n) "
            "ON CONFLICT (tenant_id, metric, day) DO UPDATE SET count = usage_counters.count + :n "
            "RETURNING count"
        ),
        {"t": scope.tenant_id, "m": metric, "d": utcnow().date(), "n": amount},
    ).scalar_one()
    if used > allowed:
        raise QuotaExceeded(
            "Daily plan limit reached", details={"limit": limit_name, "allowed": allowed, "plan": scope.plan}
        )
    return used


def usage_today(session: Session, tenant_id: UUID) -> dict[str, int]:
    rows = session.execute(
        text("SELECT metric, count FROM usage_counters WHERE tenant_id = :t AND day = :d"),
        {"t": tenant_id, "d": utcnow().date()},
    )
    return {r.metric: r.count for r in rows}


# --- Content screening ----------------------------------------------------------------------------

_INJECTION = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\b(ignore|disregard|forget|override)\b[^.\n]{0,40}\b(previous|prior|above|earlier|all|any|system)\b"
        r"[^.\n]{0,30}\b(instruction|prompt|rule|direction|context|message)s?\b",
        r"\byou are (now|no longer)\b",
        r"\b(system|developer|assistant)\s*(prompt|message|override|:)",
        r"\bnew instructions?\b\s*:",
        r"\b(reveal|print|show|repeat|leak|exfiltrate)\b[^.\n]{0,40}\b(system prompt|instructions|api key|"
        r"secret|password|credentials?|token)s?\b",
        r"\b(call|invoke|use|run|execute)\b[^.\n]{0,25}\b(tool|function|command|shell|code)\b",
        r"\b(send|post|forward|upload|email)\b[^.\n]{0,40}\b(to|at)\b\s+(https?://|[\w.+-]+@)",
        r"<\s*/?\s*(system|instructions?|tool_use|function_calls?|antml)[^>]*>",
        r"\bdo not (tell|inform|mention)[^.\n]{0,30}\b(user|analyst|reader)\b",
        r"\bas an? (ai|language model|assistant)\b[^.\n]{0,40}\b(must|should|will)\b",
        r"\b(recommend|advise|tell)\b[^.\n]{0,40}\b(buy|sell|short)\b[^.\n]{0,30}\b(immediately|now|urgent)",
    )
]


@dataclass(frozen=True)
class Screening:
    flagged: bool
    reasons: tuple[str, ...] = ()


def screen_content(text_value: str, *, source: str = "") -> Screening:
    """Detect instruction-like text in retrieved content. Flagged content is withheld from the model."""
    reasons = tuple(sorted({f"pattern_{i}" for i, p in enumerate(_INJECTION) if p.search(text_value or "")}))
    if reasons:
        log("security", "content_screening.flagged", Severity.SECURITY, source=source, reasons=list(reasons))
    return Screening(flagged=bool(reasons), reasons=reasons)
