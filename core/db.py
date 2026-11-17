"""Database primitives. PostgreSQL is the system of record (ADR-0005).

Tenant isolation (ADR-0008) has two controls. Application queries filter by tenant, and every
tenant-private table has a row-level security policy keyed on ``app.tenant_id``. A scoped session
switches to the unprivileged ``aurex_app`` role, so the policy applies even if a filter is forgotten.
"""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from functools import lru_cache
from uuid import UUID

from sqlalchemy import DateTime, Engine, MetaData, create_engine, func, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from core.config import get_settings

APP_ROLE = "aurex_app"

NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)


class IdMixin:
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class CreatedMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TenantMixin:
    """Marks a table as tenant-private. The migration adds the row-level security policy."""

    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), index=True)


@lru_cache
def get_engine() -> Engine:
    return create_engine(get_settings().database_url, pool_pre_ping=True, pool_size=10, max_overflow=20)


@lru_cache
def _factory() -> sessionmaker[Session]:
    return sessionmaker(get_engine(), expire_on_commit=False)


def apply_tenant(session: Session, tenant_id: UUID | None) -> None:
    """Bind the current transaction to one tenant and drop to the unprivileged role."""
    session.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": str(tenant_id) if tenant_id else ""}
    )
    session.execute(text(f"SET LOCAL ROLE {APP_ROLE}"))


@contextmanager
def tenant_session(tenant_id: UUID | None) -> Iterator[Session]:
    """Session for request handling. Without a tenant, tenant-private tables return no rows."""
    with _factory()() as session, session.begin():
        apply_tenant(session, tenant_id)
        yield session


@contextmanager
def system_session() -> Iterator[Session]:
    """Privileged session for sign-in, ingestion and schedulers. Never used with caller-supplied filters."""
    with _factory()() as session, session.begin():
        yield session


def tenant_tables() -> dict[str, str]:
    """Tables that carry a tenant: ``strict`` (always private) or ``shared`` (NULL tenant means shared data)."""
    return {
        t.name: ("shared" if t.info.get("rls") == "shared" else "strict")
        for t in Base.metadata.sorted_tables
        if "tenant_id" in t.c
    }


_READ_ONLY_FOR_APP = ("license_records", "connector_runs", "entities", "facts", "calendar_events", "jobs")
_CURRENT = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"


def apply_security(connection) -> None:
    """Create the application role, grants, row-level security policies and the audit guard. Idempotent.

    Runs after every migration so a new tenant table cannot ship without its policy.
    """
    run = lambda sql: connection.execute(text(sql))  # noqa: E731
    run(
        f"DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN "
        f"CREATE ROLE {APP_ROLE} NOLOGIN; END IF; END $$"
    )
    run(f"GRANT {APP_ROLE} TO CURRENT_USER")
    run(f"GRANT USAGE ON SCHEMA public TO {APP_ROLE}")
    run(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {APP_ROLE}")
    run(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {APP_ROLE}")
    existing = {t.name for t in Base.metadata.sorted_tables}
    for table in _READ_ONLY_FOR_APP:
        if table in existing:
            run(f"REVOKE INSERT, UPDATE, DELETE ON {table} FROM {APP_ROLE}")
    run(f"REVOKE UPDATE, DELETE, TRUNCATE ON audit_events FROM {APP_ROLE}")

    def policy(table: str, using: str, check: str) -> None:
        run(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        run(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        run(f"CREATE POLICY tenant_isolation ON {table} USING ({using}) WITH CHECK ({check})")

    for table, mode in tenant_tables().items():
        own = f"tenant_id = {_CURRENT}"
        policy(table, f"tenant_id IS NULL OR {own}" if mode == "shared" else own, own)
    policy("tenants", f"id = {_CURRENT}", f"id = {_CURRENT}")
    member = f"EXISTS (SELECT 1 FROM memberships m WHERE m.user_id = users.id AND m.tenant_id = {_CURRENT})"
    policy("users", member, member)

    run(
        "CREATE OR REPLACE FUNCTION aurex_audit_guard() RETURNS trigger LANGUAGE plpgsql AS $$ "
        "BEGIN RAISE EXCEPTION 'audit_events is append-only'; END $$"
    )
    run("DROP TRIGGER IF EXISTS audit_events_append_only ON audit_events")
    run(
        "CREATE TRIGGER audit_events_append_only BEFORE UPDATE OR DELETE ON audit_events "
        "FOR EACH ROW EXECUTE FUNCTION aurex_audit_guard()"
    )
