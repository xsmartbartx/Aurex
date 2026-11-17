# ADR-0006: Evidence-first AI

- Status: Accepted
- Date: 2026-11-15

## Context

Cited AI answers are no longer distinctive; verifiable ones are.

## Decision

The language model plans, chooses tools and writes; it never originates figures. Tools record evidence (passages, facts, observations, calculations, graph links) in a ledger. A verifier checks each statement's citations and figures against the ledger, withholds unsupported statements and labels inference. Every answer is stored with its data cut-off and engine version and can be reproduced. Models are reached only through `modules.integration`; without a model key an offline engine writes template statements from the same evidence.

## Consequences

Numeric fidelity and reference resolution are testable release metrics.

## Alternatives considered

Free-form chat over retrieved text.
