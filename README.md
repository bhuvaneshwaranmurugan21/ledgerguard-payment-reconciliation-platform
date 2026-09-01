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

Part 1 is undergoing a fail-closed correction. Stage 0 establishes the corrective baseline; Stage 1
freezes the complete financial semantics and validates worked acceptance examples. The existing
schemas still require the corresponding contract corrections before Part 1 can be declared
complete.

| Area | Status |
|---|---|
| Stage 0 baseline governance | `LOCAL_VERIFIED` after CI |
| Financial semantic decisions | `DESIGNED/MODELED` and frozen |
| Semantic acceptance examples | `LOCAL_VERIFIED` after CI |
| Corrected domain contracts | `UNCLAIMED` until encoded and validated |
| Reconciliation implementation | `UNCLAIMED` |
| Managed AWS reconciliation | `UNCLAIMED` |
| Performance and cost | `UNCLAIMED` |
| Production custody or compliance | `UNCLAIMED` |

See the [architecture](docs/architecture.md), [correctness model](docs/correctness.md),
[failure model](docs/failure-model.md), [scorecard](docs/scorecard.md), and
[project completion contract](contracts/project-completion-v1.json). The active gate is the
[Stage 1 completion contract](contracts/part1-stage1-completion-v1.json); its evidence is the
[semantic decision register](docs/semantic-decisions.md),
[requirements ledger](docs/part1-requirements.md), and
[worked financial examples](docs/financial-examples.md). The corrective integration record is the
[Stage 1 gap audit](docs/stage1-gap-audit.md).

## Foundation validation

```bash
python -m pip install -e '.[dev]'
ledgerguard-foundation
ruff format --check .
ruff check .
mypy src
pytest
```

## Scope

The planned managed validation uses synthetic data in one AWS region. It will not establish
financial custody, PCI certification, multi-region recovery, or sustained production operation.

## License

MIT
