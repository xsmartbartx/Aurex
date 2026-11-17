# ADR-0010: License register and four enforcement points

- Status: Accepted
- Date: 2026-11-15

## Context

Provider terms differ for display, export, API redistribution and use with AI.

## Decision

Each dataset references a license record with flags per channel, required delay, expiry and attribution. Enforcement: ingestion refuses datasets without a record; retrieval filters by the caller's data-class entitlements and the channel (`display`, `api`, `export`, `model_external`, `model_local`); AI tools retrieve only data cleared for the engine's channel; outputs carry freshness and attribution. Usage per dataset, tenant and channel is counted for licensor reporting.

## Consequences

License compliance by construction.

## Alternatives considered

Manual review of uses.
