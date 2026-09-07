# LedgerGuard — Part 3, Stage 2 execution plan

**Stage:** Exact-target AWS qualification and capability probes  
**Status:** Execution plan only; no Stage 2 repository or AWS action has been performed  
**Planning date:** 2026-09-07  
**Scope:** Part 3 Stage 2 only. Later stages appear solely where Stage 2 must define a safe handoff.

## 1. Decision and exact starting point

Begin Stage 2 from the verified Stage 1 squash commit
`5abef1a07899bd8ecd202008f1c397890184a0d2`, whose tree is
`77f13e8a68c46ccdcdae426b82c37c66d5e3ed81` and whose sole parent is the accepted
Part 2 closure `cb81704adcfdfac5d93879cd6c189fc2213bbe79`.

PR #19 and main CI run `34105604941` passed. The two main jobs were `foundation`
(`101689780829`) and `part3-stage1-current` (`101689780591`). The independently
downloaded main artifact `10013159831` contained 223 verified members and had ZIP
SHA-256 `f1338e2320a1113410c7a0ac6a90b5eebb73abe512fcc5a53ca6f77aafdf641f`.
Both clean runs passed 658 tests with no failures, errors, or skips, killed all 29
mutations, and produced the accepted wheel SHA-256
`0d31d8caa2a736dc0f7daf6f7283a875399988b31b94a47b308b22ad83e62802`.

Stage 2 must not reopen Stage 1 semantics, rerun Stage 1 merely to create activity,
or begin Terraform workload implementation. It must consume the verified closure,
establish the exact AWS qualification surface, prove that surface on an immutable
`main` commit, clean every probe mutation, and close only its three owned Part 3
master gates.

The current local checkout still points at the former Stage 1 PR branch. Execution
must create a fresh worktree from fetched `origin/main` at `5abef1a…`; it must not
reuse that old branch as the Stage 2 base.

## 2. Authority baseline

### 2.1 Controlling sources

| Authority | Identity / meaning |
|---|---|
| Original master plan | SHA-256 `0a7f2541d1ab5ce4d0aadabd871ddfe6f75bfdb6b7261efed7f97315b1e874df`; Part 3 lines 221–303 |
| Normalized Part 3 requirements | `spec/part3-requirements-v1.json`, 99 atomic requirements; SHA-256 `ffad2f173f413eff53000c2fdd7e3840e395e5b9775f4c32bd1df07c776d2cd9` |
| Part 3 traceability | `spec/part3-traceability-v1.json`; SHA-256 `238059c3bf9b8c6818b8292a08ad3d1dea33e5cf6ee6b59c9dfc8fa688da46b8` |
| Part 3 master gates | `spec/part3-master-gates-v1.json`; SHA-256 `abd6004b1285ab180db6750085ce166781677dabb82e421fbd36d4e8067d11aa` |
| Frozen AWS target | `.github/ledgerguard-target.json`; SHA-256 `d9dccdc0dbae17638f02ac6596be1b1f0a8c24dddc57974f97024ed1cc415058` |
| Project completion contract | `contracts/project-completion-v1.json`; SHA-256 `9a323c8b7800c90fc3ad1697ec407f6756ceebba8df266ab88deba97fe6017b6` |
| Part 2 → Part 3 handoff | `contracts/part2-part3-handoff-v1.json`; SHA-256 `c1f666b37927c77f9ddf310aaef28c139951fa9d1597381c3d65338228627361` |
| Part 2 conformance addendum | `spec/part2-master-conformance-addendum-v1.json`; SHA-256 `9424cf42f42372ca0cea18bd58d875f24a75c1ecf35e952537c3ec0b253178a1` |
| Overall Part 3 execution plan | `spec/sources/part3-execution-plan-v1.md`; SHA-256 `c05797e39f2659fe28401c1e90ac101093fa852822a9f60b5099974e6567e318` |
| Stage 1 detailed plan | `spec/sources/part3-stage1-execution-plan-v1.md`; SHA-256 `ae9c8d640565cfe70d2aaf04e1be2fbcafe2ecc3425ac893904fa64b98a646ab` |
| Stage 1 external closure | PR #19, merge `5abef1a…`, main run `34105604941`, and the independent closure receipt |

Master requirements and frozen financial authorities outrank implementation
convenience. The overall Part 3 plan determines sequencing. This detailed plan may
clarify an ambiguous mechanism, but it may not delete or relabel an obligation.

### 2.2 Required target

| Dimension | Required value |
|---|---|
| Repository | `bhuvaneshwaranmurugan21/ledgerguard-payment-reconciliation-platform` |
| Trusted branch | `refs/heads/main` only |
| AWS account | `857229544428`, compared privately and represented by a sanitized fingerprint in public evidence |
| AWS region | `ap-southeast-2` for regional calls |
| OIDC role | `LedgerGuardGitHubOidcRole` |
| Runtime contract | Glue 5.1, Spark 3.5.6, Python 3.11 |
| Cost ceiling | USD 10 gross for the whole LedgerGuard project, not a new Stage 2 allowance |
| AWS workflow trigger | Manual `workflow_dispatch` only, exact immutable `main` SHA supplied and checked |

