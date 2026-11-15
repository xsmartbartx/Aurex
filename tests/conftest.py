"""Test setup: a dedicated database, migrated and seeded once per session. No live network calls."""

import os
import uuid

TEST_URL = os.environ.get(
    "AUREX_TEST_DATABASE_URL", "postgresql+psycopg://aurex:aurex-dev-password@localhost:54329/aurex_test"
)
os.environ["AUREX_DATABASE_URL"] = TEST_URL
os.environ["AUREX_DEPLOYMENT_MODE"] = "cloud"  # new tenants start on Community, so limits are testable
os.environ["AUREX_SEC_USER_AGENT"] = ""
if os.environ.get("AUREX_EVAL_ENGINE") != "model":  # model evaluation keeps the key and is billed
    os.environ["AUREX_ANTHROPIC_API_KEY"] = ""
os.environ["AUREX_STRIPE_SECRET_KEY"] = ""
os.environ["AUREX_RATE_LIMIT_PER_MINUTE"] = "100000"

import httpx  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402

PASSWORD = "Correct-horse-9-battery"
HEADERS = {"x-aurex-client": "tests"}


def _refuse_network(request: httpx.Request) -> httpx.Response:
    raise AssertionError(f"Unexpected live call to {request.url.host}")


def recorded_ecb(request: httpx.Request) -> httpx.Response:
    """Stand-in for the ECB Data Portal: deterministic series in the portal's CSV layout."""
    import calendar
    import random
    from datetime import date, timedelta

    flow, key = request.url.path.split("/")[-2:]
    end = date.today() - timedelta(days=1)
    rows = ["KEY,FREQ,CURRENCY,TIME_PERIOD,OBS_VALUE,OBS_STATUS,TITLE"]
    if flow == "EXR":
        for currency, level in (("USD", 1.09), ("GBP", 0.85), ("CHF", 0.95)):
            rng = random.Random(currency)
            day = end - timedelta(days=760)
            while day <= end:
                if day.weekday() < 5:
                    level *= 1 + rng.gauss(0, 0.004)
                    rows.append(f"EXR.D.{currency}.EUR.SP00.A,D,{currency},{day.isoformat()},{level:.4f},A,x")
                day += timedelta(days=1)
    else:
        rng = random.Random(key)
        frequency = key.split(".")[0]
        level = {"FM": 2.5, "EST": 2.4, "YC": 2.9, "MNA": 1.1, "ICP": 2.2}.get(flow, 1.0)
        if frequency in ("D", "B"):
            day = end - timedelta(days=760)
            while day <= end:
                if day.weekday() < 5:
                    if flow != "FM":
                        level += rng.gauss(0, 0.02)
                    rows.append(f"{flow}.{key},{frequency},EUR,{day.isoformat()},{level:.4f},A,x")
                day += timedelta(days=1)
        else:
            for months_back in range(24, 0, -3 if frequency == "Q" else -1):
                year, month = divmod(end.year * 12 + end.month - 1 - months_back, 12)
                month += 1
                period = f"{year}-Q{(month - 1) // 3 + 1}" if frequency == "Q" else f"{year}-{month:02d}"
                level += rng.gauss(0, 0.1)
                rows.append(f"{flow}.{key},{frequency},EUR,{period},{level:.3f},A,x")
                _ = calendar
    return httpx.Response(200, text="\n".join(rows) + "\n")


@pytest.fixture(scope="session", autouse=True)
def database():
    url = make_url(TEST_URL)
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f'DROP DATABASE IF EXISTS "{url.database}" WITH (FORCE)'))
        connection.execute(text(f'CREATE DATABASE "{url.database}"'))
    admin.dispose()

    from modules.integration import http
    from pipelines.bootstrap import bootstrap
    from pipelines.worker import ingest_dataset

    http.set_transport(httpx.MockTransport(_refuse_network))
    bootstrap()
    assert ingest_dataset({"code": "demo"})["status"] == "success"
    http.set_transport(httpx.MockTransport(recorded_ecb))
    for code in ("ecb-fx", "ecb-rates", "ecb-macro"):
        assert ingest_dataset({"code": code})["status"] == "success", code
    from core.db import system_session
    from modules.graph import seed as graph_seed

    with system_session() as session:
        graph_seed.refresh(session)
    http.set_transport(httpx.MockTransport(_refuse_network))
    yield


@pytest.fixture(autouse=True)
def _reset_limits():
    from security.controls import rate_limiter

    rate_limiter.reset()
    yield


@pytest.fixture
def transport():
    """Install a recorded transport for one test: ``transport(handler)``."""
    from modules.integration import http

    def install(handler):
        http.set_transport(httpx.MockTransport(handler))

    yield install
    http.set_transport(httpx.MockTransport(_refuse_network))


class Account:
    def __init__(self, client: TestClient, email: str):
        self.client = client
        self.email = email
        self.me = client.get("/api/v1/auth/me").json()
        self.tenant_id = uuid.UUID(self.me["tenant"]["id"])
        self.user_id = uuid.UUID(self.me["user"]["id"])

    def get(self, path: str, **kwargs):
        return self.client.get(f"/api/v1{path}", **kwargs)

    def post(self, path: str, json=None, **kwargs):
        return self.client.post(f"/api/v1{path}", json=json, headers=HEADERS, **kwargs)

    def patch(self, path: str, json=None):
        return self.client.patch(f"/api/v1{path}", json=json, headers=HEADERS)

    def put(self, path: str, json=None):
        return self.client.put(f"/api/v1{path}", json=json, headers=HEADERS)

    def delete(self, path: str):
        return self.client.delete(f"/api/v1{path}", headers=HEADERS)

    def scope(self):
        from core.db import system_session
        from security import auth

        token = self.client.cookies.get(auth.SESSION_COOKIE)
        with system_session() as session:
            return auth.resolve_session(session, token)


@pytest.fixture
def make_account():
    from interface.api.main import app

    def make(plan: str = "enterprise", organization: str = "Test Org") -> Account:
        from core.db import system_session
        from security.models import Tenant

        client = TestClient(app)
        email = f"user-{uuid.uuid4().hex[:10]}@example.com"
        response = client.post(
            "/api/v1/auth/signup",
            json={"email": email, "password": PASSWORD, "organization": f"{organization} {uuid.uuid4().hex[:6]}"},
        )
        assert response.status_code == 201, response.text
        account = Account(client, email)
        if plan != "community":
            with system_session() as session:
                session.get(Tenant, account.tenant_id).plan = plan
            account.me = client.get("/api/v1/auth/me").json()
        return account

    return make


@pytest.fixture(scope="module")
def make_account_module():
    """Accounts shared by the tests of one module (evaluation runs)."""
    from interface.api.main import app

    def make(plan: str = "enterprise") -> Account:
        client = TestClient(app)
        email = f"eval-{uuid.uuid4().hex[:10]}@example.com"
        response = client.post(
            "/api/v1/auth/signup",
            json={"email": email, "password": PASSWORD, "organization": f"Eval {uuid.uuid4().hex[:6]}"},
        )
        assert response.status_code == 201, response.text
        account = Account(client, email)
        from core.db import system_session
        from security.models import Tenant

        with system_session() as session:
            session.get(Tenant, account.tenant_id).plan = plan
        return account

    return make


@pytest.fixture
def account(make_account) -> Account:
    return make_account()
