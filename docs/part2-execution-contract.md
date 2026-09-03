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
