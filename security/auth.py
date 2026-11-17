"""Identity, sessions and scope resolution. Only this layer decides access (section 4.4, rule 5)."""

import hashlib
import re
import secrets
from datetime import timedelta
from uuid import UUID

from argon2 import PasswordHasher
from argon2.exceptions import Argon2Error, InvalidHashError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.config import get_settings
from core.errors import Conflict, EntitlementDenied, Forbidden, NotFound, Unauthenticated, ValidationFailure  # noqa: F401
from core.types import Role, Scope, utcnow
from modules.logging import record_audit
from security.models import ApiKey, Invite, Membership, Tenant, User, UserSession
from security.plans import API_KEYS, MEMBERS, get_plan

_hasher = PasswordHasher()
_DUMMY_HASH = _hasher.hash("aurex-timing-equalizer")
SESSION_COOKIE = "aurex_session"
API_KEY_PREFIX = "aurex_"


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def check_password_strength(password: str) -> None:
    if len(password) < 10 or len(password) > 200:
        raise ValidationFailure("Password must be between 10 and 200 characters")
    if password.lower() == password or not re.search(r"\d|[^A-Za-z0-9]", password):
        raise ValidationFailure("Password needs an upper-case letter and a digit or symbol")


def _slugify(name: str, session: Session) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:48] or "workspace"
    slug = base
    while session.scalar(select(Tenant.id).where(Tenant.slug == slug)):
        slug = f"{base}-{secrets.token_hex(2)}"
    return slug


def _open_session(session: Session, user: User, tenant_id: UUID) -> str:
    token = secrets.token_urlsafe(32)
    session.add(
        UserSession(
            user_id=user.id,
            tenant_id=tenant_id,
            token_hash=hash_token(token),
            expires_at=utcnow() + timedelta(hours=get_settings().session_ttl_hours),
        )
    )
    user.last_login_at = utcnow()
    return token


def sign_up(session: Session, *, email: str, password: str, display_name: str, organization: str) -> str:
    """Create a user and the tenant they own.

    Platform administrators are the configured admin emails; without that setting, the first account.
    """
    settings = get_settings()
    first_user = session.scalar(select(func.count()).select_from(User)) == 0
    if not settings.allow_signup and not first_user:
        raise Forbidden("Sign-up is disabled on this deployment")
    email = email.strip().lower()
    check_password_strength(password)
    if session.scalar(select(User.id).where(User.email == email)):
        raise Conflict("An account with this email already exists")
    user = User(
        email=email,
        password_hash=_hasher.hash(password),
        display_name=display_name or email.split("@")[0],
        is_platform_admin=(settings.is_platform_admin_email(email) if settings.platform_admin_emails else first_user),
    )
    tenant = Tenant(name=organization, slug=_slugify(organization, session), plan=settings.default_plan)
    session.add_all([user, tenant])
    session.flush()
    session.add(Membership(user_id=user.id, tenant_id=tenant.id, role=Role.OWNER.value))
    record_audit(
        session, action="auth.sign_up", tenant_id=tenant.id, actor_id=user.id, object_type="user", object_id=user.id
    )
    return _open_session(session, user, tenant.id)


def sign_in(session: Session, *, email: str, password: str) -> str:
    email = email.strip().lower()
    user = session.scalar(select(User).where(User.email == email))
    try:
        ok = _hasher.verify(user.password_hash if user else _DUMMY_HASH, password) and user is not None
    except (Argon2Error, InvalidHashError):
        ok = False
    if not ok or not user.is_active:
        # The caller records the denial in its own transaction; this one is rolled back.
        raise Unauthenticated("Email or password is incorrect")
    membership = session.scalar(select(Membership).where(Membership.user_id == user.id).order_by(Membership.created_at))
    if membership is None:
        raise Forbidden("This account does not belong to an organization")
    if _hasher.check_needs_rehash(user.password_hash):
        user.password_hash = _hasher.hash(password)
    record_audit(session, action="auth.sign_in", tenant_id=membership.tenant_id, actor_id=user.id)
    return _open_session(session, user, membership.tenant_id)


def sign_out(session: Session, token: str) -> None:
    row = session.scalar(select(UserSession).where(UserSession.token_hash == hash_token(token)))
    if row and row.revoked_at is None:
        row.revoked_at = utcnow()
        record_audit(session, action="auth.sign_out", tenant_id=row.tenant_id, actor_id=row.user_id)


