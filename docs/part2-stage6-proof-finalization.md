# Part 2 Stage 6 proof finalization

## Authority model

The local store has one authoritative pointer: `control/HEAD`. Its value is the SHA-256 address of
a canonical commit object. A commit contains the complete proof and case head maps, its parent,
the exact updated-key inventory, the immutable objects written for that transition, and the digest
of the initiating request. Files that are not reachable from `HEAD` have no financial authority.

Writers serialize through a process lock and compare the observed head to `expected_head`. A stale
writer fails with execution ownership. Successful publication is one atomic filesystem replacement
of `HEAD`; no per-proof pointer can become authoritative independently.

## Durable sequence

The enforced order is:

1. canonical attempt request;
2. content-addressed proof and case objects;
3. content-addressed commit;
4. atomic authoritative head replacement;
5. immutable outcome receipt.

Each file is flushed before its parent directory is synchronized. An existing immutable path is
accepted only when its bytes are identical. Temporary files are removed after interrupted replace
operations.

## Proof and case history

Every updated reconciliation key receives exactly one proof revision. Revision one has no
predecessor; each successor increments by one and names the prior proof identity. An initial match
has no case. An initial exception opens a stable case derived from the grain, reconciliation key,
and initial exception proof. Continuing exceptions append `OPEN` revisions. A later match appends
`RESOLVED_BY_LATE_DATA`. Every case revision binds the current proof, retains the original case
identity, and names its exact predecessor.

Historical objects and commits are never rewritten or removed. History verification walks from
`HEAD` to genesis and checks each transition in forward order.

## Recovery and retries

Termination before head publication leaves only non-authoritative request, object, or commit data;
the same attempt can complete deterministically. Termination after head publication is recovered by
finding the exact attempt and request digest in authoritative history and recreating the receipt.
That recovery still works after later commits.

An exact retry returns the original receipt without another revision. Reusing an attempt identity
with different expected head, time, policy, manifest, run, source content, or candidates is rejected.
Two writers with the same expected head cannot both publish.

## State handoff and failure ownership

The request persists the complete admitted records underlying each grain state, including bank
observation multiplicity. Later work reconstructs policy versions, run manifests, source digests,
transaction state, and settlement state from authoritative history only. Policy or run reuse,
source-content conflict, grain contamination, and prior-history removal fail closed.

Admission and financial validation keep their established reason ownership. Failures introduced by
storage, integrity, locking, conditional publication, or recovery use `EXECUTION_FAILURE`,
`NO_AUTHORITATIVE_PARTIAL_PROOF`, and `authoritative_proof: false`.

## Local-only boundary

Canonical JSON is the Stage 6 local persistence representation. This does not replace the accepted
managed Parquet design: Spark/Parquet parity and managed persistence remain later-stage work. The
production finalizer imports no reference oracle, Spark, Parquet, network, AWS, or infrastructure
client.
