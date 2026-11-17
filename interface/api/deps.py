"""Request dependencies: identity, tenant-bound database session, limits. Order follows section 4.6:
schema validation (FastAPI), then identity and entitlements, then module logic."""

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from core.config import get_settings
from core.db import system_session, tenant_session
from core.errors import Forbidden, Unauthenticated
from core.types import Scope
from security import auth
from security.controls import rate_limiter

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
CLIENT_HEADER = "x-aurex-client"


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def get_scope(request: Request) -> Scope:
    header = request.headers.get("authorization", "")
    cookie = request.cookies.get(auth.SESSION_COOKIE)
    with system_session() as session:
        if header.lower().startswith("bearer "):
            scope = auth.resolve_api_key(session, header[7:].strip())
        elif cookie:
            # A cookie is sent by the browser automatically, so state-changing requests must also carry
            # a custom header that a cross-site form cannot set (CSRF).
            if request.method not in SAFE_METHODS and not request.headers.get(CLIENT_HEADER):
                raise Forbidden("Missing client header", code="csrf_check_failed")
            scope = auth.resolve_session(session, cookie)
        else:
            raise Unauthenticated("Sign in to continue")
    rate_limiter.check(f"tenant:{scope.tenant_id}", get_settings().rate_limit_per_minute)
    request.state.scope = scope
    return scope


def get_db(scope: Annotated[Scope, Depends(get_scope)]) -> Iterator[Session]:
    with tenant_session(scope.tenant_id) as session:
        yield session


def platform_admin(scope: Annotated[Scope, Depends(get_scope)]) -> Scope:
    if not scope.platform_admin:
        raise Forbidden("Platform administration is restricted to the deployment administrator")
    return scope


ScopeDep = Annotated[Scope, Depends(get_scope)]
DbDep = Annotated[Session, Depends(get_db)]
AdminDep = Annotated[Scope, Depends(platform_admin)]
