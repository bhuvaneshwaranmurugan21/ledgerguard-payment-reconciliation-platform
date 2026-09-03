# Part 2 Stage 3 admission and normalization

## Result being established

Stage 3 establishes a production admission boundary that converts one policy-bound, manifest-bound
input bundle into immutable reconciliation-ready records or one owned admission rejection. It is a
candidate until external pull-request closure completes.

The command surface is:

```bash
ledgerguard-part2-stage3-admit \
  --repository . \
  --policy /controlled/input/policy.json \
  --manifest /controlled/input/manifest.json \
  --input-root /controlled/input/objects
```

The command is read-only. Success prints one canonicalizable JSON result with run, policy,
manifest, record, replay, and semantic-digest fields. Rejection prints one owned reason and exits
2. Both outcomes state `authoritative_proof: false`.

## Admission order

1. Verify the active registry and all referenced v2 schema bytes.
2. Strictly parse and schema-validate policy; recompute its digest and enforce version reuse.
3. Strictly parse and schema-validate manifest; bind policy, run, exact family set, and object set.
4. For each locator in deterministic order, verify size, digest, framing, and record count.
5. Strictly parse and schema-validate each record, recompute business digest, and derive source
   identity.
6. Classify identical replay or fail changed content under the same identity.
7. Apply checked journal, key, currency, reference, and ambiguity admission rules.
8. Publish the immutable admitted batch and candidate state only after every check passes.

No partial state or source record escapes a failed bundle.

## Failure ownership

The exact Stage 3 admission domain is `SCHEMA_VIOLATION`, `SOURCE_IDENTITY_MISMATCH`,
`POLICY_MISMATCH`, `IDENTITY_CONFLICT`, `CURRENCY_DOMAIN_VIOLATION`, `UNBALANCED_JOURNAL`, and
`AMBIGUOUS_BANK_ALLOCATION`. No Stage 3 path invents a new reason, converts an admission defect to
an execution failure, or emits a proof.

## Evidence standard

The candidate must pass Ruff formatting and linting, strict mypy, the complete repository test
suite with zero skips, 100% statement and branch coverage of `ledgerguard.reconciliation`, all
fifteen targeted mutation checks, wheel installation, and at least two independent clean CPython
3.11.13 runs from hash-locked dependencies. The deterministic payload and wheel hash must agree.

CI replays the immutable Part 1, Stage 1, and Stage 2 closures, executes Stage 3 twice from the raw
pull-request head, and creates a schema-validated immutable evidence envelope only for the exact
Stage 3 branch while the pull request is draft. Local success cannot promote the candidate.
