# Stage 2 financial-contract gap audit

## Audited boundary

- Accepted Stage 1 merge: `155211c5df0985b332d3ba8c9d7b82ec4fc10c6a`
- Accepted Stage 1 tree: `0bb7631d533418ecf78c2d4b9f3e44959fee767d`
- Accepted Stage 1 head: `46b1f4e852ea40b24adaa30625074a2a05654259`
- Stage 1 post-merge CI: `33505222160`, success on `main`
- Stage 0 validator digest:
  `3da80eb91b0948f50c5080c7198e78a0a1716a36c7ca7267ec205099b981282b`
- Stage 1 validator digest:
  `4234ac61999de769b87b2329512a8741761023b6c258dfd2207beb66f7dbc191`
- AWS execution or infrastructure mutation: none

## Reproduced contract gaps

| Contract | Reproduced `v1` behavior | `v2` correction |
|---|---|---|
| Processor event | Required negative reference may be null; capture may carry a reference | Non-null conditional reference and capture prohibition |
| Journal | Entry type and processor are optional; both grain keys can coexist | Required namespace and entry type with entry-dependent exclusive key |
| Processor settlement | Components are unbounded and reported/recomputed meaning is unclear | Int64 fields and an explicit reported-net source value |
| Bank entry | Money is unbounded and reference structure is weak | Int64 amount and a non-whitespace optional settlement reference |
| Policy | Signs, roles, references, allocation and permitted accounts are absent | Complete frozen financial interpretation |
| Proof | Transaction requires a bank placeholder; settlement loses pairwise deltas | Mutually exclusive grain-specific proof shapes |
| Case revision | Grain, initial exception proof and actor restrictions are absent | Grain identity, closed statuses/reasons and actor/revision conditions |
| Run manifest | Only S3 locations validate | Honest local-file and immutable S3-object variants |

All source and output contracts also lacked shared signed-64 bounds, a canonical UTC shape, a single
closed currency domain, and common taxonomies.

## Enforcement gap

JSON Schema cannot prove journal balance, property-level line uniqueness, checked aggregation,
reference existence, capture capacity, replay/conflict across records, settlement uniqueness, exact
allocation, proof arithmetic, or append-only history. Stage 2 records these requirements in the
machine-readable invariant register and assigns them to Part 2 runtime validation. None is silently
weakened or claimed as schema-enforced.

## Versioning disposition

The eight top-level `v1` schemas remain byte-identical because Stage 0 evidence binds them. The
active corrected contracts use `v2` identities and are selected exclusively through a digest-bound
registry. This preserves the rejected contract history without allowing it into later execution.

## Stage 2 boundary

Stage 2 establishes locally verified contract structure and governance. Complete reconciliation
coherence, an independent oracle, Spark parity, AWS execution, infrastructure, performance, and
cost remain outside this stage.
