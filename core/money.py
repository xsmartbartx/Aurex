"""Money primitive: decimal arithmetic with an explicit currency. Mixing currencies is an error, not a guess."""

from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal

from core.errors import ValidationFailure

ZERO = Decimal("0")


def to_decimal(value: object) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(repr(value))
    try:
        return Decimal(str(value).strip())
    except Exception as exc:
        raise ValidationFailure("Not a decimal number", details={"value": str(value)[:40]}) from exc


def normalize_currency(code: str) -> str:
    code = (code or "").strip().upper()
    if len(code) != 3 or not code.isalpha():
        raise ValidationFailure("Currency must be a 3-letter ISO 4217 code", details={"currency": code[:8]})
    return code


@dataclass(frozen=True)
class Money:
    amount: Decimal
    currency: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "amount", to_decimal(self.amount))
        object.__setattr__(self, "currency", normalize_currency(self.currency))

    def _check(self, other: "Money") -> None:
        if other.currency != self.currency:
            raise ValidationFailure("Currency mismatch", details={"left": self.currency, "right": other.currency})

    def __add__(self, other: "Money") -> "Money":
        self._check(other)
        return Money(self.amount + other.amount, self.currency)

    def __sub__(self, other: "Money") -> "Money":
        self._check(other)
        return Money(self.amount - other.amount, self.currency)

    def __mul__(self, factor: Decimal | int) -> "Money":
        return Money(self.amount * to_decimal(factor), self.currency)

    def convert(self, to_currency: str, rate: Decimal) -> "Money":
        """Convert with a dated rate quoted as units of ``to_currency`` per unit of this currency."""
        rate = to_decimal(rate)
        if rate <= ZERO:
            raise ValidationFailure("Conversion rate must be positive")
        return Money(self.amount * rate, to_currency)

    def rounded(self, places: int = 2) -> "Money":
        quantum = Decimal(1).scaleb(-places)
        return Money(self.amount.quantize(quantum, rounding=ROUND_HALF_EVEN), self.currency)
