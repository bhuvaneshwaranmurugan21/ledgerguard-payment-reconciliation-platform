# Failure model

## Required behavioral scenarios

| Scenario | Required behavior | Earliest proof level |
|---|---|---|
| Identical record replay | No second business effect | `LOCAL_VERIFIED` |
| Identifier reused with changed payload | Reject the conflicting input | `LOCAL_VERIFIED` |
| Unbalanced journal | Reject before reconciliation | `LOCAL_VERIFIED` |
| Balanced journal with wrong account role | Emit exact ledger exception | `LOCAL_VERIFIED` |
| Missing processor event | Preserve ledger difference as exception | `LOCAL_VERIFIED` |
| Missing ledger movement | Preserve processor difference as exception | `LOCAL_VERIFIED` |
| Missing bank deposit | Preserve settlement difference as exception | `LOCAL_VERIFIED` |
| Split bank deposit | Aggregate once under one settlement key | `LOCAL_VERIFIED` |
| Duplicate bank movement | Reject double allocation or identity conflict | `LOCAL_VERIFIED` |
| Out-of-order reversal | Open unresolved-reference exception | `LOCAL_VERIFIED` |
| Original arrives later | Produce a new resolved proof revision | `LOCAL_VERIFIED` |
| Currency contamination | Reject cross-currency aggregation | `LOCAL_VERIFIED` |
| Changed reconciliation policy | Produce a new policy-bound proof | `LOCAL_VERIFIED` |
| Worker failure before finalization | No authoritative partial proof | `LOCAL_VERIFIED` |
| Managed retry after failure | Complete without duplicate proof or case | `AWS_VERIFIED` |
| Source object changed after manifest | Reject exact-object identity | `AWS_VERIFIED` |
| Infrastructure partial apply | Recover and prove clean inventory | `AWS_VERIFIED` |

## Failure ownership

Source-contract failures belong to admission. Financial differences belong to reconciliation and
remain visible as business exceptions. Infrastructure and worker failures belong to execution and
must not be mislabeled as financial mismatches.

## Evidence rule

A generic failed job is not proof of a semantic scenario. Evidence must contain the expected reason
class, source identity, unchanged authoritative state where required, and attributable run and
attempt identifiers.