def change_password(session: Session, scope: Scope, *, current: str, new: str) -> None:
    user = session.get(User, scope.user_id)
    try:
        _hasher.verify(user.password_hash, current)
    except (Argon2Error, InvalidHashError) as exc:
        raise Unauthenticated("Current password is incorrect") from exc
    check_password_strength(new)
    user.password_hash = _hasher.hash(new)
    for row in session.scalars(
        select(UserSession).where(UserSession.user_id == user.id, UserSession.revoked_at.is_(None))
    ):
        row.revoked_at = utcnow()
    record_audit(session, action="auth.password_changed", tenant_id=scope.tenant_id, actor_id=user.id)


def _build_scope(session: Session, user: User, tenant_id: UUID, *, via_api_key: bool = False) -> Scope:
    row = session.execute(
        select(Membership.role, Tenant.plan, Tenant.status)
        .join(Tenant, Tenant.id == Membership.tenant_id)
        .where(Membership.user_id == user.id, Membership.tenant_id == tenant_id)
    ).first()
    if row is None or not user.is_active:
        raise Unauthenticated("Session is no longer valid")
    if row.status != "active":
        raise Forbidden("This organization is suspended")
    plan = get_plan(row.plan)
    return Scope(
        tenant_id=tenant_id,
        user_id=user.id,
        role=Role(row.role),
        plan=plan.code,
        entitlements=plan.entitlements,
        limits=dict(plan.limits),
        platform_admin=user.is_platform_admin,
        via_api_key=via_api_key,
    )


def scope_for(session: Session, user_id: UUID, tenant_id: UUID) -> Scope:
    """Rebuild a member's scope for background work started on their behalf (e.g. an AI run)."""
    user = session.get(User, user_id)
    if user is None:
        raise Unauthenticated("The member no longer exists")
    return _build_scope(session, user, tenant_id)


def external_models_allowed(session: Session, tenant_id: UUID) -> bool:
    """Tenant policy (section 4.7, rule 6): may data be sent to an external model provider?"""
    tenant = session.get(Tenant, tenant_id)
    return (tenant.model_policy or {}).get("external_models", "allow") != "deny" if tenant else False


def resolve_session(session: Session, token: str) -> Scope:
    row = session.scalar(select(UserSession).where(UserSession.token_hash == hash_token(token)))
    if row is None or row.revoked_at is not None or row.expires_at <= utcnow():
        raise Unauthenticated("Sign in to continue")
    return _build_scope(session, session.get(User, row.user_id), row.tenant_id)


def resolve_api_key(session: Session, key: str) -> Scope:
    row = session.scalar(select(ApiKey).where(ApiKey.key_hash == hash_token(key)))
    if row is None or row.revoked_at is not None:
        raise Unauthenticated("API key is not valid")
    scope = _build_scope(session, session.get(User, row.user_id), row.tenant_id, via_api_key=True)
    if not scope.has(API_KEYS):
        raise EntitlementDenied("The current plan does not include API access")
    row.last_used_at = utcnow()
    return scope


def switch_tenant(session: Session, token: str, tenant_id: UUID) -> Scope:
    row = session.scalar(select(UserSession).where(UserSession.token_hash == hash_token(token)))
    if row is None or row.revoked_at is not None:
        raise Unauthenticated("Sign in to continue")
    scope = _build_scope(session, session.get(User, row.user_id), tenant_id)
    row.tenant_id = tenant_id
    return scope


# --- API keys -------------------------------------------------------------------------------------


def create_api_key(session: Session, scope: Scope, name: str) -> tuple[ApiKey, str]:
    require(scope, API_KEYS)
    active = session.scalar(
        select(func.count()).select_from(ApiKey).where(ApiKey.tenant_id == scope.tenant_id, ApiKey.revoked_at.is_(None))
    )
    check_limit(scope, "api_keys", active)
    secret = API_KEY_PREFIX + secrets.token_urlsafe(32)
    row = ApiKey(
        tenant_id=scope.tenant_id, user_id=scope.user_id, name=name, prefix=secret[:12], key_hash=hash_token(secret)
    )
    session.add(row)
    session.flush()
    record_audit(
        session,
        action="api_key.created",
        tenant_id=scope.tenant_id,
        actor_id=scope.user_id,
        object_type="api_key",
        object_id=row.id,
    )
    return row, secret


def revoke_api_key(session: Session, scope: Scope, key_id: UUID) -> None:
    row = session.get(ApiKey, key_id)
    if row is None or row.tenant_id != scope.tenant_id:
        raise NotFound("API key not found")
    if row.user_id != scope.user_id and not scope.at_least(Role.ADMIN):
        raise Forbidden("Only an administrator can revoke another member's key")
    row.revoked_at = utcnow()
    record_audit(
        session,
        action="api_key.revoked",
        tenant_id=scope.tenant_id,
        actor_id=scope.user_id,
        object_type="api_key",
        object_id=row.id,
    )


# --- Organization ---------------------------------------------------------------------------------


