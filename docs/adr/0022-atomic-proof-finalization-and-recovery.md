# ADR 0022: Atomic proof finalization and deterministic recovery

## Status

Accepted for Part 2 Stage 6.

## Decision

Use immutable canonical JSON objects addressed by SHA-256 and one atomically replaced local
control head. A commit is authoritative only when reachable from that head. Serialize writers with
an operating-system file lock and require an exact expected-head comparison before publication.

Persist the attempt request first, then proof and case objects, then the commit, then the head, and
finally the receipt. Flush file contents and containing directories across each durable boundary.
Recover missing receipts from authoritative history. Treat unreachable objects as harmless
non-authoritative remnants that an exact retry may reuse byte-for-byte.

Proofs and cases are append-only chains. Their schema identities and self-digests are verified on
write and read. The authoritative request retains enough admitted state to reconstruct replay and
conflict controls across batches.

## Rationale

A single authority pointer gives transaction and settlement finalization one atomic boundary.
Content addressing detects corruption and prevents in-place history changes. Persisted request
identity makes retries distinguishable from attempt reuse. The write order gives each crash window
a deterministic interpretation without rollback or deletion.

## Rejected alternatives

- Per-proof mutable pointers permit partial batch authority.
- Overwriting a latest proof or case destroys audit history.
- Trusting a receipt without walking authoritative history permits orphaned success claims.
- Retrying solely from the current in-memory state can create a new revision for an already
  committed attempt.
- Amount, time, or arrival-order recovery heuristics weaken identity and are not used.

## Consequences

The local store can leave unreachable immutable files after a crash; they are never authoritative
and do not need destructive cleanup for correctness. Stage 7 must separately prove Spark parity
and any Parquet representation. AWS and infrastructure operations remain forbidden in Stage 6.
