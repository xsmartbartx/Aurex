"""Data subject rights: personal and organization export, and account deletion with its safeguards."""

import json

from fastapi.testclient import TestClient
from sqlalchemy import func, select, text

from core.config import get_settings
from core.db import system_session, tenant_tables
from interface.api.main import app
from security.models import Membership, Tenant, User
from tests.conftest import PASSWORD


def _join(owner, member, role: str = "analyst") -> None:
    """Add ``member`` to ``owner``'s organization and switch the member's session to it."""
    with system_session() as session:
        session.add(Membership(user_id=member.user_id, tenant_id=owner.tenant_id, role=role))
    assert member.post("/auth/switch-tenant", {"tenant_id": str(owner.tenant_id)}).status_code == 200


def _rows_left(tenant_id) -> dict[str, int]:
    with system_session() as session:
        counts = {
            name: session.scalar(text(f"SELECT count(*) FROM {name} WHERE tenant_id = :t"), {"t": tenant_id})  # noqa: S608
            for name in tenant_tables()
        }
    return {name: count for name, count in counts.items() if count}


def test_personal_export_has_the_account_and_no_credentials(make_account):
    account = make_account()
    account.post("/auth/api-keys", {"name": "Notebook"})
    response = account.get("/auth/me/export")
    assert response.status_code == 200
    assert response.headers["content-disposition"].startswith('attachment; filename="aurex-my-data-')
    assert response.headers["cache-control"] == "no-store"
    data = response.json()
    assert data["account"]["email"] == account.email and "password_hash" not in data["account"]
    assert [m["organization_id"] for m in data["memberships"]] == [str(account.tenant_id)]
    assert data["api_keys"][0]["name"] == "Notebook" and data["sign_ins"] and data["activity"]
    body = response.text
    assert all(secret not in body for secret in ("password_hash", "token_hash", "key_hash", "$argon2"))


def test_organization_export_is_for_owners_and_holds_every_private_row(make_account):
    owner, member = make_account(), make_account()
    owner.post("/markets/watchlists", {"name": "Exported list"})
    owner.post("/org/invites", {"email": "someone@example.com", "role": "viewer"})
    _join(owner, member)
    assert member.get("/org/export").status_code == 403

    response = owner.get("/org/export")
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    data = response.json()
    assert data["organization"]["id"] == str(owner.tenant_id)
    assert {m["email"] for m in data["members"]} == {owner.email, member.email}
    tables = data["tables"]
    assert [w["name"] for w in tables["watchlists"]] == ["Exported list"]
    assert tables["invites"][0]["email"] == "someone@example.com" and "token_hash" not in tables["invites"][0]
    assert "user_sessions" not in tables and "audit_events" in tables
    assert all(row.get("tenant_id") == str(owner.tenant_id) for rows in tables.values() for row in rows)
    assert "token_hash" not in json.dumps(data)


def test_deleting_an_account_closes_the_organization_it_owns_alone(make_account):
    account = make_account()
    account.post("/markets/watchlists", {"name": "Goes away"})
    account.post("/auth/api-keys", {"name": "Goes too"})
    assert account.post("/auth/me/delete", {"password": "wrong-password-1A"}).status_code == 401
    assert "watchlists" in _rows_left(account.tenant_id)

    response = account.post("/auth/me/delete", {"password": PASSWORD})
    assert response.status_code == 200
    assert response.json()["status"] == "deleted" and len(response.json()["organizations_closed"]) == 1
    assert "aurex_session" in response.headers.get("set-cookie", "")

    assert _rows_left(account.tenant_id) == {"audit_events": _rows_left(account.tenant_id)["audit_events"]}
    with system_session() as session:
        assert session.get(Tenant, account.tenant_id) is None and session.get(User, account.user_id) is None
        actions = set(
            session.scalars(text("SELECT action FROM audit_events WHERE actor_id = :u"), {"u": account.user_id})
        )
    assert {"org.closed", "auth.account_deleted"} <= actions  # the audit trail outlives the account
    login = TestClient(app).post("/api/v1/auth/login", json={"email": account.email, "password": PASSWORD})
    assert login.status_code == 401


def test_a_member_leaving_keeps_the_organization_and_an_owner_cannot_orphan_it(make_account):
    owner, member = make_account(), make_account()
    owner.post("/markets/watchlists", {"name": "Team list"})
    _join(owner, member)

    refused = owner.post("/auth/me/delete", {"password": PASSWORD})
    assert refused.status_code == 409 and "only owner" in refused.json()["error"]["message"]
    with system_session() as session:
        assert session.get(User, owner.user_id) is not None

    own_organization = member.me["tenant"]["name"]  # recorded at sign-up, before the switch
    left = member.post("/auth/me/delete", {"password": PASSWORD})
    assert left.status_code == 200 and left.json()["organizations_closed"] == [own_organization]
    with system_session() as session:
        assert session.get(Tenant, owner.tenant_id) is not None
        assert session.get(Membership, (member.user_id, owner.tenant_id)) is None
        assert session.get(Tenant, member.tenant_id) is None  # the member's own one-person organization closed
    assert "watchlists" in _rows_left(owner.tenant_id) and owner.get("/auth/me").status_code == 200


def test_paying_organizations_and_the_deployment_administrator_are_protected(make_account, monkeypatch):
    payer = make_account()
    with system_session() as session:
        tenant = session.get(Tenant, payer.tenant_id)
        tenant.plan, tenant.stripe_subscription_id = "pro", "sub_test_active"
    refused = payer.post("/auth/me/delete", {"password": PASSWORD})
    assert refused.status_code == 409 and "subscription" in refused.json()["error"]["message"]

    admin = make_account()
    monkeypatch.setattr(get_settings(), "platform_admin_emails", [admin.email])
    assert admin.post("/auth/me/delete", {"password": PASSWORD}).status_code == 403
    with system_session() as session:
        assert (
            session.scalar(select(func.count()).select_from(User).where(User.id.in_([payer.user_id, admin.user_id])))
            == 2
        )
