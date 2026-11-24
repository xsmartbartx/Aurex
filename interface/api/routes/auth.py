"""Sign-up, sign-in, sessions and API keys."""

from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Request, Response
from pydantic import EmailStr, Field
from sqlalchemy import select

from core.config import get_settings
from core.db import system_session
from core.errors import Unauthenticated
from interface.api.deps import AdminDep, DbDep, ScopeDep, client_ip
from modules.integration import mail
from modules.logging import record_audit
from modules.validation import Strict
from security import auth
from security.controls import rate_limiter, usage_today
from security.models import ApiKey, Membership, Tenant, User
from security.plans import get_plan

router = APIRouter(prefix="/auth", tags=["auth"])


class SignUp(Strict):
    email: EmailStr
    password: str = Field(min_length=10, max_length=200)
    display_name: str = Field(default="", max_length=120)
    organization: str = Field(min_length=2, max_length=120)


class SignIn(Strict):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


class PasswordChange(Strict):
    current: str = Field(min_length=1, max_length=200)
    new: str = Field(min_length=10, max_length=200)


class InviteAccept(Strict):
    token: str = Field(min_length=20, max_length=100)
    password: str = Field(min_length=1, max_length=200)
    display_name: str = Field(default="", max_length=120)


class PasswordForgot(Strict):
    email: EmailStr


class PasswordResetIn(Strict):
    token: str = Field(min_length=20, max_length=100)
    password: str = Field(min_length=10, max_length=200)


class ResetIssue(Strict):
    email: EmailStr


class KeyCreate(Strict):
    name: str = Field(min_length=1, max_length=80)


class TenantSwitch(Strict):
    tenant_id: UUID


