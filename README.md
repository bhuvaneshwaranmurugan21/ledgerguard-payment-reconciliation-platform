# LedgerGuard

**A three-way payment reconciliation platform that proves processor activity, balanced internal
ledger movement, and bank settlement agree at the correct business grain.**

[![CI](https://github.com/bhuvaneshwaranmurugan21/ledgerguard-payment-reconciliation-platform/actions/workflows/ci.yml/badge.svg)](https://github.com/bhuvaneshwaranmurugan21/ledgerguard-payment-reconciliation-platform/actions/workflows/ci.yml)
[![AWS OIDC](https://github.com/bhuvaneshwaranmurugan21/ledgerguard-payment-reconciliation-platform/actions/workflows/aws-oidc-identity.yml/badge.svg)](https://github.com/bhuvaneshwaranmurugan21/ledgerguard-payment-reconciliation-platform/actions/workflows/aws-oidc-identity.yml)

A completed payment pipeline does not prove that money reconciles. LedgerGuard keeps processor,
ledger, and bank evidence independent, reconstructs their financial meaning, and emits a versioned
proof or an exact unexplained difference. It never treats equal row counts as settlement proof.

## Correctness boundary

LedgerGuard reconciles at two grains:

- **Transaction:** processor captures, refunds, chargebacks, and reversals against the relevant
  balanced ledger movements.
- **Settlement:** processor payout reports and deductions against clearing-account movements and
  actual bank deposits.

All money uses integer minor units plus an explicit currency. Identical redelivery is idempotent;
identity reuse with different content is rejected. Late data creates a new proof revision instead
of rewriting historical evidence.

## Current status

Part 1 is operationally complete. The failed non-squash PR #8 attempt remains recorded; replacement
PR #9 passed exact-head CI, was squash-merged, and passed independent post-merge `main` CI. Part 2
Stage 1 was then closed by PR #10. PR #11 closed Stage 2, externally verifying the separately
packaged, side-effect-free reference oracle. Stage 3 added production admission and normalization;
PR #12 passed exact-head CI, was squash-merged, and passed independent post-merge `main` CI. PR #13
then closed Stage 4 transaction reconciliation with exact-head CI, a squash merge, and independent
post-merge `main` CI. PR #14 closed Stage 5 settlement reconciliation. Stage 6 is now the local
verified proof-finalization candidate; external closure is still pending. The overall project
remains `PROJECT_IN_PROGRESS`.

The immutable Stage 1 status statement was: Part 2
is now `PART2_IN_PROGRESS`. No reconciliation
oracle or engine is claimed by Stage 1. It remains here solely so the accepted Stage 1 validator
can be reproduced from later Part 2 trees without changing its historical assertion.

| Area | Status |
|---|---|
| Stage 0 baseline governance | `LOCAL_VERIFIED` after CI |
| Financial semantic decisions | `DESIGNED/MODELED` and frozen |
| Semantic acceptance examples | `LOCAL_VERIFIED` after CI |
| Corrected active `v2` contracts | `LOCAL_VERIFIED` after CI |
| Canonical contract coherence | `LOCAL_VERIFIED` after CI |
| Historical Stage 4 governance | `LOCAL_VERIFIED` and byte-preserved |
| C0 truthful correction checkpoint | `EXACT_HEAD_CI_VERIFIED` and byte-preserved |
| C1 requirement and gate authority | `LOCAL_VERIFIED` — 331/331 owned, 14/14 inventoried, zero effective orphans |
| C2 completion and scorecard authority | `LOCAL_VERIFIED` — schema-backed invariants and scoped evidence for 12 dimensions |
| Stage 6 reproducibility | `EXACT_HEAD_CI_VERIFIED` — 224 tests, 95.737964% coverage, 20/20 mutation checks, two equal clean runs |
| Full Stage 0–7 conformance | `LOCAL_VERIFIED` — 331/331 re-audited, all 14 gates closed after PR #9 squash and independent `main` CI |
| Part 2 Stage 1 execution authority | `LOCAL_VERIFIED` after PR #10 squash and independent main CI |
| Local Spark/Parquet toolchain | `LOCAL_VERIFIED` — Python 3.11.13, Java 17, Spark 3.5.6 |
| Historical `v1` contracts | `SUPERSEDED_BEFORE_RUNTIME_USE` and byte-preserved |
| Production admission and normalization | `EXTERNALLY_VERIFIED` after PR #12 squash and independent main CI |
| Transaction-grain reconciliation | `EXTERNALLY_VERIFIED` after PR #13 squash and independent main CI |
| Settlement-grain reconciliation | `EXTERNALLY_VERIFIED` after PR #14 squash and independent main CI |
| Atomic proof and case finalization | `LOCAL_VERIFIED` candidate pending exact-head and post-merge closure |
| Independent reference oracle | `EXTERNALLY_VERIFIED` after PR #11 squash and independent main CI |
| Spark reconciliation parity | `UNCLAIMED` |
| Historical AWS identity-plane execution | `AWS_VERIFIED_WRONG_TARGET` |
| Frozen-target identity and managed AWS reconciliation | `UNCLAIMED` |
| AWS account-wide nonmutation | `NOT_PROVEN` |
| Performance and cost | `UNCLAIMED` |
| Production custody or compliance | `UNCLAIMED` |

See the [active architecture](docs/architecture-v2.md), [correctness model](docs/correctness.md),
[active failure model](docs/failure-model-v2.md), [active scorecard authority](docs/scorecard-v2.md),
[Stage 5 gap audit](docs/stage5-gap-audit.md), and
[project completion contract](contracts/project-completion-v1.json). The active contract authority
is the [version registry](contracts/active-contract-set-v1.json), supported by the
[contract model](docs/contract-model.md), [Stage 2 requirements](docs/part1-stage2-requirements.md),
and [Stage 2 gap audit](docs/stage2-gap-audit.md). Canonical byte and linked-artifact authority is
defined by the [coherence model](docs/contract-coherence.md) and
[Stage 3 gap audit](docs/stage3-gap-audit.md). Active Part 1 authority is the
[corrective completion document](docs/part1-correction.md), the
[C0 correction contract](contracts/part1-c0-correction-v1.json), and the
[owner-approved amendments](spec/part1-authority-amendments-v1.json). C1 adds the
[requirement and gate authority](docs/part1-requirement-authority.md), its deterministic
[331-requirement ledger](spec/part1-requirement-ledger-v1.json), and the exact
[14-gate registry](spec/part1-gate-registry-v1.json). C2 adds the schema-backed
[completion and scorecard authority](docs/part1-completion-authority.md). The prior
[Stage 4 completion document](docs/part1-completion.md) and
[Part 2 handoff](contracts/part1-part2-handoff-v1.json) are preserved historical authorities. Stage
7 closure is defined by the preserved [v1 promotion contract](contracts/part1-stage7-promotion-v1.json),
the active [v2 recovery contract](contracts/part1-stage7-promotion-recovery-v2.json), and the
[promotion audit](docs/stage7-gap-audit.md). Historical stage authorities and every v1/v2 schema
remain immutable. Part 2 begins with the [Stage 1 gap audit](docs/part2-stage1-gap-audit.md),
[execution contract](docs/part2-execution-contract.md), and
[machine-readable authority](spec/part2-stage1-authority-v1.json). Stage 2 adds the
[reference-oracle gap audit](docs/part2-stage2-gap-audit.md),
[oracle contract](docs/part2-stage2-reference-oracle.md), and
[independence decision](docs/adr/0018-independent-reference-oracle.md). Stage 3 adds the
[admission gap audit](docs/part2-stage3-gap-audit.md),
[admission contract](docs/part2-stage3-admission-normalization.md), and
[production admission decision](docs/adr/0019-production-admission-and-normalization.md). Stage 4
adds the [transaction gap audit](docs/part2-stage4-gap-audit.md),
[transaction contract](docs/part2-stage4-transaction-reconciliation.md), and
[transaction decision](docs/adr/0020-transaction-reconciliation-and-reference-capacity.md). Stage 5
adds the [settlement gap audit](docs/part2-stage5-gap-audit.md),
[settlement contract](docs/part2-stage5-settlement-reconciliation.md), and
[bank-allocation decision](docs/adr/0021-settlement-reconciliation-and-exact-bank-allocation.md).
Stage 6 adds the [proof-finalization gap audit](docs/part2-stage6-gap-audit.md),
[finalization contract](docs/part2-stage6-proof-finalization.md), and
[atomic recovery decision](docs/adr/0022-atomic-proof-finalization-and-recovery.md).
Stage 7 adds the [Spark parity gap audit](docs/part2-stage7-gap-audit.md),
[Spark parity contract](docs/part2-stage7-spark-parity.md), and
[logical Parquet decision](docs/adr/0023-spark-logical-parity-and-parquet.md).

## Foundation validation

```bash
python -m pip install -e '.[dev]'
ledgerguard-foundation
ledgerguard-c0
ledgerguard-stage7
ledgerguard-part2-stage1
ledgerguard-part2-stage2
ledgerguard-part2-stage3
ledgerguard-part2-stage4
ledgerguard-part2-stage5
ledgerguard-part2-stage6
ledgerguard-part2-stage7
ruff format --check .
ruff check .
mypy src
pytest
```

## Scope

The planned managed validation uses synthetic data in one AWS region. It will not establish
financial custody, PCI certification, multi-region recovery, or sustained production operation.

Parts 1 and 2 perform no AWS execution and mutate no AWS infrastructure. Part 1's highest claim is
`LOCAL_VERIFIED`; Part 2 Stage 7 adds genuine local Spark/Parquet logical parity, the complete failure
matrix, and critical-path validation. Managed reconciliation, performance, scale, production
operation, and final Part 2 closure remain unclaimed.

## License

MIT
