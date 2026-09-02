# ADR 0015: Fail-closed Stage 7 promotion

## Status

Accepted.

## Decision

Treat Part 1 promotion as a two-surface gate. The repository-resident validator proves the final
state, complete requirement ownership, frozen Stage 6 entry evidence, claim boundary, failure
policy, and promotion contract. GitHub evidence then proves exact-head PR CI, immutable squash
merge, and independent post-merge `main` CI. Neither surface substitutes for the other.

Keep the corrective PR draft until its final state-changing head passes every required check.
Promoting the PR from draft changes no repository bytes. Merge only that checked head, and treat
post-merge CI failure as an incomplete Part 1 requiring a new corrective PR.

## Consequences

The historical Phase 8 failure remains immutable while the corrected state has explicit evidence.
Green local tests alone cannot authorize merge. Green PR CI alone cannot establish post-merge
completion. No AWS permission or execution is introduced by the promotion path.