def create_invite(session: Session, scope: Scope, *, email: str, role: Role) -> tuple[Invite, str]:
    require_role(scope, Role.ADMIN)
    require(scope, MEMBERS)
    if role == Role.OWNER:
        raise ValidationFailure("Ownership is transferred, not invited")
    members = session.scalar(
        select(func.count()).select_from(Membership).where(Membership.tenant_id == scope.tenant_id)
    )
    pending = session.scalar(
        select(func.count())
        .select_from(Invite)
        .where(Invite.tenant_id == scope.tenant_id, Invite.accepted_at.is_(None), Invite.expires_at > utcnow())
    )
    check_limit(scope, "members", members + pending)
    token = secrets.token_urlsafe(32)
    row = Invite(
        tenant_id=scope.tenant_id,
        email=email.strip().lower(),
        role=role.value,
        token_hash=hash_token(token),
        created_by=scope.user_id,
        expires_at=utcnow() + timedelta(days=7),
    )
    session.add(row)
    session.flush()
    record_audit(
        session,
        action="org.invite_created",
        tenant_id=scope.tenant_id,
        actor_id=scope.user_id,
        object_type="invite",
        object_id=row.id,
        role=role.value,
    )
    return row, token


def accept_invite(session: Session, *, token: str, password: str, display_name: str) -> str:
    invite = session.scalar(select(Invite).where(Invite.token_hash == hash_token(token)))
    if invite is None or invite.accepted_at is not None or invite.expires_at <= utcnow():
        raise NotFound("Invitation is invalid or has expired")
    user = session.scalar(select(User).where(User.email == invite.email))
    if user is None:
        check_password_strength(password)
        user = User(
            email=invite.email,
            password_hash=_hasher.hash(password),
            display_name=display_name or invite.email.split("@")[0],
            is_platform_admin=get_settings().is_platform_admin_email(invite.email),
        )
        session.add(user)
        session.flush()
    else:
        try:
            _hasher.verify(user.password_hash, password)
        except (Argon2Error, InvalidHashError) as exc:
            raise Unauthenticated("Enter the password of your existing account") from exc
    if not session.get(Membership, (user.id, invite.tenant_id)):
        session.add(Membership(user_id=user.id, tenant_id=invite.tenant_id, role=invite.role))
    invite.accepted_at = utcnow()
    record_audit(
        session,
        action="org.invite_accepted",
        tenant_id=invite.tenant_id,
        actor_id=user.id,
        object_type="invite",
        object_id=invite.id,
    )
    return _open_session(session, user, invite.tenant_id)


def set_member_role(session: Session, scope: Scope, user_id: UUID, role: Role) -> None:
    require_role(scope, Role.ADMIN)
    member = session.get(Membership, (user_id, scope.tenant_id))
    if member is None:
        raise NotFound("Member not found")
    if Role.OWNER in (Role(member.role), role) and scope.role != Role.OWNER:
        raise Forbidden("Only the owner can change ownership")
    if member.role == Role.OWNER.value and role != Role.OWNER and _owner_count(session, scope.tenant_id) <= 1:
        raise Conflict("An organization needs at least one owner")
    member.role = role.value
    record_audit(
        session,
        action="org.role_changed",
        tenant_id=scope.tenant_id,
        actor_id=scope.user_id,
        object_type="user",
        object_id=user_id,
        role=role.value,
    )


def remove_member(session: Session, scope: Scope, user_id: UUID) -> None:
    require_role(scope, Role.ADMIN)
    member = session.get(Membership, (user_id, scope.tenant_id))
    if member is None:
        raise NotFound("Member not found")
    if member.role == Role.OWNER.value and (scope.role != Role.OWNER or _owner_count(session, scope.tenant_id) <= 1):
        raise Conflict("The last owner cannot be removed")
    session.delete(member)
    for row in session.scalars(
        select(UserSession).where(UserSession.user_id == user_id, UserSession.tenant_id == scope.tenant_id)
    ):
        row.revoked_at = utcnow()
    record_audit(
        session,
        action="org.member_removed",
        tenant_id=scope.tenant_id,
        actor_id=scope.user_id,
        object_type="user",
        object_id=user_id,
    )


def _owner_count(session: Session, tenant_id: UUID) -> int:
    return session.scalar(
        select(func.count())
        .select_from(Membership)
        .where(Membership.tenant_id == tenant_id, Membership.role == Role.OWNER.value)
    )


# --- Checks used by the API -----------------------------------------------------------------------


def require(scope: Scope, entitlement: str) -> None:
    scope.require(entitlement)


def require_role(scope: Scope, role: Role) -> None:
    scope.require_role(role)


def check_limit(scope: Scope, limit: str, current: int) -> None:
    scope.check_limit(limit, current)
