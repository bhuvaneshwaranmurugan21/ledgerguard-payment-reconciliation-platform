# Draft foundation gap audit

## Audited boundary

- Base: `main` at `ae36abc157c3cfb018880314d5732e3d91d403bf`
- Draft head: `08066c92bb182ad6ec829d6feaf36dc34ad10d51`
- Draft size: one commit, 32 changed files
- Existing validation: seven tests, 86.80% coverage, deterministic local simulation, Terraform
  formatting, and repository CI

The draft established useful intent but cannot be promoted unchanged. Its transaction-only bank
mapping, currency naming, journal derivation, late-data behavior, region binding, placeholder
orchestration, and evidence vocabulary conflict with the frozen foundation.

## Exact disposition

| Draft surface | Disposition | Reason |
|---|---|---|
| OIDC identity workflow | Replace | Bind exact repository, account, role, branch, and approved region |
| CI workflow | Replace | Validate schemas, target, completion contract, formatting, typing, and tests |
| Terraform workflow | Defer | Infrastructure is not authorized until Part 3 |
| Repository ignore rules | Preserve with cleanup | Existing exclusions remain valid |
| Make targets | Replace | Establish one complete quality entry point |
| README | Replace | Explain two reconciliation grains and honest current claims |
| External payment schema | Replace | Separate processor event, payout, bank, journal, manifest, policy, proof, and case contracts |
| Presentation-coaching document | Exclude | It is not project engineering documentation |
| Architecture document | Replace | Model transaction and settlement reconciliation independently |
| Claims document | Replace | Use the portfolio-wide four-level evidence vocabulary |
| Cost model | Defer | Freeze the ceiling now; implement measured cost controls with Part 3 and Part 4 |
| Failure lab | Replace | Add settlement-grain, late-data, policy, tamper, and managed recovery boundaries |
| Runbook | Defer | A runnable managed procedure belongs with implemented infrastructure |
| Threat model | Defer | Rebuild against actual Part 3 identities and data flow |
| Workload model | Replace in Part 2 | Use deterministic 100K and 1M managed measurement targets |
| Local simulation evidence | Exclude | It was produced by the rejected single-grain kernel |
| Terraform provider lock | Defer | Regenerate from the Part 3 provider contract before authority is issued |
| Terraform README | Defer | Rebuild with the actual managed topology |
| Terraform resources and outputs | Exclude | The state machine contains placeholder work and no Glue job or Athena verifier |
| Terraform variables and versions | Defer | Recreate for the approved region and exact runtime |
| Python project configuration | Replace | Pin current foundation validation dependencies |
| Package initializer | Replace | Do not expose the rejected engine as a public API |
| AWS evidence validator | Replace later | Evidence must validate semantic results, attribution, scale, cost, and teardown |
| CLI | Defer | Add only with the Part 2 executable system |
| Reconciliation engine | Exclude | Bank truth is incorrectly keyed by payment and journal movement is oversimplified |
| Domain model | Exclude | Uses cents for INR and collapses transaction and settlement grains |
| Simulator | Exclude | Its expected result inherits the rejected domain model |
| AWS evidence tests | Defer | Rebuild with the managed evidence contract |
| Engine tests | Exclude | They validate known-invalid business semantics |
| Simulator tests | Exclude | They validate evidence from the known-invalid kernel |

## Corrective decisions

1. Bank entries are cash movements, not per-payment records.
2. Transaction reconciliation and settlement reconciliation have separate keys and equations.
3. Monetary fields use integer minor units and a currency exponent policy.
4. Relevant ledger account roles determine financial movement; total debits do not.
5. Out-of-order references remain visible as exceptions and may resolve through a new revision.
6. Historical proofs and case revisions are immutable.
7. The AWS target uses the approved repository-specific role and region.
8. No managed-workload code or claim enters `main` during Part 1.

## Residual work after Part 1

The generator, reference oracle, Spark engine, failure laboratory, infrastructure, managed
evidence, scale measurements, cost measurement, runbook, threat model, and release remain gated by
Parts 2 through 5. Their absence is explicit and cannot be used as evidence of foundation
completion.

## Stage 0 reproducibility record

The historical draft was materialized from commit
`08066c92bb182ad6ec829d6feaf36dc34ad10d51`. All 32 fetched files matched their Git blob
identities. Its parent was
`ae36abc157c3cfb018880314d5732e3d91d403bf`, and GitHub comparison showed exactly one draft
commit. The draft and corrective main histories diverge at that parent, proving the rejected
commit is not part of the corrective main lineage.

The declared historical test command could not be reproduced with the available offline toolchain
because its pinned coverage plugin was unavailable. That limitation is recorded instead of
weakening the command. A supplementary run without the unavailable coverage arguments passed all
seven historical tests, and the deterministic simulation reproduced byte-identically. Current
linting identified five toolchain-compatibility findings; strict typing passed.

Independent probes reproduced the material semantic defects: bank settlement matched at payment
grain, balanced but financially irrelevant account roles contributed to a match, and the model
used a currency-specific amount name for INR. The Terraform state machine was statically confirmed
to contain pass-through placeholders and was not executed.

The exhaustive machine-readable disposition and Stage 0 boundary are frozen in
[`part1-stage0-completion-v1.json`](../contracts/part1-stage0-completion-v1.json).