def _set_cookie(response: Response, token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        auth.SESSION_COOKIE,
        token,
        max_age=settings.session_ttl_hours * 3600,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


@router.post("/signup", status_code=201)
def sign_up(body: SignUp, request: Request, response: Response) -> dict:
    rate_limiter.check(f"signup:{client_ip(request)}", 10, 3600)
    with system_session() as session:
        token = auth.sign_up(
            session,
            email=body.email,
            password=body.password,
            display_name=body.display_name,
            organization=body.organization,
        )
    _set_cookie(response, token)
    return {"status": "created"}


@router.post("/login")
def sign_in(body: SignIn, request: Request, response: Response) -> dict:
    rate_limiter.check(f"login:{client_ip(request)}", 20, 300)
    rate_limiter.check(f"login:{body.email.lower()}", 8, 300)
    try:
        with system_session() as session:
            token = auth.sign_in(session, email=body.email, password=body.password)
    except Unauthenticated:
        with system_session() as session:
            record_audit(session, action="auth.sign_in", outcome="denied")
        raise
    _set_cookie(response, token)
    return {"status": "ok"}


@router.post("/logout")
def sign_out(request: Request, response: Response) -> dict:
    token = request.cookies.get(auth.SESSION_COOKIE)
    if token:
        with system_session() as session:
            auth.sign_out(session, token)
    response.delete_cookie(auth.SESSION_COOKIE, path="/")
    return {"status": "ok"}


def _reset_link(token: str) -> str:
    return f"{get_settings().public_url}/reset-password/{token}"


def _send_reset_email(to: str, link: str) -> bool:
    return mail.send(
        to=to,
        subject="Reset your AUREX password",
        body="Someone asked to reset the password of your AUREX account.\n\n"
        f"Set a new password within the hour: {link}\n\n"
        "The link works once. If you did not ask for it, ignore this message: your password stays as it is.\n",
    )


@router.post("/password/forgot", status_code=202)
def forgot_password(body: PasswordForgot, request: Request, background: BackgroundTasks) -> dict:
    """Email a reset link. The answer is the same whether or not an account uses the address."""
    rate_limiter.check(f"reset:{client_ip(request)}", 10, 900)
    rate_limiter.check(f"reset:{body.email.lower()}", 3, 900)
    email_enabled = mail.configured()
    if email_enabled:
        with system_session() as session:
            issued = auth.request_password_reset(session, email=body.email)
        if issued:
            user, token = issued
            # Sent after the response, so the reply takes as long whether or not the account exists.
            background.add_task(_send_reset_email, user.email, _reset_link(token))
    # Without email the deployment administrator issues reset links (POST /auth/admin/password-reset).
    return {"status": "accepted", "email_enabled": email_enabled}


@router.post("/password/reset")
def reset_password(body: PasswordResetIn, request: Request) -> dict:
    rate_limiter.check(f"reset-use:{client_ip(request)}", 20, 900)
    with system_session() as session:
        auth.reset_password(session, token=body.token, password=body.password)
    return {"status": "password_reset"}


@router.post("/admin/password-reset", status_code=201)
def issue_password_reset(body: ResetIssue, scope: AdminDep) -> dict:
    """The deployment administrator issues a reset link for an account."""
    with system_session() as session:
        user, token, expires_at = auth.issue_password_reset(session, scope, email=body.email)
        email = user.email
    link = _reset_link(token)
    sent = _send_reset_email(email, link)
    # The link is a credential; it is shown to the administrator only when it could not be emailed.
    return {"emailed": sent, "link": None if sent else link, "expires_at": expires_at}


@router.post("/invites/accept")
def accept_invite(body: InviteAccept, request: Request, response: Response) -> dict:
    rate_limiter.check(f"invite:{client_ip(request)}", 20, 300)
    with system_session() as session:
        token = auth.accept_invite(session, token=body.token, password=body.password, display_name=body.display_name)
    _set_cookie(response, token)
    return {"status": "ok"}


@router.get("/me")
def me(scope: ScopeDep) -> dict:
    settings = get_settings()
    with system_session() as session:
        user = session.get(User, scope.user_id)
        tenant = session.get(Tenant, scope.tenant_id)
        memberships = session.execute(
            select(Tenant.id, Tenant.name, Membership.role)
            .join(Membership, Membership.tenant_id == Tenant.id)
            .where(Membership.user_id == scope.user_id)
            .order_by(Tenant.name)
        ).all()
        usage = usage_today(session, scope.tenant_id)
    plan = get_plan(scope.plan)
    return {
        "user": {
            "id": user.id,
            "email": user.email,
            "display_name": user.display_name,
            "platform_admin": user.is_platform_admin,
        },
        "tenant": {
            "id": tenant.id,
            "name": tenant.name,
            "slug": tenant.slug,
            "plan": plan.code,
            "plan_name": plan.name,
            "status": tenant.status,
        },
        "role": scope.role.value,
        "entitlements": sorted(scope.entitlements),
        "limits": scope.limits,
        "usage_today": usage,
        "memberships": [{"tenant_id": m.id, "name": m.name, "role": m.role} for m in memberships],
        "deployment": {
            "mode": settings.deployment_mode,
            "billing_enabled": settings.billing_enabled,
            "ai_engine": "anthropic" if settings.anthropic_api_key else "offline",
            "ai_model": settings.ai_model if settings.anthropic_api_key else "aurex-offline-1",
        },
    }


@router.post("/password")
def change_password(body: PasswordChange, scope: ScopeDep, response: Response) -> dict:
    with system_session() as session:
        auth.change_password(session, scope, current=body.current, new=body.new)
    response.delete_cookie(auth.SESSION_COOKIE, path="/")
    return {"status": "ok", "detail": "Password changed. Sign in again."}


@router.post("/switch-tenant")
def switch_tenant(body: TenantSwitch, request: Request, scope: ScopeDep) -> dict:
    token = request.cookies.get(auth.SESSION_COOKIE)
    if not token:
        raise Unauthenticated("Switching organizations needs a browser session")
    with system_session() as session:
        auth.switch_tenant(session, token, body.tenant_id)
    return {"status": "ok"}


@router.get("/api-keys")
def list_keys(scope: ScopeDep, db: DbDep) -> list[dict]:
    rows = db.scalars(
        select(ApiKey)
        .where(ApiKey.tenant_id == scope.tenant_id, ApiKey.revoked_at.is_(None))
        .order_by(ApiKey.created_at.desc())
    )
    return [
        {
            "id": k.id,
            "name": k.name,
            "prefix": k.prefix,
            "created_at": k.created_at,
            "last_used_at": k.last_used_at,
            "own": k.user_id == scope.user_id,
        }
        for k in rows
    ]


@router.post("/api-keys", status_code=201)
def create_key(body: KeyCreate, scope: ScopeDep) -> dict:
    with system_session() as session:
        row, secret = auth.create_api_key(session, scope, body.name)
        return {
            "id": row.id,
            "name": row.name,
            "prefix": row.prefix,
            "key": secret,
            "detail": "Store this key now. It is not shown again.",
        }


@router.delete("/api-keys/{key_id}", status_code=204)
def revoke_key(key_id: UUID, scope: ScopeDep) -> None:
    with system_session() as session:
        auth.revoke_api_key(session, scope, key_id)
