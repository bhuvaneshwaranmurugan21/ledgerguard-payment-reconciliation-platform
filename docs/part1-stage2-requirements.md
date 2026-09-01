# Part 1 Stage 2 contract requirements

Stage 1 remains the authority for financial meaning. This supplement records whether each frozen
requirement has been encoded in the active contract set and where non-schema enforcement belongs.

| Requirement | Stage 2 contract encoding | Remaining Part 2 runtime responsibility | Stage 2 state |
|---|---|---|---|
| `P1-R01` | Independent source contracts and grain-specific proof totals | Reconstruct independent truths and compare them | Encoded |
| `P1-R02` | Exclusive transaction and settlement keys, proofs, and cases | Build canonical key digests and group records | Encoded |
| `P1-R03` | Shared signed 64-bit and positive/non-negative integer types | Checked arithmetic and overflow rejection | Encoded |
| `P1-R04` | Currency appears in every record and proof key | Reject cross-currency source sets | Encoded |
| `P1-R05` | Complete source identity and canonical digest field shapes | Canonicalize bytes and classify replay/conflict | Encoded |
| `P1-R06` | Event reference conditionals, journal namespace, entry type and grain key | Resolve references, validate balance, roles and capture capacity | Encoded |
| `P1-R07` | Five settlement components, reported net and exact policy formula | Recompute net and emit formula mismatch | Encoded |
| `P1-R08` | Bank reference, normalization, permitted-account and allocation policy | Allocate exact normalized identities once | Encoded |
| `P1-R09` | Proof/case revision and predecessor shapes | Enforce sequential append-only history | Encoded |
| `P1-R10` | Non-negative tolerances and status-specific reason structures | Calculate status only after complete semantic validation | Encoded |
| `P1-R11` | Authoritative proof/case reasons restricted to financial ownership | Keep admission, financial and execution paths disjoint | Encoded |
| `P1-R12` | No admission or execution reason can validate as authoritative proof | Conditional finalization and unchanged authoritative state | Encoded |

`Encoded` means the contract shape and enforcement ownership are locally verified. It does not mean
the Part 2 runtime behavior exists.
