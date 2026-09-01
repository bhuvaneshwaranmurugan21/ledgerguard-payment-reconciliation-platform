# Part 1 requirements ledger

This ledger records the requirements exercised by the financial-semantics stage. A requirement is
not complete merely because it appears in prose; it needs a frozen decision and acceptance evidence.

| Requirement | Description | Decision | Specification path | Acceptance evidence | Stage 1 state |
|---|---|---|---|---|---|
| `P1-R01` | Preserve independent processor, ledger, and bank truths | `SEM-001` | `claim_boundary`, transaction and settlement sections | Wrong-role, missing-bank, and formula examples | Frozen |
| `P1-R02` | Separate transaction and settlement grains | `SEM-006`, `SEM-011` | `transaction.grain`, `settlement.grain` | Transaction and settlement case families | Frozen |
| `P1-R03` | Use integer minor-unit money | `SEM-002` | `money` | Signed-overflow admission counterexample | Frozen |
| `P1-R04` | Forbid cross-currency aggregation | `SEM-003` | `money.cross_currency_aggregation` | Admission rejection with no proof | Frozen |
| `P1-R05` | Bind source identity to canonical business content | `SEM-004`, `SEM-005` | `canonical_identity` | Replay, conflict, and Unicode tests | Frozen |
| `P1-R06` | Require valid journals and relevant account roles | `SEM-009`, `SEM-010` | `transaction.journal_validity` | Capture, refund, and wrong-role cases | Frozen |
| `P1-R07` | Recompute processor settlement net | `SEM-012` | `settlement.expected_net_formula` | Formula-mismatch case | Frozen |
| `P1-R08` | Allocate bank entries only through explicit exact rules | `SEM-014` | `settlement.bank_allocation` | Split, unallocated, disallowed-account, and ambiguous-reference cases | Frozen |
| `P1-R09` | Preserve immutable proof and case revision history | `SEM-017` | `proof`, `case` | Decision inventory and lifecycle review | Frozen |
| `P1-R10` | Keep tolerated amounts visible | `SEM-015` | `status` | Within-tolerance case | Frozen |
| `P1-R11` | Separate admission, financial, and execution failures | `SEM-018` | `failure_ownership` | Disjoint-ownership test | Frozen |
| `P1-R12` | Forbid authoritative partial proof after failure | `SEM-018` | `failure_ownership` | Atomicity assertions | Frozen |

## Evidence interpretation

- A frozen semantic decision is `DESIGNED/MODELED` evidence.
- A passing acceptance example is `LOCAL_VERIFIED` evidence for the decision and arithmetic only.
- The examples do not establish implemented reconciliation execution.
- No AWS evidence is produced or claimed.

## Stage 1 completion rule

Stage 1 requires all listed decisions to be frozen, all executable acceptance examples to pass, the
failure ownership sets to remain disjoint, the unresolved-decision count to equal zero, and the
completed Stage 0 contract and validator to remain intact.
