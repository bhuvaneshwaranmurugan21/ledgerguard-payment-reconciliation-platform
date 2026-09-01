# ADR 0003: Represent late data as immutable revisions

## Status

Accepted.

## Context

Settlement files, bank statements, reversals, and corrections may arrive after an earlier proof.
Editing the earlier result would destroy the history required to explain when and why a financial
difference existed.

## Decision

Every reconciliation result is immutable. New source data or a changed policy creates a new proof
revision that names its predecessor, source manifest, and policy. Case history is append-only.

## Consequences

Consumers must resolve the current revision through control state while retaining access to prior
evidence. Late data may resolve an exception but never erases its earlier existence.
