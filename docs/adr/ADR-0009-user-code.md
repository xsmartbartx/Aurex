# ADR-0009: No user code until an isolated runner exists

- Status: Accepted
- Date: 2026-11-15

## Context

Notebooks and scripts are the largest attack surface in a quant product.

## Decision

User-defined logic is declarative: strategies and indicators are definitions with bounded parameters evaluated by the financial engine. A sandboxed runner (no credentials, no network, data only through the API with the user's token, quotas) is a prerequisite for notebooks and must pass the pentest flow first.

## Consequences

Quant features ship without executing arbitrary code.

## Alternatives considered

Executing user code in the application process.
