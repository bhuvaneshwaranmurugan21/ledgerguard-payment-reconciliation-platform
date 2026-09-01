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

Part 1 freezes the domain contracts, correctness model, AWS target, completion contract, and
scorecard. It performs no managed reconciliation and creates no AWS workload claim.

| Area | Status |
|---|---|
| Domain and completion contracts | `LOCAL_VERIFIED` after CI |
| Reconciliation implementation | `DESIGNED/MODELED` |
| Managed AWS reconciliation | `UNCLAIMED` |
| Performance and cost | `UNCLAIMED` |
| Production custody or compliance | `UNCLAIMED` |

See the [architecture](docs/architecture.md), [correctness model](docs/correctness.md),
[failure model](docs/failure-model.md), [scorecard](docs/scorecard.md), and
[completion contract](contracts/project-completion-v1.json).

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
