# ADR-0008: Tenant isolation in the database

- Status: Accepted
- Date: 2026-11-15

## Context

Isolation must hold even when application code forgets a filter.

## Decision

Every tenant table carries `tenant_id`. Request sessions set `app.tenant_id` and switch to the unprivileged `aurex_app` role, under which row-level security policies admit only the tenant's rows (and shared rows with `tenant_id IS NULL`, read-only). Policies are re-applied after every migration so a new table cannot ship without one. Sign-in and background jobs use a privileged session and never take caller-supplied filters.

## Consequences

Isolation from the first release, verified by tests that bypass application filters.

## Alternatives considered

Filtering in application code only; a database per tenant.
