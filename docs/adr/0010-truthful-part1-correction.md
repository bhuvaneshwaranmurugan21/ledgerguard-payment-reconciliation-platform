# ADR 0010: Truthful Part 1 correction authority

## Status

Accepted for C0 on 2026-09-02.

## Context

The Stage 0–7 conformance audit found that the accepted Stage 4 tree was internally reproducible
but did not conform to the complete original authority. Two facts cannot be repaired by rewriting
history:

1. a historical push workflow assumed an AWS role and called STS in a target other than the
   currently frozen target; and
2. Stage 2 preserved the original v1 contracts and activated v2, although the original instruction
   required correcting the unreleased v1 contracts in place.

The same audit found 96 non-passing requirements and only 4 of 14 mandatory gates passing. An
active Part 1 completion claim is therefore not defensible.

## Decision

Part 1 returns to `PART1_CORRECTION_IN_PROGRESS`; Part 2 remains blocked. The owner-approved
amendments in `spec/part1-authority-amendments-v1.json` replace only the two impossible literal
authorities. Every other original requirement remains controlling.

The accepted Stage 4 tree remains append-only evidence. Its complete 95-file inventory is
digest-bound, and every file changed by C0 is snapshotted. C0 reconstructs that exact logical tree
and runs the unchanged Stage 4 entry point against it in an isolated process.

Historical identity-plane execution is stated narrowly. It does not prove the current frozen
target, managed reconciliation, account-wide nonmutation, or infrastructure behavior beyond the
observed workflow steps. No AWS action is authorized by this decision.

Historical v1 and accepted v2 schema bytes remain immutable. The active v2 registry is formally
accepted, and future incompatible changes require another version.

## Consequences

- Stage 4 remains valid historical evidence, not current completion authority.
- C0 cannot restore `PART1_FOUNDATION_COMPLETE` or unlock Part 2.
- C1–C7 must close the remaining audit findings and prospective promotion gates.
- The corrective PR remains draft; C0 does not authorize merge.
