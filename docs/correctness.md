# Correctness model

## Financial truths

LedgerGuard compares processor evidence, internal ledger evidence, and bank evidence. None is
silently designated correct merely because another source is absent. Reconciliation exposes both
agreement and the exact unexplained difference.

## Monetary representation

- All monetary values are signed or unsigned integers in the currency's minor unit as defined by
  the active policy.
- A currency is part of every reconciliation key.
- Cross-currency addition is forbidden.
- Foreign exchange conversion requires a separate rate, source, timestamp, and policy and is not
  included in the current project.
- A nonzero tolerance produces `WITHIN_TOLERANCE`, not `MATCHED`, and the tolerated amount remains
  visible.

## Immutable identity

Each source record is permanently bound to one canonical payload digest. An identical redelivery
has no second business effect. The same identity with different content is a conflict. A file name,
row position, arrival order, or retry attempt is not a business identity.

## Journal validity

Every journal has at least two one-sided postings. Total debits equal total credits and are
positive. Reconciliation reads movement from the required account roles; journal balance alone
cannot prove correct payment treatment.

## Transaction reconciliation

For a transaction key and currency, signed processor event movement must equal the movement of the
policy-selected ledger accounts.

Captures contribute positive captured value. Refunds, chargebacks, and reversals contribute
negative economic movement according to explicit reference and account-role rules. A missing
reference produces an unresolved exception and never invents an original event.

## Settlement reconciliation

For a settlement key and currency:

```text
expected_net_minor = gross_minor
                   - fee_minor
                   - refund_minor
                   - chargeback_minor
                   - reserve_minor
```

The following values must agree under the active policy:

1. Processor expected net settlement.
2. Relevant internal clearing-account movement.
3. Aggregate bank cash movement.

Multiple bank entries may satisfy one settlement. One bank entry may not be assigned to multiple
settlements unless an explicit allocation record is introduced in a later contract.

## Late and out-of-order data

An event may arrive after an earlier reconciliation. Historical proof is never edited. The system
creates a new proof revision that names its predecessor and the new source manifest. An unresolved
reference may become resolved only when the required record arrives and the complete reconciliation
is repeated.

## Policy versioning

Currency exponents, account-role mappings, tolerance, deductions, reference rules, and settlement
formulas belong to a versioned policy. Reprocessing under a changed policy creates a new proof; it
does not reinterpret an old proof in place.

## Case revisions

Exception history is append-only. Automatic execution may open a case and resolve it through late
or corrected data. Accepted variance and write-off require an authorized operator boundary that is
modeled but remains outside the bounded managed workload.

## Failure atomicity

A failed parse, schema validation, identity validation, journal validation, reconciliation, or
evidence-finalization step cannot produce an authoritative partial proof. Temporary output may
exist under an attempt-scoped path but must not be referenced by finalized control state.

## Required reason classes

- `IDENTITY_CONFLICT`
- `SCHEMA_VIOLATION`
- `UNBALANCED_JOURNAL`
- `INVALID_ACCOUNT_ROLE`
- `UNRESOLVED_REFERENCE`
- `MISSING_LEDGER_MOVEMENT`
- `MISSING_PROCESSOR_ACTIVITY`
- `MISSING_BANK_SETTLEMENT`
- `DUPLICATE_BANK_MOVEMENT`
- `FEE_MISMATCH`
- `CURRENCY_DOMAIN_VIOLATION`
- `POLICY_MISMATCH`
- `SOURCE_IDENTITY_MISMATCH`
- `EXECUTION_FAILURE`

Part 2 may add reason classes only with a contract update, tests, and documentation.
