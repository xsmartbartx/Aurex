"""API: authentication, Markets, entitlements and license enforcement."""

import pytest
from sqlalchemy import select, update

from core.db import system_session
from modules.datalab.models import Dataset, LicenseRecord
from modules.markets import service
from tests.conftest import PASSWORD


def test_health_and_error_structure(account):
    assert account.get("/health").json()["status"] == "ok"
    missing = account.get("/markets/instruments/NOPE.NONE")
    assert missing.status_code == 404
    error = missing.json()["error"]
    assert set(error) == {"code", "message", "details", "request_id"} and error["code"] == "not_found"
    invalid = account.post("/markets/watchlists", {"name": "", "unknown": 1})
    assert invalid.status_code == 422 and invalid.json()["error"]["code"] == "validation_failed"


def test_authentication_flow(make_account):
    from fastapi.testclient import TestClient

    from interface.api.main import app

    account = make_account()
    anonymous = TestClient(app)
    assert anonymous.get("/api/v1/auth/me").status_code == 401
    assert anonymous.get("/api/v1/markets/watchlists").status_code == 401
    bad = anonymous.post("/api/v1/auth/login", json={"email": account.email, "password": "Wrong-password-1"})
    assert bad.status_code == 401 and "incorrect" in bad.json()["error"]["message"]
    unknown = anonymous.post("/api/v1/auth/login", json={"email": "nobody@example.com", "password": "x" * 12})
    assert unknown.json()["error"]["message"] == bad.json()["error"]["message"]  # no account enumeration
    assert anonymous.post("/api/v1/auth/login", json={"email": account.email, "password": PASSWORD}).status_code == 200
    assert anonymous.get("/api/v1/auth/me").json()["user"]["email"] == account.email
    anonymous.post("/api/v1/auth/logout")
    assert anonymous.get("/api/v1/auth/me").status_code == 401


def test_weak_passwords_and_duplicate_accounts_are_rejected(account):
    from fastapi.testclient import TestClient

    from interface.api.main import app

    client = TestClient(app)
    weak = client.post(
        "/api/v1/auth/signup", json={"email": "new@example.com", "password": "alllowercase", "organization": "Org"}
    )
    assert weak.status_code == 422
    duplicate = client.post(
        "/api/v1/auth/signup", json={"email": account.email, "password": PASSWORD, "organization": "Org"}
    )
    assert duplicate.status_code == 409


def test_state_changes_from_a_cookie_need_the_client_header(account):
    response = account.client.post("/api/v1/markets/watchlists", json={"name": "No header"})
    assert response.status_code == 403 and response.json()["error"]["code"] == "csrf_check_failed"


def test_search_chart_and_provenance(account):
    found = account.get("/markets/instruments", params={"q": "orca"}).json()["items"]
    assert found[0]["instrument"]["symbol"] == "ORCA.DEMO" and found[0]["quote"]["last"] > 0
    assert found[0]["quote"]["freshness_class"] == "demonstration"
    detail = account.get("/markets/instruments/ORCA.DEMO").json()
    series_id = detail["series"][0]["id"]
    chart = account.get(
        f"/markets/series/{series_id}/chart",
        params={"range": "1Y", "interval": "1W", "indicator": ["sma:10", "rsi:14"]},
    ).json()
    assert 45 <= len(chart["points"]) <= 54
    assert chart["provenance"]["license_class"] == "demonstration"
    assert "not market data" in chart["provenance"]["attribution"]
    assert chart["quality"]["demonstration"] == len(chart["points"])
    assert len(chart["indicators"][0]["lines"]["value"]) == len(chart["points"])
    assert chart["indicators"][0]["lines"]["value"][0] is not None  # warm-up history was loaded
    assert chart["summary"]["engine_version"]
    point = chart["points"][-1]
    assert point["l"] <= point["v"] <= point["h"] and point["known_at"]
    assert account.get(f"/markets/series/{series_id}/chart", params={"interval": "5m"}).status_code == 422
    assert account.get(f"/markets/series/{series_id}/chart", params={"indicator": ["os.system:1"]}).status_code == 422


def test_point_in_time_chart_excludes_later_data(account):
    chart = account.get(
        "/markets/series/DEMO:ORCA/chart", params={"range": "3M", "as_of": "2022-06-30T23:00:00Z"}
    ).json()
    assert chart["points"] and chart["points"][-1]["t"] <= "2022-06-30T23:59:59Z"
    assert all(p["known_at"] <= "2022-06-30T23:00:00Z" for p in chart["points"])


