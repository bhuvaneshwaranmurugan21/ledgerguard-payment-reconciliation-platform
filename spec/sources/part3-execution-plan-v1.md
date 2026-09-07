# LedgerGuard Part 3 — Audited Execution Plan

**Planning date:** 2026-09-05  
**Planning-only deliverable:** no repository, GitHub, or AWS mutation is authorized by this document.  
**Repository baseline:** `main` at `cb81704adcfdfac5d93879cd6c189fc2213bbe79`  
**Master-plan source digest:** `a3d57722e8292629adfdcf90e32b90555eef8d80df5408523c0f71adeec454a0`  
**Part 3 target state:** `AWS_DEPLOYMENT_VERIFIED`  
**Part 3 workload boundary:** reconciliation workloads remain prohibited.

## 1. Executive decision

Part 1 and Part 2 have valid repository-defined closure authorities, but the attached master plan and the repository are not perfectly congruent. Therefore the correct starting action for Part 3 is not Terraform implementation. It is an append-only Part 2-to-Part 3 conformance recovery that preserves all accepted history while making the missing master-plan obligations explicit.

The plan uses eight stages. The split is functional rather than cosmetic: each stage eliminates a materially different risk and creates a trustworthy entry condition for the next stage.

| Stage | Purpose | Principal risk retired | AWS mutation |
|---|---|---|---|
| 1 | Part 3 entry authority and conformance recovery | False “100%” claim or inherited ambiguity | None |
| 2 | Exact-target AWS qualification | Wrong account, region, role, permissions, backend, budget, or dirty environment | Only a definition-only Glue create/read/delete probe |
| 3 | Deployable managed-runtime package | Local code that cannot run reproducibly on Glue 5.1 | None |
| 4 | Minimal Terraform platform and policy controls | Overbuilt, insecure, unbounded, or undeletable infrastructure | None; offline validation only |
| 5 | Real orchestration and authority semantics | Placeholder workflow or partial-authority publication | None; offline and definition validation only |
| 6 | Exact-source plan-only proof | Unreviewed Terraform drift or plan substitution | No apply and no workload |
| 7 | Controlled zero-workload canary and teardown | Deployment, configuration, cleanup, or residue failure | Expected infrastructure only; no workload execution |
| 8 | Part 3 audit, promotion, and closure | Premature or self-referential completion claim | None beyond read-only verification |

Part 3 finishes only after all six master gates are externally supported:

1. `environment_qualified`
2. `live_iam_parity_verified`
3. `glue_definition_probe_verified`
4. `plan_only_verified`
5. `zero_workload_canary_verified`
6. `teardown_verified`

The final claim is limited to safe deployment and destruction of the managed platform. It does not claim managed reconciliation, AWS data-processing correctness, performance, scale, production operation, custody, compliance, or overall project completion.

## 2. Audited awareness of completed work

### 2.1 Part 1

Part 1 is operationally closed under its append-only corrective authority:

- Replacement PR #9 was squash-merged as `3ef17666e3fe3bc655ba1c8733beb3cb00acdbec` and independent `main` CI passed.
- All 331 Part 1 requirements and 14 mandatory gates were re-audited.
- Frozen financial semantics, two reconciliation grains, canonical identities, accepted v2 contracts, historical v1 contracts, failure ownership, scorecard authority, and documentation governance are preserved.
- Stage 6 reproducibility established 224 tests, 95.737964% line coverage, 100% critical-validator branch coverage, 20 killed mutations, and two equal clean runs.
- No managed workload or infrastructure mutation was claimed.

This closure remains authoritative. Part 3 must consume it; it must not rewrite it.

### 2.2 Part 2

Part 2 is operationally closed against its repository-defined execution authority:

- Stage 2 independently implemented the reference oracle.
- Stages 3–5 implemented production admission, transaction reconciliation, and three-way settlement reconciliation.
- Stage 6 implemented an append-only, content-addressed local proof/case store with conditional authority and deterministic crash/concurrency recovery.
- Stage 7 executed genuine Spark 3.5.6 logic and independent Parquet logical readback, closing 21 behavioral scenarios, 21 reason codes, and eight critical paths.
- Stage 8 normalized and re-audited 203 requirements, 69 stage gates, and six master gates with zero critical, major, or open findings.
- PR #17 promotion was squash-merged as `71b42d6622558093a2bfaced58724f2ab71e793e`; its independent `main` CI passed.
- PR #18 closure attestation was squash-merged as `cb81704adcfdfac5d93879cd6c189fc2213bbe79`; its tree exactly matched validated head `0ff1603ca378479fdd46d09840cc015c8a1f1500`, and independent `main` CI run `33904881790` passed.
- The active bounded state is `LOCAL_RECONCILIATION_VERIFIED`.

The accepted claim boundary is equally important: AWS execution, managed persistence, managed reconciliation, infrastructure mutation, performance, scale, production operation, and project completion remain false or unclaimed.

