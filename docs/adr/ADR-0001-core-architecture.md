# ADR-0001: Layered modular architecture

- Status: Accepted
- Date: 2026-11-15

## Context

The standards adopted for AUREX prescribe a layered modular architecture and reject both an unstructured monolith and early microservices.

## Decision

Code is organized in layers — system interface, pipeline, security, product modules, platform modules, core — with dependencies pointing downward. Modules communicate through defined interfaces and share no mutable state.

## Consequences

Clear ownership and testable boundaries for a small team; extraction of services stays possible later.

## Alternatives considered

Unstructured monolith (coupling); microservices from the start (operational cost without measured need).
