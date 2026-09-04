# ADR 0024: Part 2 terminal promotion and closure

## Status

Accepted for the Stage 8 promotion candidate.

## Decision

Part 2 closure uses an audited promotion transaction followed by a repository closure-attestation
transaction. The promotion contract may record externally verified Stage 1 through 7 master-gate
evidence, but it remains `PART2_IN_PROGRESS` and cannot assert final completion.

After the promotion PR is squash-merged and independent main CI passes, a separate attestation PR
records the now-known merge topology and CI evidence. That record is validated against the final
completion schema before `LOCAL_RECONCILIATION_VERIFIED` becomes the active Part 2 state.

Historical stage contracts remain immutable candidate-time authorities. Derived normalized ledgers
may reconcile their two trace formats but may not edit requirement text, ownership, evidence, or
stage verdicts. Failure behavior remains owned by Stage 6; Stage 7 provides exhaustive matrix and
critical-path verification.

## Consequences

The first PR cannot make a premature post-merge claim. The second PR can publish complete evidence
without granting CI write permission or asking a workflow to commit to the repository. Closure does
not recurse because the attestation records the already promoted implementation transaction rather
than creating new reconciliation behavior.

Automatic CI remains read-only. Both transactions are local-only and perform no AWS action,
workflow dispatch, managed persistence, infrastructure mutation, performance run, or production
operation.
