# Part 2 execution contract

## Objective

Part 2 must produce a locally verified executable reconciliation system without using AWS. Its
completion state is `LOCAL_RECONCILIATION_VERIFIED`; Stage 1 establishes the authority and toolchain
needed to reach that state without claiming it prematurely.

## Ordered stages

1. Establish the execution contract, frozen entry evidence, ownership, toolchain, and CI boundary.
2. Build an independent reference oracle from the frozen semantics and examples.
3. Implement canonical admission, identity, policy, checked arithmetic, and normalization.
4. Implement transaction-grain reconciliation and exact negative-event reference capacity.
5. Implement settlement-grain three-way reconciliation and exact bank allocation.
6. Implement atomic proof finalization, append-only revisions, failure ownership, and deterministic recovery.
7. Prove local/Spark parity, the complete failure matrix, critical paths, and coverage quality.
8. Re-audit all Part 2 requirements and gates, publish reproducible evidence, and close Part 2.

Every stage consumes the same inherited Part 1 authorities. A later stage may add implementation or
evidence, but it may not reinterpret the financial grains, identity scopes, money representation,
bank allocation rules, reason domains, proof atomicity, or revision semantics.

## Stage 1 completion boundary

Stage 1 owns six internal gates: Part 1 closure proof, handoff authority binding, future runtime
ownership, toolchain compatibility, fail-closed validation, and the non-AWS transition. Passing
these gates establishes `PART2_STAGE1_EXECUTION_CONTRACT_ESTABLISHED` while the active project state
becomes `PART2_IN_PROGRESS`.

All six master Part 2 completion gates remain `UNCLAIMED`. In particular, a Spark session that
writes and reads a deterministic Parquet fixture is only toolchain evidence. It cannot satisfy
`spark_parity_verified` because no reconciliation implementation exists in Stage 1.

## Reproducibility contract

The local lane uses exact CPython 3.11.13, Java 17, Apache Spark 3.5.6, and Py4J 0.10.9.7. Both
`PYSPARK_DRIVER_PYTHON` and `PYSPARK_PYTHON` must identify the clean environment interpreter.
Spark SQL ANSI mode is enabled and the session timezone is UTC. All Python dependencies are
installed from complete hash-locked Part 2 lock files.

The compatibility probe executes at least twice in independent clean environments. It verifies
signed-long preservation, `decimal(38,0)` arithmetic, exact deltas above the IEEE-754 safe-integer
boundary, Parquet write/read behavior, and equality of the canonical logical payload. Output is
always outside the repository.

The minimal Stage 1 Spark surface does not include pandas or PyArrow. Spark's JVM Parquet path is
the tested requirement; unused optional Python data-frame or Arrow dependencies would expand the
lock and compatibility surface without adding evidence.

## CI and AWS boundary

Automatic CI checks out the raw event head, installs exact Python and Java versions, validates the
immutable Part 1 closure in a separate checkout, and then executes Stage 1 twice from the active
tree. Its token permissions are read-only. It cannot request an OIDC token, configure AWS
credentials, invoke an AWS CLI command, dispatch the manual identity workflow, or mutate a resource.

The existing AWS identity workflow remains manual-dispatch-only and is not a Part 2 Stage 1 gate.
AWS account `857229544428`, region `ap-southeast-2`, role `LedgerGuardGitHubOidcRole`, and Glue 5.1
remain frozen future targets—not evidence of execution.

## Failure policy

Missing authority, digest drift, incomplete ownership, an unknown reason code, a missing scenario,
runtime version drift, unequal Spark driver and worker interpreters, non-hashed dependency input,
non-deterministic clean runs, automatic AWS capability, or claim inflation fails Stage 1.

No failed check may be disabled, skipped, weakened, or renamed to obtain completion. Local success
alone is insufficient: exact-head pull-request CI, squash merge, and independent `main` CI are
external closure requirements.

## Stage 2 reference-oracle boundary

