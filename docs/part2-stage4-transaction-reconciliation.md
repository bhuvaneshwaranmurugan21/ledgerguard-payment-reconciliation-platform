# Part 2 Stage 4 transaction reconciliation

Stage 4 converts an admitted source state into deterministic transaction candidates. It keeps the
processor and ledger views independent, evaluates the full union of transaction keys, applies
checked signed 64-bit arithmetic, and preserves source counts so missing evidence cannot become a
genuine zero.

The read-only command is:

```bash
ledgerguard-part2-stage4-reconcile \
  --repository . \
  --policy /controlled/input/policy.json \
  --manifest /controlled/input/manifest.json \
  --input-root /controlled/input/objects
```

Success prints policy and manifest bindings, immutable transaction candidates, state and semantic
digests, and `authoritative_proof: false`. Admission or calculation rejection exits 2 and emits its
owned admission reason. No partial candidate is published.

Transaction candidates contain the exact transaction key components, processor and ledger totals,
signed delta, absolute difference, source counts, deterministic reasons, and status. They are not
proofs: Stage 4 does not assign proof identity, revision, predecessor, creation time, persistence,
or authoritative state.
