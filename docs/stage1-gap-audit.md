# Stage 1 financial-semantics gap audit

## Audited boundary

- Completed Stage 0 merge: `9a920a300b50fe46bb534e7fc9f32ad5eda1224c`
- Completed Stage 0 tree: `738221ba63364837f12c2ce3279b0514db08f2e5`
- Rejected Stage 1 draft parent: `7f36c7cd0e093f75e1e97cb99ba28d7fb4d69d07`
- Rejected Stage 1 draft tree: `3a97aa68828b401820a03a3c72d9a70e9568a68f`
- Financial schemas changed by Stage 1: no
- Managed AWS execution or infrastructure mutation: no

The pre-integration Stage 1 draft proved semantic intent in isolation but predated the completed
Stage 0 baseline. It could not be merged safely because five overlapping status, audit, validator,
and test files had incompatible histories. Stage 1 was reconstructed on the exact Stage 0 tree.

## Executable-readiness gaps

The initial foundation validator proved inventory, schema metastructure, selected constants, and
repository policy. It did not prove that the financial contracts had one executable interpretation.
The following gaps were reproduced before the Stage 1 decisions were frozen.

| Gap | Reproduced behavior | Stage 1 decision | Later contract action |
|---|---|---|---|
| Nullable negative-event reference | `reference_event_id: null` satisfies the required property | Negative events require one non-null exact capture reference | Encode conditional non-null reference |
| Optional journal entry type | Journal without `entry_type` validates | Entry type is mandatory | Add it to required properties |
| Dual-grain journal | Payment and settlement IDs can both be present | Exactly one applicable business key is allowed | Encode entry-type-dependent exclusivity |
| Missing journal processor | Journal context does not identify processor | Processor and ledger-system namespace are required | Extend journal context |
| Incomplete policy | Signs, roles, reference rules, and bank allocation are absent | Policy owns all financial interpretation | Extend policy contract |
| Transaction proof bank placeholder | Transaction proof requires `bank_minor` | Transaction proofs contain processor and ledger totals only | Add grain-specific proof structures |
| Settlement difference collapse | One difference hides three-way disagreement | Preserve three signed pairwise deltas and maximum difference | Extend settlement proof totals |
| Case grain absent | One key string can collide across grains | Grain is part of case identity | Extend case revision contract |
| Open reason strings | Arbitrary reason values validate | Reason taxonomy is closed | Enumerate reason classes |
| Undefined digest scope | Transport values and digest self-reference are unspecified | Canonical digest excludes digest and transport metadata | Encode canonicalization |
| Bank allocation ambiguity | Missing references have no explicit outcome | Unknown references stay unallocated; ambiguity fails admission | Encode bank and policy rules |
| Manifest location mismatch | Only S3 locations are accepted | Local and object-storage identities must be honest | Extend manifest identity |
| Failure-ownership contradiction | Currency contamination was both admission failure and finalized exception | Unsafe currency combinations authorize no proof | Preserve admission ownership |
| Stale Stage 1 baseline | Draft Stage 1 predated completed Stage 0 | Bind Stage 1 to the exact Stage 0 tree and validator digest | Preserve Stage 0 in every later stage |
| Shared-audit digest collision | Draft Stage 1 appended to Stage 0's digest-bound audit | Stage-specific audits are immutable and separate | Keep evidence ownership explicit |

## Stage 1 disposition

The financial meaning of every listed gap is frozen in
[`financial-semantics-v1.json`](../spec/financial-semantics-v1.json). The existing schemas are not
silently edited in this stage. Their incompatible corrections remain explicit contract work, and
the overall foundation remains a correction candidate until those changes and the final Part 1
coherence gates pass.

Stage 1 adds a digest-bound completion contract, a fail-closed validator, and adversarial
specification tests. It preserves the exact Stage 0 contract and audit, adds no reconciliation
engine, and makes no AWS or managed-execution claim.
