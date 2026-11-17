"""Tenant isolation: cross-tenant reads and writes must fail through the API and in the database."""

import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from core.db import system_session, tenant_session, tenant_tables
from modules.logging.audit import AuditEvent
from modules.markets.models import Watchlist
from security.models import User


@pytest.fixture
def two_tenants(make_account):
    a, b = make_account(), make_account()
    a_list = a.post("/markets/watchlists", {"name": "Alpha private"}).json()
    b_list = b.post("/markets/watchlists", {"name": "Beta private"}).json()
    return a, b, a_list["id"], b_list["id"]


def test_api_never_returns_another_tenants_objects(two_tenants):
    a, b, a_list, b_list = two_tenants
    assert a.get(f"/markets/watchlists/{b_list}").status_code == 404
    assert a.post(f"/markets/watchlists/{b_list}/items", {"instrument": "ORCA.DEMO"}).status_code == 404
    assert a.patch(f"/markets/watchlists/{b_list}", {"name": "taken"}).status_code == 404
    assert a.delete(f"/markets/watchlists/{b_list}").status_code == 404
    names = [w["name"] for w in a.get("/markets/watchlists").json()["items"]]
    assert "Beta private" not in names and "Alpha private" in names
    assert b.get(f"/markets/watchlists/{b_list}").json()["name"] == "Beta private"


def test_row_level_security_hides_rows_even_without_a_filter(two_tenants):
    a, b, a_list, b_list = two_tenants
    with tenant_session(a.tenant_id) as session:
        seen = session.scalars(select(Watchlist.name)).all()  # deliberately unfiltered
        assert "Alpha private" in seen and "Beta private" not in seen
        assert session.get(Watchlist, uuid.UUID(b_list)) is None
        assert session.execute(text("UPDATE watchlists SET name = 'x' WHERE id = :i"), {"i": b_list}).rowcount == 0
        assert session.execute(text("DELETE FROM watchlists WHERE id = :i"), {"i": b_list}).rowcount == 0
        emails = session.scalars(select(User.email)).all()
        assert emails == [a.email]  # other tenants' users are invisible
    with tenant_session(None) as session:  # no tenant bound: nothing private is visible
        assert session.scalars(select(Watchlist.name)).all() == []


def test_row_level_security_rejects_writes_for_another_tenant(two_tenants):
    a, b, *_ = two_tenants
    with pytest.raises(DBAPIError), tenant_session(a.tenant_id) as session:
        session.execute(
            text(
                "INSERT INTO watchlists (id, tenant_id, user_id, name, shared) "
                "VALUES (gen_random_uuid(), :t, :u, 'planted', false)"
            ),
            {"t": b.tenant_id, "u": b.user_id},
        )
    with tenant_session(a.tenant_id) as session:  # another tenant's row is not visible, so nothing changes
        assert (
            session.execute(text("UPDATE tenants SET status = 'suspended' WHERE id = :t"), {"t": b.tenant_id}).rowcount
            == 0
        )
    assert b.get("/auth/me").status_code == 200
    with pytest.raises(DBAPIError), tenant_session(a.tenant_id) as session:
        # Shared reference data cannot be written from a tenant session.
        session.execute(text("UPDATE license_records SET allow_export = true"))


def test_every_tenant_table_has_a_policy():
    with system_session() as session:
        protected = set(
            session.scalars(text("SELECT tablename FROM pg_policies WHERE policyname = 'tenant_isolation'"))
        )
        enabled = set(
            session.scalars(
                text("SELECT relname FROM pg_class WHERE relrowsecurity AND relnamespace = 'public'::regnamespace")
            )
        )
    expected = set(tenant_tables()) | {"tenants", "users"}
    assert expected <= protected and expected <= enabled


def test_audit_trail_is_append_only_and_tenant_scoped(two_tenants):
    a, b, *_ = two_tenants
    with tenant_session(a.tenant_id) as session:
        actions = session.scalars(select(AuditEvent.action)).all()
        tenants = set(session.scalars(select(AuditEvent.tenant_id)))
    assert "watchlist.created" in actions and "auth.sign_up" in actions
    assert tenants == {a.tenant_id}
    with pytest.raises(DBAPIError), tenant_session(a.tenant_id) as session:
        session.execute(text("DELETE FROM audit_events"))
    with pytest.raises(DBAPIError), system_session() as session:  # even the owner cannot rewrite history
        session.execute(text("UPDATE audit_events SET outcome = 'tampered'"))


def test_sign_in_and_administration_are_audited(make_account):
    account = make_account()
    account.client.post("/api/v1/auth/login", json={"email": account.email, "password": "wrong-password-1A"})
    account.post("/auth/logout")
    with system_session() as session:
        rows = session.execute(
            select(AuditEvent.action, AuditEvent.outcome).where(AuditEvent.tenant_id == account.tenant_id)
        ).all()
        denied = session.scalar(
            select(AuditEvent.id).where(AuditEvent.action == "auth.sign_in", AuditEvent.outcome == "denied").limit(1)
        )
    assert ("auth.sign_up", "success") in rows and ("auth.sign_out", "success") in rows
    assert denied is not None