def test_watchlist_lifecycle(account):
    lists = account.get("/markets/watchlists").json()["items"]
    assert [w["name"] for w in lists] == ["My watchlist"]
    wid = lists[0]["id"]
    added = account.post(f"/markets/watchlists/{wid}/items", {"instrument": "ORCA.DEMO"}).json()
    assert added["items"][0]["quote"]["change_pct"] is not None
    assert account.post(f"/markets/watchlists/{wid}/items", {"instrument": "ORCA.DEMO"}).status_code == 409
    account.post(f"/markets/watchlists/{wid}/items", {"instrument": "HLXB.DEMO"})
    item = account.get(f"/markets/watchlists/{wid}").json()["items"][1]
    pinned = account.patch(f"/markets/watchlists/{wid}/items/{item['id']}", {"pinned": True}).json()
    assert pinned["items"][0]["instrument"]["symbol"] == "HLXB.DEMO"  # pinned instruments come first
    after = account.delete(f"/markets/watchlists/{wid}/items/{item['id']}").json()
    assert [i["instrument"]["symbol"] for i in after["items"]] == ["ORCA.DEMO"]
    assert account.delete(f"/markets/watchlists/{wid}").status_code == 204


def test_plan_limits_and_entitlements(make_account):
    community = make_account(plan="community")
    assert community.me["tenant"]["plan"] == "community"
    community.get("/markets/watchlists")
    limit = community.post("/markets/watchlists", {"name": "Second"})
    assert limit.status_code == 403 and limit.json()["error"]["details"]["limit"] == "watchlists"
    alert = community.post("/markets/alerts", {"instrument": "ORCA.DEMO", "condition": "above", "threshold": 1})
    assert alert.status_code == 403 and alert.json()["error"]["code"] == "entitlement_denied"
    assert community.post("/markets/screener", {}).status_code == 403
    assert community.get("/markets/series/DEMO:ORCA/export").status_code == 403
    assert community.post("/auth/api-keys", {"name": "ci"}).status_code == 403

    pro = make_account(plan="pro")
    assert pro.post("/markets/watchlists", {"name": "Second"}).status_code == 201
    assert pro.post("/markets/screener", {"types": ["equity"]}).status_code == 200


def test_alert_rules_fire_notifications_once_per_cooldown(make_account):
    account = make_account(plan="pro")
    created = account.post(
        "/markets/alerts", {"instrument": "ORCA.DEMO", "condition": "above", "threshold": "0.01", "note": "watch"}
    )
    assert created.status_code == 201
    rule = account.get("/markets/alerts").json()["items"][0]
    assert rule["provenance"]["license_class"] == "demonstration"
    from decimal import Decimal
    from uuid import UUID

    values = {UUID(rule["series"]["id"]): (Decimal("50"), Decimal("49"), "Orca")}
    with system_session() as session:
        assert service.evaluate_alerts(session, values) == 1
    with system_session() as session:
        assert service.evaluate_alerts(session, values) == 0  # cooldown
    inbox = account.get("/markets/notifications").json()
    assert inbox["unread"] == 1 and inbox["items"][0]["kind"] == "alert"
    assert account.post("/markets/notifications/read", {}).json()["updated"] == 1
    assert account.patch(f"/markets/alerts/{rule['id']}", {"active": False}).status_code == 200
    assert account.delete(f"/markets/alerts/{rule['id']}").status_code == 204
    assert (
        account.post(
            "/markets/alerts", {"instrument": "ORCA.DEMO", "condition": "sideways", "threshold": 1}
        ).status_code
        == 422
    )


@pytest.mark.parametrize(
    "condition,threshold,last,previous,expected",
    [
        ("above", 10, 11, 9, True),
        ("above", 10, 10, 9, False),
        ("below", 10, 9, 11, True),
        ("change_pct_above", 5, 106, 100, True),
        ("change_pct_above", 5, 104, 100, False),
        ("change_pct_below", 5, 94, 100, True),
        ("change_pct_below", 5, 96, 100, False),
        ("above", 10, None, 9, False),
        ("change_pct_above", 5, 106, None, False),
    ],
)
def test_alert_conditions(condition, threshold, last, previous, expected):
    from decimal import Decimal

    def dec(value):
        return Decimal(value) if value is not None else None

    assert service.triggered(condition, Decimal(threshold), dec(last), dec(previous)) is expected


def test_screener_and_correlations(account):
    screen = account.post(
        "/markets/screener", {"types": ["equity"], "filters": {"net_margin": {"min": 10}}, "sort": "net_margin"}
    ).json()
    margins = [row["net_margin"] for row in screen["rows"]]
    assert margins and all(m >= 10 for m in margins) and margins == sorted(margins, reverse=True)
    assert account.post("/markets/screener", {"sort": "password"}).status_code == 422
    ids = [row["instrument"]["id"] for row in screen["rows"][:3]]
    matrix = account.get("/markets/correlations", params={"instrument": ids}).json()
    assert len(matrix["matrix"]) == len(ids) and matrix["matrix"][0][0] == 1.0
    assert matrix["sources"][0]["license_class"] == "demonstration"
    assert account.get("/markets/correlations", params={"instrument": ids[:1]}).status_code == 422