AWS documents Glue 5.1 as Spark 3.5.6 and Python 3.11 in its
[Glue release notes](https://docs.aws.amazon.com/glue/latest/dg/release-notes.html).
The live run must still record the actual service/runtime values; documentation is
not execution evidence.

### 2.3 Non-negotiable inherited behavior

Stage 2 must preserve all accepted Part 1, Part 2, and Stage 1 bytes and behavior,
including the two reconciliation grains, integer minor units, currency isolation,
checked signed 64-bit arithmetic, canonical identities, exact bank allocation,
append-only proof/case history, independent-oracle isolation, corrected-source
causality, retry/recovery semantics, and the accepted failure taxonomy.

Automatic PR/push CI remains unable to obtain an OIDC token and performs no AWS
call. AWS qualification occurs only after the implementation transaction is on
`main`, through manual workflows tied to an exact SHA.

## 3. Part 3 outlook and Stage 2 boundary

Part 3 proves that the current repository can safely deploy, validate, and destroy
the minimal managed platform before a reconciliation workload runs. Stage 2 is the
environment trust gate. It verifies who the workflow is, what it can do, whether
the shared control-plane prerequisites are fit, whether budget headroom exists,
and whether tightly bounded non-workload probes clean themselves.

Stage 2 may perform these mutations only:

1. One isolated S3 probe object/version set under a run-specific qualification
   prefix, followed by deletion of every version and delete marker.
2. Conditional lease items under a run-specific key in an already qualified
   account-side lease table, followed by owner-checked deletion.
3. One uniquely named, inert Glue job definition, followed by readback, a zero-run
   assertion, deletion, and an independent absence check.

It may not call `StartJobRun`, `StartExecution`, `StartSyncExecution`, or
`StartQueryExecution`; create workload infrastructure; run Terraform apply; write
business DynamoDB state; publish financial data; or describe the Part 3 platform as
deployed. A syntax-only Step Functions validation is allowed because AWS explicitly
documents that `ValidateStateMachineDefinition` validates without creating a state
machine: [AWS API reference](https://docs.aws.amazon.com/step-functions/latest/apireference/API_ValidateStateMachineDefinition.html).

Stage 2 closes only:

- `environment_qualified`
- `live_iam_parity_verified`
- `glue_definition_probe_verified`
- carryover `LG-P3-G001` — exact-target AWS identity and IAM qualification

Infrastructure implementation (`LG-P3-G008`) remains open for Stages 4–7. Generator,
property, packaging, managed correctness, scale, release, and AWS workload claims
retain their existing owners.

## 4. Gap audit: Part 3 Stage 1 → Part 3 Stage 2

`OWNED_OPEN` means work is assigned and still requires executed evidence. A planned
file or a local test cannot substitute for a live AWS observation.

| ID | Current fact | Gap and root cause | Stage 2 disposition | Completion evidence |
|---|---|---|---|---|
| P3-S2-A01 | Stage 1 is externally complete, but its squash tree necessarily contains pre-merge `IN_PROGRESS` text and producer gate rows pending external facts. | A commit cannot attest to its own future merge and CI. | Add an append-only Stage 1 external-closure receipt; advance active status to Stage 2 without rewriting Stage 1 producer evidence. | Receipt binds PR head, squash SHA/tree/parent, PR/main runs, job IDs, artifact IDs/digests, G013/G014 results. |
| P3-S2-A02 | `LG-P3-G001` is `OWNED_OPEN`; the historical identity run is classified `AWS_VERIFIED_WRONG_TARGET`. | Static target coherence is not live frozen-target proof. | Execute exact-target OIDC qualification after code merges to main. | Sanitized caller/session evidence matches account, role, repository, branch, region, exact SHA. |
| P3-S2-A03 | The existing manual OIDC workflow checks target JSON and caller account/role. | It does not require a supplied exact SHA, explicitly reject non-main refs, compare live trust/permissions, inventory resources, or emit a complete evidence envelope. | Preserve historical workflow evidence; add Stage 2 workflows and validators with strict inputs and richer scope. | Static negative tests plus successful exact-main live runs. |
| P3-S2-A04 | No canonical desired trust policy or deploy-role permission policy exists. | Live parity has no checked-in semantic target. | Add versioned desired-state contracts and action/resource/condition rationale. | Schema validation and exact normalized live comparison. |
| P3-S2-A05 | No live IAM comparator exists. | JSON order, policy versions, inline/managed policy composition, and wildcard semantics are not adjudicated. | Implement deterministic semantic normalization and exact effective-policy comparison. | Missing, excess, wildcard, wrong repo/ref/account/region tests; live zero-diff evidence. |
| P3-S2-A06 | Backend location and governance are unknown. | No Terraform backend has been implemented, and local state is forbidden as a fallback. | Qualify an existing shared S3 backend or stop for a separate bootstrap transaction. | Encryption, versioning, public blocking, TLS policy, location, tags, isolated key access, complete probe cleanup. |
| P3-S2-A07 | No Stage 2 operation lease resource is established in the repository. | Terraform locking and the account-side workflow lease are distinct concerns. | Qualify an existing shared lease table and exact key namespace; otherwise require bootstrap. | Real conditional acquisition, competitor rejection, expiry takeover, owner-only release, empty final key. |
| P3-S2-A08 | The plan prefers S3 lockfiles; no pinned backend decision record exists. | DynamoDB-based Terraform backend locking is deprecated and must not be introduced by inertia. | Record S3 `use_lockfile` decision, selected Terraform pin, permissions, migration assumptions, and separation from the operation lease. | ADR plus static policy/backend validation. |
| P3-S2-A09 | Budget headroom is unverified. | USD 10 is a gross project ceiling; billing data is delayed and cannot be treated as real-time zero. | Build a cost ledger and freshness classifier; reserve a conservative bound for all authorized Stage 2 probe calls. | Cost Explorer/Budgets timestamps, known prior spend classification, probe estimate/reserve, fail-closed headroom equation. |
| P3-S2-A10 | S3, Athena, CloudWatch, quotas, tagging, and inventory visibility are unproved. | No API success or complete visibility evidence exists. | Run bounded read-only checks and make AccessDenied/partial pagination fatal. | Raw/sanitized response digests, pagination records, and visibility coverage matrix. |
| P3-S2-A11 | No Step Functions definition exists yet. | The production state machine belongs to Stage 4, but Stage 2 must qualify validation capability. | Add a clearly labeled qualification-only ASL fixture; validate only its syntax and keep it outside deployable infrastructure. | `ValidateStateMachineDefinition` returns `OK`; zero state-machine creation/execution. |
| P3-S2-A12 | The future Glue job role/script path does not exist in the repository. | `CreateJob` requires a service role and command definition; inventing or broadening one inside the probe would violate scope. | Require a pre-qualified probe service role and isolated inert script location in shared control-plane assets, or stop for bootstrap. | Exact role trust/PassRole parity, inert script digest, job definition equality, zero runs, deletion. |
| P3-S2-A13 | No clean-inventory verifier exists. | Tagging APIs alone omit untagged resources; AccessDenied is not absence. | Combine exact names/prefixes, required tags, shared-resource allowlist, S3 global checks, and service-specific target-region APIs. | Complete before/after inventories with identical allowed control-plane state and no workload resources. |
| P3-S2-A14 | No Stage 2 evidence schema, live run journal, or independent inspector exists. | A workflow cannot self-attest its final GitHub result or artifact transfer. | Add producer evidence plus a separate external inspection and closure transaction. | Run/job/artifact identities, safe manifest, raw report checks, API journal, cleanup proof, independent ZIP digest. |
| P3-S2-A15 | Stage 1 established current test ownership and protected authority hashes. | Stage 2 could accidentally weaken inherited validation while adding AWS code. | Extend the current runner additively and keep historical worktree checks. | Complete test inventory, protected-byte comparison, no skip/xfail, coverage/mutation evidence. |

No Stage 1 implementation defect remains open. A01 is a normal temporal closure
handoff, not retroactive incompleteness.

## 5. Stage 2 atomic requirement ownership

All 22 rows below are currently `OWNED_OPEN` in the normalized master ledger.

| Requirement | Required result | Owning package / gate |
|---|---|---|
| `P3-M-L226-01` | OIDC identity verified | E / G005, G018 |
| `P3-M-L227-01` | Exact account verified | E / G005, G018 |
| `P3-M-L227-02` | `ap-southeast-2` verified | E / G005, G018 |
| `P3-M-L228-01` | Repository trust boundary verified | B, E / G004–G006 |
| `P3-M-L228-02` | Main branch trust boundary verified | B, E / G004–G006 |
| `P3-M-L229-01` | Live IAM equals checked-in IAM | B, E / G006, G018 |
| `P3-M-L230-01` | Backend access and controls verified | B, E, F / G007 |
| `P3-M-L231-01` | Lease behavior verified | B, F / G008, G019 |
| `P3-M-L232-01` | Honest budget headroom verified | B, E / G009 |
| `P3-M-L233-01` | S3 capability verified | E, F / G007, G010 |
| `P3-M-L234-01` | Glue definition create verified | F / G012, G019 |
| `P3-M-L234-02` | Glue definition read/compare verified | F / G012, G019 |
| `P3-M-L234-03` | Glue definition delete/absence verified | F / G012–G013, G019 |
| `P3-M-L235-01` | Step Functions definition validation verified | E / G011 |
| `P3-M-L236-01` | Athena workgroup access verified without query | E / G010 |
| `P3-M-L237-01` | CloudWatch evidence access verified | E / G010 |
| `P3-M-L238-01` | No active LedgerGuard workload resource exists | E, F / G013 |
| `P3-M-L239-01` | No CloudShell dependency | A–G / G004 |
| `P3-M-L266-01` | Managed execution restricted to main | C–F / G004–G005 |
| `P3-M-L266-02` | Managed execution restricted to manual dispatch | C–F / G004 |
| `P3-M-L267-01` | OIDC credentials are short-lived | B, E, F / G005 |
| `P3-M-L276-01` | Gross run-cost ceiling enforced | B, E, F / G009 |

The Stage 2 adjudication must reference these stable source IDs. It should add
implementation, tests, evidence, and verdicts in a new append-only document rather
than rewriting the Stage 1 normalized source ledger.

## 6. Execution packages and dependency order

Seven packages are necessary because each ends at a different failure boundary.

| Package | Purpose | Depends on | Exit evidence |
|---|---|---|---|
| A | Freeze entry and Stage 2 authority | Verified Stage 1 closure | Stage 1 closure import, baseline freeze, Stage 2 ledger/gates/traceability |
| B | Settle target, IAM, backend, lease, inventory, and cost decisions | A | Versioned desired-state contracts and zero unresolved required decision |
| C | Implement validators, evidence producers, and manual workflows | B | Locally testable exact behavior; no AWS call |
| D | Prove and publish the implementation transaction | C | Two clean runs, exact-head CI/artifact, squash topology, main CI |
| E | Execute read-only qualification on exact main | D | External identity/IAM/backend/budget/capability/inventory evidence |
| F | Execute bounded mutation probes and cleanup | E | Lease/S3/Glue proofs, injected cleanup cases, final clean inventory |
| G | Independently inspect and close Stage 2 | F | Evidence-only closure transaction, external closure receipt, Stage 3 handoff |

If any package fails, later packages remain blocked. A failure must retain its raw
evidence and exact inputs; rerunning unchanged code is acceptable only when the
failure is shown to be transient.

## 7. Package A — Entry freeze and execution authority

### A1. Establish the worktree

1. Fetch `origin/main` and independently confirm GitHub main is `5abef1a…`.
2. Verify its tree, sole parent, PR #19 merge state, main CI run, both jobs, and
   accepted artifact identities against the external Stage 1 closure receipt.
3. Require a clean repository and create a dedicated Stage 2 branch/worktree from
   that exact commit. Record base commit/tree before editing.
4. Refuse to proceed if `main` moved until the new commit is audited. Do not silently
   transplant the old plan onto a different base.

### A2. Add append-only authority

Planned repository artifacts:

- `spec/part3-stage1-external-closure-v1.json`
- `contracts/part3-stage2-execution-v1.json`
- `spec/part3-stage2-requirement-adjudication-v1.json`
- `spec/part3-stage2-gate-registry-v1.json`
- `spec/part3-stage2-traceability-v1.json`
- `spec/part3-stage2-scenario-registry-v1.json`
- `spec/part3-stage2-baseline-freeze-v1.json`
- `docs/part3-stage2-gap-audit.md`
- `docs/part3-stage2-execution.md`

The Stage 1 gate registry stays byte-preserved as the producer's pre-external
declaration. The new closure record carries actual G013/G014 evidence. Active
README/status surfaces advance to `PART3_STAGE2_IN_PROGRESS`, identify the Stage 1
squash/main run, keep all six AWS master gates truthful, and state that Stage 2 AWS
facts are not yet verified.

### A3. Freeze inheritance

Build a complete path/digest inventory for accepted contracts, source, tests,
historical closure authorities, and Stage 1 implementation. Categorize files as:

- immutable historical authority;
- evolvable production source with baseline identity;
- active documentation;
- new Stage 2-owned surface.

The validator must reject a missing protected path, byte drift in immutable files,
untracked requirement, duplicate owner, or broad `AWS_VERIFIED` status before live
evidence exists.

**Package A exit:** the correct base is frozen, all 22 requirements and all planned
gates have owners, Stage 1 closure is represented append-only, and active status is
truthful.

## 8. Package B — Resolve every design decision before AWS code

### B1. Desired OIDC trust policy

Create a canonical trust-policy contract for the existing role. It must require:

- the exact GitHub OIDC provider in account `857229544428`;
- `sts:AssumeRoleWithWebIdentity` only;
- audience `sts.amazonaws.com`;
- subject `repo:bhuvaneshwaranmurugan21/ledgerguard-payment-reconciliation-platform:ref:refs/heads/main`;
- no organization-wide, repository-wide, tag, pull-request, environment, or wildcard
  subject;
- a bounded role session duration compatible with the workflows.

AWS warns that failing to restrict GitHub's `sub` claim can permit outside
repositories to assume the role: [AWS IAM OIDC guidance](https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles_create_for-idp_oidc.html).
GitHub's OIDC model uses audience and subject claims to scope cloud trust:
[GitHub OIDC reference](https://docs.github.com/actions/reference/openid-connect-reference).

### B2. Desired permission policy

Define the exact Stage 2 effective permission set, statement by statement. It must
contain no wildcard action, `NotAction`, or `NotResource`. `Resource: "*"` is allowed
only for an explicitly enumerated read-only API that AWS does not support at resource
scope; each such exception needs a service-authorization citation and a test proving
that no write action can enter the exception set.

The expected action families are:

- IAM self-inspection: role, role tags, inline policies, attached policies, default
  policy versions, and policy documents.
- S3 control inspection and isolated-prefix object/version operations.
- DynamoDB table inspection and conditional `GetItem`/`PutItem`/`DeleteItem` for one
  qualified lease key namespace.
- Glue `CreateJob`, `GetJob`, `GetJobRuns`, and `DeleteJob` for the exact probe-name
  prefix; no run action.
- `iam:PassRole` for one exact Glue probe service-role ARN, conditioned on
  `iam:PassedToService = glue.amazonaws.com`.
- Step Functions definition validation and inventory reads; no create/start action.
- Athena workgroup/query-history reads; no query-start action.
- CloudWatch Logs/metrics reads; no log/metric write action.
- Budgets and Cost Explorer reads.
- Resource Tagging and Service Quotas reads.

Where IAM cannot enforce a resource/name restriction for an API, the workflow input
validator and evidence inspector must enforce it too. This defense does not replace
IAM; it narrows the remaining API semantics.

### B3. IAM parity algorithm

Implement semantic normalization, not text comparison:

1. Fetch the role, tags, trust document, inline policies, attached managed policies,
   and every active default version.
2. URL-decode policy documents where the API representation requires it.
3. Reject duplicate statement SIDs, `Deny` surprises, `NotAction`, `NotResource`,
   unsupported principals, wildcard actions, unapproved global resources, policy
   boundaries that change effective authority, and unexpected attached/inline policy.
4. Normalize scalar/list forms, statement ordering, set-like Actions/Resources,
   Principals, and Conditions without changing condition meaning.
5. Compare the complete effective desired documents and return exact missing/excess
   statements and trust differences.
6. Hash raw sanitized and normalized forms. Never print credentials or OIDC tokens.

A broader live role is a failure even if required actions are present. A narrower
role is also a failure because later probes would be unreliable.

### B4. Backend decision

Prefer an existing governed shared-lab S3 backend. Its contract must name the bucket,
region, isolated LedgerGuard state prefix, lockfile key convention, KMS/SSE mode,
and allowed principal. Verify versioning, encryption, public-access block, TLS-only
bucket policy, ownership controls, lifecycle behavior, and access scope.

Use Terraform S3 `use_lockfile`; HashiCorp marks DynamoDB-based S3 backend locking as
deprecated: [Terraform S3 backend](https://developer.hashicorp.com/terraform/language/backend/s3).
The operation lease remains separate from Terraform state locking.

The probe writes outside the real state key under
`qualification/<sha>/<run-id>/<attempt>/`. In a versioned bucket, a normal delete
creates a delete marker rather than removing prior versions. Cleanup must list and
delete every exact version and marker, then prove the prefix empty. AWS documents
this behavior in its [S3 versioning guide](https://docs.aws.amazon.com/AmazonS3/latest/userguide/Versioning.html).

If no backend satisfies the contract, record `BLOCKED_BOOTSTRAP_REQUIRED`. Do not use
local state, an unencrypted bucket, or a bucket borrowed without ownership evidence.

### B5. Operation lease decision

Name one existing shared account-side DynamoDB lease table and a LedgerGuard key
namespace. Verify active state, encryption, point-in-time recovery decision, billing
mode, key schema, tags, and least-privilege access. Lease records contain:

- key, owner nonce, repository, exact SHA, workflow run/attempt;
- acquired epoch, expires epoch, purpose, and evidence correlation ID.

Acquire with a conditional write that succeeds only when the key is absent or the
record is expired. A competitor must receive `ConditionalCheckFailedException`.
An explicitly expired fixture proves takeover without waiting. Release uses a
condition on exact owner nonce and commit/run identity. DynamoDB condition
expressions make writes conditional on the current item state:
[AWS condition-expression guide](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/Expressions.OperatorsAndFunctions.html).
TTL is cleanup assistance only; the workflow explicitly deletes its item.

If no qualified table exists, require the same separate bootstrap decision as the
backend. Do not repurpose a business-state table.

### B6. Qualification fixtures

Create two non-production fixtures:

1. A minimal ASL document whose only purpose is API syntax validation. It is never
   passed to CreateStateMachine and is excluded from Stage 4 deployable definitions.
2. A minimal inert Glue Python script and exact job-definition contract. The job uses
   Glue 5.1, a bounded timeout/worker configuration, zero retries, one exact probe
   service role, an isolated script URI, and qualification tags. No workflow path
   contains a job-run API.

`CreateJob`, `GetJob`, `DeleteJob`, and job-run APIs are distinct in AWS's
[Glue Jobs API](https://docs.aws.amazon.com/glue/latest/dg/aws-glue-api-jobs-job.html).
The policy deny-list and static scanner must explicitly reject `StartJobRun`.

### B7. Inventory and cost contracts

Define the workload resource namespace, mandatory tags, target-region services,
global S3 names, and qualified shared control-plane allowlist. Resource Groups
Tagging evidence is supplementary; service-specific enumerations are mandatory so
untagged resources cannot disappear from the proof.

Define the headroom equation:

`remaining = 10.00 - known_gross_project_spend - conservative_unbilled_reserve`

`remaining` must exceed the checked-in maximum authorized Stage 2 probe estimate.
The ledger must include known historical LedgerGuard AWS activity, exact query
window, cost metric, currency, rounding rule, billing timestamp, source freshness,
and any conservative unknown reserve. Cost Explorer refreshes at least daily and
may receive later data; Budgets commonly updates every 8–12 hours. Record the actual
age and classify it rather than reporting delayed data as real-time zero:
[Cost Explorer freshness](https://docs.aws.amazon.com/cost-management/latest/userguide/ce-what-is.html),
[AWS Budgets freshness](https://docs.aws.amazon.com/cost-management/latest/userguide/budgets-managing-costs.html).

If billing access, historical attribution, currency, freshness, or reserve is not
defensible, headroom is `UNKNOWN` and the live mutation probe remains blocked.

**Package B exit:** every required name, ARN pattern, action, resource, condition,
cost rule, cleanup rule, and evidence field is decided and schema-valid. Missing
shared backend, lease table, or Glue probe role triggers the bootstrap branch.

## 9. Bootstrap contingency — a hard branch, not a workaround

The preferred path consumes governed shared-lab control-plane assets. Read-only
discovery determines whether they exist and meet policy. If any required asset is
absent, Stage 2 pauses after producing a concrete bootstrap diff and cost estimate.

A separately authorized bootstrap transaction may create only:

- a governed shared S3 backend with versioning, encryption, public blocking, TLS-only
  policy, lifecycle rules, and isolated project prefixes;
- a shared operation-lease DynamoDB table;
- an inert Glue probe service role with Glue trust and no data-plane authority;
- any narrowly required cost-read or inventory-read permission.

It must not create LedgerGuard workload infrastructure or modify
`LedgerGuardGitHubOidcRole` from inside a workflow that assumed that same role.
Administrator-side IAM changes require independent policy review and a fresh live
parity run. Bootstrap evidence must prove topology, tags, cost bounds, and clean
failure recovery before Stage 2 resumes.

## 10. Package C — Implementation and local proof

### C1. Planned implementation surfaces

Use small modules with explicit boundaries:

- a pure contract/normalization library for targets, policies, inventory, costs,
  lease semantics, and response adjudication;
- an AWS adapter that exposes only the approved operation enum and rejects any
  unknown service/action before invocation;
- a read-only preflight CLI;
- a capability-probe CLI with an append-only mutation journal and `finally` cleanup;
- a cleanup/recovery CLI that accepts only a recorded Stage 2 probe identity;
- a producer evidence builder;
- an independent artifact inspector that does not import producer verdict logic.

Pin Python 3.11.13 and all added dependencies with hashes. Capture AWS CLI/SDK,
Terraform, action, and schema versions. Keep AWS clients out of pure reconciliation
modules and keep the reference oracle out of Stage 2 packages.

### C2. Manual workflows

Add three narrowly separated workflows:

1. **Read-only qualification** — `workflow_dispatch`, exact SHA input, main-only,
   OIDC, read APIs, artifact upload.
2. **Capability probe** — `workflow_dispatch`, exact SHA and accepted preflight
   artifact identity, shared concurrency/lease, bounded S3/DynamoDB/Glue mutations,
   `if: always()` cleanup and post-clean inventory.
3. **Recovery cleanup** — `workflow_dispatch`, exact failed-run identity and probe
   resource journal, performs only bounded cleanup and absence verification.

Each job must check `github.ref == refs/heads/main`, input SHA equals `github.sha`,
checkout equals that SHA, repository equals the frozen value, and region/role
variables agree with the target contract before requesting OIDC. Actions use commit
SHAs, permissions are explicit, timeouts are bounded, concurrency does not cancel an
active mutation, and artifacts use safe complete manifests.

The capability workflow must not accept arbitrary resource names. Names derive from
the exact repository, commit, run ID, attempt, and a validated prefix. The recovery
workflow accepts only a signed/digest-bound producer journal from the failed run.

### C3. Call allowlist and negative deny-list

The static validator must parse workflow commands and source adapters. It permits
only enumerated operations and rejects at least:

- Glue `StartJobRun`, batch starts, triggers, crawlers, sessions, or interactive runs;
- Step Functions create/update/start/redrive operations;
- Athena `StartQueryExecution`;
- Terraform apply/destroy/import or local backend fallback;
- workload S3 prefixes, DynamoDB business tables, and unbounded resource lists;
- IAM create/update/attach/detach/pass of any role except exact PassRole to the probe
  service role;
- secrets, static AWS keys, PR-triggered OIDC, pull-request trust, or floating actions.

### C4. Evidence model

Every live artifact contains:

- repository/workflow/run/attempt/event/ref/exact commit/checked-out commit;
- sanitized account fingerprint, region, role/session fingerprint, credential mode;
- input authority hashes and tool/provider/action versions;
- normalized IAM desired/live documents and exact diff result;
- backend/lease identities and probe journals;
- before/after inventory and pagination coverage;
- Step Functions validation result; Athena/Glue/Step Functions negative execution
  queries; CloudWatch/quota/budget observations;
- cost timestamps, latency class, calculation inputs, reserve, and verdict;
- every attempted mutation, response identity, cleanup attempt, and final absence;
- explicit `managed_reconciliation_started: false` and scoped negative claims;
- manifest SHA-256 for every member, excluding a declared self-file.

Raw account IDs, role ARNs containing the raw account, OIDC tokens, credentials,
signed URLs, request headers, financial records, and environment dumps must not enter
logs or artifacts. Evidence records sanitized fingerprints and boolean exact-match
results while validators compare the private raw values inside the runner.

### C5. Local test campaign

Use deterministic documents and pure adapters for local tests. These tests verify
decision logic; they never count as AWS evidence.

Required local scenarios:

| Group | Scenarios |
|---|---|
| Entry/authority | Correct Stage 1 closure accepted; wrong tree/parent/run/artifact rejected; immutable-byte drift rejected; 22/22 requirements mapped once |
| Workflow boundary | PR trigger, push trigger, non-main ref, omitted/malformed/mismatched SHA, unpinned action, excessive permission, missing timeout, cancel-in-progress, static key, CloudShell, or forbidden API rejected |
| OIDC trust | Wrong provider, audience, owner, repository, branch, pull-request subject, environment subject, wildcard, absent condition, excess principal/action rejected |
| IAM permissions | Missing action, excess action, wildcard action, unapproved global resource, broad PassRole, wrong service condition, extra policy attachment, boundary/SCP visibility omission rejected |
| Policy normalization | Reordered equivalent documents pass; scalar/list and URL encoding normalize; changed condition semantics do not normalize away |
| Backend | Wrong region, no versioning, weak encryption, public access, missing TLS deny, wrong prefix, object mismatch, leftover version/delete marker rejected |
| Lease | First acquire, identical owner recovery, competitor rejection, expired takeover, wrong-owner release rejection, correct release, empty final key |
| Cost | Fresh headroom pass; stale/absent billing, wrong currency/window, negative/over-ceiling headroom, omitted historical activity, insufficient reserve rejected |
| Services | ASL `OK` accepted; `FAIL` rejected without depending on diagnostic wording; Athena/CloudWatch/quota pagination and AccessDenied fail closed |
| Glue | Definition equality, unexpected defaults normalization, zero runs, delete/absence; altered role/script/runtime/timeout/tags and any start call rejected |
| Inventory | Exact clean state; tagged and untagged residue; shared allowlist drift; incomplete pagination; AccessDenied; wrong-region observation rejected |
| Evidence | Missing member, duplicate/path traversal/symlink, digest mismatch, leaked account/credential patterns, incomplete journal, producer self-asserted GitHub success rejected |
| Recovery | Fault after S3 write, lease acquisition, and Glue create invokes real cleanup logic in controlled local process tests; unknown journal/resource cannot be cleaned |

Execute source mutations against the owned pure logic. Mutation families must cover
branch/ref bypass, account/region bypass, wildcard acceptance, policy-diff inversion,
stale-budget acceptance, headroom arithmetic, delete-marker omission, lease owner and
expiry predicates, Glue run prohibition, cleanup result inversion, inventory
AccessDenied-as-empty, evidence leakage, and master-gate promotion without external
evidence. Every registered mutation must be executed and killed by a meaningful
assertion; import or syntax failure does not count as a semantic kill.

### C6. Local quality gates

- Ruff format and lint pass.
- Strict mypy covers every current source and Stage 2 tool module.
- JSON/YAML schemas and all authority references validate.
- Every collected current test runs; no skip, xfail, filtering, or swallowed error.
- All existing historical worktree validators remain mandatory.
- Overall current-source branch coverage stays at least 90%.
- Every new pure Stage 2 semantic/evidence module has 100% statements and branches.
- All registered Stage 2 mutations die with zero execution errors/skips.
- Two fresh Python 3.11.13 environments build and install the wheel; source bytes,
  wheel bytes, normalized evidence, test inventory, coverage scope, mutation results,
  and declared deterministic digests agree.

**Package C exit:** implementation is locally complete and cannot perform an
unapproved AWS operation; no AWS claim has been made.

## 11. Package D — Implementation repository transaction

1. Review the complete diff against the A baseline. Reject unrelated workload
   Terraform, generator, Glue execution package, production state machine, financial
   changes, or Stage 3+ implementation.
2. Run the full two-environment validator and independently inspect its raw reports.
3. Open one draft Stage 2 implementation PR. Lead with the wrong-target qualification
   gap, desired IAM parity, safety boundaries, and exact validation evidence.
4. Automatic PR CI checks out the raw PR head and runs all historical/current local
   validation. It has no `id-token: write`, configure-credentials step, AWS CLI/API
   invocation, or workflow dispatch.
5. Download the exact-head CI artifact; independently verify head/run/job/workflow,
   manifest, raw tests, coverage, mutations, wheel, authority hashes, and zero-AWS
   execution.
6. Mark ready only after all local gates pass. The user performs the established
   manual squash merge.
7. Verify the squash has one parent equal to `5abef1a…`, its tree equals the validated
   PR head tree, and independent main CI passes on that exact squash.

AWS qualification must not run from the PR or before the implementation squash is
accepted on main.

**Package D exit:** the exact qualification code and workflows are immutable on
`main`, locally proven, and ready for live execution.

## 12. Package E — Exact-main read-only AWS qualification

### E1. Pre-dispatch checks

Read the current main SHA and require it equals the accepted Package D squash. Verify
the manual workflow source and desired-policy hashes at that commit. Record GitHub
variables without exposing their values and require region/role/backend/lease/probe
configuration to be complete.

The dispatch must use the exact SHA input. If main moves before the job starts, the
job fails before OIDC. Do not automatically substitute the newer SHA.

### E2. Identity and trust

After all local/ref checks, request short-lived OIDC credentials with a bounded
session name/duration. Privately compare STS account and assumed-role identity with
the frozen target. Fetch and compare the live role trust and permission policies.
Record only sanitized identity evidence.

IAM drift stops the workflow before S3 write, lease write, or Glue create. The
workflow must output an exact redacted diff. Remediation is an administrator-side,
explicitly reviewed IAM change followed by a new qualification run.

### E3. Read-only control-plane checks

Verify:

- backend location, versioning, encryption, public block, TLS policy, lifecycle,
  tags, state-prefix isolation, and permission visibility;
- lease-table state/schema/encryption/tags and empty LedgerGuard qualification key;
- Glue probe role trust and exact PassRole boundary;
- `ValidateStateMachineDefinition` returns `OK` for the qualification fixture;
- exact Athena workgroup inspection succeeds, with no query start;
- CloudWatch Logs and metrics evidence APIs are visible;
- required service quotas are retrievable and sufficient for later minimal resources;
- Budgets/Cost Explorer data and timestamps support the headroom verdict;
- before inventory contains no active LedgerGuard workload resource;
- Glue job-run, Step Functions execution, and Athena query observations show no
  Stage 2 probe workload.

For Step Functions diagnostics, accept/reject using the API's `result`, not the
diagnostic message order or wording, which AWS documents as changeable.

### E4. Independent acceptance

After GitHub marks the workflow successful, independently fetch run and job metadata,
download the artifact, compute its ZIP digest, validate every member and schema, and
recompute policy, inventory, cost, and claim verdicts. Producer output alone does not
close a gate.

**Package E exit:** exact-target identity, trust, IAM, read capabilities, backend
controls, budget headroom, qualification ASL, and clean starting inventory pass.
The capability probe remains unexecuted.

## 13. Package F — Bounded capability probes and cleanup

### F1. Admission

The capability workflow accepts only the Package E exact commit, run, artifact ID,
artifact digest, and successful independent-inspection digest. It repeats target,
IAM, budget, lease-empty, and starting-inventory checks before mutation.

Acquire the real operation lease first. If another owner holds it, exit without
mutation and record the conflict. GitHub concurrency is additional protection, not
a substitute for the account-side lease.

### F2. S3 probe

1. Write deterministic nonfinancial bytes to the isolated qualification prefix.
2. Read them back and verify payload digest, metadata, encryption, bucket, and prefix.
3. Delete the exact object version and any marker/version created by the test.
4. List the exact prefix with complete pagination and require it empty.

No state file or real `.tflock` key is touched.

### F3. Lease probe

Use a separate test key so the workflow's guarding lease is never endangered by its
own behavioral tests. Prove real conditional acquisition, competitor failure,
expired-record takeover, wrong-owner release failure, correct release, and empty
final state. Persist request/response codes and item hashes without leaking identity
fields.

### F4. Glue definition-only probe

1. Upload the inert script under the same isolated S3 probe prefix and verify its
   digest.
2. Create one uniquely named Glue job definition using the exact probe role and
   contract.
3. Read the job and compare normalized fields. Unexpected defaults are recorded and
   adjudicated; required-field drift fails.
4. Query job runs and require zero.
5. Delete the job, require subsequent `GetJob` absence, and independently inventory
   the exact name/prefix.
6. Remove every script object version/delete marker and prove the prefix empty.

No step has permission to start a run. A zero-run result must also be present in the
post-clean inventory.

### F5. Real cleanup fault cases

Run controlled failure injections after S3 write, test-lease acquisition, and Glue
creation. Each case exercises the actual adapter and cleanup path, then verifies
absence. Expected injected failures are distinguished from API defects; the overall
gate passes only when cleanup and absence checks succeed.

The final `always()` cleanup releases only the owner-matched guarding lease. A runner
loss can prevent in-job cleanup, so every future execution begins with residual
inventory detection and the recovery workflow can remove only digest-bound Stage 2
probe resources. Stage 2 remains blocked until an independent later run proves
absence.

### F6. Post-probe evidence

Repeat the complete inventory and negative execution checks. Before and after may
differ only in append-only CloudTrail/service observation metadata outside the owned
resource inventory; all probe resources and lease items must be absent. Record the
updated cost-data latency separately; do not expect immediate billing visibility.

Independently inspect GitHub success and the artifact exactly as in Package E.

**Package F exit:** backend write semantics, operation lease behavior, and Glue
definition CRUD are externally proved; all cleanup paths pass; no managed workload
ran; active workload inventory and probe residue are empty.

## 14. Package G — Evidence-only closure transaction

AWS facts cannot be committed before they exist. After E and F pass, create a new
branch from their exact tested main commit and add only bounded evidence/authority
changes:

- sanitized read-only and capability run receipts;
- independent inspection reports and external ZIP digests;
- per-requirement Stage 2 adjudication for all 22 source IDs;
- master-gate adjudication marking only the three Stage 2 gates externally verified;
- `LG-P3-G001` closure; all other carryovers retain their owner/state;
- clean-inventory, no-workload, cost-freshness, and cleanup receipts;
- active README/status updated to Stage 2 completed and Stage 3 next;
- a Stage 2 → Stage 3 handoff freezing operational source/workflow/policy/artifact
  identities and the remaining claim boundary.

Do not modify the tested workflow, policy, probe, or reconciliation bytes in this
closure branch. If such a byte changes, AWS evidence becomes stale and the affected
live qualification must be repeated on the new operational SHA.

Run local validation and exact-head CI, independently inspect its artifact, then use
the established manual squash process. Verify the closure squash topology/tree and
main CI. The final external receipt may attest to this merge without creating an
infinite self-attestation chain because it is retained outside the producer commit.

**Package G exit:** all 22 requirements have executed evidence; the three owned
master gates are externally verified; the environment is clean; Stage 3 has an exact
immutable handoff; Part 3 and the overall project remain in progress.

## 15. Stage 2 gate registry

| Gate | Acceptance criterion | Primary evidence |
|---|---|---|
| `P3-S2-G001` exact entry | Stage 1 squash/tree/parent/PR/main CI/artifacts independently bound | External closure import and baseline freeze |
| `P3-S2-G002` immutable inheritance | Protected historical/financial/Stage 1 authorities remain byte-identical | Complete path/digest comparison |
| `P3-S2-G003` requirement completeness | All 22 Stage 2 source requirements map bidirectionally to code, tests, evidence, and verdict | Requirement adjudication and reverse index |
| `P3-S2-G004` execution boundary | AWS workflows are manual/main/exact-SHA only; automatic CI has no OIDC/AWS path | Workflow parser, permission/action scan, CI logs |
| `P3-S2-G005` exact identity | Account, region, repository, branch, role, session, SHA match target | STS/GitHub/target evidence, sanitized identity fingerprint |
| `P3-S2-G006` live IAM parity | Trust and complete effective permissions exactly equal desired semantics | Raw/normalized policy hashes and zero-diff report |
| `P3-S2-G007` backend readiness | Shared backend controls and isolated read/write/delete/version cleanup pass | Bucket configuration and object-version journal |
| `P3-S2-G008` lease correctness | Acquire/conflict/expiry/owner-release behavior passes; final key absent | Conditional-write results and final GetItem |
| `P3-S2-G009` cost headroom | Gross-project equation is positive over reserved probe cost with honest freshness | Budget/CE data, timestamps, reserve and calculation |
| `P3-S2-G010` service visibility | S3, Athena, CloudWatch, quotas, tagging, and service inventories complete without denied/partial pages | API coverage matrix and response hashes |
| `P3-S2-G011` Step Functions validation | Qualification ASL returns `OK`; no state machine/execution created | API result and inventory |
| `P3-S2-G012` Glue definition probe | Exact create/get/zero-runs/delete/absence sequence passes | Mutation journal, normalized definition, job-run query |
| `P3-S2-G013` clean state/no workload | Before/after workload inventory clean; every probe object/version/job/item absent; no Glue/SFN/Athena execution | Independent inventory and negative execution queries |
| `P3-S2-G014` evidence integrity | Schemas, safe complete manifests, sanitized fields, raw results, deterministic adjudication pass | Producer artifact and independent inspector |
| `P3-S2-G015` local quality | Full tests, strict typing/lint, coverage thresholds, all mutations killed, two clean runs | Raw local reports and deterministic comparison |
| `P3-S2-G016` implementation PR evidence | Exact PR head CI and artifact independently accepted | PR run/jobs/artifact/ZIP inspection |
| `P3-S2-G017` implementation publication | Squash has expected parent/tree and exact-main CI passes | Git topology and push-run inspection |
| `P3-S2-G018` read-only AWS external proof | Package E workflow and artifact independently accepted | Exact-main read-only run receipt |
| `P3-S2-G019` capability AWS external proof | Package F workflow, cleanup, and artifact independently accepted | Exact-main capability run receipt |
| `P3-S2-G020` external closure | Evidence-only squash topology/main CI pass; handoff names Stage 3 | Closure receipt and handoff |

No gate may pass from an expected path, a producer boolean, a screenshot, or a test
fixture alone. Live gates require actual API evidence and independent GitHub/artifact
inspection.

## 16. Failure handling and recovery rules

| Failure | Required response |
|---|---|
| Wrong account, region, repository, ref, or SHA | Terminate before any mutating API; preserve sanitized mismatch evidence. |
| OIDC assumption denied | Check trust/variables/live role. Do not add static keys or broaden `sub`. |
| IAM missing/excess capability | Produce semantic diff; fix through explicit administrator review; rerun from a new exact run. |
| SCP or permission visibility incomplete | Record the denied action and block. Absence cannot be inferred. |
| Backend insecure or inaccessible | Reject it; execute the bootstrap branch or select a governed asset. No local state fallback. |
| Versioned S3 cleanup incomplete | Enumerate and delete only recorded versions/markers; block until exact prefix is independently empty. |
| Lease conflict | Do not steal a live lease. If expired, takeover only through the declared condition and retain both owner observations. |
| Lease cleanup fails | Run recovery with the digest-bound journal; block all later AWS stages until absence is proved. |
| Budget stale/unavailable/insufficient | State `UNKNOWN` or `BLOCKED`; do not treat missing data as zero or dispatch mutation. |
| Glue create/read differs | Preserve response, clean exact job/script, fix contract/IAM/root cause, then use a fresh run. |
| Glue delete is eventually inconsistent | Poll bounded exact-name absence; timeout blocks. Never ignore residue. |
| Any workload start observed | Critical Stage 2 failure. Preserve evidence, stop, clean authorized resources, investigate the call path, and require a new reviewed implementation. |
| Runner cancellation/loss | Next run begins with residue detection; use recovery workflow; no new mutation until clean. |
| Main moves | Evidence remains valid only for its tested SHA; rebase/review/revalidate before publication or rerun as required. |
| Artifact missing/corrupt/leaky | Reject the run even if GitHub is green; fix evidence production and execute a new run. |
| Transient API throttle | Retain request IDs/timing, use bounded jittered retries only for documented retryable errors, and show inputs were unchanged. |

## 17. Claim and publication rules

Before live execution, Stage 2 is `IN_PROGRESS`; the three master gates remain
`NOT_EXECUTED`. After Package E, only read-only observations may be described as
verified. After Package F and independent inspection, the three Stage 2 gates may be
`AWS_VERIFIED` in the later closure transaction.

Allowed final Stage 2 claim:

> The exact LedgerGuard AWS target, desired/live IAM parity, shared control-plane
> prerequisites, bounded definition/capability probes, and clean starting state were
> independently verified on the recorded main SHA. No managed reconciliation
> workload ran, and all probe residue was removed.

Forbidden claims include deployed platform, working managed reconciliation,
production readiness, scale performance, cost finality, account-wide inactivity,
compliance, Part 3 completion, or project completion.

## 18. Final acceptance checklist

Stage 2 is complete only when every item below is true:

- [ ] Execution started from verified Stage 1 squash `5abef1a…` and its accepted tree.
- [ ] Stage 1 closure is imported append-only; producer evidence is unchanged.
- [ ] All 22 atomic requirements have one owner, tests, live evidence where required,
      and an independently adjudicated pass.
- [ ] All inherited protected authorities and accepted behavior remain valid.
- [ ] Desired OIDC trust and effective permissions are exact and live parity has zero
      unexplained difference.
- [ ] Account, region, repository, main ref, role, exact SHA, and short-lived session
      match the frozen target.
- [ ] Shared backend and operation lease resources are qualified, or the separately
      authorized bootstrap has completed and been independently verified.
- [ ] Budget headroom is positive under the gross-project equation with recorded
      freshness and conservative reserve.
- [ ] Read-only S3, Step Functions, Athena, CloudWatch, quotas, billing, tagging, and
      service inventory checks pass with complete visibility.
- [ ] Real S3 isolated-prefix, lease, and Glue definition-only probes pass.
- [ ] Controlled cleanup fault cases pass and the final probe inventory is empty.
- [ ] No Glue job run, Step Functions execution, Athena query, managed reconciliation,
      business-state write, Terraform apply, or workload resource creation occurred.
- [ ] Local lint/type/schema/tests/coverage/mutations and two clean builds pass.
- [ ] Implementation PR CI/artifact, squash topology, and main CI are independently
      verified.
- [ ] Read-only and capability workflow artifacts are independently downloaded and
      accepted by exact identity and raw evidence.
- [ ] Evidence-only closure PR, squash topology, main CI, and external receipt pass.
- [ ] `environment_qualified`, `live_iam_parity_verified`, and
      `glue_definition_probe_verified` are externally verified; the other three Part
      3 master gates remain unexecuted.
- [ ] Stage 3 receives an exact handoff; Stage 3 work has not begun inside Stage 2.

Any unchecked item keeps Stage 2 open.

## 19. Expected manual dependencies during later execution

No manual action is needed to use this plan. During execution, the user is expected
to retain the established manual squash-merge boundary for the implementation and
closure PRs. Additional manual work is required only if evidence reveals one of these
real conditions:

1. the GitHub AWS role/region/backend/lease/probe-role variables are absent or wrong;
2. `LedgerGuardGitHubOidcRole` trust or permissions require administrator remediation;
3. no governed shared backend, lease table, or Glue probe service role exists and the
   separately reviewed bootstrap must be performed;
4. a cleanup failure needs administrator access beyond the narrowly scoped recovery
   workflow.

Execution should complete all local implementation and produce exact diffs/evidence
before asking for such an action. It must never ask the user to guess a policy change
or manually clean an unidentified resource.

## 20. Final handoff

The accepted Stage 2 handoff must name:

- implementation and closure squash commit/tree/parent identities;
- exact read-only and capability workflow run/job/artifact identities and ZIP hashes;
- target, role, backend, lease, Glue probe role, policy, and workflow hashes;
- all 22 requirement verdicts and all 20 Stage 2 gate verdicts;
- the three externally verified Part 3 master gates;
- final clean inventory, zero-workload result, cost/freshness classification, and
  absence of probe residue;
- immutable operational files whose change invalidates qualification;
- remaining Part 3 gates and the single next owner: Part 3 Stage 3.

This is the end of Stage 2. It does not execute Stage 3.
