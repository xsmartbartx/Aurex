"""Plans and subscriptions. The webhook is the only unauthenticated write; it is verified by signature."""

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Request

from core.config import get_settings
from core.db import system_session
from interface.api.deps import AdminDep, ScopeDep, client_ip
from modules.integration import payments
from modules.validation import Strict
from security import billing
from security.controls import rate_limiter

router = APIRouter(tags=["billing"])


class CheckoutIn(Strict):
    plan: Literal["pro", "quant", "business"]


class TenantUpdate(Strict):
    plan: Literal["community", "pro", "quant", "business", "enterprise"] | None = None
    status: Literal["active", "suspended"] | None = None


@router.get("/billing/plans")
def plans() -> dict:
    """Public: the plan catalog shown on the pricing page."""
    settings = get_settings()
    return {
        "items": billing.catalog(),
        "billing_enabled": settings.billing_enabled,
        "deployment_mode": settings.deployment_mode,
        "sales_contact": settings.sales_contact,
        "support_contact": settings.support_contact,
        "operator": settings.operator_name,
        "signup_open": settings.allow_signup,
    }


@router.post("/billing/checkout")
def checkout(body: CheckoutIn, scope: ScopeDep) -> dict:
    with system_session() as session:
        return {"url": billing.start_checkout(session, scope, body.plan)}


@router.post("/billing/portal")
def portal(scope: ScopeDep) -> dict:
    with system_session() as session:
        return {"url": billing.portal(session, scope)}


@router.post("/billing/webhook", include_in_schema=False)
async def webhook(request: Request) -> dict:
    rate_limiter.check(f"webhook:{client_ip(request)}", 600)
    payload = await request.body()
    if len(payload) > 1_000_000:
        return {"status": "ignored"}
    event = payments.verify_event(payload, request.headers.get("stripe-signature"))
    with system_session() as session:
        return {"status": billing.handle_event(session, event)}


@router.get("/admin/tenants")
def tenants(scope: AdminDep) -> dict:
    with system_session() as session:
        return {"items": billing.list_tenants(session, scope)}


@router.patch("/admin/tenants/{tenant_id}")
def update_tenant(tenant_id: UUID, body: TenantUpdate, scope: AdminDep) -> dict:
    with system_session() as session:
        billing.set_tenant(session, scope, tenant_id, plan=body.plan, status=body.status)
    return {"status": "ok"}
