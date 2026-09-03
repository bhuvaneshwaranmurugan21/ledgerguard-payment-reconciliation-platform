# Part 2 Stage 5 settlement reconciliation

Stage 5 converts admitted settlement state into deterministic three-way candidates and a complete
bank-allocation ledger. Processor payout reports, clearing-account journals, and bank cash remain
independent facts. Bank records never acquire payment identifiers and no heuristic can create an
allocation.

The read-only command is:

```bash
ledgerguard-part2-stage5-reconcile \
  --repository . \
  --policy /controlled/input/policy.json \
  --manifest /controlled/input/manifest.json \
  --input-root /controlled/input/objects
```

Success prints policy and manifest bindings, settlement candidates, one disposition for every
unique bank identity, state and semantic digests, and `authoritative_proof: false`. Admission or
calculation rejection exits 2 and emits its owned admission reason. No partial candidate or state
is published.

Each candidate contains the exact settlement key, recomputed processor net, settlement clearing
movement, allocated bank total, all three pairwise deltas, maximum absolute difference, three
source counts, status, ordered reasons, and contributing source identities. Unallocated bank
movements remain visible once in the batch allocation ledger and are excluded from candidate bank
totals. Settlement state retains duplicate bank identities as durable in-memory diagnostics across
batches while a single prior-state replay remains idempotent.

The output is not a reconciliation proof. Stage 5 does not assign proof identity, revision,
predecessor, creation time, persistence, or authoritative state.
