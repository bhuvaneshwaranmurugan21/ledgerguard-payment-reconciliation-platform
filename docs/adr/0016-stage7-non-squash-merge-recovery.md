# ADR 0016: Fail-closed recovery from the Stage 7 non-squash merge

## Status

Accepted.

## Context

Promotion attempt 1 merged PR #8 as commit
`7151eead60e269fa5650e67d65fc8f687ddc281c`. The commit's tree exactly equals the validated PR
head tree, and independent `main` CI succeeded. GitHub nevertheless records two parents, proving a
merge commit rather than the squash required by the frozen Stage 7 contract and ADR 0015.

## Decision

Fail the attempt without rewriting history or treating tree equality as merge-strategy equivalence.
Preserve the v1 promotion contract byte-for-byte, record the observed merge and successful checks,
keep Part 2 blocked, and apply the existing failure policy through a new corrective pull request.

The replacement promotion retains every original external closure requirement. Its final validated
head must be squash-merged, the resulting `main` tree must equal that exact head tree, and a new
independent `main` push CI run must succeed before Part 2 entry is unlocked.

## Consequences

The successful PR and `main` checks from attempt 1 remain valid evidence but cannot satisfy the
failed squash gate. No requirement is disabled, relabelled, weakened, or declared equivalent. No
history rewrite is authorized. The recovery adds no AWS permission, workflow, call, or mutation.
