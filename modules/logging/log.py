import json
import re
import sys
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, TextIO

from core.config import get_settings


class Severity(StrEnum):
    INFO = "INFO"
    WARN = "WARN"
    ERROR = "ERROR"
    SECURITY = "SECURITY"


_ORDER = {"DEBUG": 0, "INFO": 1, "WARN": 2, "WARNING": 2, "ERROR": 3, "SECURITY": 4}

REDACTED = "[redacted]"
_FORBIDDEN_KEY = re.compile(
    r"pass(word|wd)?|secret|token|authorization|cookie|api[_-]?key|credential|session|signature|"
    r"email|e-mail|phone|address|ssn|card|iban|prompt|question|body|payload|content|stack|traceback",
    re.IGNORECASE,
)
_PATTERNS = [
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "[email]"),
    (re.compile(r"\b(?:aurex|sk|pk|rk|whsec)_[A-Za-z0-9_\-]{8,}"), "[key]"),
    (re.compile(r"\bBearer\s+[A-Za-z0-9._\-]{8,}", re.IGNORECASE), "[bearer]"),
    (re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{5,}"), "[jwt]"),
    (re.compile(r"(postgres(?:ql)?(?:\+\w+)?://[^:/\s]+:)[^@\s]+@"), r"\1[redacted]@"),
    (re.compile(r"\b(?:\d[ -]?){13,19}\b"), "[number]"),
]
MAX_VALUE_LEN = 300


def _clean_text(value: str) -> str:
    for pattern, repl in _PATTERNS:
        value = pattern.sub(repl, value)
    value = value.replace("\n", " ").replace("\r", " ")
    return value if len(value) <= MAX_VALUE_LEN else value[:MAX_VALUE_LEN] + "…"


def sanitize(value: Any, _depth: int = 0) -> Any:
    """Return a copy that is safe to log. Applied to logs, audit details and trace attributes."""
    if _depth > 4:
        return "[nested]"
    if isinstance(value, dict):
        return {
            str(k): (REDACTED if _FORBIDDEN_KEY.search(str(k)) else sanitize(v, _depth + 1))
            for k, v in list(value.items())[:40]
        }
    if isinstance(value, list | tuple | set | frozenset):
        return [sanitize(v, _depth + 1) for v in list(value)[:40]]
    if isinstance(value, str):
        return _clean_text(value)
    if isinstance(value, bool | int | float) or value is None:
        return value
    return _clean_text(str(value))


_stream: TextIO | None = None


def set_stream(stream: TextIO | None) -> None:
    """Redirect log output (tests)."""
    global _stream
    _stream = stream


def log(module: str, event: str, severity: Severity | str = Severity.INFO, **details: Any) -> None:
    severity = Severity(severity)
    if _ORDER[severity.value] < _ORDER.get(get_settings().log_level.upper(), 1):
        return
    record = {
        "timestamp": datetime.now(UTC).isoformat(timespec="milliseconds"),
        "module": module,
        "event": event,
        "severity": severity.value,
        "details": sanitize(details),
    }
    stream = _stream or sys.stdout
    stream.write(json.dumps(record, default=str, ensure_ascii=False) + "\n")
    stream.flush()
