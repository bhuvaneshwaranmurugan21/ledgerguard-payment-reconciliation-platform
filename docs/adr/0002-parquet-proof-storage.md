# ADR 0002: Store immutable proofs as run-scoped Parquet

## Status

Accepted for the bounded platform.

## Context

The platform needs analytical output, independent SQL verification, deterministic replay, and
immutable proof revisions. It does not currently need row-level analytical updates, table-level
time travel, or concurrent writers to shared mutable tables.

## Decision

Write normalized data, proofs, and exceptions as Parquet under run- and attempt-scoped prefixes.
Bind authoritative proofs through a manifest and conditional control state. Do not introduce an
open table format without a requirement.

## Consequences

The managed system remains smaller and its commit boundary must be explicit. A future requirement
for mutable analytical tables would trigger a new decision rather than silently expanding scope.
