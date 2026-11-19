"""Organization administration, invitations, audit trail, model policy, billing webhooks, platform admin."""

import hashlib
import hmac
import json
import time
import uuid

import pytest
from fastapi.testclient import TestClient

from core.config import get_settings
from core.db import system_session
from interface.api.main import app
from security.models import Tenant
from tests.conftest import HEADERS, PASSWORD


def test_invitation_flow_roles_and_limits(make_account):
    owner = make_account(plan="business")
    response = owner.post("/org/invites", {"email": "new.analyst@example.com", "role": "analyst"})
    assert response.status_code == 201
    link = response.json()["link"]  # no SMTP in tests, so the administrator receives the link
    assert response.json()["emailed"] is False and "/invite/" in link
    token = link.rsplit("/", 1)[1]

    guest = TestClient(app)
    accepted = guest.post(
        "/api/v1/auth/invites/accept", json={"token": token, "password": PASSWORD, "display_name": "New Analyst"}
    )
    assert accepted.status_code == 200
    me = guest.get("/api/v1/auth/me").json()
    assert me["tenant"]["id"] == str(owner.tenant_id) and me["role"] == "analyst"
    assert guest.post("/api/v1/auth/invites/accept", json={"token": token, "password": PASSWORD}).status_code == 404

    members = owner.get("/org/members").json()["items"]
    analyst = next(m for m in members if m["email"] == "new.analyst@example.com")
    # An analyst cannot administer the organization.
    assert guest.post("/api/v1/org/invites", json={"email": "x@example.com"}, headers=HEADERS).status_code == 403
    assert guest.get("/api/v1/org/audit").status_code == 403
    assert owner.patch(f"/org/members/{analyst['user_id']}", {"role": "admin"}).status_code == 200
    assert owner.delete(f"/org/members/{owner.user_id}").status_code == 409  # the last owner stays
    assert owner.delete(f"/org/members/{analyst['user_id']}").status_code == 204
    assert guest.get("/api/v1/auth/me").status_code == 401  # the removed member's session ends

    pro = make_account(plan="pro")
    assert pro.post("/org/invites", {"email": "a@example.com"}).status_code == 403  # plan without members


def test_audit_trail_viewer(make_account):
    owner = make_account(plan="business")
    owner.post("/markets/watchlists", {"name": "Audited"})
    items = owner.get("/org/audit", params={"action": "watchlist."}).json()["items"]
    assert items and items[0]["action"].startswith("watchlist.") and items[0]["actor"] == owner.email
    assert make_account(plan="pro").get("/org/audit").status_code == 403


def test_model_policy_is_owner_controlled(make_account):
    owner = make_account(plan="business")
    assert owner.get("/org").json()["model_policy"]["external_models"] == "allow"
    assert owner.patch("/org", {"external_models": "deny"}).status_code == 200
    from security import auth

    with system_session() as session:
        assert auth.external_models_allowed(session, owner.tenant_id) is False


def _signed(payload: dict, secret: str) -> tuple[bytes, str]:
    body = json.dumps(payload).encode()
    stamp = int(time.time())
    signature = hmac.new(secret.encode(), f"{stamp}.".encode() + body, hashlib.sha256).hexdigest()
    return body, f"t={stamp},v1={signature}"


