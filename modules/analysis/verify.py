"""Claim verification (ADR-0006). The language model writes; it does not originate figures.

A statement survives as a finding only if its citations resolve and every figure in it equals a value
in the cited evidence. A statement the writer marked as its own inference is shown as an assumption.
Anything else is labeled unsupported and withheld from the answer.
"""

import re
from collections.abc import Iterable

from modules.analysis.ledger import Claim, Evidence, Ledger, Section

_NUMBER = re.compile(
    r"(?<![\w.])[-−+]?\d[\d,]*(?:\.\d+)?(?:\s?(?:%|percent|bn|billion|mn|million|k|thousand|x))?", re.IGNORECASE
)
# Tokens that contain digits but are names, not figures.
_NAMES = re.compile(
    r"\b(?:10-K|10-Q|8-K|20-F|40-F|6-K|Q[1-4]|FY\s?\d{2,4}|H[12]|[1-9]\d?[DWMY]|E\d+|ISO\s?\d+|"
    r"\d{4}-\d{2}-\d{2}|\d{1,2}\s(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s\d{4}|"
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s\d{1,2},?\s\d{4})\b|\b\d{1,2}-(?:year|month|day)\b",
    re.IGNORECASE,
)
_SCALE = {"bn": 1e9, "billion": 1e9, "mn": 1e6, "million": 1e6, "k": 1e3, "thousand": 1e3}
_FACTUAL = re.compile(
    r"\d|\b(?:increase|decrease|grew|fell|rose|higher|lower|reported|filed|said|"
    r"revenue|margin|debt|cash|rate|yield|inflation)\b",
    re.IGNORECASE,
)


def _figures(text: str) -> list[tuple[float, float, bool]]:
    """Figures in a statement as (value, rounding tolerance, is_percent). Names and small counts are skipped."""
    cleaned = _NAMES.sub(" ", text)
    out = []
    for match in _NUMBER.finditer(cleaned):
        raw = match.group(0).replace(" ", "")
        digits = re.match(r"[-−+]?[\d,]*(?:\.\d+)?", raw).group(0)
        number = digits.replace(",", "").replace("−", "-").replace("+", "")
        if not number or number in ("-", "."):
            continue
        suffix = raw[len(digits) :].lower()
        decimals = len(number.split(".")[1]) if "." in number else 0
        value = float(number)
        percent = suffix in ("%", "percent")
        scale = _SCALE.get(suffix, 1.0)
        if scale == 1.0 and decimals == 0 and not percent and suffix != "x":
            if abs(value) <= 12:
                continue  # a count ("two companies", "3 filings") rather than a measured figure
            if 1900 <= value <= 2100:
                continue  # a year
        # A figure may be rounded to the precision it is written with.
        out.append((value * scale, 0.51 * 10.0 ** (-decimals) * scale, percent))
    return out


def _supports(evidence: Iterable[Evidence]) -> list[float]:
    values: list[float] = []
    for item in evidence:
        if item.value is not None:
            values.append(float(item.value))
        values.extend(float(n) for n in item.numbers)
        for ref in ((item.calculation or {}).get("inputs") or {}).values():
            if isinstance(ref, dict) and isinstance(ref.get("value"), int | float):
                values.append(float(ref["value"]))
        if item.kind == "passage":  # a figure quoted from a document is supported by that passage
            values.extend(value for value, _, _ in _figures(item.text))
    return values


def _matches(figure: tuple[float, float, bool], supports: list[float]) -> bool:
    value, tolerance, percent = figure
    for support in supports:
        candidates = [support, support * 100] if percent else [support]  # a ratio may be written as a percentage
        for candidate in candidates:
            # Direction is carried by the wording ("fell 5.3%"), so magnitudes are compared.
            if abs(abs(value) - abs(candidate)) <= max(tolerance, abs(candidate) * 0.0006):
                return True
    return False


def verify_claim(claim: Claim, ledger: Ledger, *, declared_assumption: bool = False) -> Claim:
    resolved = [ledger.get(e) for e in claim.evidence]
    missing = [e for e, item in zip(claim.evidence, resolved, strict=True) if item is None]
    items = [item for item in resolved if item is not None]
    kept = [item.id for item in items]
    figures = _figures(claim.text)

    if declared_assumption:
        unbacked = [f for f in figures if not _matches(f, _supports(items))]
        if unbacked:
            return Claim(claim.text, kept, "unsupported", "An inference may not introduce figures of its own.")
        return Claim(claim.text, kept, "assumption", "Inference by the writer, not a finding.")
    if missing and not items:
        return Claim(claim.text, [], "unsupported", "The cited evidence does not exist.")
    if not items:
        if _FACTUAL.search(claim.text):
            return Claim(claim.text, [], "unsupported", "A factual statement without evidence.")
        return Claim(claim.text, [], "assumption", "No evidence cited.")
    supports = _supports(items)
    unbacked = [f for f in figures if not _matches(f, supports)]
    if unbacked:
        shown = ", ".join(f"{v:g}" for v, _, _ in unbacked[:3])
        return Claim(claim.text, kept, "unsupported", f"Figure not found in the cited evidence: {shown}.")
    return Claim(claim.text, kept, "supported", "Some citations did not resolve." if missing else "")


def verify(
    sections: list[tuple[str, list[tuple[str, list[str], bool]]]], ledger: Ledger
) -> tuple[list[Section], dict[str, int]]:
    """Check every statement. Input statements are ``(text, evidence ids, declared_assumption)``."""
    out: list[Section] = []
    counts = {"supported": 0, "assumption": 0, "unsupported": 0}
    for heading, statements in sections:
        section = Section(heading=heading[:160])
        for text, evidence_ids, assumption in statements:
            text = " ".join(str(text).split())
            if not text:
                continue
            claim = verify_claim(
                Claim(text[:1500], list(dict.fromkeys(evidence_ids))[:12]), ledger, declared_assumption=assumption
            )
            counts[claim.status] += 1
            section.claims.append(claim)
        if section.claims:
            out.append(section)
    return out, counts