## 3. Completion-integrity audit against the attached master plan

### 3.1 Verdict

Part 1 and Part 2 are complete against their repository-defined gate systems. They are **not literally 100% complete against every workstream in the attached master plan**. This is a traceability problem, not evidence that the implemented financial engine is unsound.

The Part 2 ledger contains 203 requirements, but it omitted several explicit master-plan responsibilities. Declaring the master plan 100% satisfied would therefore weaken the original scope. The correction must be append-only: preserve the successful closure and add a new master-plan conformance record that owns the omissions.

### 3.2 Gap register and routing

| ID | Finding | Evidence | Classification | Correct owner |
|---|---|---|---|---|
| LG-P3-G001 | Frozen-target live AWS identity was never verified. Historical identity evidence is `AWS_VERIFIED_WRONG_TARGET`; the exact frozen target remains unclaimed. | Current status and README; only a manual identity workflow exists. | Part 1 master-plan carryover | Part 3 Stage 2 |
| LG-P3-G002 | `README.md` and `PROJECT_STATUS.md` still describe PR #18 as a closure candidate even though it was squash-merged and post-merge CI passed. | `main` at `cb81704…` | Post-closure publication drift | Part 3 Stage 1 |
| LG-P3-G003 | The master plan requires a scale-selectable deterministic generator for small, 10K, 100K, and 1M profiles. No generator responsibility appears in the 203-requirement ledger and no generator module exists on `main`. | Part 2 master Workstream 1 versus repository tree and ledger | Part 2 master-plan omission | Govern in Stage 1; implement in Stage 3 |
| LG-P3-G004 | The master plan requires corrected-source resolution. The v2 case schema models `RESOLVED_BY_CORRECTION`, but the finalizer emits only `OPEN` or `RESOLVED_BY_LATE_DATA`, and no Part 2 requirement owns corrected-source classification. | Case schema, finalizer, tests, requirement ledger | Part 2 behavioral omission | Part 3 Stage 1 corrective slice, before AWS packaging |
| LG-P3-G005 | Part 2 uses deterministic boundary, permutation, and metamorphic tests, but it has no explicit scale-driven property campaign tied to the missing generator. | P2-S2-R013 and dependency/tooling inventory | Partial master-plan coverage | Part 3 Stage 3 |
| LG-P3-G006 | Local Spark behavior measurements—runtime, records/sec, partition count, join strategy, shuffle, skew, and output sizes—were not captured; performance and scale correctly remain unclaimed. | Part 2 master Workstream 6 and closure claim boundary | Deferred measurement | Part 4 scale stage, not Part 3 |
| LG-P3-G007 | The 1M benchmark has not run. | Master plan and claim boundary | Expected future work | Part 4 managed scale experiment |
| LG-P3-G008 | No Terraform, managed roles, S3 platform, Glue job definition, DynamoDB tables, Athena workgroup, CloudWatch configuration, or Step Functions state machine exists on current `main`. | Repository tree: the only AWS-specific executable file is the OIDC identity workflow. | Expected Part 3 scope, not a prior defect | Part 3 Stages 2–7 |
| LG-P3-G009 | Managed workload/recovery/scale evidence is absent. | Part 2 completion authority | Correctly unclaimed | Part 4 only |
| LG-P3-G010 | Final documentation, release, scorecard, and public-evidence hygiene remain incomplete. | Project completion contract | Correctly unclaimed | Part 5 only |

### 3.3 Routing rationale

- The deterministic generator must exist before Part 4 because Part 4 needs source artifacts whose totals are independent of the managed engine. Building and validating the generator in Part 3 Stage 3 does not violate the zero-workload boundary; no AWS reconciliation is run.
- Corrected-source resolution is a local semantic omission and must be repaired before packaging the managed runtime. It cannot be deferred to an AWS failure experiment because the managed run must test already-defined behavior.
- Local and managed scale measurements belong together in Part 4. Running them in Part 3 would contradict Part 3’s defining constraint: deploy and destroy safely before any managed reconciliation workload starts.
- Final repository simplification, release notes, performance narrative, and scorecard promotion remain in Part 5. Part 3 should update only facts necessary to make its own entry and closure truthful.

## 4. Non-negotiable inherited authorities

Every Stage 1–8 change must preserve:

- The Part 1 squash closure and all historical corrective records.
- All historical v1 schema bytes and the accepted v2 contract registry.
- The two-grain model: transaction and settlement remain separate.
- Integer minor units, explicit currency domains, checked signed 64-bit arithmetic, and no cross-currency aggregation.
- Canonical identity, digest, replay, and conflict scopes.
- Exact bank allocation; no date/amount heuristic matching.
- Append-only proof and case revisions.
- The independent reference oracle’s isolation from the production package.
- The Part 2 completion authority and immutable Stage 1–8 evidence.
- The distinction between financial exception, execution failure, infrastructure failure, and operator-only action.
- Existing evidence labels: `DESIGNED/MODELED`, `LOCAL_VERIFIED`, `AWS_VERIFIED`, and `UNCLAIMED`.

