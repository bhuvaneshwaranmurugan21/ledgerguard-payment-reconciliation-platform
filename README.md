# LedgerGuard — Payment Reconciliation Platform

[![CI](https://github.com/bhuvaneshwaranmurugan21/ledgerguard-payment-reconciliation-platform/actions/workflows/ci.yml/badge.svg)](https://github.com/bhuvaneshwaranmurugan21/ledgerguard-payment-reconciliation-platform/actions/workflows/ci.yml)

LedgerGuard reconciles three independent financial truths: payment-processor events, balanced
internal journals, and bank settlements. It never calls equal row counts a settlement proof.

```mermaid
flowchart LR
    A[Processor feed] --> D[S3 immutable inputs]
    B[Balanced ledger] --> D
    C[Bank settlement] --> D
    D --> E[Glue reconciliation]
    E --> F{Three-way monetary proof}
    F -->|matched| G[Settlement evidence]
    F -->|difference| H[DynamoDB exception case]
    H --> I[Repair and replay]
```

## Correctness demonstrated locally

- integer minor-unit money and currency contracts;
- immutable feed and journal identities;
- balanced double-entry journal validation;
- one-to-many settlement matching by explicit aggregation;
- missing-settlement detection and auditable exception-to-match transition;
- reversal-reference validation;
- atomic feed rollback and deterministic replay evidence.

The Terraform topology is production-shaped but no managed-runtime claim is made until the
repository contains real Step Functions, Glue, Athena, CloudWatch, cost, and teardown evidence.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
make check
make evidence
```

