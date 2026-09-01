# Failure model

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

| Scenario | Ownership | Required behavior | Earliest evidence |
|---|---|---|---|
| Identical record replay | Admission | No second business effect | Local semantics |
| Identity reused with changed payload | Admission | Reject conflicting source identity | Local semantics |
| Unbalanced journal | Admission | Block authoritative proof | Local semantics |
| Cross-currency source combination | Admission | Reject aggregation and authorize no proof | Local semantics |
| Policy version reused with changed digest | Admission | Reject policy conflict | Local semantics |
| Ambiguous bank allocation | Admission | Allocate to neither settlement and authorize no proof | Local semantics |
| Balanced journal with wrong role | Financial | Finalize exact ledger exception | Local semantics |
| Missing processor event | Financial | Preserve ledger difference | Modelled |
| Missing ledger movement | Financial | Preserve processor difference | Modelled |
| Missing bank deposit for nonzero net | Financial | Preserve settlement exception | Local semantics |
| Zero-net settlement without bank record | Financial | Match when all other evidence is valid | Local semantics |
| Split bank deposit | Financial | Aggregate unique entries exactly once | Local semantics |
| Duplicate bank movement | Financial | Reject second allocation | Modelled |
| Disallowed bank account | Financial | Exclude the movement and preserve an exact exception | Local semantics |
| Unknown bank reference | Financial | Preserve unallocated movement and missing settlement | Local semantics |
| Out-of-order negative event | Financial | Open unresolved-reference exception | Local semantics |
| Original capture arrives later | Financial | Create new proof and case revisions | Modelled |
| Negative application exceeds capture | Financial | Emit over-applied-reference exception | Local semantics |
| Processor net formula mismatch | Financial | Use recomputed value and preserve formula exception | Local semantics |
| Changed reconciliation policy | Financial | Create new policy-bound proof revision | Modelled |
| Worker fails before finalization | Execution | Leave no authoritative partial proof | Modelled |

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
