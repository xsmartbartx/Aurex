"""Subscriptions: plans are sold through Stripe in cloud mode; entitlements follow the subscription state."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.config import get_settings
from core.errors import Forbidden, NotFound, ValidationFailure
from core.types import Role, Scope
from modules.integration import payments
from modules.logging import record_audit
from security.models import BillingEvent, Membership, Tenant, User
from security.plans import PLANS, get_plan

ACTIVE = {"active", "trialing"}
SELF_SERVE = ("pro", "quant", "business")


def catalog() -> list[dict[str, Any]]:
    """Plans as shown on the pricing page. Enterprise is sold by contract."""
    settings = get_settings()
    out = []
    for plan in PLANS.values():
        out.append(
            {
                "code": plan.code,
                "name": plan.name,
                "audience": plan.audience,
                "highlights": list(plan.highlights),
                "limits": plan.limits,
                "entitlements": sorted(plan.entitlements),
                "price_label": settings.plan_price_labels.get(
                    plan.code, "Free" if plan.code == "community" else "Contact us" if plan.code == "enterprise" else ""
                ),
                "self_serve": plan.code in SELF_SERVE and plan.code in settings.stripe_prices,
            }
        )
    return out


def _tenant(session: Session, scope: Scope) -> Tenant:
    scope.require_role(Role.OWNER)
    tenant = session.get(Tenant, scope.tenant_id)
    if tenant is None:
        raise NotFound("Organization not found")
    return tenant


def _customer(session: Session, tenant: Tenant, scope: Scope) -> str:
    if tenant.stripe_customer_id:
        return tenant.stripe_customer_id
    owner = session.get(User, scope.user_id)
    tenant.stripe_customer_id = payments.create_customer(name=tenant.name, email=owner.email, tenant_id=str(tenant.id))
    return tenant.stripe_customer_id


def start_checkout(session: Session, scope: Scope, plan_code: str) -> str:
    settings = get_settings()
    if not settings.billing_enabled:
        raise Forbidden("Plans are managed by the deployment administrator", code="billing_not_configured")
    if plan_code not in SELF_SERVE or plan_code not in settings.stripe_prices:
        raise ValidationFailure("This plan is not available for online purchase")
    tenant = _tenant(session, scope)
    url = payments.checkout_url(
        customer_id=_customer(session, tenant, scope),
        price_id=settings.stripe_prices[plan_code],
        tenant_id=str(tenant.id),
        plan=plan_code,
        success_url=f"{settings.public_url}/app/settings?tab=plan&checkout=success",
        cancel_url=f"{settings.public_url}/app/settings?tab=plan&checkout=cancelled",
    )
    record_audit(
        session,
        action="billing.checkout_started",
        tenant_id=tenant.id,
        actor_id=scope.user_id,
        object_type="tenant",
        object_id=tenant.id,
        plan=plan_code,
    )
    return url


def portal(session: Session, scope: Scope) -> str:
    settings = get_settings()
    tenant = _tenant(session, scope)
    if not settings.billing_enabled or not tenant.stripe_customer_id:
        raise ValidationFailure("There is no subscription to manage yet")
    return payments.portal_url(
        customer_id=tenant.stripe_customer_id, return_url=f"{settings.public_url}/app/settings?tab=plan"
    )


def _plan_for_price(price_id: str | None) -> str | None:
    for plan, price in get_settings().stripe_prices.items():
        if price == price_id:
            return plan
    return None


def handle_event(session: Session, event: dict[str, Any]) -> str:
    """Apply a verified webhook event once. Returns what was done."""
    event_id, kind = str(event.get("id", "")), str(event.get("type", ""))
    if not event_id or session.get(BillingEvent, event_id):
        return "duplicate"
    session.add(
        BillingEvent(
            id=event_id,
            type=kind[:80],
            received_at=datetime.now(UTC),
            payload={"type": kind, "created": event.get("created")},
        )
    )
    obj = (event.get("data") or {}).get("object") or {}
    if kind == "checkout.session.completed":
        tenant = session.get(Tenant, UUID(str(obj.get("client_reference_id"))))
        if tenant is None:
            return "unknown_tenant"
        tenant.stripe_customer_id = obj.get("customer") or tenant.stripe_customer_id
        tenant.stripe_subscription_id = obj.get("subscription") or tenant.stripe_subscription_id
        return "linked"
    if kind.startswith("customer.subscription."):
        tenant = session.scalar(select(Tenant).where(Tenant.stripe_customer_id == obj.get("customer")))
        if tenant is None:
            return "unknown_customer"
        items = (obj.get("items") or {}).get("data") or [{}]
        price_id = ((items[0] or {}).get("price") or {}).get("id")
        plan = _plan_for_price(price_id) or (obj.get("metadata") or {}).get("plan")
        status = obj.get("status")
        previous = tenant.plan
        if kind.endswith(".deleted") or status not in ACTIVE:
            tenant.plan = "community"
        elif plan in PLANS:
            tenant.plan = plan
        tenant.stripe_subscription_id = obj.get("id") or tenant.stripe_subscription_id
        record_audit(
            session,
            action="billing.plan_changed",
            tenant_id=tenant.id,
            object_type="tenant",
            object_id=tenant.id,
            previous=previous,
            plan=tenant.plan,
            status=status or "",
        )
        return f"plan:{tenant.plan}"
    return "ignored"


# --- Platform administration (deployment operator) -------------------------------------------------


def list_tenants(session: Session, scope: Scope) -> list[dict[str, Any]]:
    if not scope.platform_admin:
        raise Forbidden("Restricted to the deployment administrator")
    rows = session.scalars(select(Tenant).order_by(Tenant.created_at.desc()).limit(500))
    out = []
    for tenant in rows:
        members = session.scalars(select(Membership).where(Membership.tenant_id == tenant.id)).all()
        out.append(
            {
                "id": tenant.id,
                "name": tenant.name,
                "plan": tenant.plan,
                "status": tenant.status,
                "members": len(members),
                "created_at": tenant.created_at,
                "subscription": bool(tenant.stripe_subscription_id),
            }
        )
    return out


def set_tenant(session: Session, scope: Scope, tenant_id: UUID, *, plan: str | None, status: str | None) -> None:
    if not scope.platform_admin:
        raise Forbidden("Restricted to the deployment administrator")
    tenant = session.get(Tenant, tenant_id)
    if tenant is None:
        raise NotFound("Organization not found")
    if plan is not None:
        tenant.plan = get_plan(plan).code
    if status is not None:
        if status not in ("active", "suspended"):
            raise ValidationFailure("Status is active or suspended")
        if tenant_id == scope.tenant_id and status == "suspended":
            raise ValidationFailure("You cannot suspend your own organization")
        tenant.status = status
    record_audit(
        session,
        action="platform.tenant_updated",
        tenant_id=tenant.id,
        actor_id=scope.user_id,
        object_type="tenant",
        object_id=tenant.id,
        plan=tenant.plan,
        status=tenant.status,
    )
