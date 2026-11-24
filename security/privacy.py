"""Data subject rights: export of personal and organization data, and account deletion.

The privacy notice promises access, export and deletion, with closed accounts' data gone within 30 days, except
audit records and invoices. Export returns every stored row except credentials (password, session and key hashes).
Deletion removes the account at once; an organization the account owns alone is closed with all of its data.
Audit events are kept (they are append-only by design), and so is the payment provider's record of invoices.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from argon2.exceptions import Argon2Error, InvalidHashError
from sqlalchemy import Table, delete, func, select
from sqlalchemy.orm import Session

from core.config import get_settings
from core.db import Base, tenant_tables
from core.errors import Conflict, Forbidden, NotFound, Unauthenticated
from core.types import Role, Scope, utcnow
from modules.logging import record_audit
from modules.logging.audit import AuditEvent
from security.auth import _hasher
from security.models import ApiKey, Membership, PasswordReset, Tenant, User, UserSession

# Plans that come from a Stripe subscription. An organization on one of them cannot be closed until it is cancelled.
SUBSCRIPTION_PLANS = frozenset({"pro", "quant", "business"})
# Never exported: credentials, and sessions (live tokens' metadata is of no use outside AUREX).
_SECRET_COLUMNS = frozenset({"password_hash", "token_hash", "key_hash"})
_NOT_EXPORTED = frozenset({"user_sessions"})
_KEPT_ON_CLOSURE = frozenset({"audit_events"})


def _plain(value: Any) -> Any:
    if isinstance(value, UUID | Decimal):
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, bytes | bytearray | memoryview):
        return None
    return value


def _row(mapping: Any) -> dict[str, Any]:
    return {key: _plain(value) for key, value in dict(mapping).items() if key not in _SECRET_COLUMNS}


def _rows(session: Session, statement: Any) -> list[dict[str, Any]]:
    return [_row(row) for row in session.execute(statement).mappings()]


def _tables() -> list[Table]:
    return list(Base.metadata.sorted_tables)


def export_personal(session: Session, scope: Scope) -> dict[str, Any]:
    """Everything AUREX stores about the signed-in person, across their organizations."""
    user = session.get(User, scope.user_id)
    users, memberships, tenants = User.__table__, Membership.__table__, Tenant.__table__
    return {
        "exported_at": utcnow().isoformat(),
        "account": _rows(session, select(users).where(users.c.id == user.id))[0],
        "memberships": _rows(
            session,
            select(memberships.c.role, memberships.c.created_at, tenants.c.id.label("organization_id"), tenants.c.name)
            .join(tenants, tenants.c.id == memberships.c.tenant_id)
            .where(memberships.c.user_id == user.id),
        ),
        "api_keys": _rows(session, select(ApiKey.__table__).where(ApiKey.user_id == user.id)),
        "sign_ins": _rows(
            session,
            select(UserSession.created_at, UserSession.expires_at, UserSession.revoked_at)
            .where(UserSession.user_id == user.id)
            .order_by(UserSession.created_at.desc())
            .limit(200),
        ),
        "password_resets": _rows(
            session,
            select(PasswordReset.created_at, PasswordReset.expires_at, PasswordReset.used_at).where(
                PasswordReset.user_id == user.id
            ),
        ),
        "activity": _rows(
            session,
            select(AuditEvent.__table__)
            .where(AuditEvent.actor_id == user.id)
            .order_by(AuditEvent.occurred_at.desc())
            .limit(2000),
        ),
    }


def export_organization(session: Session, scope: Scope) -> dict[str, Any]:
    """Every row the organization owns, table by table. Owners only."""
    scope.require_role(Role.OWNER)
    tenant_id = scope.tenant_id
    tenants, users, memberships = Tenant.__table__, User.__table__, Membership.__table__
    data: dict[str, Any] = {
        "exported_at": utcnow().isoformat(),
        "organization": _rows(session, select(tenants).where(tenants.c.id == tenant_id))[0],
        "members": _rows(
            session,
            select(users.c.id, users.c.email, users.c.display_name, memberships.c.role, memberships.c.created_at)
            .join(memberships, memberships.c.user_id == users.c.id)
            .where(memberships.c.tenant_id == tenant_id),
        ),
        "tables": {},
    }
    private = tenant_tables()
    for table in _tables():
        if table.name in private and table.name not in _NOT_EXPORTED:
            rows = _rows(session, select(table).where(table.c.tenant_id == tenant_id))
            if rows:
                data["tables"][table.name] = rows
    return data


def _purge_organization(session: Session, tenant_id: UUID) -> None:
    """Delete every row of an organization, children before parents, then the organization itself."""
    private = tenant_tables()
    tables = {table.name: table for table in _tables()}
    for table in reversed(_tables()):
        if table.name in _KEPT_ON_CLOSURE:
            continue
        if table.name in private:
            session.execute(delete(table).where(table.c.tenant_id == tenant_id))
            continue
        # Shared tables can still hold rows that point at this organization's private rows (for example reference
        # rows of a privately imported dataset); they go with it.
        for fk in table.foreign_keys:
            parent = tables.get(fk.column.table.name)
            if parent is not None and parent.name in private:
                owned = select(parent.c[fk.column.name]).where(parent.c.tenant_id == tenant_id)
                session.execute(delete(table).where(fk.parent.in_(owned)))
    session.execute(delete(Tenant.__table__).where(Tenant.__table__.c.id == tenant_id))


def delete_account(session: Session, scope: Scope, *, password: str) -> list[str]:
    """Delete the signed-in account. Organizations it owns alone are closed with their data; returns their names.

    Refused, before anything changes, when it would leave a team without an owner, close an organization that is
    still paying, or remove the deployment's configured administrator.
    """
    user = session.get(User, scope.user_id)
    if user is None:
        raise NotFound("Account not found")
    try:
        _hasher.verify(user.password_hash, password)
    except (Argon2Error, InvalidHashError) as exc:
        raise Unauthenticated("The password is incorrect") from exc
    if get_settings().is_platform_admin_email(user.email):
        raise Forbidden(
            "This account administers the deployment. Remove its email from AUREX_PLATFORM_ADMIN_EMAILS first."
        )

    closing: list[Tenant] = []
    leaving: list[UUID] = []
    for membership in session.scalars(select(Membership).where(Membership.user_id == user.id)).all():
        tenant = session.get(Tenant, membership.tenant_id)
        others = session.scalar(
            select(func.count())
            .select_from(Membership)
            .where(Membership.tenant_id == tenant.id, Membership.user_id != user.id)
        )
        other_owners = session.scalar(
            select(func.count())
            .select_from(Membership)
            .where(
                Membership.tenant_id == tenant.id,
                Membership.user_id != user.id,
                Membership.role == Role.OWNER.value,
            )
        )
        if membership.role == Role.OWNER.value and others and not other_owners:
            raise Conflict(
                f"You are the only owner of {tenant.name}, which has other members. "
                "Make one of them an owner, or remove them, first."
            )
        if others:
            leaving.append(tenant.id)
            continue
        if tenant.stripe_subscription_id and tenant.plan in SUBSCRIPTION_PLANS:
            raise Conflict(
                f"{tenant.name} has an active subscription. Cancel it under Settings → Plan → "
                "Manage subscription, then delete the account."
            )
        closing.append(tenant)

    closed = []
    for tenant in closing:
        _purge_organization(session, tenant.id)
        record_audit(
            session,
            action="org.closed",
            tenant_id=tenant.id,
            actor_id=user.id,
            object_type="tenant",
            object_id=tenant.id,
            reason="account_deleted",
        )
        closed.append(tenant.name)
    for tenant_id in leaving:
        record_audit(
            session,
            action="org.member_left",
            tenant_id=tenant_id,
            actor_id=user.id,
            object_type="user",
            object_id=user.id,
        )
    record_audit(
        session,
        action="auth.account_deleted",
        actor_id=user.id,
        object_type="user",
        object_id=user.id,
        organizations_closed=len(closed),
    )
    # Memberships elsewhere, sessions, API keys and reset links go with the account (foreign keys cascade).
    session.execute(delete(User.__table__).where(User.__table__.c.id == user.id))
    return closed
