# ADR 0014: Make Stage 6 reproducibility evidence fail closed

## Status

Accepted for the Stage 6 corrective candidate.

## Context

Passing tests in one mutable development environment cannot establish reproducibility, exact
dependency identity, deterministic results, raw pull-request-head validation, or the provenance of
CI evidence. Stage 6 also has to preserve every earlier correction and both historical contract
families without invoking AWS or mutating infrastructure.

## Decision

Define one ordered 12-action validation profile. Execute it in two independently created virtual
environments against non-editable wheels built with exact bootstrap and transitive dependency
locks. Compare canonical timestamp-free results, enforce line and critical-branch thresholds, run a
fixed mutation catalog, and replay the frozen Stage 5 checkpoint from immutable snapshots.

On pull requests, check out and assert the raw head SHA. Bind the deterministic result to trusted
workflow metadata in a schema-validated evidence envelope, then publish that envelope with a digest
manifest as the Stage 6 artifact. Require a draft PR, the complete 14-gate inventory, and explicit
false AWS-execution and infrastructure-mutation fields.

## Consequences

- Any change after local validation invalidates the candidate and requires both clean runs again.
- Exact-head CI and the downloaded artifact are required in addition to local success.
- Historical Phase 8 verdicts, Stage 0–5 evidence, v1 schemas, accepted v2 schema bytes, and frozen
  semantic authorities remain unchanged.
- Stage 6 does not authorize merge, post-merge completion, AWS execution, infrastructure mutation,
  or Part 2 entry.
