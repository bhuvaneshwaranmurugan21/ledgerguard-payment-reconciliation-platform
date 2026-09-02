# Active failure model

## Ownership rule

LedgerGuard separates admission failures, financial exceptions, and execution failures. Ownership
determines whether an authoritative proof is permitted.

### Admission failures

Admission failures make the source set unsafe to interpret and block authoritative proofs for the
run:

- `SCHEMA_VIOLATION`
- `IDENTITY_CONFLICT`
- `UNBALANCED_JOURNAL`
- `CURRENCY_DOMAIN_VIOLATION`
- `POLICY_MISMATCH`
- `SOURCE_IDENTITY_MISMATCH`
- `AMBIGUOUS_BANK_ALLOCATION`

Rejection evidence may be retained, but it is not a reconciliation proof.

### Financial exceptions

Interpretable financial disagreement produces a finalized exception proof and, when applicable, an
open case:

- `INVALID_ACCOUNT_ROLE`
- `UNRESOLVED_REFERENCE`
- `OVER_APPLIED_REFERENCE`
- `MISSING_LEDGER_MOVEMENT`
- `MISSING_PROCESSOR_ACTIVITY`
- `MISSING_BANK_SETTLEMENT`
- `UNALLOCATED_BANK_MOVEMENT`
- `INVALID_BANK_ACCOUNT`
- `DUPLICATE_BANK_MOVEMENT`
- `SETTLEMENT_FORMULA_MISMATCH`
- `PROCESSOR_LEDGER_MISMATCH`
- `PROCESSOR_BANK_MISMATCH`
- `LEDGER_BANK_MISMATCH`

### Execution failures

Worker, temporary storage, lock, and finalization failures produce `EXECUTION_FAILURE`. They cannot be
reclassified as a financial mismatch and cannot authorize partial proof state.

## Required behavioral scenarios

| Scenario | Ownership | Reason code(s) | Authoritative outcome | Earliest evidence |
|---|---|---|---|---|
| Identical record replay | Admission | — | `IDEMPOTENT_NO_SECOND_BUSINESS_EFFECT` | Local semantics |
| Identity reused with changed payload | Admission | `IDENTITY_CONFLICT` | `RUN_REJECTED_NO_PROOF` | Local semantics |
| Unbalanced journal | Admission | `UNBALANCED_JOURNAL` | `RUN_REJECTED_NO_PROOF` | Local semantics |
| Cross-currency source combination | Admission | `CURRENCY_DOMAIN_VIOLATION` | `RUN_REJECTED_NO_PROOF` | Local semantics |
| Policy version reused with changed digest | Admission | `POLICY_MISMATCH` | `RUN_REJECTED_NO_PROOF` | Local semantics |
| Ambiguous bank allocation | Admission | `AMBIGUOUS_BANK_ALLOCATION` | `RUN_REJECTED_NO_PROOF` | Local semantics |
| Balanced journal with wrong role | Financial | `INVALID_ACCOUNT_ROLE` | `EXCEPTION_PROOF_FINALIZED` | Local semantics |
| Missing processor event | Financial | `MISSING_PROCESSOR_ACTIVITY` | `EXCEPTION_PROOF_FINALIZED` | Modelled |
| Missing ledger movement | Financial | `MISSING_LEDGER_MOVEMENT` | `EXCEPTION_PROOF_FINALIZED` | Modelled |
| Missing bank deposit for nonzero net | Financial | `MISSING_BANK_SETTLEMENT` | `EXCEPTION_PROOF_FINALIZED` | Local semantics |
| Zero-net settlement without bank record | Financial | — | `MATCHED_PROOF_FINALIZED` | Local semantics |
| Split bank deposit | Financial | — | `MATCHED_PROOF_FINALIZED` | Local semantics |
| Duplicate bank movement | Financial | `DUPLICATE_BANK_MOVEMENT` | `EXCEPTION_PROOF_FINALIZED` | Modelled |
| Disallowed bank account | Financial | `INVALID_BANK_ACCOUNT` | `EXCEPTION_PROOF_FINALIZED` | Local semantics |
| Unknown bank reference | Financial | `UNALLOCATED_BANK_MOVEMENT`, `MISSING_BANK_SETTLEMENT` | `EXCEPTION_PROOF_FINALIZED` | Local semantics |
| Out-of-order negative event | Financial | `UNRESOLVED_REFERENCE` | `EXCEPTION_PROOF_FINALIZED` | Local semantics |
| Original capture arrives later | Financial | — | `NEW_PROOF_AND_CASE_REVISION` | Modelled |
| Negative application exceeds capture | Financial | `OVER_APPLIED_REFERENCE` | `EXCEPTION_PROOF_FINALIZED` | Local semantics |
| Processor net formula mismatch | Financial | `SETTLEMENT_FORMULA_MISMATCH` | `EXCEPTION_PROOF_FINALIZED` | Local semantics |
| Changed reconciliation policy | Financial | — | `NEW_POLICY_BOUND_PROOF_REVISION` | Modelled |
| Worker fails before finalization | Execution | `EXECUTION_FAILURE` | `NO_AUTHORITATIVE_PARTIAL_PROOF` | Modelled |

A dash is an explicit successful or revision outcome with no reason code; it never invents a reason
outside the frozen domains. The machine-readable scenario authority is
[`part1-stage5-documentation-authority-v1.json`](../spec/part1-stage5-documentation-authority-v1.json).

`Local semantics` means the decision and arithmetic are covered by executable specification examples;
it does not mean the end-to-end runtime behavior has been implemented.

## Status precedence

A semantic reason always prevents `MATCHED`, even when monetary difference is zero. Tolerance applies
only after complete and semantically valid evidence exists. Missing evidence, invalid references,
formula mismatch, account-role failure, and policy failure cannot be tolerated away.

## Atomicity requirement

```text
attempt output + complete validation + conditional finalization = authoritative proof
```

Temporary attempt output may exist after a failure but must not be referenced by authoritative
control state.

## Evidence rule

A generic failure is insufficient. Evidence must contain the expected ownership and reason class,
source and business identities, run and attempt identity, relevant monetary totals, and unchanged
authoritative state where required.
