"""Core primitives, boundary validation and log content."""

import io
import json
from decimal import Decimal

import pytest

from core.errors import ValidationFailure
from core.money import Money
from modules.logging import log, sanitize
from modules.logging.log import set_stream
from modules.validation import Strict, parse_csv, require_symbol, validate


def test_money_arithmetic_is_decimal_and_currency_checked():
    assert (Money("0.1", "eur") + Money("0.2", "EUR")).amount == Decimal("0.3")
    with pytest.raises(ValidationFailure):
        Money("1", "EUR") + Money("1", "USD")
    with pytest.raises(ValidationFailure):
        Money("1", "EURO")


def test_money_round_trip_conversion_is_invariant():
    rate = Decimal("1.1214")
    start = Money("1000", "EUR")
    back = start.convert("USD", rate).convert("EUR", 1 / rate).rounded(6)
    assert back == Money("1000", "EUR").rounded(6)


def test_validate_reports_fields_without_echoing_input():
    class Body(Strict):
        name: str
        size: int

    with pytest.raises(ValidationFailure) as failure:
        validate(Body, {"name": "x", "size": "secret-value", "extra": 1})
    details = json.dumps(failure.value.details)
    assert "size" in details and "extra" in details
    assert "secret-value" not in details


@pytest.mark.parametrize(
    "raw",
    [
        b"date,quantity\n2024-01-01,=HYPERLINK(1)\n",  # formula injection
        b"date\n2024-01-01\n",  # missing column
        b"date,quantity,evil\n2024-01-01,1,2\n",  # unexpected column
        b"date,quantity\n",  # no rows
        b"date,quantity\n\x00\x01,1\n",  # binary content
        b"date,quantity\n2024-01-01,1,2,3\n",  # ragged row
    ],
)
def test_csv_upload_rejects_malformed_input(raw):
    with pytest.raises(ValidationFailure):
        parse_csv(raw, required={"date", "quantity"})


def test_csv_upload_accepts_signed_numbers_and_enforces_size():
    rows = parse_csv(b"Date,Quantity\n2024-01-01,-5\n2024-01-02,+3\n", required={"date", "quantity"})
    assert [r["quantity"] for r in rows] == ["-5", "+3"]
    with pytest.raises(ValidationFailure):
        parse_csv(b"date,quantity\n" + b"2024-01-01,1\n" * 50, required={"date", "quantity"}, max_rows=10)
    with pytest.raises(ValidationFailure):
        parse_csv(b"x" * 100, required={"date"}, max_bytes=10)


def test_symbol_validation():
    assert require_symbol(" eurusd ") == "EURUSD"
    with pytest.raises(ValidationFailure):
        require_symbol("DROP TABLE;--")


FORBIDDEN = [
    "hunter2-password",
    "alice@example.com",
    "aurex_abcdefghijklmnop",
    "Bearer abcdefghijklmnop",
    "postgresql://user:dbsecret@host/db",
    "4111 1111 1111 1111",
    "Traceback (most recent call last)",
]


def test_log_schema_and_forbidden_data():
    stream = io.StringIO()
    set_stream(stream)
    try:
        log(
            "tests",
            "sample",
            "SECURITY",
            password="hunter2-password",
            user_email="alice@example.com",
            note="contact alice@example.com with key aurex_abcdefghijklmnop",
            header="Bearer abcdefghijklmnop",
            dsn="connect postgresql://user:dbsecret@host/db now",
            card="4111 1111 1111 1111",
            stack="Traceback (most recent call last)",
            nested={"token": "abc", "ok": 1},
            count=3,
        )
    finally:
        set_stream(None)
    line = stream.getvalue().strip()
    record = json.loads(line)
    assert set(record) == {"timestamp", "module", "event", "severity", "details"}
    assert record["severity"] == "SECURITY" and record["details"]["count"] == 3
    assert record["details"]["nested"] == {"token": "[redacted]", "ok": 1}
    for value in FORBIDDEN:
        assert value not in line
    assert "dbsecret" not in line


def test_sanitize_bounds_size_and_depth():
    assert len(sanitize("x" * 5000)) < 400
    deep = {"a": {"b": {"c": {"d": {"e": {"f": 1}}}}}}
    assert "[nested]" in json.dumps(sanitize(deep))
