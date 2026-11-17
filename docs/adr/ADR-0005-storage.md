# ADR-0005: PostgreSQL for everything at this stage

- Status: Accepted
- Date: 2026-11-15

## Context

Time series, full-text search, a job queue and an audit trail are needed; every extra component adds backup, security and license work.

## Decision

PostgreSQL 17 is the system of record, full-text search (generated tsvector columns), the job queue (`FOR UPDATE SKIP LOCKED`) and the audit store. No cache, broker or vector store yet. TimescaleDB and Redis were reviewed: Timescale's license forbids offering the database as a service, and Redis 8's licenses need a deliberate choice (Valkey is the BSD alternative) — neither is needed at current volumes.

## Consequences

One backup and security model; no license constraints on the cloud mode.

## Alternatives considered

TimescaleDB, Redis or Valkey, a dedicated search engine, a message broker.
