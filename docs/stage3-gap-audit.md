# Stage 3 contract-coherence gap audit

## Accepted boundary

- Stage 2 main merge: `583fbd13a129ac067a23f6348d05077d8b9250eb`
- Stage 2 main tree: `40283451e9b73217c598ccea2d6eaea3a75797da`
- Accepted Stage 2 head: `a6bbcbc24d9acda5d2a04a54cce890eaf90fab00`
- Stage 2 PR CI: `33511658292`, success on the exact head
- Stage 2 post-merge CI: `33511951023`, success on `main`
- Stage 0/1/2 validator digests are preserved by the Stage 3 completion contract.
- No AWS execution or infrastructure mutation occurred.

## Reproduced gaps

Stage 2 correctly encoded record shapes, but shape validation alone does not define input bytes or
cross-artifact identity. In the accepted Python validation stack, JSON Schema treats `1.0` as an
integer because it is mathematically integral. The active timestamp schema also accepted the
calendar-impossible value `2026-02-30T00:00:00Z`. Neither behavior is acceptable at a financial
admission boundary.

Stage 2 also owned only external reference targets, not every referenced fragment. It did not yet
freeze canonical byte vectors for policy, manifest, proof and case digests; derive proof and case
identities; bind the entire policy → manifest → proof → case chain; or prove bidirectional Stage 3
traceability.

## Corrective disposition

The v1 and v2 schemas remain byte-identical. Stage 3 adds a strict pre-schema parser, calendar-aware
timestamp normalization, canonical UTF-8 bytes, explicit digest exclusions, domain-separated
identity derivation, complete reference-fragment resolution, cross-contract set equality and a
golden linked-artifact chain. The active schemas still validate canonicalized specimens after the
stricter boundary has admitted them.

This layering avoids rewriting accepted contract history while preventing a permissive library
interpretation from becoming financial truth.

## Remaining boundary

Stage 3 validates contract coherence locally. Part 1 still requires its final completion-governance
freeze. Reconciliation execution, Spark parity, managed AWS evidence, performance and cost remain
outside this stage.
