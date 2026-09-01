# Financial contract model

## Authority

The active contract set is declared by
[`active-contract-set-v1.json`](../contracts/active-contract-set-v1.json). Directory discovery is
not authority: Part 2 consumers must load the registry, verify its digests, and use only its active
`v2` entries.

The top-level `v1` schemas are preserved historical artifacts. They are not accepted runtime input
contracts.

## Validation layers

| Layer | Enforces | Does not claim |
|---|---|---|
| JSON Schema | Required fields, closed objects, data types, int64 bounds, enums, grain shapes, actor and revision conditionals | Cross-record or arithmetic correctness |
| Stage 2 governance | Active inventory, unique `$id` values, SHA-256 bindings, offline references, semantic traceability, closed taxonomies | Reconciliation execution |
| Part 2 runtime | Canonical digests, journal balance, checked sums, replay/conflict, references, allocation, proof arithmetic, history | Managed AWS execution |

The machine-readable ownership record is
[`contract-invariants-v1.json`](../spec/contract-invariants-v1.json).

## Shared primitives

`common-v2.schema.json` owns signed 64-bit bounds, supported currencies, canonical UTC timestamp
shape, SHA-256 shape, identifiers, financial reasons, grains, account roles, and case statuses.
Domain contracts reference these definitions by local registry identity. This prevents a proof from
silently using a different reason or money domain than a source record.

## Source contracts

- Processor events carry positive raw amounts. Captures forbid a reference; refunds, chargebacks,
  and reversals require one exact capture reference.
- Processor settlements carry five non-negative components and a signed reported net. Formula
  agreement is deliberately assessed as a financial rule, not a schema admission rule.
- Journals declare ledger system, processor, entry type, and exactly one applicable grain key.
  Schema validation requires positive postings; runtime admission validates unique lines and
  balanced totals.
- Bank entries are cash movements and contain no payment key. Settlement references may retain
  surrounding source whitespace because exact allocation performs the frozen normalization.

## Policy contract

Policy owns the complete interpretation: currency exponents and tolerances, event signs, clearing
roles and side signs, allowed counterpart roles, reference capacity, settlement formula, exact bank
allocation, permitted accounts, status rules, late-data behavior, version, and digest.

Reusing a policy version with different canonical bytes remains a runtime admission failure.

## Manifest contract

A manifest may name repository-relative local files or immutable versioned S3 objects. The variants
are mutually exclusive. Every manifest contains all four source families and binds policy, source
commit, object bytes, counts, and its own canonical digest.

## Proof and case contracts

Transaction proofs contain processor and ledger totals only. Settlement proofs contain processor,
clearing, and bank totals plus all three signed deltas. Status controls the closed reason shape;
admission and execution reasons cannot enter an authoritative proof.

Case identity includes grain, reconciliation key, and initial exception proof. Revision one has no
predecessor; later revisions require one. System actors cannot accept variance or write off a case.
Sequential history and immutable predecessor bytes remain Part 2 runtime responsibilities.

## Claim boundary

Stage 2 verifies contract encoding locally. It adds no reconciliation engine, Spark job, AWS
execution, or infrastructure mutation.
