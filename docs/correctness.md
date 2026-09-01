# Correctness model

## Authority and claim boundary

This document defines LedgerGuard's financial semantics. The machine-readable companion is
[`financial-semantics-v1.json`](../spec/financial-semantics-v1.json). If prose and the specification
disagree, the discrepancy is a defect; neither silently overrides the other.

The semantics and acceptance examples are locally validated. No reconciliation engine or managed
reconciliation is claimed by this stage.

## Glossary

| Term | Definition |
|---|---|
| Source record | Immutable evidence received from one source system |
| Source identity | Family- and source-qualified identity used for replay and conflict detection |
| Business identity | Financial grouping identity used for reconciliation |
| Transaction grain | Processor event class compared with relevant ledger movement for a payment |
| Settlement grain | Processor payout net compared with clearing movement and bank cash |
| Policy | Versioned currency, sign, role, tolerance, reference, and bank-allocation rules |
| Proof | Immutable, policy- and source-bound reconciliation result |
| Case | Append-only exception history linked to an initial exception proof |
| Replay | Same source identity and same canonical business payload |
| Identity conflict | Same source identity with a different canonical business payload |
| Late data | Required evidence received after an earlier proof was finalized |
| Finalization | Conditional act that makes a fully validated proof authoritative |

`Balanced`, `matched`, `settled`, `resolved`, and `finalized` are distinct states. For example, a
journal can be balanced but financially wrong, and an exception can be finalized without being
resolved.

## Independent financial truths

Processor, internal ledger, and bank records remain independent. LedgerGuard never mutates a source
record or silently designates a source correct because another source is absent. It reconstructs
each source's economic movement and exposes exact agreement or disagreement.

Record counts are provenance, not reconciliation proof. Counts are retained to distinguish a
genuine zero from missing evidence.

## Monetary representation

- Money is an integer in the currency's minor unit.
- Currency is part of every reconciliation key.
- Floating-point monetary values are forbidden.
- Cross-currency aggregation is forbidden.
- Foreign-exchange conversion is outside the project boundary.
- Summation must detect signed 64-bit overflow and fail admission rather than wrap.
- Tolerances are non-negative integer minor-unit values.
- Currency exponent and tolerance are policy-controlled.

The bounded policy supports INR and USD with exponent two and JPY with exponent zero. An
unsupported currency or an incomplete currency policy is an admission failure.

## Time semantics

- `occurred_at` is processor business-event time.
- `effective_at` is ledger-effective time.
- `value_at` is bank-value time.
- `received_at` is ingestion time.
- `created_at` is proof or case creation time.

Canonical timestamps use RFC 3339 UTC. Arrival order can determine which manifest contains a
record, but cannot change the record's economic identity. Proof creation time is not part of a
reconciliation key or proof identity.

## Canonical identity

Source identities are namespaced:

| Family | Identity components |
|---|---|
| Processor event | Family, processor, source record ID |
| Processor settlement | Family, processor, source record ID |
| Ledger journal | Family, ledger system, journal ID |
| Bank entry | Family, bank account ID, bank record ID |

The business-payload digest uses SHA-256 over canonical UTF-8 JSON with NFC Unicode normalization,
lexicographically ordered object keys, and canonical UTC timestamps. It excludes the digest field
itself and transport-only `received_at` and `source_batch_id` values.
Canonicalization rejects distinct object keys that collide after Unicode normalization.

```text
same source identity + same business digest = identical replay
same source identity + different business digest = IDENTITY_CONFLICT
```

File name, row position, arrival order, and retry attempt are not business identities. A separate
full-record digest may retain transport lineage without changing replay semantics.

## Journal validity

Every journal must:

- contain at least two postings;
- have unique line identifiers;
- contain only positive, one-sided posting amounts;
- use one currency;
- have total debits equal total credits and greater than zero;
- declare entry type, processor, and exactly one applicable business key; and
- use the business-key type permitted for its entry type.

Capture, refund, chargeback, and reversal journals belong to a payment. Settlement, fee, and reserve
journals belong to a settlement. A journal cannot silently belong to both grains.

Journal balance is necessary but insufficient. A balanced journal without the policy-required
account role or posting side produces `INVALID_ACCOUNT_ROLE`.

## Transaction reconciliation

### Grain and key

The transaction key contains processor, merchant, payment, event class, and currency. Its canonical
identifier is `txn:` followed by the SHA-256 digest of the canonical structured key. Proofs retain
the inspectable components as well as the digest.

### Processor movement

| Event class | Normalized movement |
|---|---:|
| Capture | `+amount_minor` |
| Refund | `-amount_minor` |
| Chargeback | `-amount_minor` |
| Reversal | `-amount_minor` |

### Reference rules

Refunds, chargebacks, and reversals reference an exact capture identity. Negative-event reference
chains are forbidden. A missing capture produces `UNRESOLVED_REFERENCE`; the system never invents
an original event. Cumulative negative application against one capture cannot exceed its captured
amount and otherwise produces `OVER_APPLIED_REFERENCE`.

Multiple captures may share a payment ID. Each negative event remains bound to one exact capture.

### Ledger movement