def test_workspaces(account):
    listing = account.get("/markets/workspaces").json()
    assert listing["items"][0]["name"] == "Overview" and "chart" in listing["panel_types"]
    layout = {
        "preset": "columns",
        "panels": [{"type": "chart", "config": {"series": "DEMO:ORCA"}}, {"type": "watchlist", "config": {}}],
    }
    created = account.post("/markets/workspaces", {"name": "Rates", "layout": layout, "is_default": True}).json()
    assert created["is_default"] and created["layout"]["preset"] == "columns"
    saved = account.put(f"/markets/workspaces/{created['id']}", {"name": "Rates 2", "layout": layout}).json()
    assert saved["name"] == "Rates 2"
    bad = {"preset": "columns", "panels": [{"type": "iframe", "config": {}}]}
    assert account.post("/markets/workspaces", {"name": "Bad", "layout": bad}).status_code == 422
    assert account.delete(f"/markets/workspaces/{created['id']}").status_code == 204


def test_export_is_blocked_by_the_license_register(make_account):
    account = make_account(plan="quant")
    allowed = account.get("/markets/series/DEMO:ORCA/export", params={"range": "1M"})
    assert allowed.status_code == 200 and allowed.headers["content-type"].startswith("text/csv")
    assert "Demonstration data generated by AUREX" in allowed.text.splitlines()[1]
    with system_session() as session:
        license_id = session.scalar(select(Dataset.license_id).where(Dataset.code == "demo"))
        session.execute(update(LicenseRecord).where(LicenseRecord.id == license_id).values(allow_export=False))
    try:
        blocked = account.get("/markets/series/DEMO:ORCA/export")
        assert blocked.status_code == 403 and blocked.json()["error"]["code"] == "license_denied"
        assert account.get("/markets/series/DEMO:ORCA/chart").status_code == 200  # display is still allowed
    finally:
        with system_session() as session:
            session.execute(update(LicenseRecord).where(LicenseRecord.id == license_id).values(allow_export=True))


def test_api_keys_use_the_api_channel(make_account):
    from fastapi.testclient import TestClient

    from interface.api.main import app

    account = make_account(plan="quant")
    created = account.post("/auth/api-keys", {"name": "notebook"}).json()
    key = created["key"]
    assert key.startswith("aurex_") and account.get("/auth/api-keys").json()[0]["prefix"] == key[:12]
    client = TestClient(app, headers={"Authorization": f"Bearer {key}"})
    assert client.get("/api/v1/markets/series/DEMO:ORCA/chart").status_code == 200
    with system_session() as session:
        license_id = session.scalar(select(Dataset.license_id).where(Dataset.code == "demo"))
        session.execute(update(LicenseRecord).where(LicenseRecord.id == license_id).values(allow_api=False))
    try:
        denied = client.get("/api/v1/markets/series/DEMO:ORCA/chart")
        assert denied.status_code == 403 and denied.json()["error"]["details"]["channel"] == "api"
        assert account.get("/markets/series/DEMO:ORCA/chart").status_code == 200  # the terminal still displays it
    finally:
        with system_session() as session:
            session.execute(update(LicenseRecord).where(LicenseRecord.id == license_id).values(allow_api=True))
    assert account.delete(f"/auth/api-keys/{created['id']}").status_code == 204
    assert client.get("/api/v1/markets/watchlists").status_code == 401
    assert TestClient(app, headers={"Authorization": "Bearer aurex_invalid"}).get("/api/v1/auth/me").status_code == 401


def test_datalab_catalog_and_admin_only_operations(make_account):
    admin = make_account()  # not the first user of the deployment, so not a platform administrator
    datasets = {d["code"]: d for d in admin.get("/datalab/datasets").json()["items"]}
    assert datasets["demo"]["status"] == "ok" and datasets["demo"]["license"]["data_class"] == "demonstration"
    assert datasets["demo"]["counts"]["series"] == 11 and datasets["ecb-fx"]["accessible"]
    runs = admin.get("/datalab/datasets/demo/runs").json()["items"]
    assert runs[0]["status"] == "success" and runs[0]["stored"]["observations"] > 0
    assert admin.post("/datalab/datasets/demo/run").status_code == 403
    assert admin.patch("/datalab/datasets/demo", {"enabled": False}).status_code == 403
    assert {lic["code"] for lic in admin.get("/datalab/licenses").json()["items"]} >= {"aurex-demo", "sec-edgar"}
    assert admin.post("/datalab/companies/track", {"cik": "320193"}).json()["queued"] is True
    assert admin.post("/datalab/companies/track", {"cik": "320193"}).json()["queued"] is False  # deduplicated
