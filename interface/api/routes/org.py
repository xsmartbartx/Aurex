"""Organization administration: members, invitations, roles, settings, audit trail and usage."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import EmailStr, Field
from sqlalchemy import func, select

from core import entitlements as ent
from core.config import get_settings
from core.db import system_session
from core.types import Role
from interface.api.deps import DbDep, ScopeDep, attachment
from modules.datalab.models import Dataset, DatasetUsage
from modules.integration import mail
from modules.logging import record_audit
from modules.logging.audit import AuditEvent
from modules.validation import Strict, clean_text
from security import auth, privacy
from security.controls import rate_limiter, usage_today
from security.models import Invite, Membership, Tenant, User

router = APIRouter(prefix="/org", tags=["organization"])


class InviteIn(Strict):
    email: EmailStr
    role: Literal["admin", "analyst", "viewer"] = "analyst"


class RoleIn(Strict):
    role: Literal["owner", "admin", "analyst", "viewer"]


class SettingsIn(Strict):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    external_models: Literal["allow", "deny"] | None = None


@router.get("")
def organization(scope: ScopeDep, db: DbDep) -> dict:
    tenant = db.get(Tenant, scope.tenant_id)
    return {
        "id": tenant.id,
        "name": tenant.name,
        "slug": tenant.slug,
        "plan": tenant.plan,
        "status": tenant.status,
        "created_at": tenant.created_at,
        "model_policy": {"external_models": "allow", **(tenant.model_policy or {})},
        "email_configured": mail.configured(),
    }


@router.patch("")
def update_organization(body: SettingsIn, scope: ScopeDep, db: DbDep) -> dict:
    scope.require_role(Role.ADMIN)
    tenant = db.get(Tenant, scope.tenant_id)
    if body.name:
        tenant.name = clean_text(body.name, max_len=120)
    if body.external_models:
        scope.require_role(Role.OWNER)
        tenant.model_policy = {**(tenant.model_policy or {}), "external_models": body.external_models}
    record_audit(
        db,
        action="org.settings_changed",
        tenant_id=scope.tenant_id,
        actor_id=scope.user_id,
        object_type="tenant",
        object_id=scope.tenant_id,
        external_models=body.external_models or "",
    )
    return {"status": "ok"}


@router.get("/members")
def members(scope: ScopeDep, db: DbDep) -> dict:
    rows = db.execute(
        select(User.id, User.email, User.display_name, User.last_login_at, Membership.role, Membership.created_at)
        .join(Membership, Membership.user_id == User.id)
        .where(Membership.tenant_id == scope.tenant_id)
        .order_by(Membership.created_at)
    ).all()
    invites = []
    if scope.at_least(Role.ADMIN):
        invites = [
            {"id": i.id, "email": i.email, "role": i.role, "expires_at": i.expires_at}
            for i in db.scalars(select(Invite).where(Invite.tenant_id == scope.tenant_id, Invite.accepted_at.is_(None)))
        ]
    return {
        "items": [
            {
                "user_id": r.id,
                "email": r.email,
                "display_name": r.display_name,
                "role": r.role,
                "joined_at": r.created_at,
                "last_login_at": r.last_login_at,
                "you": r.id == scope.user_id,
            }
            for r in rows
        ],
        "invites": invites,
        "limit": scope.limits.get("members"),
    }


@router.post("/invites", status_code=201)
def invite(body: InviteIn, scope: ScopeDep) -> dict:
    with system_session() as session:
        row, token = auth.create_invite(session, scope, email=body.email, role=Role(body.role))
        tenant = session.get(Tenant, scope.tenant_id)
        inviter = session.get(User, scope.user_id)
        link = f"{get_settings().public_url}/invite/{token}"
        sent = mail.send(
            to=row.email,
            subject=f"Join {tenant.name} on AUREX",
            body=f"{inviter.display_name} invited you to the {tenant.name} workspace on AUREX.\n\n"
            f"Accept within 7 days: {link}\n",
        )
    # The link is a credential; it is shown to the administrator only when it could not be emailed.
    return {"id": row.id, "emailed": sent, "link": None if sent else link}


@router.delete("/invites/{invite_id}", status_code=204)
def revoke_invite(invite_id: UUID, scope: ScopeDep, db: DbDep) -> None:
    scope.require_role(Role.ADMIN)
    row = db.get(Invite, invite_id)
    if row is not None and row.tenant_id == scope.tenant_id and row.accepted_at is None:
        db.delete(row)
        record_audit(
            db,
            action="org.invite_revoked",
            tenant_id=scope.tenant_id,
            actor_id=scope.user_id,
            object_type="invite",
            object_id=invite_id,
        )


@router.patch("/members/{user_id}")
def change_role(user_id: UUID, body: RoleIn, scope: ScopeDep) -> dict:
    with system_session() as session:
        auth.set_member_role(session, scope, user_id, Role(body.role))
    return {"status": "ok"}


@router.delete("/members/{user_id}", status_code=204)
def remove(user_id: UUID, scope: ScopeDep) -> None:
    with system_session() as session:
        auth.remove_member(session, scope, user_id)


@router.get("/export")
def export_organization(scope: ScopeDep):
    """Download every row the organization owns (owners only)."""
    rate_limiter.check(f"org-export:{scope.tenant_id}", 5, 3600)
    with system_session() as session:
        data = privacy.export_organization(session, scope)
        record_audit(session, action="org.data_exported", tenant_id=scope.tenant_id, actor_id=scope.user_id)
    return attachment(data, f"aurex-organization-{data['exported_at'][:10]}.json")


@router.get("/audit")
def audit(
    scope: ScopeDep,
    db: DbDep,
    action: Annotated[str, Query(max_length=80)] = "",
    outcome: Literal["", "success", "denied", "failure"] = "",
    before: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> dict:
    """The organization's audit trail. Append-only; visible to administrators on plans that include it."""
    scope.require(ent.AUDIT)
    scope.require_role(Role.ADMIN)
    stmt = select(AuditEvent).where(AuditEvent.tenant_id == scope.tenant_id)
    if action:
        stmt = stmt.where(AuditEvent.action.startswith(clean_text(action, max_len=80)))
    if outcome:
        stmt = stmt.where(AuditEvent.outcome == outcome)
    if before:
        stmt = stmt.where(AuditEvent.occurred_at < before)
    rows = list(db.scalars(stmt.order_by(AuditEvent.occurred_at.desc()).limit(limit)))
    emails = dict(
        db.execute(select(User.id, User.email).where(User.id.in_({r.actor_id for r in rows if r.actor_id}))).all()
    )
    return {
        "items": [
            {
                "id": r.id,
                "occurred_at": r.occurred_at,
                "action": r.action,
                "outcome": r.outcome,
                "actor": emails.get(r.actor_id, str(r.actor_id) if r.actor_id else "system"),
                "object_type": r.object_type,
                "object_id": r.object_id,
                "details": r.details,
            }
            for r in rows
        ]
    }


@router.get("/usage")
def usage(scope: ScopeDep, db: DbDep) -> dict:
    """Today's metered usage against plan limits, and data use per dataset over 30 days."""
    with system_session() as session:
        today = usage_today(session, scope.tenant_id)
    rows = db.execute(
        select(Dataset.name, DatasetUsage.channel, func.sum(DatasetUsage.count))
        .join(Dataset, Dataset.id == DatasetUsage.dataset_id)
        .where(DatasetUsage.tenant_id == scope.tenant_id, DatasetUsage.day >= func.current_date() - 30)
        .group_by(Dataset.name, DatasetUsage.channel)
        .order_by(Dataset.name)
    ).all()
    return {
        "today": today,
        "limits": scope.limits,
        "datasets": [{"dataset": name, "channel": channel, "count": int(count)} for name, channel, count in rows],
    }
