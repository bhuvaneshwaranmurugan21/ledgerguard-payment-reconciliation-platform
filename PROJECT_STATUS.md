# Project status

## Active boundary — Part 3 Stage 4

Stage 3 is externally accepted at PR #26 squash `3370898d83539fe41594c7cb7ad15e920dcb5674`.
The immutable external receipt and append-only gate-name correction remain authoritative.
Stage 4 is in progress on draft PR #27. It is not ready to merge or deploy.

The successor implements resource controls, actual runtime transport and catalog schemas,
exact-decimal budget admission, separated IAM policy construction, and source-bound security
review. Local evidence is recorded in `docs/part3-stage4-execution-checkpoint.md`.
The previous source `81be7bd` passed both independent native jobs (run 34530756877)
and full repository CI (34530756937). Its verified 100% critical coverage and 22 killed
mutations remain historical evidence. User-dispatched read-only run 34559335116 verified
the accepted Stage 2 IAM/trust and backend/lease baseline with 43 read-only calls and no
mutations. The actual backend KMS ARN was supplied and bound to the review packet.

The current successor completes named reader/recovery identities, their self-observation
permissions, exact bootstrap attachments, and rejection of role/policy/default-version drift.
Local qualification passed 387 tests with 100% of 478 package statements and 226 branches;
full native qualification and independent inspection must bind this successor before acceptance.
The original 22 mutation entries remain unchanged; four additional administrator faults are
registered. See `docs/part3-stage4-administrator-handoff.md` for the concrete handoff.
The successor IAM is not installed and document parity does not establish effective permissions.
Administrator review, restriction/capability evidence and stage publication/main gates remain open.

Stages 5–8 are pending. No AWS change, workload execution, new merge or Part 3 completion is
claimed. The combined sequence retains every stage admission and user-controlled AWS boundary.

## Historical Stage 3 producer status (unchanged below)

- Project: LedgerGuard
- Part: 3 — Managed AWS platform
- Stage: 3 — Deterministic data and Glue runtime package
- State: `LOCAL_RECONCILIATION_VERIFIED`
- Stage state: `PART3_STAGE3_IMPLEMENTED_PENDING_EXACT_HEAD_CI`
- Historical Stage 2 implementation token: `PART3_STAGE2_IN_PROGRESS`
- Highest accepted claim: Part 2 repository-local reconciliation; PR #18 closure externally verified
- Stage 1 external closure: `EXTERNALLY_VERIFIED`
- Stage 2 qualification and closure: `EXTERNALLY_VERIFIED`
- Reference oracle: `EXTERNALLY_VERIFIED`
- Production admission: `EXTERNALLY_VERIFIED`
- Transaction reconciliation: `EXTERNALLY_VERIFIED`
- Settlement reconciliation: `EXTERNALLY_VERIFIED`
- Atomic proof finalization: `EXTERNALLY_VERIFIED`
- Spark reconciliation parity: `EXTERNALLY_VERIFIED`
- Stage 7 external closure: `EXTERNALLY_VERIFIED`
- AWS execution: bounded Stage 2 qualification only
- Automatic CI AWS execution: false
- AWS infrastructure mutated: temporary run-scoped S3, lease, and Glue probe resources; cleanup complete
- Managed reconciliation execution: false
- Stage 2 external closure gate: `P3-S2-G020 EXTERNALLY_VERIFIED`
- Stage 3 AWS execution: false; repository-local generation, Spark, and packaging only
- Stage 3 candidate: four exact deterministic profiles, independent expectations and seeded
  campaign, native source-to-candidate Spark, reproducible Glue 5.1 offline bundle/SBOM, strict
  argument/path confinement, 100% owned statement/branch gate, and 24-mutation semantic gate.
  These remain candidate claims until exact-head PR CI and independent artifact inspection pass.
- External Stage 3 closure: pending user-controlled squash merge and independent exact-main CI;
  Part 3 and the overall project remain incomplete.
- Stage 3 output authority: immutable non-authoritative candidates only

## Accepted Stage 2 snapshot

The following line preserves the exact status token validated at the immutable Stage 2 tree. It is
historical entry evidence; PR #11's squash and post-merge CI promoted the oracle beyond this local
candidate state.

- Stage state: `PART2_STAGE2_REFERENCE_ORACLE_VERIFIED_CANDIDATE`

## Accepted Stage 1 snapshot

The following lines preserve the exact status surface validated at the immutable Stage 1 tree; they
are historical entry evidence, not the current Stage 2 state.

