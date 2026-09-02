# ADR 0013: Treat documentation and contracts as one checked system

## Status

Accepted for the Stage 5 corrective candidate.

## Context

The Stage 4 repository contained the required document families but did not have one exact
inventory or automated cross-document authority. Several claims were individually correct yet not
mechanically compared with the active contract registry, reason domains, AWS target, completion
authority, requirement mapping, or internal links.

## Decision

Use `spec/part1-stage5-documentation-authority-v1.json` as the Stage 5 inventory and comparison
profile. A fail-closed validator checks all 23 original Stage 5 requirements, including preserved
passes and C1 corrections. It derives contract names from the active registry, reason domains from
the financial-semantics authority, target values from the target JSON, scorecard values from the
completion authority, and traceability from the original-requirement ledger and reverse index.

Historical Phase 8 verdicts remain immutable. Stage 5 records candidate-local results pending the
final C7 audit; it does not relabel history or claim Part 1 completion.

## Consequences

- Documentation drift fails the active foundation command and CI.
- A valid link must resolve to a repository path and, when present, a real heading fragment.
- Managed-execution and implementation claims are rejected while future plans, explicit negations,
  and the bounded historical wrong-target identity event remain documentable.
- Stage 5 invokes no AWS API, mutates no infrastructure, authorizes no merge, and leaves Part 2
  blocked.