Stage 2 implements only the independent expected-result path in
`ledgerguard_reference_oracle`. It reproduces the frozen canonical identities and both financial
grains without importing production calculations. Admission or execution failure never yields an
authoritative proof. The oracle performs no persistence, Spark reconciliation, network access, AWS
execution, or infrastructure mutation.

The Stage 2 candidate covers every frozen example, coherence vector, runtime invariant, behavioral
scenario, and reason code with boundary, permutation, metamorphic, and targeted mutation checks.
Only `independent_oracle_verified` may advance, and it remains pending external closure until
exact-head draft-PR CI, immutable artifact inspection, squash merge, and independent `main` CI all
pass.

## Stage 3 admission boundary

PR #11 completed that external closure, so `independent_oracle_verified` is now
`EXTERNALLY_VERIFIED`. Stage 3 implements the production path only through complete input
admission and normalization. It verifies the frozen active v2 registry, strict canonical bytes,
policy and manifest bindings, object metadata and framing, source identity, replay/conflict,
checked journal balance, derived keys, currency domains, and bank-reference ambiguity.

Stage 3 never imports the reference oracle from production. The test path compares their owned
overlap. Admission creates only immutable in-memory candidate state and reconciliation-ready
records. It does not calculate transaction or settlement outcomes, persist state, allocate bank
movements, apply tolerance, finalize a proof, create a case revision, execute Spark, use AWS, or
mutate infrastructure.

All accepted v1 and v2 schema bytes remain frozen. The source wire protocol decisions needed above
those schemas are recorded in ADR 0019. Stage 3 uses the same exact Python 3.11.13, hash-locked,
two-clean-run evidence standard as Stage 2, with 100% statement and branch coverage of production
admission and zero survivors across the registered semantic mutations.

## Stage 4 transaction boundary

PR #12 completed the Stage 3 external closure. Stage 4 consumes admitted processor events and
transaction journals at the exact `(processor, merchant_id, payment_id, event_class, currency)`
grain. It evaluates the full outer union, derives processor amounts from policy event signs, and
derives ledger movement only from signed `PROCESSOR_CLEARING` postings. Missing evidence remains
explicit and semantic failures take precedence over tolerance.

Every refund, chargeback, and reversal must reference one exact capture source identity in the
same processor, merchant, payment, and currency scope. All negative applications share that
capture's capacity, regardless of class or arrival order. Multiple captures remain independent.
Replay observations merge with immutable prior transaction state by source identity, so identical
delivery is applied once and changed-content identity reuse fails closed.

The output is an immutable, deterministic, non-authoritative candidate. Stage 4 does not perform
settlement calculation, bank allocation, persistence, proof finalization, Spark execution, network
access, AWS execution, or infrastructure mutation. Promotion requires 100% statement and branch
coverage of the owned production surface, all registered semantic mutations killed, two equal
clean CPython 3.11.13 runs, exact-head draft-PR CI, and inspection of the immutable evidence
artifact. Local success alone does not promote Stage 4.

## Stage 5 settlement boundary

PR #13 completed the Stage 4 external closure. Stage 5 consumes admitted processor settlements,
settlement journals, and bank entries at the exact `(processor, merchant_id, settlement_id,
settlement_cycle, currency)` grain. Processor and ledger inputs form a full outer union. Processor
net is recomputed and checked per record before aggregation; clearing movement uses only
`PROCESSOR_CLEARING` credits minus debits.

Bank allocation uses only merchant, currency, and the exact NFC-normalized, outer-trimmed
settlement identifier. Case and punctuation remain significant. Every bank source identity has one
allocated or unallocated disposition, multiple distinct identities may form a split settlement,
ambiguous targets reject admission, and missing or unknown references remain visible without an
amount/date fallback. Same-manifest bank duplication is a financial exception and contributes
once; prior-state replay remains idempotent.

Candidates preserve processor-ledger, processor-bank, and ledger-bank deltas and their maximum
absolute difference. Semantic reasons precede tolerance. The output remains immutable,
deterministic, and non-authoritative. Stage 5 does not persist or finalize proofs, create revisions,
execute Spark, access AWS, or mutate infrastructure. Promotion uses the same exact Python 3.11.13,
hash-locked, 100% statement-and-branch coverage, zero-survivor mutation, two-clean-run, exact-head
draft-PR, immutable-artifact, squash-merge, and post-merge-main evidence standard.