- Stage: 1 — Execution contract and local toolchain
- State: `PART2_IN_PROGRESS`
- Stage state: `PART2_STAGE1_EXECUTION_CONTRACT_ESTABLISHED`
- Reference oracle: `UNCLAIMED`
- Reconciliation implementation: `UNCLAIMED`
- Spark reconciliation parity: `UNCLAIMED`

## Frozen Part 1 closure boundary

- Project: LedgerGuard
- Part: 1 — Foundation and completion contract
- Stage: 7 — Promotion and closure
- State: `PART1_FOUNDATION_COMPLETE`
- Overall project state: `PROJECT_IN_PROGRESS`
- Part 2 entry: `UNLOCKED_ONLY_AFTER_RECOVERY_SQUASH_AND_POSTMERGE_MAIN_CI_PASS`
- Promotion attempt 1: `FAILED_CLOSED_NON_SQUASH_MERGE`
- Active promotion: `PR_9_SQUASH_RECOVERY`
- Promotion recovery outcome: `PART1_OPERATIONALLY_COMPLETE`
- Historical Stage 4 state: `PART1_FOUNDATION_COMPLETE` (preserved, not active)
- Highest claim: `LOCAL_VERIFIED` for foundation validation
- AWS execution: false
- AWS infrastructure mutated: false
- Managed reconciliation execution: `UNCLAIMED`
- Frozen-target live identity: `UNCLAIMED`
- AWS account-wide nonmutation: `NOT_PROVEN`

## Established and preserved

- Immutable Stage 0–4 contracts, evidence, schemas, and validator outputs.
- Frozen two-grain financial semantics and locally verified examples.
- Historical v1 schemas and the accepted active v2 contract registry, all digest-bound.
- Canonical JSON, identity, replay/conflict, allocation, proof, and revision semantics.
- A 95-file accepted Stage 4 inventory with exact snapshots of every C0-mutated file.
- Owner-approved amendments for the historical AWS claim and v1-to-v2 change control.
- An immutable 108-file C0 exact-head tree that reproduces the accepted C0 result in isolation.
- A deterministic 331-requirement forward ledger, reverse index, and exact 14-gate registry.
- A schema-backed active completion authority with exact invariants and scoped evidence metadata
  for all 12 scorecard dimensions.
- An exact Stage 5 document inventory, active-contract diagram, reason/outcome map, target table,
  scorecard comparison, link resolver, and negative claim controls.
- Two clean deterministic Stage 6 runs, 224 tests with zero skips, 95.737964% line coverage,
  100% critical-validator branch coverage, and 20 mutation checks with zero survivors.
- Exact-head Stage 6 CI run `33609507209` and immutable artifact `9838502686`, independently
  revalidated by ZIP and evidence digests.
- A Stage 7 fail-closed promotion contract and complete re-audit of all 96 historical non-passes.

## Part 1 completion and Part 2 entry

The immutable historical audit remains 235 passes and 96 non-passes. It has not been edited or
relabelled. The Stage 7 audit re-evaluates all 331 requirements, all 96 historical non-passes, and
all 14 mandatory gates against the corrected repository. There are zero implementation corrections,
zero critical findings, and zero major findings remaining in the Part 1 candidate.

PR #8 passed exact-head and `main` CI, but its two-parent merge commit failed the separate
squash-only gate. That attempt remains failed and immutable. Replacement PR #9 passed exact-head
CI, was squash-merged as one-parent commit `3ef17666e3fe3bc655ba1c8733beb3cb00acdbec`, and independent
`main` CI run `33627452565` passed. Part 1 is therefore operationally complete and Part 2 entry is
unlocked.

Stage 1 established the Part 2 execution authority, responsibility ownership, exact local
Spark/Parquet toolchain, traceability, and non-AWS CI boundary. PR #10 was squash-merged as
`95b7e2a1c6a1dd758a8ce43c73bdea80117b6d91`, and independent main CI run `33710867915` passed.

Stage 2 adds an independent reference oracle for canonical identity, checked arithmetic,
transaction and settlement expectations, exact references and allocation, status and reasons, and
proof/case identity expectations. PR #11 passed exact-head CI, was squash-merged as
`55e78f76e76bff7562d43a3d001dbb74fd66d8fd`, and passed independent `main` CI; its oracle gate is
therefore externally verified.

Stage 3 added only the production admission and normalization boundary: digest-bound v2 schema
loading, strict bytes and canonical values, policy/manifest binding, atomic source replay state,
checked journal admission, exact keys, currency domains, and bank-reference ambiguity rejection.
PR #12 passed exact-head CI, was squash-merged as
`47e96d3f4846d55568c0b137fb3e4d41ead0eef1`, and passed independent `main` CI run
`33729063294`; admission is therefore externally verified.