No stage may alter old evidence to make a new gate pass. Corrections are new versioned records that name the superseded claim and preserve its bytes.

## 5. Cross-stage execution protocol

### 5.1 Repository transaction

For each implementation stage:

1. Branch from the exact verified prior-stage squash commit.
2. Record the base commit and inherited authority digests.
3. Implement only that stage’s owned scope.
4. Run clean local validation at least twice where deterministic evidence is required.
5. Open the PR as draft.
6. Require raw event-head checkout and exact-head CI proof.
7. Download and independently inspect the immutable CI artifact.
8. Mark ready only after every stage gate passes.
9. Manually squash-merge.
10. Verify one-parent topology and tree equality with the validated PR head.
11. Require independent post-merge `main` CI before opening the next stage.

AWS-derived facts require a separate evidence transaction after the relevant code is on `main`. A branch cannot claim a future AWS run. The manual workflow runs against an exact immutable `main` SHA; a later closure PR records the run, job, artifact, digest, inventory, billing classification, and cleanup facts.

### 5.2 Workflow separation

- Automatic PR and push CI has `contents: read` only and receives no OIDC token.
- AWS workflows are `workflow_dispatch` only, require `main`, require an exact commit input, and use short-lived OIDC credentials.
- GitHub concurrency prevents overlapping LedgerGuard AWS operations, but it does not replace the account-side lease.
- No CloudShell dependency is introduced.
- No rerun is accepted as a fix unless the failure is proved transient and the unchanged inputs are recorded. Code, policy, definition, or teardown defects require root-cause correction and a new exact-head transaction.

### 5.3 Evidence envelope

Every AWS workflow artifact must include, in machine-readable form:

- Repository, workflow, run ID, attempt, branch, event, exact commit, and checked-out commit.
- Sanitized account fingerprint and explicit region without publishing raw credentials or tokens.
- Tool and provider versions.
- Input contract digests.
- Lease acquisition/release identities.
- Commands/actions performed and API boundaries exercised.
- Resource allowlist and before/after inventories.
- Test, coverage, mutation, plan, definition, and policy results relevant to the stage.
- Billing estimate and billing-data freshness.
- Negative assertions: no Glue run, no Step Functions execution, no Athena query, no business DynamoDB state, no managed reconciliation.
- Artifact manifest with SHA-256 for every member.

## 6. Stage 1 — Part 3 entry authority and conformance recovery

### Objective

Create an honest, append-only Part 2-to-Part 3 handoff and close only the master-plan omissions that must exist before AWS packaging. This stage performs no AWS call.

### Deliverables

1. A normalized Part 3 requirement ledger derived line-by-line from the attached Part 3 master plan, the project completion contract, inherited Part 1/2 authorities, and this gap register.
2. A Part 3 gate registry with exact owners for the six master gates and every subordinate gate.
3. Bidirectional traceability: requirement → code/test/evidence/claim, and artifact/test → requirement.
4. An append-only Part 2 master-plan conformance correction that records G003–G006 without rewriting the 203-requirement closure.
5. Corrected active status surfaces recording PR #18 squash commit `cb81704…` and independent `main` run `33904881790` as completed facts.
6. A frozen Part 2-to-Part 3 handoff containing digests for the active contracts, Part 2 completion authority, Spark projection, production package roots, reason taxonomy, and claim boundary.
7. Explicit corrected-source resolution:
   - A correction must be distinguishable from merely late-arriving evidence.
   - The event that authorizes the classification must be deterministic and schema-bound; time or operator intuition cannot decide it.
   - The new proof and case revision must retain predecessor identities and initial-exception identity.
   - System correction may emit `RESOLVED_BY_CORRECTION`; accepted variance and write-off remain operator-only and out of scope.
   - Replay, changed-content identity reuse, and ambiguous correction provenance fail closed.
8. Focused tests for exception → correction resolution, repeated correction, correction conflict, policy change versus source correction, and immutable historical readback.

### Validation

- All frozen Part 1 and Part 2 closure validators rerun unchanged.
- Old authority files are byte-identical.
- New correction tests achieve 100% statement and branch coverage over the changed semantic surface.
- Registered semantic mutations for late/correction misclassification, predecessor loss, actor-boundary breach, and historical rewrite all die.
- Two clean runs produce equal logical evidence digests.
- README and project status assertions agree with the immutable GitHub merge/run facts.
- Automatic CI proves zero OIDC permission and zero AWS action/API invocation.

### Failure paths

