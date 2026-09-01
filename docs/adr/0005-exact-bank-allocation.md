# ADR 0005: Allocate bank movements only by exact settlement reference

## Status

Accepted.

## Context

Bank deposits normally aggregate payments and deductions. They need not contain a payment ID, and
equal amounts or nearby dates do not prove that a bank movement belongs to a processor settlement.
Heuristic matching could make unrelated cash appear reconciled.

## Decision

Bank allocation uses an exact settlement reference after NFC normalization and trimming surrounding
whitespace. Comparison is case-sensitive and preserves punctuation. Policy also restricts permitted
bank accounts.

Multiple unique bank entries may aggregate into one settlement. One bank identity may be allocated
once. Missing, unknown, ambiguous, or disallowed references remain visible; no amount/date fallback
exists.

## Consequences

Some genuine settlements may remain unresolved when bank narration is incomplete. This false-negative
risk is accepted because a visible exception is safer than a false financial match. Introducing an
allocation record or another matching strategy requires a new explicit contract decision.
