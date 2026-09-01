# ADR 0007: Version the corrected contract set and separate enforcement layers

## Status

Accepted for Part 1 Stage 2.

## Context

Stage 0 evidence binds the exact bytes of the original eight `v1` schemas. Stage 1 preserves those
bytes while freezing financial semantics that the schemas do not fully encode. Editing a published
`$id` in place would break historical evidence and make two different contracts claim the same
identity.

JSON Schema also cannot prove arithmetic, cross-record identity, reference existence, allocation,
or append-only history. Treating comments or ignored extension keywords as enforcement would create
a false correctness claim.

## Decision

The original top-level `v1` schemas remain immutable and are classified
`SUPERSEDED_BEFORE_RUNTIME_USE`. Corrected contracts use version `2.0`, distinct `$id` values, and
the `contracts/v2/` directory. The digest-bound active contract registry is the only authority for
contract discovery.

Validation has three explicit layers:

1. JSON Schema validates one-document structure, types, bounds, enums, and conditional shapes.
2. Stage 2 governance validates schema identity, local reference resolution, digests, taxonomy, and
   requirements traceability.
3. Part 2 runtime validation owns checked arithmetic, cross-record identity, references,
   allocation, proof recomputation, and history sequencing.

All references resolve from checked-in resources. Validation must not fetch a schema over the
network.

## Consequences

Historical evidence remains reproducible, while later code has one unambiguous active contract set.
The repository does not claim JSON Schema enforces relational or arithmetic invariants. A future
breaking change must receive a new version and `$id`; changing bytes while retaining an active
identity is forbidden.
