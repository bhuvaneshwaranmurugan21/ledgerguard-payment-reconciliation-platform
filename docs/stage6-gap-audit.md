# Part 1 Stage 6 gap audit

## Entry condition

Stage 5 is frozen at remote head `8d1d50ae62499ace6585160e2bb4326e7ec40594`, tree
`0df6f1a593b0d59a4214ed979e14fe261715daef`, and successful exact-head CI run `33599528118`.
Stage 6 must reproduce that checkpoint from immutable configuration snapshots before evaluating any
new candidate control.

## Baseline

The original Stage 6 authority contains 35 requirements. The immutable Phase 8 verdict is nine
passes, one partial, 18 failures, and seven not-proven results. Stage 6 supplies reproducibility and
validation controls for those gaps; it does not rewrite the historical verdict or claim Part 1
completion.

## Corrections

| Gap | Stage 6 corrective authority | Fail-closed validation |
|---|---|---|
| Environment drift | Exact Python, bootstrap, build, and transitive dependency pins with hashes | Two fresh virtual environments install only the locked artifacts |
| Editable-install ambiguity | A wheel is built without isolation and installed non-editably | Tests execute against the installed distribution while repository evidence remains explicit |
| Incomplete quality command | One ordered 12-action profile | Missing, reordered, skipped, or failed actions reject the candidate |
| Weak coverage evidence | Repository line coverage at least 95% and 100% branch coverage for the critical evidence validator | Coverage JSON and zero-skip JUnit evidence are checked programmatically |
| Mutation blind spots | Exact 20-test mutation catalog | Any survivor, failure, error, skip, or catalog drift rejects the candidate |
| Nondeterministic results | Two clean runs produce canonical equal payloads | Timestamp-free canonical JSON must be byte-equivalent and digest-equivalent |
| Historical checkpoint drift | Stage 5 manifest, configuration snapshots, and validator replay | Any Stage 5 snapshot, test authority, v1 schema, or accepted v2 schema difference fails closed |
| Untrusted PR checkout | Raw pull-request head SHA and checked-out SHA must match | CI evidence rejects merge-ref or stale-head validation |
| Unstructured CI proof | Schema-backed evidence envelope and digest manifest | Artifact content, exact head, PR draft state, no-AWS boundary, and all 14 gates are validated |

## Failure paths

A dependency hash mismatch, unsupported interpreter, build failure, test failure, skip, coverage
shortfall, surviving mutation, unequal clean run, historical replay difference, schema drift, raw-head
mismatch, non-draft PR, AWS flag, infrastructure-mutation flag, incomplete gate inventory, missing
artifact, or digest mismatch blocks Stage 6. A failure is corrected at its source and the complete
two-run command restarts from a clean environment.

## Exit boundary

Stage 6 exits only when the final candidate passes two local clean runs, the exact raw PR head passes
the same workflow, the downloaded evidence artifact validates against its schema and manifest, the
PR remains draft, and the diff has no unrelated changes or unresolved findings. Merge remains
prohibited, post-merge validation remains Stage 7 work, Part 1 remains
`PART1_CORRECTION_IN_PROGRESS`, and Part 2 remains `BLOCKED`.
