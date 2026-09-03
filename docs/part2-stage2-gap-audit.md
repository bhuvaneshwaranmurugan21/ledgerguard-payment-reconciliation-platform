# Part 2 Stage 2 reference-oracle gap audit

## Entry evidence

Stage 2 starts from PR #10's squash commit
`95b7e2a1c6a1dd758a8ce43c73bdea80117b6d91`, tree
`668e2e89473b026d9857d162fb9e45a3c8f465a1`, and sole parent
`3ef17666e3fe3bc655ba1c8733beb3cb00acdbec`. Exact-head CI run `33657002427` and independent
post-merge `main` CI run `33710867915` passed. The eight inherited Part 1 authorities remain
bound to the digests recorded by Stage 1.

## Gap being closed

Stage 1 established ownership and an exact local toolchain but deliberately left
`reference_oracle_implemented` false. The frozen schemas, semantics, examples, invariants,
coherence vectors, reason domains, and failure scenarios therefore had no separately packaged
executable expected-result implementation.

Stage 2 closes only that gap. It adds a side-effect-free reference oracle for canonical identity,
checked arithmetic, transaction expectations, settlement expectations, proof/case identities,
and failure-without-proof decisions. It also adds bidirectional requirements, gate traceability,
coverage inventories, negative mutation tests, deterministic clean-run evidence, and exact-head CI
evidence.

## Separation from later runtime work

The oracle consumes explicit immutable values and returns expected decisions. It does not read or
write operational stores, publish authoritative proofs, recover failed workers, execute Spark
reconciliation, call AWS, or implement the production reconciliation path. Production source must
not import the oracle. Later comparison tests may evaluate production and oracle results separately.

Checked arithmetic, identity, transaction, settlement, and revision behavior in this stage are
independent expectations for later runtime verification. Their presence does not claim that the
production enforcement responsibility is complete.

## Acceptance boundary

The local candidate may mark only `independent_oracle_verified` as pending external closure. The
other five Part 2 master gates remain `UNCLAIMED`. Final promotion requires exact-head draft-PR CI,
inspection of the immutable evidence artifact, squash merge, and an independent successful main CI
run. No AWS execution or infrastructure mutation is part of Stage 2.