Stage 4 added transaction-grain reconciliation over the immutable Stage 3 handoff. It implements
the full outer grain union, policy signs, clearing-account movement, checked arithmetic, exact
capture references, cumulative cross-class negative-event capacity, deterministic status and
reason precedence, and replay-safe immutable candidate state. It does not add settlement
reconciliation, bank allocation, durable persistence, proof/case/revision finalization, Spark,
AWS execution, or infrastructure mutation. PR #13 passed exact-head CI, was squash-merged as
`c423ae7e6e92d37ffa8a796b4efacbf9ba6692f1`, and passed independent post-merge `main` CI run
`33741521494`; transaction reconciliation is therefore externally verified.

Stage 5 adds settlement-grain three-way reconciliation and a deterministic allocation ledger over
the immutable Stage 3 handoff. It recomputes every processor net before aggregation, isolates
settlement clearing movement, preserves all three pairwise deltas, and allocates bank identities
only by exact normalized settlement reference. Missing, unknown, ambiguous, duplicate, or
disallowed bank evidence fails visibly. The result is immutable and non-authoritative. Stage 5 does
not persist or finalize proofs, create revisions, execute Spark, access AWS, or mutate
infrastructure. PR #14 passed exact-head CI, was squash-merged as
`89373adf968ff7071693f8cce5d12901fd9b1e69`, and passed independent post-merge `main` CI run
`33777351580`; settlement reconciliation is therefore externally verified.

Stage 6 adds a local content-addressed proof store with one conditional authoritative head. It
finalizes complete transaction and settlement candidate batches atomically, appends proof and case
revisions, owns storage and conflict failures as non-authoritative execution failures, and recovers
deterministically across real process termination and concurrent writers. Authoritative history
also preserves the admission and reconciliation states required for later-batch replay. Stage 6
does not execute Spark, write managed Parquet, access AWS, dispatch workflows, mutate
infrastructure, or close Part 2. It remains a local candidate until exact-head draft-PR CI and
immutable evidence inspection complete. That historical candidate boundary was subsequently closed
by PR #15 as recorded below.

PR #15 passed exact-head CI, was squash-merged as
`376e686813e6271e2d6787467a5500ba0827dfcb`, and passed independent post-merge `main` CI run
`33850525300`; atomic proof finalization is therefore externally verified. Stage 7 adds genuine
Spark 3.5.6 recomputation and Parquet logical readback for both financial grains, binds the complete
failure taxonomy to executable evidence, and exercises the accepted critical paths. It does not
call AWS, transfer authority to Spark, claim managed persistence, or close Part 2.

PR #16 passed exact-head CI run `33857511781`, was squash-merged as
`8fac3795ed0dac5284dd3b1595bd8fc9f6dc7344`, and passed independent post-merge `main` CI run
`33863399041`. The validated PR head and squash merge share tree
`6ae471cd73a1255df99edd953b8d0e0850790362`; genuine Spark parity, the complete failure matrix,
deterministic replay, and all eight critical paths are therefore externally verified.

Stage 8 freezes that closure, normalizes and re-audits all 203 Part 2 requirements and 69 stage
gates, and adjudicates the six master Part 2 gates. Both promotion and closure-attestation transactions are complete. PR #18 was squash-merged
at `cb81704adcfdfac5d93879cd6c189fc2213bbe79`, with exact-head CI `33879453002` and independent
main CI `33904881790` passing.

PR #17 passed exact-head CI run `33871740027`, was squash-merged as
`71b42d6622558093a2bfaced58724f2ab71e793e`, and passed independent post-merge `main` CI run
`33874130476`. Its one parent is the Stage 7 closure and its tree
`406f40dfb1e94e38031505e23a6d77b50198840f` equals the validated PR head tree exactly.

The historical terminal Part 2 authority remains unchanged and active for its accepted local scope.
The append-only Part 2 master conformance addendum records all original-master carryovers with
owners. Part 3 Stage 1 is externally complete. Part 3 Stage 2 has independently accepted read-only
and bounded capability evidence on exact main commit
`aa136331e44dcd181f766b42d76ee2616a22f435`. PR #25 closed its evidence transaction at squash
commit `d0fb01392f7f975909229f418c13a9c73ba8395e`; PR and post-merge main CI passed. All 22
requirements and all 20 Stage 2 gates are externally verified. Stage 3 begins from that exact
one-parent base and owns only deterministic data, property-campaign, and native source-to-candidate
Spark package gaps G003, G005, and G011. Exactly three Part 3 master gates are `AWS_VERIFIED`;
the other three remain `NOT_EXECUTED`.
No managed reconciliation, deployed-platform, performance, scale, production-readiness, Part 3,
or overall-project completion claim is made.
