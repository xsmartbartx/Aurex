"""Stripe adapter. Payment details are entered on Stripe's hosted pages and never pass through AUREX."""

import json
from typing import Any

import stripe

from core.config import get_settings
from core.errors import ProviderError, ValidationFailure
from modules.logging import Severity, log


def _client() -> stripe.StripeClient:
    key = get_settings().stripe_secret_key
    if not key:
        raise ProviderError("Billing is not configured on this deployment", code="billing_not_configured")
    return stripe.StripeClient(key, max_network_retries=2)


def _call(action: str, fn, params: dict[str, Any]) -> Any:
    try:
        return fn(params=params)
    except stripe.AuthenticationError as exc:
        raise ProviderError("The payment provider rejected the API key", code="billing_auth_failed") from exc
    except stripe.InvalidRequestError as exc:
        log("integration", "billing.invalid_request", Severity.ERROR, action=action, code=exc.code or "")
        raise ProviderError("The payment provider rejected the request", code="billing_rejected") from exc
    except stripe.StripeError as exc:
        raise ProviderError("The payment provider is unavailable", code="billing_unavailable") from exc


def create_customer(*, name: str, email: str, tenant_id: str) -> str:
    client = _client()
    customer = _call(
        "customer", client.v1.customers.create, {"name": name, "email": email, "metadata": {"tenant_id": tenant_id}}
    )
    return customer.id


def checkout_url(
    *, customer_id: str, price_id: str, tenant_id: str, plan: str, success_url: str, cancel_url: str
) -> str:
    client = _client()
    session = _call(
        "checkout",
        client.v1.checkout.sessions.create,
        {
            "mode": "subscription",
            "customer": customer_id,
            "client_reference_id": tenant_id,
            "line_items": [{"price": price_id, "quantity": 1}],
            "success_url": success_url,
            "cancel_url": cancel_url,
            "allow_promotion_codes": True,
            "billing_address_collection": "auto",
            "metadata": {"tenant_id": tenant_id, "plan": plan},
            "subscription_data": {"metadata": {"tenant_id": tenant_id, "plan": plan}},
        },
    )
    return session.url


def portal_url(*, customer_id: str, return_url: str) -> str:
    client = _client()
    session = _call(
        "portal", client.v1.billing_portal.sessions.create, {"customer": customer_id, "return_url": return_url}
    )
    return session.url


def verify_event(payload: bytes, signature: str | None) -> dict[str, Any]:
    """Check the webhook signature, then return the event as plain data."""
    secret = get_settings().stripe_webhook_secret
    if not secret:
        raise ProviderError("Billing webhooks are not configured", code="billing_not_configured")
    try:
        _client().construct_event(payload, signature, secret)
    except (stripe.SignatureVerificationError, ValueError) as exc:
        log("integration", "billing.webhook_rejected", Severity.SECURITY)
        raise ValidationFailure("Invalid webhook signature", code="invalid_signature") from exc
    return json.loads(payload)
