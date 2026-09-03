# ADR 0021: Settlement reconciliation and exact bank allocation

- Status: accepted for the Part 2 Stage 5 candidate
- Scope: local production settlement calculation only

## Context

Stage 4 produces transaction candidates but intentionally performs no settlement calculation or
bank allocation. Stage 3 admits settlement records and normalizes bank references, but its unique
observation view cannot distinguish a bank identity repeated inside one manifest from an identical
record replayed from prior state. A bank record also lacks processor and settlement-cycle fields,
so an unknown reference cannot safely be assigned to an arbitrary settlement grain.

## Decision

Stage 5 consumes the immutable Stage 3 admission boundary directly and does not reinterpret Stage
4 transaction candidates. Admission retains an additive, immutable occurrence view. Existing
new-effect and unique-observation views and their digests remain unchanged. Multiple occurrences
of one bank identity in a new manifest produce one financial contribution and
`DUPLICATE_BANK_MOVEMENT`; one observation of a record already present in prior state remains an
idempotent replay. Duplicate diagnostics are retained in settlement state so a later batch cannot
erase an already-observed duplicate merely by replaying or omitting that identity.

Settlement keys contain processor, merchant, settlement identifier, settlement cycle, and
currency. Processor and settlement-journal records form a full outer key union. Every processor
record recomputes gross less fee, refund, chargeback, and reserve with checked signed 64-bit
operations. Reported net is validated per record before recomputed values are aggregated, so
offsetting reporting errors cannot conceal `SETTLEMENT_FORMULA_MISMATCH`.

Settlement clearing movement uses only `PROCESSOR_CLEARING` postings, with credit positive and
debit negative. A wrong clearing-posting count is `INVALID_ACCOUNT_ROLE`; total journal debit is
never substituted for the designated movement.

Bank allocation first builds the complete target index from processor and journal settlement keys.
The lookup is merchant, currency, and the settlement identifier after NFC normalization and outer
whitespace trimming. Case and punctuation remain significant. Zero targets leave the movement
unallocated; multiple targets fail admission before any candidate is returned. Amount, date,
arrival order, or proximity never select a target.

Every unique bank identity has exactly one allocation-ledger disposition. A missing reference is
`UNALLOCATED_MISSING_REFERENCE`; an unknown reference is `UNALLOCATED_UNKNOWN_REFERENCE`. Both
carry `UNALLOCATED_BANK_MOVEMENT` and never contribute to a candidate bank total. This diagnostic
is owned once by the reconciliation batch rather than copied onto unrelated settlement grains.
An exact-reference record from a disallowed account remains visible in diagnostic bank totals but
forces `INVALID_BANK_ACCOUNT`, so it cannot authorize `MATCHED`.

Candidates preserve the three pairwise signed deltas and define difference as their maximum
checked absolute value. Semantic reasons force `EXCEPTION`. Only otherwise can zero be `MATCHED`,
or a nonzero difference inside the currency settlement tolerance be `WITHIN_TOLERANCE`.

## Boundary

Stage 5 returns immutable, deterministic, non-authoritative candidates, allocation records, and
in-memory state. It does not assign proof identity, finalize or persist proof, create revisions,
execute Spark, access a network or AWS API, or mutate infrastructure. Production never imports the
independent reference oracle.

## Rejected alternatives

- Treating duplicate delivery as additional cash would double financial effect.
- Treating all same-identity observations as duplicates would break idempotent replay.
- Attaching an unknown bank movement to every settlement in a merchant/currency domain would
  create false exceptions and repeated ownership.
- Lowercasing, punctuation removal, amount matching, or date matching would create false matches.
- Aggregate-only processor formula validation would allow row-level errors to cancel.
- Emitting a placeholder proof would violate the accepted atomic finalization boundary.