- If corrected-source provenance cannot be expressed without changing an accepted schema, stop and create an additive v3 proposal; never mutate v2.
- If old validators require stale candidate wording, preserve their historical snapshot inputs and update only active documents. Do not weaken the validator.
- If the Part 3 master ledger cannot trace a master-plan bullet, the stage remains open.

### Exit gate

Stage 1 closes only when the repository has a truthful active Part 2 closure, an append-only conformance correction, no unresolved pre-AWS semantic omission, complete Part 3 ownership, exact-head CI/artifact evidence, squash topology, and independent `main` CI.

## 7. Stage 2 — Exact-target AWS qualification and capability probes

### Objective

Prove the exact AWS identity, permissions, backend/lease readiness, budget headroom, service capabilities, and clean starting inventory before implementing or applying workload infrastructure.

### Required target

- Repository: `bhuvaneshwaranmurugan21/ledgerguard-payment-reconciliation-platform`
- Branch trust: `main` only
- Account: checked against the frozen target contract
- Region: `ap-southeast-2`
- OIDC role: `LedgerGuardGitHubOidcRole`
- Managed runtime: Glue 5.1 / Spark 3.5.6 / Python 3.11
- Gross Part 3 project ceiling: USD 10

AWS currently documents Glue 5.1 as Spark 3.5.6 and Python 3.11, matching the frozen target: <https://docs.aws.amazon.com/glue/latest/dg/release-notes.html>.

### Deliverables

1. A fail-closed manual read-only preflight workflow.
2. A canonical desired-state document for the GitHub OIDC trust policy and deploy-role permissions.
3. A live IAM parity comparator that normalizes policy JSON and rejects missing, extra, wildcard, wrong-repository, wrong-ref, wrong-account, or wrong-region capability.
4. A backend/lease decision record:
   - Prefer an already governed shared lab S3 backend after verifying versioning, encryption, public-access blocking, isolated state key, and access scope.
   - Use current Terraform S3 lockfile support rather than creating new DynamoDB locking solely for Terraform; HashiCorp documents DynamoDB-based S3 backend locking as deprecated: <https://developer.hashicorp.com/terraform/language/backend/s3>.
   - Keep the LedgerGuard operation lease distinct from Terraform state locking. It must be an account-side conditional lease with owner, exact SHA, workflow run, expiry, and safe release semantics.
   - If no qualified shared backend exists, stop. A separately authorized bootstrap plan is required; local state is not an implicit fallback.
5. Read-only or non-workload capability checks for backend access, S3, Step Functions definition validation, Athena workgroup inspection, CloudWatch log/metric inspection, AWS Budgets/cost access, tagging/inventory APIs, and service quotas.
6. A definition-only Glue probe that creates one uniquely named inert job definition, reads and compares it, deletes it, and independently proves deletion. It must never call `StartJobRun`.
7. A clean-inventory verifier using exact names, required tags, Terraform state knowledge when available, service-specific APIs, and negative execution queries.

### IAM rule

The deployment workflow must not silently manage the role it is currently using. Drift in `LedgerGuardGitHubOidcRole` blocks progress and is remediated through an explicitly authorized IAM change followed by a fresh parity run.

### Validation and evidence

- Caller account and assumed-role session match the frozen target.
- GitHub repository and `refs/heads/main` trust conditions match exactly.
- Backend read/write/delete is tested only within an isolated probe key and cleaned.
- Lease acquisition, competing acquisition rejection, expiry behavior, owner-only release, and empty final lease are proved.
- Glue definition create/get/delete succeeds and leaves no definition.
- Step Functions validation accepts the current definition without creating a state machine.
- No Athena query is started.
- No Glue job run or Step Functions execution exists for the probe identity.
- Budget data includes timestamp and latency classification; unavailable or stale billing data cannot be presented as zero cost.
- Before/after inventory is empty for active LedgerGuard workload resources.

### Failure paths

- Wrong account/region/repository/ref: terminate before any mutating API.
- IAM drift: produce exact missing/excess actions and trust-condition differences; do not broaden to `*`.
- Probe delete failure: run bounded cleanup using the recorded exact ARN/name; block Stage 3 until independent absence is proved.
- Budget headroom below reserve: do not proceed.
- Missing inventory visibility: qualify additional read permissions; absence cannot be inferred from AccessDenied.

### Exit gate

`environment_qualified`, `live_iam_parity_verified`, and `glue_definition_probe_verified` are externally verified; the environment is clean; no workload has run; all ephemeral probe state is absent.

## 8. Stage 3 — Deterministic data assets and deployable Glue package

### Objective

Produce the exact source artifacts that Part 4 will run, while preserving the independent-oracle boundary and executing no managed workload.

### Deliverables

1. A deterministic, streaming/bounded-memory data generator with profiles:
   - `correctness-small`
   - `local-10k`
   - `local-100k`
   - `managed-1m`
