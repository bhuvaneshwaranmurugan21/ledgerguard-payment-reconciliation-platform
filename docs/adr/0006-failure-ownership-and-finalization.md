# ADR 0006: Separate admission, financial, and execution failures

## Status

Accepted.

## Context

A malformed source record, a real monetary difference, and a failed worker require different
responses. Collapsing them into one generic exception can mislabel operational failure as missing
money or publish a proof from incomplete evidence.

## Decision

Schema, identity, currency, policy, journal-balance, source-identity, and ambiguous-allocation
failures belong to admission and cannot authorize proofs. Interpretable source disagreements belong
to financial reconciliation and produce explicit exception proofs. Worker, storage, lock, and
finalization failures belong to execution.

Attempt-scoped output becomes authoritative only after complete validation and successful conditional
finalization. A failed admission or execution attempt cannot publish an authoritative partial proof.

## Consequences

Failures require precise ownership, reason, source identity, run identity, and unchanged authoritative
state where applicable. Temporary output may exist after failure, but consumers cannot discover it
through finalized control state.
