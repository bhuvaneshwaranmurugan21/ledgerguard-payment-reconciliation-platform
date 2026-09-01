# Contract coherence model

## Admission order

Contract data is admitted in one order: strict UTF-8 JSON parsing, recursive NFC normalization,
calendar-aware timestamp canonicalization, active-schema validation, semantic binding validation,
then canonical digest or identity derivation. A later layer cannot repair or reinterpret a failure
from an earlier layer.

The strict parser rejects duplicate and normalization-colliding keys before they become a mapping.
It rejects every decimal or exponent representation, non-finite value, signed-64 overflow, UTF-8
BOM and Unicode surrogate. Booleans remain booleans and cannot satisfy an integer requirement.

## Canonical bytes

Objects are emitted as UTF-8 JSON with NFC strings, Unicode-code-point key order, no insignificant
whitespace and no ASCII escaping. Arrays retain their declared order. Offset-aware timestamps are
validated against the Gregorian calendar, converted to UTC, rendered with `Z`, limited to six
fractional digits and stripped only of trailing fractional zeroes.

Digest scopes exclude their own digest field. Source business digests additionally exclude
`received_at` and `source_batch_id`, keeping transport lineage outside financial identity. Golden
vectors freeze both canonical bytes and SHA-256 results.

## Linked authority chain

The policy digest binds the complete interpretation. A manifest binds the same policy version and
digest, source commit, four exact source families and each immutable object. A proof binds the
manifest digest, policy digest, run, grain key and proof identity. An exception case derives its
stable identity from the initial exception proof and later revisions bind the immediately preceding
case-revision digest.

No artifact may substitute a valid but unrelated policy, manifest, proof or case. Every family in a
manifest resolves through the active-contract registry rather than directory discovery.

## Validation ownership

Stage 3 is a contract oracle, not a reconciliation engine. It proves byte interpretation,
cross-contract domains, reference fragments, linked identities, traceability, preservation and
failure behavior. Part 2 remains responsible for record-set arithmetic, balance, allocation,
replay state and authoritative proof production.