## Stage 6 proof-finalization boundary

PR #14 completed the Stage 5 external closure. Stage 6 promotes complete transaction and settlement
candidate batches through one local conditional authority pointer. Canonical requests, proofs, case
revisions, and commits are immutable and content-addressed. Each authoritative read revalidates
canonical encoding, digests, schemas, inventories, and predecessor chains.

Proof revisions are append-only. Exceptions open or continue a stable case; a later match appends a
`RESOLVED_BY_LATE_DATA` case revision. Exact and historical retries return the original receipt,
attempt reuse with changed inputs fails, and concurrent writers sharing one expected head yield one
winner. Real process termination at each durable boundary must recover without partial authority.

The authoritative request also retains the complete admitted transaction and settlement states
needed for deterministic cross-batch replay. No state is trusted from unreachable files. Storage,
integrity, conflict, and recovery failures are execution-owned and cannot issue a partial financial
proof.

This is a local canonical JSON store only. Stage 6 does not execute Spark, establish Parquet parity,
call AWS, dispatch workflows, mutate infrastructure, or claim managed persistence. Exact-head CI,
immutable evidence, squash merge, and independent post-merge `main` CI remain required for external
closure.

## Stage 7 Spark parity and critical-path boundary

PR #15 completed Stage 6 external closure. Stage 7 runs the accepted transaction and settlement
candidate model through genuine Spark 3.5.6 expressions under Java 17 and CPython 3.11.13. Spark
recomputes both grains' deltas and differences with `decimal(38,0)`, applies semantic reason
precedence, writes typed Parquet outside the repository, reads it independently, and compares the
canonical logical projection with the local engine.

The validation matrix binds all twenty-one frozen behavioral scenarios, all twenty-one closed
failure reason codes, and matched, exception, late-data, policy-change, replay, conflict, crash, and
concurrency critical paths to executable tests. Physical Parquet bytes are not claimed deterministic;
logical rows and their canonical digest are. Spark output remains non-authoritative until Stage 6
finalization. Stage 7 performs no AWS or infrastructure operation and does not close Part 2.

## Stage 8 promotion and closure boundary

PR #16 completed Stage 7 external closure. Stage 8 adds no reconciliation behavior. It freezes the
exact Stage 7 PR head, squash commit, sole parent, tree, exact-head CI, independent main CI, and
immutable artifact evidence. It then normalizes and re-audits every Stage 1 through 8 requirement
and gate, preserves the original owner of each master completion gate, and publishes deterministic
closure evidence.

The promotion candidate remains `PART2_IN_PROGRESS`. It may record the six master gates as
externally verified because their owning implementation and verification stages have completed,
but it may not claim the final `LOCAL_RECONCILIATION_VERIFIED` state before its own promotion
protocol succeeds.

Terminal closure uses two pull requests. The first validates and squash-promotes the audited
implementation tree. After independent post-merge main CI passes, the second publishes the exact
repository-resident closure record and active final status. Both transactions require exact-head
CI, a one-parent squash merge, validated tree equality where applicable, and independent main CI.
This prevents either a pre-merge claim or an infinite self-attestation cycle.

Stage 8 performs no AWS call, workflow dispatch, infrastructure mutation, managed persistence,
managed reconciliation, performance or scale execution, or production operation. Those claims
remain owned by later project parts.

PR #17 satisfied the promotion transaction at squash commit
`71b42d6622558093a2bfaced58724f2ab71e793e` and independent main CI run `33874130476`.
The separate closure-attestation transaction publishes the schema-valid completion authority and
changes no reconciliation implementation. Its exact-head evidence, manual squash merge, and
independent main CI are the remaining publication controls. The completion authority is bounded to
local reconciliation and leaves AWS, managed execution, performance, scale, production operation,
and overall project completion unclaimed.
