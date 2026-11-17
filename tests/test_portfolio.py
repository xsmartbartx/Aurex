"""Portfolio analytics against independently computed reference values, imports, scenarios and isolation."""

from datetime import date
from decimal import Decimal

import pytest

from core.errors import ValidationFailure
from modules.processing import portfolio as calc

D = Decimal


def txn(day, kind, instrument=None, quantity=1, price=0, fees=0, currency="USD"):
    return calc.Txn(date.fromisoformat(day), kind, instrument, D(str(quantity)), D(str(price)), D(str(fees)), currency)


def test_average_cost_and_realized_result():
    book = calc.Book()
    for t in (
        txn("2024-01-02", "deposit", price=10000),
        txn("2024-01-03", "buy", "A", 10, 100, 5),
        txn("2024-01-04", "buy", "A", 10, 120, 5),
        txn("2024-01-05", "sell", "A", 5, 130, 5),
    ):
        calc.apply(book, t)
    position = book.positions["A"]
    assert position.quantity == 15
    assert position.cost == D("1657.50")  # (1005 + 1205) / 20 * 15
    assert position.realized == D("92.50")  # 650 - 5 - 110.5 * 5
    assert book.cash["USD"] == D("10000") - D("1005") - D("1205") + D("645")
    with pytest.raises(ValidationFailure):
        calc.apply(book, txn("2024-01-06", "sell", "A", 16, 100))


def test_time_weighted_return_excludes_deposits():
    prices = {
        "A": calc.AsOf(
            [(date(2024, 1, 1), 100.0), (date(2024, 1, 2), 110.0), (date(2024, 1, 3), 110.0), (date(2024, 1, 4), 99.0)]
        )
    }
    txns = [
        txn("2024-01-01", "deposit", price=1000),
        txn("2024-01-01", "buy", "A", 10, 100),
        txn("2024-01-03", "deposit", price=5000),
    ]
    valued = calc.valuation(txns, prices, {}, "USD", date(2024, 1, 4))
    assert valued["values"] == pytest.approx([1000, 1100, 6100, 5990])
    # +10%, 0% (the deposit is not a return), then -1.8033% (-110 on 6100)
    assert valued["index"][-1] == pytest.approx(100 * 1.10 * 1.0 * (5990 / 6100))


def test_currency_conversion_uses_ecb_quotes():
    fx = {"USD": calc.AsOf([(date(2024, 1, 1), 1.10)]), "GBP": calc.AsOf([(date(2024, 1, 1), 0.85)])}
    assert calc.fx_factor("USD", "EUR", date(2024, 1, 2), fx) == pytest.approx(1 / 1.10)
    assert calc.fx_factor("EUR", "USD", date(2024, 1, 2), fx) == pytest.approx(1.10)
    assert calc.fx_factor("GBP", "USD", date(2024, 1, 2), fx) == pytest.approx(1.10 / 0.85)
    assert calc.fx_factor("JPY", "EUR", date(2024, 1, 2), fx) is None  # never guessed


def test_concentration_and_limits():
    positions = [
        {"instrument": "A", "quantity": 1, "value": 600.0, "currency": "USD", "sector": "Tech", "type": "equity"},
        {"instrument": "B", "quantity": 1, "value": 400.0, "currency": "EUR", "sector": "Utilities", "type": "equity"},
    ]
    for row in positions:
        row["weight"] = row["value"] / 1000 * 100
    exposure = calc.exposures(positions, [], 1000.0)
    assert exposure["concentration"]["hhi"] == pytest.approx(0.36 + 0.16)
    assert exposure["concentration"]["effective_positions"] == pytest.approx(1 / 0.52)
    breaches = calc.check_limits(positions, exposure, {"max_position_pct": 50, "min_cash_pct": 5})
    assert {(b["limit"], b["subject"]) for b in breaches} == {("max_position_pct", "A"), ("min_cash_pct", "cash")}


def test_scenario_uses_the_most_specific_shock_and_currency_moves():
    positions = [
        {"instrument": "A", "quantity": 1, "value": 1000.0, "currency": "USD", "sector": "Tech", "type": "equity"},
        {"instrument": "B", "quantity": 1, "value": 1000.0, "currency": "EUR", "sector": "Food", "type": "equity"},
    ]
    result = calc.scenario(
        positions,
        [{"currency": "USD", "amount": 500, "value": 500.0}],
        "EUR",
        [
            {"target_type": "sector", "target": "Tech", "shock_pct": -30},
            {"target_type": "type", "target": "equity", "shock_pct": -10},
            {"target_type": "currency", "target": "USD", "shock_pct": -10},
        ],
    )
    impacts = {r["instrument"]: r["impact"] for r in result["positions"]}
    assert impacts["A"] == pytest.approx(1000 * 0.7 * 0.9 - 1000)
    assert impacts["B"] == pytest.approx(-100)
    assert impacts["Cash USD"] == pytest.approx(-50)
    assert result["impact"] == pytest.approx(sum(impacts.values()))


