"""Password reset: emailed or administrator-issued links that work once, expire, and end every session."""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from core.db import system_session, tenant_session
from core.types import utcnow
from interface.api.main import app
from modules.integration import mail
from security.models import PasswordReset, User
from tests.conftest import PASSWORD

NEW_PASSWORD = "Fresh-start-2026!"


@pytest.fixture
def outbox(monkeypatch):
    """Email that would have been sent, with delivery switched on."""
    sent: list[dict] = []
    monkeypatch.setattr(mail, "configured", lambda: True)
    monkeypatch.setattr(mail, "send", lambda **message: sent.append(message) or True)
    return sent


def _token(link: str) -> str:
    return link.rstrip("/").rsplit("/", 1)[1]


def _link_in(message: dict) -> str:
    return next(word for word in message["body"].split() if "/reset-password/" in word)


def _login(email: str, password: str) -> int:
    return TestClient(app).post("/api/v1/auth/login", json={"email": email, "password": password}).status_code


def test_forgot_password_emails_a_link_that_works_once_and_ends_sessions(make_account, outbox):
    account = make_account()
    guest = TestClient(app)
    answer = guest.post("/api/v1/auth/password/forgot", json={"email": account.email.upper()})
    assert answer.status_code == 202 and answer.json() == {"status": "accepted", "email_enabled": True}
    assert len(outbox) == 1 and outbox[0]["to"] == account.email
    token = _token(_link_in(outbox[0]))

    weak = guest.post("/api/v1/auth/password/reset", json={"token": token, "password": "alllowercase1"})
    assert weak.status_code == 422  # a weak password leaves the link usable
    done = guest.post("/api/v1/auth/password/reset", json={"token": token, "password": NEW_PASSWORD})
    assert done.status_code == 200 and done.json() == {"status": "password_reset"}

    assert account.get("/auth/me").status_code == 401  # the session that was signed in has ended
    assert _login(account.email, PASSWORD) == 401 and _login(account.email, NEW_PASSWORD) == 200
    again = guest.post("/api/v1/auth/password/reset", json={"token": token, "password": "Another-one-77"})
    assert again.status_code == 404  # single use


def test_unknown_and_deactivated_accounts_get_the_same_answer_and_no_email(make_account, outbox):
    account = make_account()
    with system_session() as session:
        session.get(User, account.user_id).is_active = False
    guest = TestClient(app)
    for email in ("nobody-here@example.com", account.email):
        answer = guest.post("/api/v1/auth/password/forgot", json={"email": email})
        assert answer.status_code == 202 and answer.json() == {"status": "accepted", "email_enabled": True}
    assert outbox == []


def test_without_email_no_link_is_created(make_account, monkeypatch):
    monkeypatch.setattr(mail, "configured", lambda: False)
    account = make_account()
    answer = TestClient(app).post("/api/v1/auth/password/forgot", json={"email": account.email})
    assert answer.json() == {"status": "accepted", "email_enabled": False}
    with system_session() as session:
        assert session.scalar(select(PasswordReset).where(PasswordReset.user_id == account.user_id)) is None


def test_only_the_newest_link_works_and_links_expire(make_account, outbox):
    account = make_account()
    guest = TestClient(app)
    guest.post("/api/v1/auth/password/forgot", json={"email": account.email})
    guest.post("/api/v1/auth/password/forgot", json={"email": account.email})
    first, second = (_token(_link_in(message)) for message in outbox)
    assert guest.post("/api/v1/auth/password/reset", json={"token": first, "password": NEW_PASSWORD}).status_code == 404

    with system_session() as session:
        for row in session.scalars(select(PasswordReset).where(PasswordReset.user_id == account.user_id)):
            row.expires_at = utcnow() - timedelta(seconds=1)
    assert (
        guest.post("/api/v1/auth/password/reset", json={"token": second, "password": NEW_PASSWORD}).status_code == 404
    )
    assert _login(account.email, PASSWORD) == 200


def test_requests_are_rate_limited_per_address(make_account, outbox):
    account = make_account()
    guest = TestClient(app)
    codes = [guest.post("/api/v1/auth/password/forgot", json={"email": account.email}).status_code for _ in range(4)]
    assert codes == [202, 202, 202, 429]


def test_platform_administrator_issues_a_link_when_email_is_off(make_account, monkeypatch):
    monkeypatch.setattr(mail, "configured", lambda: False)
    monkeypatch.setattr(mail, "send", lambda **message: False)
    admin, member = make_account(), make_account()
    with system_session() as session:
        session.get(User, admin.user_id).is_platform_admin = True

    assert member.post("/auth/admin/password-reset", {"email": admin.email}).status_code == 403
    assert admin.post("/auth/admin/password-reset", {"email": "nobody-here@example.com"}).status_code == 404
    issued = admin.post("/auth/admin/password-reset", {"email": member.email})
    assert issued.status_code == 201 and issued.json()["emailed"] is False
    link = issued.json()["link"]
    assert "/reset-password/" in link and issued.json()["expires_at"]

    reset = TestClient(app).post("/api/v1/auth/password/reset", json={"token": _token(link), "password": NEW_PASSWORD})
    assert reset.status_code == 200 and _login(member.email, NEW_PASSWORD) == 200
    with system_session() as session:
        row = session.scalar(select(PasswordReset).where(PasswordReset.user_id == member.user_id))
        assert row.requested_by == admin.user_id and row.used_at is not None
        actions = session.scalars(
            text("SELECT action FROM audit_events WHERE object_id = :u ORDER BY 1"), {"u": str(member.user_id)}
        ).all()
    assert "platform.password_reset_issued" in actions and "auth.password_reset" in actions


def test_reset_links_are_invisible_to_tenant_sessions(make_account, outbox):
    account = make_account()
    TestClient(app).post("/api/v1/auth/password/forgot", json={"email": account.email})
    with tenant_session(account.tenant_id) as session:
        assert session.scalars(select(PasswordReset)).all() == []
    with system_session() as session:
        assert session.scalars(select(PasswordReset).where(PasswordReset.user_id == account.user_id)).all()
