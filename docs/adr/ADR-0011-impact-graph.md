# ADR-0011: Market Impact Graph

- Status: Accepted
- Date: 2026-11-15

## Context

Relationship analysis must not present hypotheses as facts.

## Decision

Links require relation, method (reported fact, statistical estimate, analyst-defined, AI-extracted), confidence with its basis, a source reference and a review status; the database rejects links without a source. Statistical links store window and standard error. Scenarios follow accepted transmission and exposure links only; a path's confidence is its weakest link's; every scenario is labeled as not a forecast. Member-defined links are tenant-private and start as proposed.

## Consequences

Every path can be traced to its sources.

## Alternatives considered

Unstructured AI narratives.