2. Explicit profile parameters for seed, merchants, currencies, settlements, postings, exception rate, split deposits, skew, late data, duplicates, conflicts, missing records, and policy changes.
3. Independent expected totals and scenario inventory produced without importing or calling production reconciliation code.
4. Canonical manifests, source file digests, row counts, byte counts, currency totals, and expected reason counts.
5. Deterministic seeded property/metamorphic campaigns covering ordering, partitioning, unrelated-merchant isolation, split deposits, replay, identity conflict, and currency isolation.
6. A Glue 5.1 entrypoint and reproducible dependency artifact built from the exact repository tree.
7. Strict job arguments for run ID, attempt ID, policy/manifest digests, input prefix, candidate output prefix, evidence prefix, and control-record identity.
8. S3 path validation that rejects traversal, wrong bucket, wrong run prefix, mutable aliasing, or cross-run output reuse.
9. A production package that does not contain or import the reference oracle.
10. A software bill of materials, wheel/zip inventory, file modes, normalized timestamps, and artifact SHA-256.

### Validation

- Same seed/profile/toolchain produces byte-identical canonical source files and manifests where promised.
- Different seeds or semantic parameters produce different identities.
- `small`, 10K, and 100K generation runs complete within the available 8 GB machine without unbounded collection.
- The 1M profile is generation-capable with bounded memory; reconciliation and managed execution remain deferred to Part 4.
- Expected totals are recomputed by an independent reader.
- Glue package installs/imports under Python 3.11 and uses Spark 3.5.6-compatible APIs.
- Local Spark correctness fixtures remain logically identical to the accepted Part 2 engine.
- No AWS SDK/client import appears in the pure reconciliation modules.
- New generator/property and packaging surfaces receive 100% owned branch coverage and zero surviving semantic mutations.

### Failure paths

- Memory growth: stream/chunk output and replace global collections with bounded aggregators; do not reduce the required profile.
- Non-deterministic Parquet bytes: claim deterministic logical rows/digests only unless physical reproducibility is actually proved.
- Glue/local dependency mismatch: resolve package/runtime compatibility; do not pin an unsupported artifact or suppress import failures.
- Oracle coupling: fail the packaging gate if any production dependency reaches the oracle package.

### Exit gate

The generator omission is closed, corrected-source behavior is included in the deployable package, package identity is reproducible, and the exact artifact is ready for infrastructure wiring without any AWS workload execution.

## 9. Stage 4 — Minimal Terraform platform, security, observability, and cost controls

### Objective

Define the smallest platform that can execute Part 4 correctly, securely, observably, and recoverably. No resource is applied in this stage.

### Infrastructure design

1. **S3 workload bucket**
   - Private, encrypted, versioned, TLS-only, public access blocked.
   - Prefixes for code, input, candidate output, authoritative manifests, cases/proofs, Athena results, and evidence.
   - Lifecycle rules for short-lived run artifacts and incomplete multipart uploads.
   - Bucket policy limited to exact roles and prefixes.
2. **Glue**
   - One Glue 5.1 Spark job with exact Python 3.11 package identity.
   - Bounded worker type/count, timeout, retry count, and concurrency.
   - Observability metrics and continuous logging configured without raw financial payloads. AWS describes Glue observability metrics as CloudWatch signals for reliability and performance diagnosis: <https://docs.aws.amazon.com/glue/latest/dg/monitor-observability.html>.
   - Minimal catalog database/tables required for Athena validation; no crawler unless a concrete requirement proves it necessary.
3. **Step Functions**
   - One Standard workflow with logging, timeout, traceable execution name, and exact service roles.
   - S3 pointers rather than large inline payloads.
4. **DynamoDB**
   - On-demand, encrypted control/case table; use a second table only if the access-pattern and isolation ADR proves it clearer.
   - Conditional run registration and authoritative-head publication.
   - TTL only for explicitly ephemeral records; immutable proof/case history cannot expire accidentally.
5. **Athena**
   - One enforced workgroup with dedicated output prefix, metrics enabled, requester-side override disabled, and a per-query scan cutoff. Athena supports workgroup/per-query data controls and can cancel queries that exceed the configured limit: <https://docs.aws.amazon.com/athena/latest/ug/workgroups-setting-control-limits-cloudwatch.html>.
6. **CloudWatch**
   - Explicit log groups, short retention, alarms/metrics needed for run success, failure, runtime, unresolved amount, exception rate, and cleanup.
7. **IAM**
   - Separate deploy, Step Functions, and Glue responsibilities.
   - Exact resource and prefix scoping, explicit PassRole boundaries, and no broad administration policy.
8. **Backend and leases**
   - Isolated remote-state key with S3 lockfile.
   - Separate conditional operation lease; expiry does not itself grant authority to delete another owner’s resources.
9. **Tags and naming**
   - Project, environment, owner, run, expiry, stage, managed-by, and exact-source SHA where service tagging supports it.

### Durable authority model

The AWS design must mirror Stage 6’s proven local semantics:

