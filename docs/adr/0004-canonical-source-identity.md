# ADR 0004: Separate canonical source identity from transport lineage

## Status

Accepted.

## Context

The same financial record can arrive in another batch or at another ingestion time. Treating batch,
file, row, or receipt time as business identity would create a second financial effect. Conversely,
reusing a source identity with a changed amount, currency, reference, or posting must not be treated
as harmless replay.

Digest fields also cannot include themselves, and visually equivalent Unicode must not generate
different identities.

## Decision

Source identity is qualified by record family and source-system namespace. A business-payload digest
uses SHA-256 over canonical UTF-8 JSON with NFC Unicode normalization, ordered keys, and canonical UTC
timestamps. It excludes `payload_sha256`, `received_at`, and `source_batch_id`.

Identical source identity and business digest is idempotent replay. Identical source identity with a
different business digest is `IDENTITY_CONFLICT` and blocks authoritative processing.

A separate full-record digest may retain transport lineage.

## Consequences

Replay remains stable across redelivery and batching. Changed economic content fails closed. Schema
and implementation work must use one canonicalization routine and adversarially test Unicode,
timestamps, exclusions, and changed payloads.
