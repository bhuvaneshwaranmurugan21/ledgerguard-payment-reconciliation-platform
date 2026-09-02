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

Part 1 foundation is `PART1_FOUNDATION_COMPLETE`, but operational promotion attempt 1 failed closed
because PR #8 used a merge commit instead of the required squash. Part 2 remains blocked until
replacement PR #9 is squash-merged and its independent post-merge `main` CI succeeds. The overall
project remains `PROJECT_IN_PROGRESS`.

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
| Full Stage 0–7 conformance | `LOCAL_VERIFIED` candidate — 331/331 re-audited, 13/14 gates passed; squash promotion recovery active |
| Historical `v1` contracts | `SUPERSEDED_BEFORE_RUNTIME_USE` and byte-preserved |
| Reconciliation implementation | `UNCLAIMED` |
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
remain immutable.

## Foundation validation

```bash
python -m pip install -e '.[dev]'
ledgerguard-foundation
ledgerguard-c0
ledgerguard-stage7
ruff format --check .
ruff check .
mypy src
pytest
```

## Scope

The planned managed validation uses synthetic data in one AWS region. It will not establish
financial custody, PCI certification, multi-region recovery, or sustained production operation.

Part 1 performs no AWS execution and mutates no AWS infrastructure. Its highest completion claim is
`LOCAL_VERIFIED`; managed reconciliation, performance, scale, and production operation remain
unclaimed.

## License

MIT
