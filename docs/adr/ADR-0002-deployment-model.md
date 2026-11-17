# ADR-0002: One artifact, several processes

- Status: Accepted
- Date: 2026-11-15

## Context

AUREX must run locally, self-hosted and as a cloud service, operated by a small team.

## Decision

One backend image runs as API, worker and migration job; the web terminal is a second image that only calls the public API. Boundaries are enforced by import-linter contracts in CI, not by network separation. A component is extracted only when measured load needs independent scaling, isolation is required for security (a future user-code runner), or a contract needs a separate release cycle.

## Consequences

Lowest operating cost; the same build in every mode; architecture rules stay enforceable.

## Alternatives considered

Separate services per module; a serverless split.
