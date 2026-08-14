# Managed reconciliation runbook

1. Pin processor, ledger, and settlement manifests to one run ID.
2. Record contract and reconciliation policy digests.
3. Execute the happy path and capture Glue and Step Functions identifiers.
4. Verify source totals independently before matching.
5. Inject missing, duplicated, split, late, reversed, and currency-invalid records.
6. Prove differences remain visible and matched publication is blocked.
7. Repair the source fixture, replay, and record the case transition.
8. Export monetary totals, logs, latency, throughput, cost, and evidence digest.
9. Destroy infrastructure and verify that no billable compute remains.

No evidence bundle may expose customer data, account IDs, secret values, or unmasked ARNs.