- Glue writes immutable candidate objects only.
- Candidate proof/case bodies and their manifests remain content-addressed in S3.
- DynamoDB can contain run registrations, summaries, candidate/head metadata, and case heads, but no candidate becomes authoritative through a partial bulk write.
- Final authority is a single conditional publication record that names a complete validated inventory and predecessor.
- Partially written candidates remain unreachable if validation or final publication fails and are eligible for explicit garbage collection.

### Static validation

- `terraform fmt`, `validate`, provider lock verification, TFLint, policy/security scanning, shell/YAML/JSON validation, ASL schema validation, and documentation links.
- Tests assert encryption, public blocking, TLS, versioning, lifecycle, retention, scan cutoff, timeout, worker bounds, retry bounds, OIDC/ref restriction, least privilege, tags, and destroyability.
- Terraform graph and plan-policy tests reject unexpected resources, data sources, providers, replacements, or deletes.
- No secret, account credential, raw synthetic financial record, generated-assistance language, or placeholder state appears.

### Failure paths

- Unsupported service attribute/provider behavior: pin a supported provider and prove equivalent control; never delete the requirement.
- Circular IAM/state-machine dependency: split policies or use narrowly scoped late binding; never grant wildcard access as a shortcut.
- Resource cannot be cleanly destroyed: redesign before apply.
- Cost estimate threatens the USD 10 ceiling: reduce idle retention or unnecessary resources, not verification coverage.

### Exit gate

The complete platform is represented in reviewable, locked Terraform and passes all static/security/cost/destroyability gates without touching AWS resources.

## 10. Stage 5 — Real orchestration and fail-closed control semantics

### Objective

Implement the complete state machine and the supporting run/finalization protocol. No placeholder state and no managed execution is permitted.

### Required state-machine behavior

1. Validate execution input shape, exact run/attempt identity, manifest digest, policy digest, source artifact identity, and allowed prefixes.
2. Conditionally register the run; identical replay resolves to the existing authority, while conflicting reuse fails.
3. Start Glue through the optimized `StartJobRun.sync` integration. AWS explicitly supports the `.sync` Glue integration: <https://docs.aws.amazon.com/step-functions/latest/dg/connect-glue.html>.
4. Require Glue’s immutable candidate manifest, job-run identity, counts, digests, and completion marker.
5. Start bounded Athena validation through the configured workgroup and obtain terminal query state/results. Step Functions supports Athena integration: <https://docs.aws.amazon.com/step-functions/latest/dg/connect-athena.html>.
6. Compare generator-oracle totals, Glue candidate totals, and Athena results before authority publication.
7. Materialize idempotent case-head and summary candidates.
8. Conditionally publish the authoritative run/commit pointer only when every required object and query proof exists.
9. Capture exact terminal failure ownership without converting infrastructure failures into financial exceptions.

### Control semantics

- Standard Workflow, not Express, because audit history, long-running `.sync` tasks, and deterministic execution identity are required.
- Retry only named transient service errors with capped attempts and backoff.
- Semantic/schema/identity failures are never retried as infrastructure transients.
- `Catch` paths preserve original error, failed state, attempt, and candidate inventory.
- Redrive creates a new attempt identity while preserving the run/reconciliation identity.
- State input/output carries pointers and digests, not datasets or raw financial records.
- The direct DynamoDB integration is used only where its supported operations and payload limits fit; otherwise the design must introduce a narrowly justified finalization component rather than force unsafe multi-item pseudo-atomicity. AWS documents Step Functions’ DynamoDB integration here: <https://docs.aws.amazon.com/step-functions/latest/dg/connect-ddb.html>.

### Validation

- AWS `ValidateStateMachineDefinition` accepts the rendered definition.
- Static reachability proves no placeholder, dead-end success, missing catch, unbounded retry, or success path that bypasses validation/finalization.
- IAM analysis maps every task state to the exact required action/resource.
- Deterministic transition tests cover happy path, registration replay/conflict, Glue failure/timeout, missing candidate evidence, Athena failure/cutoff, totals mismatch, conditional publication conflict, and cleanup handoff.
- No mocked success is accepted as managed evidence; these tests validate definition semantics only. Live behavior remains Part 4.

### Exit gate

The orchestration is complete, validates against AWS’s definition API, is least-privileged, and cannot publish partial authority. No state machine execution has occurred.

## 11. Stage 6 — Exact-source plan-only proof

### Objective

Prove that the exact current `main` source produces a bounded, expected Terraform plan without applying it or starting a workload.

### Workflow

1. Require exact `main` commit input and confirm raw event-head checkout.
2. Run Stage 2 identity, IAM, backend, lease, budget, and clean-inventory preflight.
3. Acquire the account-side operation lease conditionally.
4. Initialize the pinned Terraform/provider set against the qualified isolated backend key.
5. Create a binary saved plan.
6. Render its JSON and validate:
   - Exact resource-type/name/address allowlist.
   - Expected create count.
   - No update, delete, replacement, import, or unknown target.
   - Exact account/region, tags, IAM boundaries, runtime, worker/timeout, retention, encryption, and cost-control attributes.
   - No workload action or executable local provisioner.
