# ADR 0012: Use a schema-backed corrective completion and scorecard authority

- Status: accepted for corrective workstream C2
- Date: 2026-09-02

## Context

The historical project completion document contains numeric scorecard targets and narrative gates,
but has no enforcing JSON Schema. Its scorecard cannot record current evidence, evidence required
for a target, Part 1 contribution or remaining evidence. Mutating it would rewrite an accepted
historical authority and repeat the version-control conflict already identified by the conformance
audit.

## Decision

Preserve `contracts/project-completion-v1.json` exactly. Introduce a versioned active Part 1
completion authority with a Draft 2020-12 schema. Encode the exact current correction boundary,
final completion invariants, six C2-owned requirement IDs, twelve fixed scorecard dimensions and
the frozen AWS target. Store scoped evidence metadata for every scorecard dimension and state
explicitly that targets are not achieved scores.

## Consequences

- Completion structure and invariants fail closed under schema validation.
- Historical completion bytes remain reproducible.
- Scorecard evidence is machine-readable and cannot be inferred from targets.
- Stage 5 can compare documentation against one canonical scorecard authority.
- C2 cannot claim Part 1 completion, unlock Part 2, call AWS or authorize merge.
