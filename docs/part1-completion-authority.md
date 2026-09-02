# Part 1 completion and scorecard authority

## Active boundary

LedgerGuard Part 1 remains `PART1_CORRECTION_IN_PROGRESS`; the project remains
`PROJECT_IN_PROGRESS`, and Part 2 remains `BLOCKED`. The active machine authority is
`contracts/part1-completion-authority-v2.json`, validated by
`spec/part1-completion-authority-v2.schema.json`.

The earlier `contracts/project-completion-v1.json` is preserved as historical authority. It is not
rewritten and no longer controls active Part 1 completion because it lacks an explicit schema and
per-dimension scorecard evidence fields.

## Exact completion invariants

Part 1 can return to `PART1_FOUNDATION_COMPLETE` only after formally approved amendments and all
effective requirements are resolved, all 14 mandatory gates pass, exact-head pull-request CI and
independent post-merge `main` CI pass, critical and major findings are zero, and mechanically
derived remaining work is zero. Until then, the checked-in state must remain correction in
progress and Part 2 must remain blocked.

The current frozen audit baseline remains 235 passing and 96 non-passing requirements out of 331.
C2 records corrected authority; it does not relabel that baseline or issue the final C7 verdict.

## Scorecard semantics

Every scorecard dimension stores its target, exact evidence level and scope, evidence required to
achieve the target, whether Part 1 contributes, and explicit remaining evidence. Numeric values
are targets, never achieved scores. Design, local validation, managed execution, performance and
production operation remain distinct evidence scopes.

The only permitted generic evidence levels are `DESIGNED/MODELED`, `LOCAL_VERIFIED`,
`AWS_VERIFIED`, and `UNCLAIMED`. A level is meaningful only with its stated scope. For example,
local verification of financial contracts is not implementation or managed-reconciliation proof.

## AWS and execution boundary

C2 performs no AWS call, dispatches no AWS workflow and mutates no infrastructure. Historical
wrong-target identity-plane execution is not frozen-target or managed-reconciliation evidence.
Managed reconciliation, performance, scale, cost measurement and production operation remain
unclaimed.