The transaction view reads `PROCESSOR_CLEARING` movement as:

```text
ledger_minor = clearing_debits - clearing_credits
```

Thus a capture clearing debit is positive and a refund, chargeback, or reversal clearing credit is
negative. Policy also defines the allowed counterpart roles; total journal debit is never used as a
substitute for the relevant account movement.

### Comparison

```text
processor_ledger_delta_minor = processor_minor - ledger_minor
difference_minor = abs(processor_ledger_delta_minor)
```

Missing processor and ledger counts remain explicit. An absent source is not silently converted to
a genuine zero.

## Settlement reconciliation

### Grain and key

The settlement key contains processor, merchant, settlement ID, settlement cycle, and currency. Its
canonical identifier is `stl:` followed by the digest of the structured key. Within the bounded
domain a settlement ID is unique for merchant and currency; incompatible reuse is a conflict.

### Processor expected net

```text
expected_net_minor = gross_minor
                   - fee_minor
                   - refund_minor
                   - chargeback_minor
                   - reserve_minor
```

The value is recomputed. A reported value that differs produces `SETTLEMENT_FORMULA_MISMATCH` and
prevents `MATCHED`, even when ledger and bank equal the recomputed result. Expected net may be
positive, zero, or negative.

### Clearing movement

Settlement clearing orientation is intentionally opposite to transaction orientation:

```text
ledger_clearing_minor = clearing_credits - clearing_debits
```

A positive payout settlement reduces the clearing receivable through a credit and is normalized
positive. A negative settlement uses a clearing debit and is normalized negative.

### Bank movement and allocation

Bank credit is positive and bank debit is negative. Allocation uses only an exact settlement
reference after NFC normalization and trimming surrounding whitespace. Matching is case-sensitive,
preserves punctuation, and checks policy-permitted bank accounts.

Multiple bank entries may aggregate into one settlement. One bank identity may be allocated once.
Missing or unknown references remain `UNALLOCATED_BANK_MOVEMENT`; equal amount or nearby date cannot
force a match. If one normalized reference identifies multiple settlement candidates, allocation
fails admission and the bank entry is allocated to neither candidate.

### Three-way differences

```text
processor_ledger_delta_minor = processor_net_minor - ledger_clearing_minor
processor_bank_delta_minor = processor_net_minor - bank_minor
ledger_bank_delta_minor = ledger_clearing_minor - bank_minor
```

```text
difference_minor = max(
    abs(processor_ledger_delta_minor),
    abs(processor_bank_delta_minor),
    abs(ledger_bank_delta_minor)
)
```

A zero-net settlement may legitimately have no clearing or bank record if no semantic error exists.
A nonzero expected net with no allocated bank record produces `MISSING_BANK_SETTLEMENT`.

## Status and tolerance

- `MATCHED`: difference is zero and no reason code exists.
- `WITHIN_TOLERANCE`: difference is nonzero, no semantic failure exists, and the difference is at
  most the grain- and currency-specific tolerance. `TOLERATED_DIFFERENCE` remains visible.
- `EXCEPTION`: a semantic reason exists or difference exceeds tolerance.

Tolerance cannot hide admission, identity, missing-evidence, reference, policy, formula, or account
role failures. A zero monetary difference cannot override a semantic exception.

## Grain-specific proof semantics

A transaction proof contains processor and ledger totals, their delta and counts. It contains no
placeholder bank total.

A settlement proof contains processor net, clearing movement, bank movement, all three signed
pairwise deltas, maximum absolute difference, and contributing counts.

Proof identity binds grain, reconciliation key, revision, source-manifest digest, and policy digest.
Creation time is excluded. Historical proof revisions are immutable.

## Policy identity

Each proof binds `policy_version` and `policy_sha256`. Reusing one version with different content is
`POLICY_MISMATCH`. A legitimate changed policy creates a new policy-bound proof revision and never
reinterprets an old proof in place.

Policy owns currency exponents, tolerances, event signs, ledger roles and sides, counterpart roles,
reference rules, capture capacity, bank normalization, permitted bank accounts, settlement formula,
and late-data strategy.

## Case revisions

Case identity contains grain, reconciliation key, and initial exception proof. History is
append-only. Revisions are sequential and every revision after one names its predecessor.

The system may open a case or resolve it through late data or corrected data. Accepted variance and
write-off require an authorized operator boundary and cannot be produced by a system actor.

Late evidence triggers complete reconciliation and a new proof revision. It never erases the prior
exception or case revision.

## Failure atomicity

Schema, identity, currency, policy, journal-balance, source-identity, and ambiguous-allocation
failures belong to admission and cannot authorize a proof. Financial differences produce explicit
exception proofs. Worker and finalization failures belong to execution and cannot masquerade as
missing money.

Temporary attempt output becomes authoritative only after complete validation and successful
conditional finalization. No failed attempt may authorize a partial proof.

## Executable examples

The worked examples are explained in [`financial-examples.md`](financial-examples.md) and encoded in
[`financial-examples-v1.json`](../spec/financial-examples-v1.json). Their acceptance checks live in
`tests/test_financial_semantics_spec.py`; they are specification tests, not an implementation claim.
