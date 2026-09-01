# ADR 0008: Put strict canonical admission before schema validation

## Status

Accepted.

## Context

JSON Schema describes values rather than their original JSON number representation. A decimal such
as `1.0` can therefore satisfy an integer schema, and date-time format handling depends on validator
capabilities. Financial identity cannot vary with parser defaults or accept an impossible calendar
date. Independent schemas also cannot prove that policy, manifest, proof and case artifacts refer to
one another.

## Decision

LedgerGuard uses a strict JSON admission profile before active-schema validation. Only signed-64
integer tokens are accepted for numbers; decimal, exponent and non-finite tokens fail. Duplicate,
NFC-colliding and surrogate-containing Unicode fails. Timestamps use explicit calendar-aware RFC
3339 normalization.

Canonical UTF-8 bytes and explicit top-level exclusions define every SHA-256 digest. Transaction,
settlement, proof and case identifiers are domain-prefixed hashes of frozen component objects. The
Stage 3 oracle validates the complete policy → manifest → proof → case binding and resolves every
JSON-reference fragment offline.

## Consequences

Equivalent encodings produce one identity, while ambiguous or permissively parsed inputs fail
before financial processing. Historical v1 and active v2 contracts remain immutable. The added
oracle is local contract governance and does not authorize reconciliation execution or AWS work.
