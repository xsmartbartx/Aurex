"""Evidence ledger (section 4.7): what an answer rests on.

Tools add evidence while a run gathers material. Each item gets an id (E1, E2, ...) that statements cite.
An item is a passage, a reported fact, an observation or a calculation, and always names its source.
"""

from dataclasses import dataclass, field
from typing import Any, Literal

EvidenceKind = Literal["passage", "fact", "observation", "calculation", "dataset", "link"]
ClaimStatus = Literal["supported", "assumption", "unsupported"]


@dataclass
class Evidence:
    id: str
    kind: EvidenceKind
    label: str
    value: float | None = None
    unit: str = ""
    text: str = ""
    source: dict[str, Any] = field(default_factory=dict)  # dataset, attribution, license class, ids, dates
    calculation: dict[str, Any] | None = None  # definition, version, inputs
    recipe: dict[str, Any] | None = None  # tool and input that reproduce a calculation
    numbers: list[float] = field(default_factory=list)  # further figures this item supports (inputs, years)

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if v not in (None, "", [], {})} | {
            "id": self.id,
            "kind": self.kind,
        }

    def for_model(self) -> dict[str, Any]:
        """The compact view a model sees. Source text is data, never instructions."""
        out: dict[str, Any] = {"id": self.id, "kind": self.kind, "label": self.label}
        if self.value is not None:
            out["value"], out["unit"] = self.value, self.unit
        if self.text:
            out["text"] = self.text
        if self.calculation:
            out["definition"] = self.calculation.get("definition")
        for key in ("period_end", "filed_at", "published_at", "ref_time", "freshness_class", "status", "license_class"):
            if key in self.source:
                out[key] = self.source[key]
        return out


@dataclass
class Claim:
    text: str
    evidence: list[str] = field(default_factory=list)
    status: ClaimStatus = "supported"
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"text": self.text, "evidence": self.evidence, "status": self.status, "note": self.note}


@dataclass
class Section:
    heading: str
    claims: list[Claim] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"heading": self.heading, "claims": [c.to_dict() for c in self.claims]}


class Ledger:
    def __init__(self) -> None:
        self._items: dict[str, Evidence] = {}
        self._keys: dict[tuple, str] = {}
        self.gaps: list[str] = []

    def add(self, kind: EvidenceKind, label: str, *, key: tuple | None = None, **fields: Any) -> Evidence:
        """Record an item. The same underlying source is recorded once, so its id is stable within a run."""
        if key is not None and key in self._keys:
            return self._items[self._keys[key]]
        item = Evidence(id=f"E{len(self._items) + 1}", kind=kind, label=label, **fields)
        self._items[item.id] = item
        if key is not None:
            self._keys[key] = item.id
        return item

    def gap(self, text: str) -> None:
        if text and text not in self.gaps:
            self.gaps.append(text)

    def get(self, evidence_id: str) -> Evidence | None:
        return self._items.get(evidence_id)

    def __len__(self) -> int:
        return len(self._items)

    def all(self) -> list[Evidence]:
        return list(self._items.values())

    def cited(self, sections: list[Section]) -> list[Evidence]:
        used = {e for s in sections for c in s.claims for e in c.evidence}
        return [item for item in self._items.values() if item.id in used]
