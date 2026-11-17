"""Error model shared by all modules. The API renders it as ``{"error": {code, message, details}}``."""

from typing import Any


class AurexError(Exception):
    status = 500
    code = "internal_error"

    def __init__(self, message: str, *, details: dict[str, Any] | None = None, code: str | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}
        if code:
            self.code = code

    def to_dict(self) -> dict[str, Any]:
        return {"error": {"code": self.code, "message": self.message, "details": self.details}}


class ValidationFailure(AurexError):
    status = 422
    code = "validation_failed"


class NotFound(AurexError):
    status = 404
    code = "not_found"


class Unauthenticated(AurexError):
    status = 401
    code = "unauthenticated"


class Forbidden(AurexError):
    status = 403
    code = "forbidden"


class EntitlementDenied(Forbidden):
    code = "entitlement_denied"


class LicenseDenied(Forbidden):
    code = "license_denied"


class Conflict(AurexError):
    status = 409
    code = "conflict"


class RateLimited(AurexError):
    status = 429
    code = "rate_limited"


class QuotaExceeded(AurexError):
    status = 402
    code = "quota_exceeded"


class ProviderError(AurexError):
    status = 502
    code = "provider_error"
