# ADR 0009: Preserve historical stage views while active status advances

## Status

Accepted.

## Context

Stage 3 correctly bound the documentation and tests used to establish its completion state. Some of
those files are also active repository surfaces and must change when Part 1 completes. Validating
Stage 3 against their later bytes would conflate historical and current state. Rebinding the Stage 3
contract would alter accepted evidence.

## Decision

LedgerGuard stores exact copies only for Stage 3 artifacts that must evolve. A manifest binds each
copy to its logical path, SHA-256 digest, Git blob identity, accepted merge, tree and CI runs. The
unchanged Stage 3 validator executes against a temporary historical view containing those bytes.

The current repository is validated independently by the Stage 4 Part 1 completion validator.
Original Stage 0–3 contracts and evidence remain unchanged.

## Consequences

Historical validation stays reproducible while active status remains truthful. The additional
snapshot is small and explicit. Every future mutable historical surface must be added deliberately
rather than silently reinterpreted.
