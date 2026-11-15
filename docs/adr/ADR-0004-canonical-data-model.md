# ADR-0004: Canonical data model with provenance and point in time

- Status: Accepted
- Date: 2026-11-15

## Context

Six modules need one view of instruments, entities, observations, documents and facts, and research must be reproducible.

## Decision

Connectors produce canonical batches (`core/canonical.py`). Every value belongs to a dataset with a license record. Observations keep reference time, the time they became known and a version; corrections add versions. Facts keep the filing date. Money uses Decimal with an explicit currency.

## Consequences

Backtests and answer reproduction can read data as it was known; no value exists without its source and license.

## Alternatives considered

A separate model per module; overwriting revised values.