7. Hash the binary plan, JSON plan, source tree, package, lock files, and policy verdict.
8. Prove inventory remains empty, clear any empty state/lease record, and release the lease by owner identity.

### Evidence

- Immutable plan-only artifact bound to workflow run, attempt, exact commit, Terraform/provider versions, backend key fingerprint, package digest, plan digests, policy results, clean inventories, and lease release.
- Estimated monthly standing cost and canary cost with explicit assumptions.
- Billing timestamp/classification; never equate delayed Cost Explorer data with zero spend.

### Failure paths

- Stale plan or source mismatch: discard and rebuild; never apply a plan not bound to the exact commit and dependency locks.
- Unexpected resource/change: fail and fix Terraform/policy root cause.
- Lock/lease contention: stop without force-unlock unless ownership and expiry are independently proved.
- Backend residue: clean the exact isolated key only after verifying it belongs to this failed attempt.

### Exit gate

`plan_only_verified` is externally verified, the expected resource set is fully known, and AWS still has no active LedgerGuard workload resource or execution.

## 12. Stage 7 — Controlled zero-workload deployment canary and teardown

### Objective

Apply the exact validated platform, inspect its control plane, prove that no reconciliation workload starts, destroy the exact inventory, and independently prove a clean environment.

### Admission

- Manual dispatch from the exact Stage 6-verified `main` commit.
- Explicit canary confirmation and cost ceiling input.
- Fresh identity/IAM/backend/budget/inventory preflight.
- Exclusive operation lease.
- Fresh saved plan validated by the same policy as Stage 6. The Stage 6 binary plan is evidence, not blindly reused after time or state has changed.

### Apply and control-plane validation

1. Apply only the newly validated saved plan.
2. Reconcile Terraform state, expected-address allowlist, tag inventory, and service-specific inventory.
3. Verify S3 encryption/versioning/public-block/TLS/lifecycle and exact allowed prefixes.
4. Verify Glue job version 5.1, package digest, arguments, role, workers, timeouts, concurrency, logging, and observability settings.
5. Verify Glue catalog schemas and table locations.
6. Verify the Step Functions definition hash, Standard type, logging, role, timeouts, retries/catches, and task resources.
7. Verify DynamoDB key schema, billing mode, encryption, TTL scope, conditional-write permissions, and zero business items.
8. Verify Athena workgroup enforcement, result location, metrics, and scan cutoff.
9. Verify CloudWatch log retention and required metric/alarm definitions.
10. Verify role trust and permission parity after deployment.

### Mandatory zero-workload proof

Before destroy, prove all of the following through authoritative APIs:

- Glue job-run count is zero.
- Step Functions execution count is zero.
- Athena query-execution count is zero for the workgroup.
- DynamoDB business/control state contains zero run, proof, case, or summary records.
- S3 business prefixes contain zero datasets, candidates, proofs, cases, or query results. Deployment code/config objects are inventoried separately.
- No scheduled trigger, EventBridge rule, crawler, or automatic invocation path exists.

### Teardown

1. Generate and validate an exact destroy plan against the deployed state and allowlist.
2. Cancel/stop only executions proven to belong to this canary, although the zero-execution gate should make this unnecessary.
3. Apply the saved destroy plan from an always-running cleanup path.
4. Verify Terraform state contains zero managed resources.
5. Verify every expected service inventory is absent.
6. Verify no active Glue run, Step Functions execution, Athena query, S3 multipart upload, or DynamoDB business record remains.
7. Remove the isolated state key only under the backend retention policy; do not damage a shared backend.
8. Release the operation lease only after independent cleanup passes.
9. Run a fresh, separately invoked read-only inventory after the deployment workflow ends.

### Failure paths

- Apply failure: preserve logs and partial inventory, then run exact cleanup; success cannot be claimed.
- Control mismatch: preserve evidence, destroy, fix source, repeat from plan-only proof.
- Unexpected workload start: stop it, preserve evidence, destroy, identify the trigger, and invalidate the canary.
- Destroy failure: retain the lease, create a bounded rescue inventory, and remove only exact owned resources. Part 3 remains blocked until independent clean proof passes.
- Incomplete visibility or AccessDenied: treat state as unknown, not clean.

### Evidence and exit gate

The immutable canary artifact must bind source, plan, applied inventory, configuration assertions, zero-workload queries, destroy plan, post-destroy state, independent clean inventory, lease release, and billing classification.

Stage 7 closes only when `zero_workload_canary_verified` and `teardown_verified` are externally verified with no active resource, lease, query, execution, job run, multipart upload, or Terraform state residue.

