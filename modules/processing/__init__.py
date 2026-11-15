"""The financial engine: deterministic, versioned calculations (section 4.3).

Pure functions only. The engine reads nothing and writes nothing; callers pass values in and receive a
``Calculation`` that names its definition, version and inputs, so any figure can be reproduced.
"""

from dataclasses import dataclass, field
from typing import Any

ENGINE_VERSION = "1.0.0"


@dataclass(frozen=True)
class Calculation:
    definition: str
    inputs: dict[str, Any]
    output: Any
    unit: str = ""
    version: str = ENGINE_VERSION
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "definition": self.definition,
            "version": self.version,
            "inputs": self.inputs,
            "output": self.output,
            "unit": self.unit,
            "notes": list(self.notes),
        }


__all__ = ["ENGINE_VERSION", "Calculation"]
