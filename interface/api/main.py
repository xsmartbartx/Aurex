"""AUREX API. The only entry point to the system; the web terminal is one of its clients."""

import time
import uuid
from importlib import import_module

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException

from core.config import get_settings
from core.db import get_engine
from core.errors import AurexError
from modules.logging import Severity, log

API_PREFIX = "/api/v1"
ROUTERS = ("auth", "markets", "datalab", "intelligence", "portfolio", "quant", "graph", "org", "billing")

settings = get_settings()
settings.assert_safe()

app = FastAPI(
    title="AUREX API",
    version="0.1.0",
    description="Financial intelligence platform. Analysis, education and simulation only: "
    "no trade execution and no investment advice.",
    docs_url=f"{API_PREFIX}/docs",
    redoc_url=None,
    openapi_url=f"{API_PREFIX}/openapi.json",
)


def _error(status: int, code: str, message: str, details: dict | None = None, request_id: str = "") -> JSONResponse:
    body = {"error": {"code": code, "message": message, "details": details or {}, "request_id": request_id}}
    return JSONResponse(body, status_code=status)


@app.middleware("http")
async def request_context(request: Request, call_next):
    request_id = uuid.uuid4().hex[:16]
    request.state.request_id = request_id
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception as exc:  # noqa: BLE001 - last line of defence; no stack trace leaves the process
        log(
            "api",
            "request.unhandled",
            Severity.ERROR,
            request_id=request_id,
            error=type(exc).__name__,
            path=request.url.path,
        )
        response = _error(500, "internal_error", "Unexpected error", request_id=request_id)
    route = request.scope.get("route")
    scope = getattr(request.state, "scope", None)
    log(
        "api",
        "request",
        request_id=request_id,
        method=request.method,
        route=getattr(route, "path", request.url.path),
        status=response.status_code,
        ms=round((time.perf_counter() - started) * 1000, 1),
        tenant=str(scope.tenant_id) if scope else "",
    )
    response.headers["X-Request-Id"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Cache-Control"] = "no-store"
    return response


@app.exception_handler(AurexError)
async def aurex_error(request: Request, exc: AurexError) -> JSONResponse:
    if exc.status in (401, 403):
        log("api", "request.denied", Severity.SECURITY, code=exc.code, path=request.url.path)
    headers = {}
    if exc.status == 429 and "retry_after_seconds" in exc.details:
        headers["Retry-After"] = str(exc.details["retry_after_seconds"])
    response = _error(exc.status, exc.code, exc.message, exc.details, getattr(request.state, "request_id", ""))
    response.headers.update(headers)
    return response


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    issues = [{"field": ".".join(str(p) for p in e["loc"][1:]), "problem": e["msg"]} for e in exc.errors()[:25]]
    return _error(
        422, "validation_failed", "Invalid request", {"issues": issues}, getattr(request.state, "request_id", "")
    )


@app.exception_handler(StarletteHTTPException)
async def http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    code = {404: "not_found", 405: "method_not_allowed"}.get(exc.status_code, "http_error")
    return _error(exc.status_code, code, str(exc.detail), request_id=getattr(request.state, "request_id", ""))


@app.get(f"{API_PREFIX}/health", tags=["system"])
def health() -> dict:
    with get_engine().connect() as connection:
        connection.execute(text("SELECT 1"))
    return {"status": "ok", "version": app.version, "deployment_mode": settings.deployment_mode}


for name in ROUTERS:
    module = import_module(f"interface.api.routes.{name}")
    app.include_router(module.router, prefix=API_PREFIX)