# --- API -------------------------------------------------------------------------------------------


def test_demo_portfolio_analytics(make_account):
    account = make_account(plan="pro")
    portfolio_id = account.post("/portfolios/demo").json()["id"]
    result = account.get(f"/portfolios/{portfolio_id}/analytics").json()
    assert not result["empty"] and result["base_currency"] == "EUR"
    weights = (
        sum(p["weight"] for p in result["positions"]) + sum(c["value"] for c in result["cash"]) / result["value"] * 100
    )
    assert weights == pytest.approx(100, abs=0.01)
    assert result["value"] == pytest.approx(
        sum(p["value"] for p in result["positions"]) + sum(c["value"] for c in result["cash"])
    )
    assert result["performance"]["method"].startswith("time-weighted")
    assert "excess_return" in result["performance"]["benchmark"]
    assert any("demonstration" in g for g in result["gaps"])
    assert {s["dataset"] for s in result["sources"]} >= {"demo", "ecb-fx"}
    shocked = account.post(
        f"/portfolios/{portfolio_id}/scenario",
        {"shocks": [{"target_type": "type", "target": "equity", "shock_pct": -20}]},
    ).json()
    assert shocked["impact"] < 0 and shocked["label"].endswith("Not a forecast.")


def test_transactions_validation_and_csv_import(make_account):
    account = make_account(plan="pro")
    portfolio_id = account.post("/portfolios", {"name": "Imported", "base_currency": "USD"}).json()["id"]
    good = (
        b"date,type,symbol,quantity,price,fees,currency,note\n"
        b"2024-01-02,deposit,,1,5000,0,USD,funding\n"
        b"2024-01-03,buy,ORCA.DEMO,10,100,1,USD,\n"
        b"2024-02-01,sell,ORCA.DEMO,4,110,1,,\n"
    )
    headers = {"x-aurex-client": "tests"}
    response = account.client.post(
        f"/api/v1/portfolios/{portfolio_id}/import", files={"file": ("t.csv", good, "text/csv")}, headers=headers
    )
    assert response.status_code == 201, response.text
    assert response.json()["added"] == 3
    oversell = b"date,type,symbol,quantity,price\n2024-03-01,sell,ORCA.DEMO,100,1\n"
    bad = account.client.post(
        f"/api/v1/portfolios/{portfolio_id}/import", files={"file": ("t.csv", oversell, "text/csv")}, headers=headers
    )
    assert bad.status_code == 422 and "exceeds" in bad.json()["error"]["message"]
    unknown = b"date,type,symbol,quantity,price\n2024-03-01,buy,NOPE.X,1,1\n"
    bad = account.client.post(
        f"/api/v1/portfolios/{portfolio_id}/import", files={"file": ("t.csv", unknown, "text/csv")}, headers=headers
    )
    assert bad.status_code == 422 and bad.json()["error"]["message"].startswith("Line 2")
    assert len(account.get(f"/portfolios/{portfolio_id}/transactions").json()["items"]) == 3
    future = account.post(
        f"/portfolios/{portfolio_id}/transactions",
        {"type": "buy", "executed_on": "2099-01-01", "instrument": "ORCA.DEMO", "price": 1},
    )
    assert future.status_code == 422


def test_portfolios_are_private_and_limited_by_plan(make_account):
    owner, other = make_account(plan="pro"), make_account(plan="pro")
    portfolio_id = owner.post("/portfolios", {"name": "Mine"}).json()["id"]
    assert other.get(f"/portfolios/{portfolio_id}/analytics").status_code == 404
    assert (
        other.post(
            f"/portfolios/{portfolio_id}/transactions",
            {"type": "deposit", "executed_on": "2024-01-01", "price": 1, "currency": "EUR"},
        ).status_code
        == 404
    )
    community = make_account(plan="community")
    assert community.post("/portfolios", {"name": "One"}).status_code == 201
    assert community.post("/portfolios", {"name": "Two"}).status_code == 403
    community_id = community.get("/portfolios").json()["items"][0]["id"]
    assert (
        community.post(
            f"/portfolios/{community_id}/scenario", {"shocks": [{"target_type": "all", "shock_pct": -5}]}
        ).status_code
        == 403
    )


def test_risk_agent_reads_the_users_portfolio(make_account):
    from pipelines.worker import run_one

    account = make_account(plan="pro")
    account.post("/portfolios/demo")
    response = account.post(
        "/intelligence/questions", {"question": "How concentrated is my portfolio?", "agent": "risk"}
    )
    while run_one():
        pass
    record = account.get(f"/intelligence/questions/{response.json()['id']}").json()
    claims = [c for s in record["answer"]["sections"] for c in s["claims"]]
    assert any("largest position" in c["text"] for c in claims)
    assert all(c["status"] == "supported" for c in claims)
