# ADR-0007: Agent permissions

- Status: Accepted
- Date: 2026-11-15

## Context

Documents and uploads can contain instructions aimed at the model.

## Decision

A tool registry declares each tool's schema, side-effect class and entitlement. Agents have allow-lists, act with the requesting user's scope, and run under step, time and tool-call budgets. Read-only tools only; side effects (sharing, changing theses or limits) happen in the interface on the user's action. Retrieved passages are screened and flagged text is withheld.

## Consequences

Least privilege; injection cannot trigger actions.

## Alternatives considered

Agents with broad access.