## 13. Stage 8 — Part 3 audit, promotion, and closure

### Objective

Re-audit every Part 3 requirement and gate, freeze the Stage 7 AWS evidence, and promote the repository to `AWS_DEPLOYMENT_VERIFIED` without claiming a managed reconciliation workload.

### Promotion transaction

1. Normalize the Part 3 requirement ledger and gate adjudication.
2. Trace every requirement bidirectionally to implementation, test, AWS evidence, or explicit future owner.
3. Freeze the exact successful qualification, plan-only, canary, teardown, and independent inventory runs/artifacts.
4. Recalculate evidence digests independently.
5. Confirm all six master gates are externally verified.
6. Confirm zero critical/major/open Part 3 finding.
7. Confirm Part 4 owns every managed correctness, failure, recovery, performance, scale, and cost-per-million claim.
8. Open a draft promotion PR; run exact-head CI, deterministic re-audit, mutation/claim-boundary tests, immutable artifact inspection, manual squash merge, tree/parent verification, and independent `main` CI.

### Closure-attestation transaction

After the promotion squash and independent `main` CI exist:

1. Open a separate closure PR from the exact promotion commit.
2. Record the promotion head/tree, squash commit/parent, exact-head run/job, post-merge run/job, AWS artifact identities, and final clean inventory.
3. Publish the schema-valid Part 3 completion authority with state `AWS_DEPLOYMENT_VERIFIED`.
4. Update active README/status/architecture/runbook facts without changing historical snapshots.
5. State explicitly:
   - AWS platform deployment and teardown: verified.
   - Glue job execution: false.
   - Step Functions execution: false.
   - Athena query execution: false.
   - Managed reconciliation/persistence: unclaimed.
   - Performance/scale/production operation/project completion: unclaimed.
6. Require exact-head CI and immutable closure artifact inspection.
7. Manually squash-merge, verify one parent and tree equality, then require independent `main` CI.

### Final Part 3 exit gate

Part 3 is complete only if:

- Read-only qualification passed on the exact frozen target.
- Live IAM equals checked-in least privilege.
- The Glue definition probe created/read/deleted cleanly and ran no job.
- Plan-only proof passed.
- Controlled deployment and exact configuration validation passed.
- No managed workload executed.
- Exact destroy succeeded.
- Independent clean-state verification passed.
- No orphaned lease or active resource remains.
- Billing is honestly classified under the USD 10 ceiling.
- Promotion and closure both pass exact-head CI, manual squash topology, and independent post-merge `main` CI.

The highest valid claim is then `AWS_DEPLOYMENT_VERIFIED`.

## 14. Deferred work ledger

### Part 4

- Local 10K/100K Spark behavior baseline and the master-plan metrics omitted from Part 2.
- Managed correctness workload.
- Managed semantic failure laboratory.
- Real recovery/redrive proof.
- 100K and 1M managed comparisons.
- Oracle/Glue/Athena totals agreement.
- Runtime, throughput, DPU-seconds, shuffle/spill/skew, Athena bytes, immediate cost, and cost per million.
- Managed proof/case persistence behavior under success and failure.
- Final claim `AWS_RECONCILIATION_VERIFIED`/`AWS_VERIFIED` only after its own evidence gates.

### Part 5

- Full technical defect audit.
- Complete human-facing documentation consistency audit.
- Performance/cost/failure/recovery narrative consolidation.
- Repository simplification and five-minute review path.
- Secret, dependency, action-pin, naming, generated-assistance-language, and public-evidence identifier hygiene.
- Final scorecard adjudication.
- Reproducible release archive, annotated `v1.0.0`, release notes, and `PROJECT_COMPLETE` authority.

Deferral is acceptable only because the owner and entry conditions are explicit. No deferred item may be counted as a Part 3 pass.

## 15. Required manual boundaries and access

The eventual execution will require the user to:

- Authorize each publication branch/PR and manually squash-merge after evidence inspection.
- Manually dispatch AWS workflows on the exact instructed `main` commit.
- Approve any IAM remediation if live parity fails; the execution must not broaden privileges autonomously.
- Provide or authorize a qualified shared Terraform backend/bootstrap if none exists.
- Ensure the AWS cost ceiling remains available.

No CloudShell work is required. The executor should perform repository and workflow work through the configured GitHub/AWS OIDC path and ask for user action only at genuine manual or authorization boundaries.

## 16. Definition of a high-quality Part 3 completion

High-quality completion is not “Terraform apply succeeded.” It is a reproducible chain showing:

`exact source → exact identity → qualified permissions → reviewed saved plan → allowlisted resources → exact configuration → zero workload → validated destroy plan → empty state → independent clean inventory → externally closed authority`.

Any missing link keeps Part 3 open. A green alarm, a retry, documentation, or an empty Terraform state cannot substitute for the missing evidence.