@pytest.fixture
def billing(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_dummy")
    monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_test_secret")
    monkeypatch.setattr(settings, "stripe_prices", {"pro": "price_pro", "quant": "price_quant"})
    # Start from the defaults whatever the local .env sets, so "not configured" assertions hold everywhere.
    monkeypatch.setattr(settings, "stripe_portal_configuration", "")
    monkeypatch.setattr(settings, "stripe_automatic_tax", False)
    return settings


def test_subscription_webhooks_change_the_plan_once(make_account, billing):
    account = make_account(plan="community")
    with system_session() as session:
        session.get(Tenant, account.tenant_id).stripe_customer_id = "cus_test_1"
    client = TestClient(app)

    def send(event):
        body, signature = _signed(event, "whsec_test_secret")
        return client.post("/api/v1/billing/webhook", content=body, headers={"stripe-signature": signature})

    event = {
        "id": f"evt_{uuid.uuid4().hex}",
        "type": "customer.subscription.updated",
        "created": int(time.time()),
        "data": {
            "object": {
                "id": "sub_1",
                "customer": "cus_test_1",
                "status": "active",
                "items": {"data": [{"price": {"id": "price_quant"}}]},
            }
        },
    }
    assert send(event).json()["status"] == "plan:quant"
    assert account.get("/auth/me").json()["tenant"]["plan"] == "quant"
    assert send(event).json()["status"] == "duplicate"
    cancelled = {
        **event,
        "id": f"evt_{uuid.uuid4().hex}",
        "type": "customer.subscription.deleted",
        "data": {"object": {**event["data"]["object"], "status": "canceled"}},
    }
    assert send(cancelled).json()["status"] == "plan:community"

    body, _ = _signed(event, "wrong_secret")
    forged = client.post("/api/v1/billing/webhook", content=body, headers={"stripe-signature": "t=1,v1=00"})
    assert forged.status_code == 422 and forged.json()["error"]["code"] == "invalid_signature"


def test_checkouts_of_other_products_on_a_shared_stripe_account_are_ignored(make_account, billing):
    account = make_account(plan="community")
    client = TestClient(app)

    def checkout_completed(metadata, reference):
        event = {
            "id": f"evt_{uuid.uuid4().hex}",
            "type": "checkout.session.completed",
            "created": int(time.time()),
            "data": {
                "object": {
                    "client_reference_id": reference,
                    "customer": "cus_shared_1",
                    "subscription": "sub_shared_1",
                    "metadata": metadata,
                }
            },
        }
        body, signature = _signed(event, "whsec_test_secret")
        return client.post("/api/v1/billing/webhook", content=body, headers={"stripe-signature": signature})

    # Another product's checkout: no AUREX mark and a reference that is not one of AUREX's organizations.
    foreign = checkout_completed({"plan": "team"}, "org_2xYz")
    assert foreign.status_code == 200 and foreign.json()["status"] == "ignored"
    assert checkout_completed({"app": "aurex"}, "not-a-uuid").json()["status"] == "unknown_tenant"

    assert checkout_completed({"app": "aurex", "plan": "pro"}, str(account.tenant_id)).json()["status"] == "linked"
    with system_session() as session:
        tenant = session.get(Tenant, account.tenant_id)
        assert (tenant.stripe_customer_id, tenant.stripe_subscription_id) == ("cus_shared_1", "sub_shared_1")


def test_stripe_requests_carry_the_aurex_mark_and_portal_configuration(monkeypatch, billing):
    from types import SimpleNamespace

    from modules.integration import payments

    calls = {}

    def recorder(name, result):
        def create(params):
            calls[name] = params
            return result

        return SimpleNamespace(create=create)

    fake = SimpleNamespace(
        v1=SimpleNamespace(
            customers=recorder("customer", SimpleNamespace(id="cus_1")),
            checkout=SimpleNamespace(sessions=recorder("checkout", SimpleNamespace(url="https://checkout.example"))),
            billing_portal=SimpleNamespace(sessions=recorder("portal", SimpleNamespace(url="https://portal.example"))),
        )
    )
    monkeypatch.setattr(payments, "_client", lambda: fake)

    payments.create_customer(name="Org", email="o@example.com", tenant_id="t1")
    payments.checkout_url(
        customer_id="cus_1", price_id="price_pro", tenant_id="t1", plan="pro", success_url="s", cancel_url="c"
    )
    assert calls["customer"]["metadata"]["app"] == "aurex"
    assert calls["checkout"]["metadata"]["app"] == calls["checkout"]["subscription_data"]["metadata"]["app"] == "aurex"
    assert "automatic_tax" not in calls["checkout"]  # off until Stripe Tax is active on the account

    monkeypatch.setattr(billing, "stripe_automatic_tax", True)
    payments.checkout_url(
        customer_id="cus_1", price_id="price_pro", tenant_id="t1", plan="pro", success_url="s", cancel_url="c"
    )
    taxed = calls["checkout"]
    assert taxed["automatic_tax"] == {"enabled": True} and taxed["tax_id_collection"] == {"enabled": True}
    assert taxed["billing_address_collection"] == "required" and taxed["customer_update"]["address"] == "auto"

    payments.portal_url(customer_id="cus_1", return_url="r")
    assert "configuration" not in calls["portal"]  # the account default, when none is configured
    monkeypatch.setattr(billing, "stripe_portal_configuration", "bpc_aurex")
    payments.portal_url(customer_id="cus_1", return_url="r")
    assert calls["portal"]["configuration"] == "bpc_aurex"


def test_plan_catalog_and_checkout_guards(make_account, billing):
    plans = TestClient(app).get("/api/v1/billing/plans").json()
    assert [p["code"] for p in plans["items"]] == ["community", "pro", "quant", "business", "enterprise"]
    assert next(p for p in plans["items"] if p["code"] == "pro")["self_serve"] is True
    # A price id alone does not make a plan buyable: without a Stripe key the checkout would fail.
    billing.stripe_secret_key = ""
    plans = TestClient(app).get("/api/v1/billing/plans").json()
    assert not any(p["self_serve"] for p in plans["items"]) and plans["billing_enabled"] is False
    member = make_account(plan="community")
    assert member.post("/billing/checkout", {"plan": "enterprise"}).status_code == 422


def test_platform_administration_is_restricted(make_account):
    tenant = make_account(plan="pro")
    assert tenant.get("/admin/tenants").status_code == 403
    with system_session() as session:
        from security.models import User

        session.get(User, tenant.user_id).is_platform_admin = True
    listing = tenant.get("/admin/tenants").json()["items"]
    other = next(t for t in listing if t["id"] != str(tenant.tenant_id))
    assert tenant.patch(f"/admin/tenants/{other['id']}", {"plan": "business"}).status_code == 200
    assert tenant.patch(f"/admin/tenants/{tenant.tenant_id}", {"status": "suspended"}).status_code == 422


def test_configured_admin_email_decides_platform_rights(make_account, monkeypatch):
    """With admin emails configured, being first gives no rights and the listed email always gets them."""
    from fastapi.testclient import TestClient

    from interface.api.main import app

    monkeypatch.setattr(get_settings(), "platform_admin_emails", ["Chief.Admin@Example.com"])
    stranger = make_account()
    assert stranger.me["user"]["platform_admin"] is False
    admin = TestClient(app)
    response = admin.post(
        "/api/v1/auth/signup",
        json={"email": "chief.admin@example.com", "password": PASSWORD, "organization": f"Ops {uuid.uuid4().hex[:6]}"},
    )
    assert response.status_code == 201
    assert admin.get("/api/v1/auth/me").json()["user"]["platform_admin"] is True

    from pipelines.bootstrap import sync_platform_admins
    from security.models import User

    monkeypatch.setattr(get_settings(), "platform_admin_emails", [stranger.email])
    with system_session() as session:
        assert sync_platform_admins(session) == 1
        assert session.get(User, stranger.user_id).is_platform_admin is True


@pytest.mark.parametrize(
    ("environment", "allow_signup", "admins", "email", "first_user", "expected"),
    [
        # Outside production the first account founds the deployment, even with sign-up closed.
        ("development", False, [], "a@example.com", True, (True, True)),
        ("development", False, [], "a@example.com", False, (False, False)),
        ("development", True, [], "a@example.com", False, (True, False)),
        # In production being first gives nothing: closed stays closed and nobody becomes administrator.
        ("production", False, [], "a@example.com", True, (False, False)),
        ("production", True, [], "a@example.com", True, (True, False)),
        # A configured admin email may always sign up and administers; anyone else follows allow_signup.
        ("production", False, ["Ops@Example.com"], "ops@example.com", True, (True, True)),
        ("production", False, ["ops@example.com"], "a@example.com", True, (False, False)),
        ("production", True, ["ops@example.com"], "a@example.com", True, (True, False)),
    ],
)
def test_who_may_sign_up_and_who_administers(environment, allow_signup, admins, email, first_user, expected):
    from core.config import Settings
    from security.auth import sign_up_rights

    settings = Settings(environment=environment, allow_signup=allow_signup, platform_admin_emails=admins)
    assert sign_up_rights(settings, email, first_user=first_user) == expected


def test_client_ip_header_is_used_only_when_configured(monkeypatch):
    from starlette.requests import Request

    from interface.api.deps import client_ip

    request = Request({"type": "http", "headers": [(b"cf-connecting-ip", b"203.0.113.9")], "client": ("10.0.0.1", 1)})
    assert client_ip(request) == "10.0.0.1"
    monkeypatch.setattr(get_settings(), "client_ip_header", "CF-Connecting-IP")
    assert client_ip(request) == "203.0.113.9"
