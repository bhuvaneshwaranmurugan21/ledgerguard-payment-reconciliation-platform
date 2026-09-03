# ADR 0019: Production admission and normalization

- Status: accepted for the Part 2 Stage 3 candidate
- Scope: local, read-only production admission
- Supersedes: no contract or prior decision

## Context

The Stage 2 oracle can calculate independent expected outcomes, but production still needs a
separate fail-closed boundary between source bytes and reconciliation. That boundary must reject
untrusted transport, schema, identity, policy, and financial-shape defects before any transaction
or settlement calculation begins. It cannot import the oracle or create proof, case, revision,
persistence, Spark, network, or AWS effects.

The accepted v2 schemas deliberately describe records rather than a source-file wire protocol.
Stage 3 therefore owns the smallest transport decisions needed to admit a manifest-bound local
bundle without changing any accepted schema.

## Decision

Production admission lives in `ledgerguard.reconciliation`, separately from
`ledgerguard_reference_oracle`. The active registry file is accepted only at its frozen SHA-256.
Every registered schema is then checked against its registry digest, family, `$id`, Draft 2020-12
dialect, and resolvable local references. Network schema resolution is forbidden.

Policy and manifest are strict JSON documents. Source objects are strict UTF-8 JSON Lines using LF
framing; CR bytes and blank records are invalid. A one-or-more-record object may omit its final LF.
Because the accepted manifest requires positive `size_bytes` while permitting `record_count` zero,
an explicitly empty object has exactly one byte: LF (`0a`). Any other byte representation with a
zero record count is an identity mismatch. Size and SHA-256 are checked before parsing; count is
checked before schema admission.

Local locators are POSIX-relative paths confined beneath one resolved input root. Absolute paths,
parent traversal, symlinks, escaped resolution, missing objects, non-files, and read errors fail
admission. Stage 3 reads each source object once. S3 locators have a stable identity model but the
local Stage 3 command does not fetch them.

All strings normalize to NFC. Timestamps normalize to RFC 3339 UTC. JSON numbers are integers only
and every integer must fit signed 64-bit range. Booleans never count as integers. All money and
journal aggregates use checked signed 64-bit operations.

The policy digest, version reuse, permitted-account domain, manifest digest, policy binding, run
reuse, exact family inventory, locator uniqueness, and exact supplied-object set are checked before
records can be returned. Each record then passes its active schema, business-digest, frozen source
identity, replay/conflict, and family-specific checks. Journals must balance and have exactly one
transaction or settlement business key. The count of processor-clearing postings is retained as a
semantic annotation; a wrong count is not mislabeled as a structural balance failure.

Transaction and settlement keys use the accepted component sets. Currency must be consistent for
the same pre-currency business domain. Bank references receive only NFC normalization and outer
whitespace trimming: case and punctuation remain significant. A reference that maps to multiple
settlement targets, or a settlement identifier whose merchant/currency scope is not unique, fails
as `AMBIGUOUS_BANK_ALLOCATION`. An unknown reference remains admitted so Stage 5 can classify it as
unmatched rather than Stage 3 guessing a target.

Admission constructs candidate state in memory and publishes it only with a completely admitted
bundle. The caller's prior immutable state is never mutated. Equivalent redelivery is counted and
omitted from the new-record sequence; changed content under an existing source identity fails.
Admitted records, state, policy bytes, and manifest bytes are immutable and deterministically
ordered. Neither success nor failure can claim or persist an authoritative proof.

## Consequences

Stage 4 can consume schema-valid, canonical, keyed transaction inputs without repeating transport
interpretation. Stage 5 receives normalized settlement inputs without heuristic bank allocation.
Later persistence must supply the same immutable state semantics; Stage 3 does not pretend that its
in-memory candidate is a durable store.

Rejecting unstable reads and symlinks reduces ambiguity but does not make the local command a
privileged file-ingestion service. Its directory must still be controlled by the caller. Managed
object-store retrieval, snapshotting, and durable replay state remain future implementation work.

## Rejected alternatives

- Reusing the reference oracle in production would destroy the independence needed for differential
  validation.
- Trusting registry paths without digests would permit contract drift.
- Floating-point money, lenient JSON, guessed encodings, or unbounded integers would make canonical
  identity and totals non-deterministic.
- Lowercasing or stripping punctuation from bank references would collapse distinct external
  identifiers.
- Incrementally mutating replay state would leave partial admission after a late failure.
- Emitting placeholder proofs would violate the accepted failure and finalization boundary.
