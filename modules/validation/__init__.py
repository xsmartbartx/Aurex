"""Boundary validation. Every module validates what it receives and does not rely on upstream checks.

A schema violation stops the flow (fail-fast) with the standard error structure. This module only
checks and reports: it never repairs data and contains no business logic.
"""

import csv
import io
import re
import unicodedata
from typing import Any, TypeVar

from pydantic import BaseModel, ConfigDict
from pydantic import ValidationError as PydanticValidationError

from core.errors import ValidationFailure

T = TypeVar("T", bound=BaseModel)

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
SYMBOL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.\-_:/=^]{0,31}$")
SLUG = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


class Strict(BaseModel):
    """Base for interface objects: unknown fields are rejected, strings are trimmed."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Lenient(BaseModel):
    """Base for provider payloads: unknown fields are ignored, declared fields are checked."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)


def _issues(exc: PydanticValidationError) -> list[dict[str, Any]]:
    return [
        {"field": ".".join(str(p) for p in e["loc"]), "problem": e["msg"], "type": e["type"]}
        for e in exc.errors(include_input=False, include_url=False)[:25]
    ]


def validate(model: type[T], data: Any, *, what: str = "input") -> T:
    """Validate ``data`` against ``model`` or raise ``ValidationFailure``. Input values are not echoed."""
    try:
        return model.model_validate(data)
    except PydanticValidationError as exc:
        raise ValidationFailure(f"Invalid {what}", details={"issues": _issues(exc)}) from exc


def clean_text(value: str, *, max_len: int = 2000) -> str:
    """Normalize user text: NFC, no control characters, bounded length."""
    if not isinstance(value, str):
        raise ValidationFailure("Expected text")
    value = _CONTROL.sub("", unicodedata.normalize("NFC", value)).strip()
    if len(value) > max_len:
        raise ValidationFailure("Text is too long", details={"max_length": max_len})
    return value


def require_symbol(value: str) -> str:
    value = clean_text(value, max_len=32).upper()
    if not SYMBOL.match(value):
        raise ValidationFailure("Invalid instrument symbol")
    return value


def parse_csv(
    raw: bytes,
    *,
    required: set[str],
    optional: set[str] = frozenset(),
    max_bytes: int = 5 * 1024 * 1024,
    max_rows: int = 20000,
) -> list[dict[str, str]]:
    """Parse an untrusted CSV upload. Rejects oversized, binary, malformed or unexpected content."""
    if len(raw) > max_bytes:
        raise ValidationFailure("File is too large", details={"max_bytes": max_bytes})
    if b"\x00" in raw:
        raise ValidationFailure("File is not a text CSV")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValidationFailure("File must be UTF-8 encoded") from exc
    reader = csv.DictReader(io.StringIO(text))
    header = {(h or "").strip().lower() for h in (reader.fieldnames or [])}
    missing = required - header
    if missing:
        raise ValidationFailure("Missing columns", details={"missing": sorted(missing)})
    unknown = header - required - set(optional)
    if unknown:
        raise ValidationFailure("Unexpected columns", details={"unexpected": sorted(unknown)[:10]})
    rows: list[dict[str, str]] = []
    for index, row in enumerate(reader, start=2):
        if index - 1 > max_rows:
            raise ValidationFailure("Too many rows", details={"max_rows": max_rows})
        if None in row:
            raise ValidationFailure("Row has more cells than the header", details={"line": index})
        clean = {(k or "").strip().lower(): _CONTROL.sub("", (v or "")).strip() for k, v in row.items()}
        # A cell that a spreadsheet would execute as a formula is rejected, not escaped.
        for key, cell in clean.items():
            if cell[:1] in ("=", "@") or (cell[:1] in ("+", "-") and not _is_number(cell)):
                raise ValidationFailure("Cell looks like a formula", details={"line": index, "column": key})
        clean["_line"] = str(index)
        rows.append(clean)
    if not rows:
        raise ValidationFailure("File has no data rows")
    return rows


def _is_number(value: str) -> bool:
    try:
        float(value)
        return True
    except ValueError:
        return False


__all__ = ["SLUG", "Lenient", "Strict", "clean_text", "parse_csv", "require_symbol", "validate"]
