# LedgerGuard — Part 3, Stage 1 execution plan

**Stage:** Part 3 entry authority and conformance recovery  
**Prepared:** 2026-09-06  
**Status:** Planning complete; execution has not started  
**Verified baseline:** `main` at `cb81704adcfdfac5d93879cd6c189fc2213bbe79`  
**Scope:** Detailed planning for Stage 1 only. Subsequent stages appear solely as requirement owners and handoff dependencies.

## 1. Decision and exact resumption point

Resume at **Part 3 Stage 1, package A: establish the entry authority and conformance register**. Part 2 Stage 8 has already been squash-merged and independently validated on `main`. Do not reopen PR #18, repeat its promotion, rebuild Part 2, or begin AWS qualification as the first step.

Stage 1 has two substantive responsibilities: establish an honest, immutable handoff into Part 3, and implement the missing local corrected-source case-resolution behavior. Its completion requires executable semantics and independently attributable validation. Documentation alone cannot close it.

The audit also found a missing obligation in the supplied overall Part 3 plan: the accepted Spark implementation is a candidate projection and arithmetic-parity layer, not the complete source-to-proof DataFrame transformation required by the master plan. Stage 1 must register and assign that omission to Part 3 Stage 3 before packaging can be accepted. It must not implement that pipeline during this stage or describe it as already complete.

No repository change, branch, PR, workflow dispatch, AWS call, or implementation test run was performed to prepare this plan. Repository and CI observations below came from read-only GitHub inspection. Local files under `audit-source` are inspection copies, not a Git checkout or a new implementation.

## 2. Authority and evidence baseline

### 2.1 Exact source documents

| Source | Identity | Use |
|---|---|---|
| Attached `Ledger Guard Master Plan(1).txt` | SHA-256 `0a7f2541d1ab5ce4d0aadabd871ddfe6f75bfdb6b7261efed7f97315b1e874df` | Original requirements; Part 3 occupies lines 221–304; inherited Part 2 obligations occupy lines 113–218 |
| Attached `LedgerGuard-Part-3-Execution-Plan(3).md` | SHA-256 `c05797e39f2659fe28401c1e90ac101093fa852822a9f60b5099974e6567e318` | Accepted planning structure; section 6 is Stage 1 |
| Repository completion contract | `contracts/project-completion-v1.json` at the verified baseline | Six Part 3 master gates, claim states, target, and total project cost ceiling |
| Repository financial and contract authorities | `spec/financial-semantics-v1.json`, active contract set, accepted v2 schemas, Part 1→2 handoff | Immutable financial, identity, schema, and history constraints |
| Part 2 completion authority | `spec/part2-completion-authority-v1.json` and Stage 8 promotion freeze | Historical repository-defined closure |

The newest attachments are byte-identical to the preceding `(2).md` and unnumbered `.txt` copies. The overall Part 3 plan cites an older master attachment digest beginning `a3d577…`; preserve that historical citation and record the new supplied source separately. Do not substitute the new bytes underneath the old digest. Source normalization must retain original bytes, encoding, line locators, and a separately defined normalized-text digest.

Conflict rule: master requirements and immutable financial authorities remain mandatory. The overall Part 3 plan supplies staging and ownership. This detailed plan records necessary clarifications without rewriting accepted historical evidence. Any genuine semantic conflict blocks the relevant implementation step until an additive, traceable compatibility decision resolves it.

### 2.2 Repository and publication facts reverified

| Fact | Verified value |
|---|---|
| Repository | `bhuvaneshwaranmurugan21/ledgerguard-payment-reconciliation-platform` |
| Current `main` HEAD | `cb81704adcfdfac5d93879cd6c189fc2213bbe79` |
| Current tree | `89689d7e32cd09e36a8456484a50c23d0192897f` |
| Sole parent | `71b42d6622558093a2bfaced58724f2ab71e793e` |
| PR #18 | Closed and merged; squash commit equals current HEAD |
| PR #18 validated head | `0ff1603ca378479fdd46d09840cc015c8a1f1500` |
| Validated-head tree | `89689d7e32cd09e36a8456484a50c23d0192897f`; identical to squash tree |
| PR #18 CI | Run `33879453002`, successful |
| Independent post-merge CI | Run `33904881790`, job `101127352519`, successful |
| PR closure artifact | ID `9940336588`, available and not expired at inspection |
| Artifact name | `ledgerguard-part2-stage8-closure-0ff1603ca378479fdd46d09840cc015c8a1f1500` |
| Open PRs | None at inspection |
| Part 3 implementation files | None in the inspected recursive repository tree |
| Branch protection | API reports `protected: false`; a successful check is not evidence of a server-enforced merge gate |

The prior audit recorded the PR closure artifact ZIP digest as `284a5a3b9eb11c9ad2f2b8130151679cef390706659aa0ec7485a86cf02aee84`. This planning pass rechecked its identity and availability, not a new binary download. During execution, independently re-download and hash it before freezing that digest into a new repository authority. This is admission evidence for a new handoff, not repetition of Part 2 implementation.

Sources: [PR #18](https://github.com/bhuvaneshwaranmurugan21/ledgerguard-payment-reconciliation-platform/pull/18), [accepted squash commit](https://github.com/bhuvaneshwaranmurugan21/ledgerguard-payment-reconciliation-platform/commit/cb81704adcfdfac5d93879cd6c189fc2213bbe79), [PR CI](https://github.com/bhuvaneshwaranmurugan21/ledgerguard-payment-reconciliation-platform/actions/runs/33879453002), [independent main CI](https://github.com/bhuvaneshwaranmurugan21/ledgerguard-payment-reconciliation-platform/actions/runs/33904881790).

### 2.3 Completed work to consume

| Accepted boundary | What it supplies to Stage 1 | Evidence/limitation |
|---|---|---|
| Part 1 corrective closure, PR #9 | Two grains, financial semantics, contract registry, identity/digest rules, completion scorecard | Inherited closure at `3ef17666e3fe3bc655ba1c8733beb3cb00acdbec`; consume its authorities |
| Part 2 Stage 1, PR #10 | Runtime responsibility and gate ownership | Frozen entry authority; no need to recreate it |
| Part 2 Stage 2, PR #11 | Independent Python oracle | Preserve isolation from production implementation |
| Part 2 Stage 3, PR #12 | Manifest/source admission and immutable identity enforcement | Correction cannot bypass admission |
| Part 2 Stage 4, PR #13 | Transaction reconciliation | Preserve event-class grain, reference rules, money, and role orientation |
| Part 2 Stage 5, PR #14 | Settlement, clearing, and bank reconciliation | Preserve exact bank allocation and no double use |
| Part 2 Stage 6, PR #15 | Atomic local finalization, proof/case histories, crash and concurrency recovery | Extend carefully; validate new requests on readback and retry |
| Part 2 Stage 7, PR #16 | Real Spark expression parity and Parquet readback | Bounded projection of Python-produced candidates; not full DataFrame ingestion/reconciliation |
| Part 2 Stage 8 promotion, PR #17 | 203 requirements, 69 stage gates, six repository master gates | Closure scope is the repository-defined ledger |
| Part 2 Stage 8 attestation, PR #18 | Accepted terminal local claim and publication evidence | Already merged; active documentation still has candidate wording |

The inspected `main` CI job successfully re-executed the inherited validators, Stage 7 Spark checks, Stage 8 promotion checks, and Stage 8 closure checks. Log evidence includes:

- Stage 7: 504 passing tests in each clean run; its owned Spark module reports 68 statements and 14 branches, all covered.
- Stage 8 promotion: 514 passing tests in each clean run; its owned validator reports 169 statements and 24 branches, all covered; zero mutation survivors.
- Stage 8 closure: seven passing closure tests in each clean run; its owned validator reports 92 statements and 12 branches, all covered; zero mutation survivors.

These counts have different scopes and overlap. Do not add them into a fabricated unique-test total or present narrow validator coverage as whole-project coverage. Main-run artifact-upload steps were skipped because they are PR-branch-specific; the validation steps succeeded. That is expected workflow behavior, not missing validation.

**Completion assessment:** Part 2 is operationally closed under its accepted ledger and remains `LOCAL_RECONCILIATION_VERIFIED`. It is not defensible to claim every workstream of the attached master plan was completed. Preserve the historical closure while recording the additional master-plan obligations explicitly.

## 3. Part 3 outlook and Stage 1 boundary

Part 3 proves that the exact current source can deploy, validate, and destroy the minimal managed platform before any managed reconciliation workload runs. Its eventual target is `AWS_DEPLOYMENT_VERIFIED`. Stage 1 produces the trustworthy entry contract for that work.

| Subsequent stage | Stage 1 must provide | Stage 1 must not claim |
|---|---|---|
| 2: qualification | Frozen target references, six-gate ownership, inherited identity limitations, capability boundaries | Live identity, IAM parity, backend, lease, budget, or clean inventory verified |
| 3: data assets and package | Corrected-source contract and tests; generator, property-campaign, and full Spark-pipeline obligations | Production Glue package or full DataFrame pipeline completed |
| 4–5: infrastructure and orchestration | Immutable semantic/history contract, evidence and claim rules | Terraform or orchestration implemented |
| 6–7: plan and canary | Mandatory exact-source, no-workload, cleanup, and evidence criteria | Deployment, zero-execution inventory, or teardown proved |
| 8: closure | Bidirectional traceability and gate aggregation rules | Any of the six Part 3 master gates externally passed |

Stage 1 permits local Python and bounded local Spark validation required for regression. It performs no AWS API call and grants no OIDC credentials to automatic CI. Dependency retrieval and GitHub evidence reads are not AWS qualification. No Terraform, Glue workload, state-machine execution, Athena query, infrastructure bootstrap, or managed business-state write belongs in this stage.

### 3.1 Required clarifications to the overall Part 3 plan

Record these as an additive Stage 1 adjudication, with source locators and downstream owners:

1. **Cost scope:** the frozen contract says `gross_project_cost_ceiling_usd = 10`. This is the total project envelope, not a fresh USD 10 allocation for Part 3. Stage 2 must determine remaining headroom; Stage 1 cannot assert it.
2. **Local measurement placement:** local measurements do not violate a prohibition on managed workload execution. Keep G006 with Part 4 for comparable local/managed experiments and controlled scope, with an explicit outstanding obligation. Remove the incorrect prohibition-based rationale from active planning references.
3. **Qualification mutations:** the overall table says only Glue definition mutation, but its detailed Stage 2 includes isolated backend writes/deletes and conditional lease tests. Stage 1 must separate read-only qualification from explicitly bounded capability probes in ownership and evidence rules. No capability probe executes here.
4. **Definition validation:** the overall Stage 5 is labelled offline in one place but requires the AWS definition-validation API elsewhere. Record static validation and later main-bound service validation as distinct evidence steps; neither permits an execution.
5. **Automatic CI permissions:** current CI has `contents: read` and `pull-requests: read`. Preserve necessary read-only access; do not falsely describe the existing workflow as having only `contents: read`. Reject OIDC/write escalation.
6. **Historical versus current validation:** preserving old validators means running them unmodified against their exact historical inputs, while maintaining equally mandatory current-source regression. It does not mean retaining stale active claims or testing only old code.
7. **Publication authority:** this turn authorizes planning only. In a later execution turn, use the actual authorized scope for reversible repository work. Preserve the established manual squash-merge boundary; do not invent repeated permission requests for every routine preparation step.

## 4. Gap audit: Part 2 Stage 8 → Part 3 Stage 1

`OWNED_OPEN` below is a planning disposition, not a pass. A gap assigned downstream remains visibly open until its owner's evidence closes it.

| ID | Finding and root cause | Stage 1 disposition | Completion condition / owner |
|---|---|---|---|
| LG-P3-G001 | Exact frozen AWS target unverified; historical identity claim is wrong-target qualified | Carry forward without claiming fresh AWS facts | Stage 2 exact-target qualification |
| LG-P3-G002 | README/status still say closure candidate after PR #18 merge and successful main CI; validator hardcodes that wording | Fix active status and add external-closure evidence; preserve old inputs | Stage 1 current-status validator plus frozen closure regression |
| LG-P3-G003 | Scale-selectable generator omitted from Part 2 ledger | Register all profiles and independent totals as requirements | Stage 3 generator and package gate |
| LG-P3-G004 | Case schema models correction, but `_case_revision` has only `OPEN` and `RESOLVED_BY_LATE_DATA`; no correction provenance reaches request/recovery/history | Implement the local corrective slice, with contract and failure tests | Stage 1 correction gates; documentation cannot close this row |
| LG-P3-G005 | Existing deterministic/metamorphic coverage has no generator-driven scale campaign | Preserve existing tests; assign the missing campaign | Stage 3, linked to G003 |
| LG-P3-G006 | Local runtime/throughput/partition/join/shuffle/skew/output measurements absent | Record original Part 2 obligation and justified placement | Part 4 baseline/scale work; no local-performance claim now |
| LG-P3-G007 | 1M managed benchmark not executed | Retain future owner only | Part 4; not a Stage 1 defect |
| LG-P3-G008 | Managed infrastructure is not implemented | Normalize exact master requirements and owners | Part 3 later stages; expected work |
| LG-P3-G009 | Managed correctness/recovery evidence absent | Preserve unclaimed boundary | Part 4 |
| LG-P3-G010 | Release and final repository hygiene incomplete | Retain future owner; apply hygiene to new artifacts now | Part 5 final audit |
| **LG-P3-G011** | **New audit finding:** Spark starts from `TransactionCandidate`/`SettlementCandidate`, copying Python totals/reasons/status and recomputing selected deltas. Master Part 2 Workstream 3 requires the full native DataFrame source transformation | Add conformance correction and a hard Stage 3 packaging prerequisite | Stage 3 must implement/test the source-to-proof DataFrame pipeline, with independently derived oracle parity; accepted Stage 7 projection remains frozen |
| **LG-P3-S1-A01** | Closure validator requires `PART2_STAGE8_CLOSURE_ATTESTATION_CANDIDATE` and “not yet active on main” | Add complete PR #18 historical worktree and current-source validation | Stage 1 CI migration with no lost regression obligation |
| **LG-P3-S1-A02** | New provenance can be omitted from the early `recover_attempt` path unless explicitly bound | Include correction semantics in request/recovery identity and every read path | Stage 1 replay and recovery gate |
| **LG-P3-S1-A03** | Legacy finalizer labels every non-exception successor as late, including possible policy-only changes | Preserve historical read semantics; adjudicate source-versus-policy causation for the new correction protocol explicitly | Stage 1 decision and policy/correction tests; no invented new case state |
| **LG-P3-S1-A04** | Current branch is unprotected | Make exact-head review, manual merge checks, and post-merge evidence explicit | Stage 1 publication protocol; no unrequested repository-administration change |

G011 is supported by `verify_spark_parity` in the frozen [Spark module](https://github.com/bhuvaneshwaranmurugan21/ledgerguard-payment-reconciliation-platform/blob/cb81704adcfdfac5d93879cd6c189fc2213bbe79/src/ledgerguard_part2_stage7_spark.py) and the narrower [Stage 7 requirements](https://github.com/bhuvaneshwaranmurugan21/ledgerguard-payment-reconciliation-platform/blob/cb81704adcfdfac5d93879cd6c189fc2213bbe79/spec/part2-stage7-requirements-v1.json). This finding does not invalidate the arithmetic and Parquet tests they actually perform.

## 5. Execution packages and dependency order

Use five packages within Stage 1. They separate different failure boundaries; they are not additional project stages. A package is ready only after its stated exit evidence exists.

| Package | Purpose | Depends on | Reviewable output |
|---|---|---|---|
| A | Freeze entry facts, requirement ownership, and conformance correction | Verified PR #18 baseline | Handoff, source index, ledgers, gate registry, status plan |
| B | Define the additive corrected-source protocol and compatibility rules | A | Contract, ADR, golden scenarios, identity and transition tables |
| C | Integrate correction through admission, finalization, retry, and readback | B | Executable local behavior and complete semantic/recovery tests |
| D | Produce current-source regression and reproducible CI evidence | A–C | Two clean runs, coverage/mutation results, immutable CI artifact |
| E | Independently inspect and close the repository transaction | D | Validated PR, manual squash topology, independent main CI, closure receipt |

No package may mark an unmet prerequisite as deferred merely to proceed. Downstream ownership in A is limited to the already identified future implementation obligations; it cannot be used to move a failed Stage 1 correction or validation gate out of scope.

## 6. Package A — Entry authority and traceability

### A1. Admit the exact repository state

1. Obtain a normal Git checkout of the existing repository; read any applicable `AGENTS.md` before editing. Inspect working-tree status and preserve existing user changes. Inspection copies in this planning workspace are not a substitute for Git history.
2. Fetch `main` and PR #18's immutable head. Verify HEAD, sole parent, and tree against section 2. If unchanged, reuse the verified closure; do not rerun its implementation. If HEAD has advanced, inspect only intervening changes and their evidence before choosing the new base.
3. Recheck main CI and open PRs. If another Stage 1 branch now exists, inspect and resume its first incomplete gate instead of creating a duplicate.
4. Download the PR #18 artifact by immutable ID; reject wrong run/head/name, expired/unavailable content, unsafe archive paths, unexpected members, missing members, or digest mismatch. Independently verify its manifest and payload digests.
5. Create the Stage 1 execution branch from the admitted base when execution is authorized. Proposed name: `part3-stage1-entry-and-conformance`. Do not create it in this planning turn.
6. Record exact toolchain requirements: CPython 3.11.13, Java 17, PySpark 3.5.6, Py4J 0.10.9.7 and hash-locked dependencies. A different Python minor/patch does not satisfy the inherited runner. Provision the required runtime; do not alter version checks to fit a convenient local interpreter.

**A1 exit:** complete base provenance and artifact verification; no uncertain predecessor identity; no duplicate execution branch.

### A2. Freeze inherited authority without freezing the product against evolution

Create a new Part 2→3 handoff with:

- Source repository, base commit/tree/parent, PR #18 head/tree, exact-head and main runs/jobs, artifact identity and independently calculated digests.
- Source document hashes, source locators, original and normalized text identities.
- SHA-256 inventory of accepted v1/v2 schemas, active registry, financial semantics, canonical identity scopes, reason taxonomy, and all protected authority paths from the inherited freezes.
- Part 2 completion authority and full PR #18 historical snapshot identity.
- Baseline production package, independent oracle, Spark projection, tests, and dependency inventories. Mark these as baseline implementation identities; an intentional new production implementation gets a new identity and a reviewed diff, not a false assertion that its bytes stayed fixed.
- Explicit permanent immutability for historical authorities and accepted schemas. Do not update a protected digest to match a changed protected file.
- Claim boundary: repository-local reconciliation accepted; correction not yet verified until C–D; AWS/environment/cost/scale/production/project completion unclaimed.
- Gap ownership with original source, current disposition, required owner, entry/exit evidence, and prohibition on counting an open deferral as a pass.

Create an append-only conformance record that references the old 203-requirement closure and explains its bounded scope. Preserve the old `remaining_part2_work: 0` bytes as a historical ledger statement; active prose must clarify that original-master omissions remain assigned elsewhere. Do not erase, alter, or quietly reinterpret that old record.

### A3. Normalize the Part 3 master requirements

Each atomic ledger row must contain: stable ID, verbatim source fragment or precise locator, source digest, normative statement, inherited constraints, owner stage, dependencies, validation method, expected evidence, allowed claim level, and current state. Split conjunctions where failures can occur independently. Distinguish `PLANNED`, `IMPLEMENTED`, `LOCAL_VERIFIED`, `EXTERNALLY_VERIFIED`, `OWNED_OPEN`, and `BLOCKED` rather than treating a path or document as proof.

Use these source families to ensure the normalization is complete:

| Source family | Every obligation to retain | Owning stage(s) |
|---|---|---|
| Part 3 objective | Exact current source; minimal platform; safe deploy/validate/destroy; before reconciliation workload | 1 defines boundary; 6–8 prove it |
| Qualification | OIDC; exact account/region; repository/main trust; IAM parity; backend; lease; budget headroom; S3; Glue definition create/read/delete; Step Functions validation; Athena workgroup; CloudWatch evidence; no active workload resources; no CloudShell dependency | 2 |
| Infrastructure | Private/versioned/encrypted workload bucket and prefixes; lifecycle; multipart cleanup; necessary Glue catalog; Glue 5.1 job; real state machine; one/two justified control/case tables; bounded Athena; logs/metrics; workload roles; repository OIDC policy; backend/lease integration; requirement justification per resource | 4, with 5 consuming |
| Orchestration | Run/manifest identity; conditional registration; Glue `.sync`; independent output validation; bounded Athena; summary/case persistence; evidence-gated finalization; exact failure state; no placeholders | 5, proved live in Part 4 |
| Security/cost | Main/manual restrictions; short-lived OIDC; least privilege; private S3/TLS; synthetic data; structured logs without raw records; short retention; Glue worker/timeout bounds; Athena cutoff; run/expiry tags; gross run ceiling within project ceiling; always-running teardown; independent cleanup verification; Glue observability | 2 and 4–7 |
| Canary | Current-source prerequisites; saved plan; expected-resource apply; control-plane verification; zero Glue runs; zero state-machine executions; zero Athena queries; empty business state; exact destroy; empty state; zero active residue | 6–7 |
| Part 3 exit | Read-only qualification; IAM parity; cleaned definition probe; plan proof; deployment success; no workload; teardown; independent clean state; no lease/resources; honest billing classification | 8 aggregates owner evidence |
| Inherited corrections | Generator and independent expected totals; corrected-source resolution; property campaign; full DataFrame pipeline; explicitly retained local measurements | Stage 1 correction; Stage 3 implementation owners; Part 4 measurement owner |

Create bidirectional links: requirement → code/test/evidence/claim, and test/artifact → requirement. A future implementation row may have a planned artifact path, but must not be marked implemented or verified because the path was named. Unknown requirements, duplicate IDs, orphan tests, missing owners, circular gate dependencies, missing evidence, and inappropriate claim levels must fail the validator.

### A4. Register the six Part 3 master gates

| Frozen master gate | Evidence owner | Stage 1 state |
|---|---|---|
| `environment_qualified` | Stage 2 | Not executed |
| `live_iam_parity_verified` | Stage 2 | Not executed |
| `glue_definition_probe_verified` | Stage 2 | Not executed |
| `plan_only_verified` | Stage 6 | Not executed |
| `zero_workload_canary_verified` | Stage 7 | Not executed |
| `teardown_verified` | Stage 7, independently rechecked before Stage 8 closure | Not executed |

Keep master gate names byte-consistent with the completion contract. Local schema tests, a plan document, or a future owner cannot satisfy any of these gates.

**Package A exit:** source coverage complete; all inherited boundaries digest-bound; G002–G006 and G011 recorded; every later obligation has an owner; no Part 3 AWS gate falsely passed; no protected authority changed.

## 7. Package B — Corrected-source semantics and compatibility contract

### B1. Fix the actual missing path

The current finalizer's `_case_revision` emits `OPEN` for exceptions and `RESOLVED_BY_LATE_DATA` for every non-exception successor with an existing case. `_verify_transition` recreates that value from the persisted request. `recover_attempt` may return a receipt before reconciliation/finalization runs. The request is a strict version-1 envelope with no correction field.

Therefore changing only the emitted status, adding a CLI flag, or attaching unvalidated prose is insufficient. Correction provenance must be validated, persisted, included in request identity, checked before a replay return, and revalidated when the full history is read.

Source: [finalization implementation](https://github.com/bhuvaneshwaranmurugan21/ledgerguard-payment-reconciliation-platform/blob/cb81704adcfdfac5d93879cd6c189fc2213bbe79/src/ledgerguard/reconciliation/finalization.py), [actual local CLI](https://github.com/bhuvaneshwaranmurugan21/ledgerguard-payment-reconciliation-platform/blob/cb81704adcfdfac5d93879cd6c189fc2213bbe79/src/ledgerguard_part2_stage6.py), [case v2 schema](https://github.com/bhuvaneshwaranmurugan21/ledgerguard-payment-reconciliation-platform/blob/cb81704adcfdfac5d93879cd6c189fc2213bbe79/contracts/v2/case-revision-v2.schema.json).

### B2. Preferred additive representation

Use a separately versioned **correction-provenance companion contract** and a new internal finalization-request version. Keep accepted processor, journal, bank, policy, proof, and case v2 schemas unchanged. The existing case v2 schema already permits `SYSTEM` → `RESOLVED_BY_CORRECTION`; it forbids arbitrary extra provenance fields.

The companion must bind at least:

| Field group | Required meaning and validation |
|---|---|
| Version and correction identity | Strict schema; stable correction ID; canonical content digest; duplicate/changed-content reuse rejected |
| Scope | Exact grain, reconciliation key, currency, and source-system identity domain; verify from admitted records rather than trusting repeated strings |
| Predecessor | Exact authoritative parent head, prior proof identity/content reference, prior case revision, and initial exception identity |
| Original evidence | Existing source identity/business digest references relevant to the diagnosed discrepancy; targets must exist in verified history |
| Corrective evidence | New immutable admitted record identities/business digests and the exact manifest that carries them; no record replacement or silent deletion |
| Correction relationship | Explicit supported correction kind and machine-checkable relationship between original discrepancy and new financial facts; free text cannot authorize a status |
| Policy | Exact policy version/digest and defined treatment of policy changes; a policy update alone is never source-correction evidence |
| Provenance digest | Domain-separated canonical digest excluding only its own digest field; canonical rules are declared before fixtures are generated |

The internal request version is independent of domain-schema numbering. Version 1 requests retain their exact accepted bytes and interpretation. New correction-bearing requests use the new version, include the companion or its verified content-addressed body, and bind it transitively through `request_sha256` → commit → authoritative HEAD. No separate mutable correction flag or unbound side file may decide authoritative case state.

Existing proof IDs remain derived from grain, key, revision, manifest digest, and policy digest. Existing case IDs remain derived from grain, key, and initial exception proof. Do not add correction metadata to those frozen identity formulas. The request and case body digests provide the additional binding without redefining old IDs.

The current persisted batch carries policy identity, not the complete policy document. If causal validation needs the predecessor policy, require its original bytes, verify them against the recorded digest and schema, and retain them through the new content-addressed request inventory so later readback can repeat the validation. A digest alone cannot reconstruct a policy. Missing or altered predecessor policy bytes block that correction path; using the current policy as a substitute is forbidden.

### B3. Financial meaning before implementation

A correction is new, admitted financial evidence that explicitly repairs an earlier discrepancy under a declared deterministic relationship. It is not permission to edit the original record, waive a variance, invent a bank deposit, or reuse an immutable identity with changed bytes.

Start the contract review with these hand-checkable examples, then encode them as actual schema-valid source bundles:

| Scenario | Prior independently calculated truth | Corrective evidence | Required result |
|---|---|---|---|
| Transaction correction | Capture 1,000 minor units; valid clearing debit journal 900; difference 100 and open case | A distinct valid balanced journal contributing the missing clearing debit 100, with companion linking the original journal and discrepancy | Processor 1,000 = ledger 1,000; new proof and correction-resolved case; original journal unchanged |
| Settlement correction | Processor net 1,000; valid clearing movement 900; allocated bank 1,000 | Distinct valid balanced settlement journal adding clearing movement 100, exact same grain and currency, with linked provenance | All three totals 1,000; new proof and correction-resolved case |
| Genuine late bank data | Processor net 1,000; clearing 1,000; missing bank | A newly arrived valid bank credit 1,000 with exact settlement allocation, no correction relationship | New proof and `RESOLVED_BY_LATE_DATA` |
| Incomplete correction | Same transaction mismatch of 100 | Valid linked adjustment of 40 | Residual difference 60; retain `OPEN` if outside unchanged tolerance; preserve correction attempt provenance |
| Invalid identity reuse | Existing journal identity with 900 | Same journal ID changed to 1,000 | `IDENTITY_CONFLICT`; no new authoritative proof or case |

Counterpart postings must use the frozen allowed account roles, positive minor units, and one-sided balanced lines. The journal's clearing orientation must obey its actual event class. A credit on a capture journal is not an admissible shortcut for reversing an overstatement. Similarly, a new processor `REVERSAL` has its own event-class grain and cannot simply be assumed to cancel a capture-grain error.

Before coding, produce a correction applicability matrix across processor events, ledger journals, processor settlements, and bank records. For every claimed mode, state the permitted append-only representation, identity/reference checks, arithmetic, and expected unresolved behavior. The examples above establish the minimum two-grain success coverage; they do not prove arbitrary source replacement is supported.

If an obligation needs a correction that the accepted domain model cannot represent—for example, removing an immutable erroneous movement rather than adding an admissible adjustment—do not relabel it as late data, waive it, silently shrink the requirement, or modify v2. Produce the additive v3 compatibility proposal required by the overall plan, with old/new readers, identities, and tests specified. The affected Stage 1 gate remains blocked until a technically valid supported contract is implemented. No automatic schema escalation or fabricated completion is allowed.

### B4. Causation and transition rules

1. No existing case and a matching proof: preserve accepted no-case behavior. Do not manufacture a resolved case just because a companion is supplied.
2. Existing case, valid relevant correction, unchanged effective policy, and a non-exception result: append `RESOLVED_BY_CORRECTION`, retaining case identity, initial exception identity, prior case digest, and prior proof linkage.
3. A correction that does not resolve the financial exception: append an `OPEN` case revision with current exact reasons and bound provenance. Never convert the failure to success.
4. New late evidence without a correction relationship: preserve the accepted late-data path and outputs.
5. A policy-only change: produce the required policy proof revision under existing semantics and never classify it as source correction. Preserve legacy historical interpretation, including the known broad late label; do not retrospectively relabel history or claim that label proves source causation.
6. Mixed policy and source changes require a deterministic attribution rule. Preferred rule for a correction classification: independently evaluate the corrected source under the predecessor policy and demonstrate that source correction resolves the prior exception without relying on newly relaxed tolerance. If this cannot be proved unambiguously, fail the correction-bearing request with exact unchanged-state evidence. Ordinary policy reprocessing remains supported; do not disable it to pass this gate.
7. Correction mixed with unrelated late records must bind only its affected keys. If the same key has competing causal explanations that the frozen contract cannot distinguish, reject the ambiguous correction classification rather than using timestamps or “last writer wins.”
8. `WITHIN_TOLERANCE` retains its exact monetary difference and `TOLERATED_DIFFERENCE` reason. Under inherited non-exception case behavior it may close a case, but it must not be described as exact equality or operator acceptance.
9. `ACCEPTED_VARIANCE` and `WRITTEN_OFF` remain operator-only and unavailable to this system path. No new lifecycle status is invented in Stage 1.
10. Identical correction replay has no second correction business effect. Track correction identity through authoritative request history. Reusing that correction ID with changed provenance rejects. A new attempt retry of an already published correction must locate its committed outcome before proposing another correction revision.
11. Repeated identical ordinary inputs retain the accepted legacy retry/reprocessing behavior. Do not globally change revision semantics while adding correction-specific replay protection.
12. A new distinct correction after an incomplete correction must point to the latest authoritative predecessor and current discrepancy. It must not target stale or already-consumed evidence to apply the same adjustment twice.

The policy attribution rule and applicability matrix are **required execution decisions**, not claims that the current code already implements them. B cannot close with `TBD` in either. Use contract-compatible examples and independent calculations to settle them before implementing C.

### B5. Determinism and compatibility acceptance

- Correction status never depends on current wall time, file mtime, directory order, or operator intuition. Caller-provided timestamps remain schema-valid payload fields; changing a timestamp may change a body digest but cannot change causal classification.
- Changing order of equivalent correction references must canonicalize to the same request semantics; duplicates are rejected or explicitly normalized according to the frozen new contract, never double applied.
- Version-1 request serialization and history verification remain byte-compatible. Mixed old/new history must be verified using each request's declared version.
- Old software must reject an unsupported new request format cleanly; it must not silently read new correction history as late data. Document that a store containing new requests requires the new reader.
- Stable existing top-level failure ownership remains: schema/source/provenance input defects → admission failure; source identity conflicts → `IDENTITY_CONFLICT`; corrupt persisted state or failed atomic publication → execution/finalization failure. New diagnostic details must not mutate the frozen reason taxonomy.

**Package B exit:** strict companion schema and request-version specification; completed applicability/causation tables; independent golden examples; compatibility ADR; precise error mapping; no altered frozen financial or schema authority.

## 8. Package C — Implementation sequence and semantic proof

### C1. Minimal implementation sequence

1. Add strict companion parsing, canonicalization, identity validation, and source-reference resolution in a pure local module. Keep network, AWS, and independent oracle imports out of production semantics.
2. Validate corrective source records through the real existing manifest/admission path. A companion may reference admitted truth; it may not inject an already-matched candidate or bypass journal, currency, reference, or identity checks.
3. Add the new request version and explicit dispatch. Preserve the old request builder and old read interpretation. Bind all correction content before hashing the request.
4. Extend finalization's state validation to check historical correction IDs, predecessor ownership, exact newly admitted records, and causal relevance before publishing anything authoritative.
   Re-derive the relevant financial relationship from verified admitted source/state and bound policy inputs; a caller-supplied candidate status or a companion's asserted totals cannot prove its own correction. Use the existing production arithmetic/admission rules in production and separate expected calculations in tests.
5. Extend case classification using the validated request cause. Preserve proof/case IDs, sequential revisions, initial exception identity, reason history, and the unchanged single-HEAD atomic publication mechanism.
6. Extend `_read_request`, `_verify_transition`, `verify_history`, `load_states`, `_find_attempt`/receipt handling where necessary, and `recover_attempt`. Recovery must validate supplied correction identity before returning an existing receipt. A legacy invocation must not recover a new correction request while ignoring its extra identity.
7. Expose a supported local correction entry point. Prefer an additive CLI/command that calls the shared implementation; keep the existing Stage 6 command and flags backward compatible. The new command takes an actual provenance file and verifies its contents, not a boolean “resolve by correction” flag.
8. Confirm corrected-source objects, request, proofs, cases, commit, and outcome are all reachable through the normal read/recovery path. Do not maintain a second independently authoritative correction database.
9. Add tests as each boundary becomes executable. Expected financial values must come from hand-checked fixtures or independently implemented reference calculations, never the production output being asserted.

Do not refactor unrelated admission, transaction, settlement, or Spark modules. Any necessary change there must identify the correction invariant it serves and its current-source regression obligation.

### C2. Required test matrix

Test IDs below are proposed stable Stage 1 IDs. Each must map to actual collected test names and evidence in execution. Parameterization is encouraged when it preserves distinct outcomes and failure evidence.

| Test ID | Scenario | Required assertion |
|---|---|---|
| T01 | Transaction exception → valid correction | Independently exact totals; new proof; correction status; same case ID; predecessor and initial exception retained |
| T02 | Settlement exception → valid correction | All three deltas correct; exact bank allocation unchanged; same history guarantees |
| T03 | Genuine late bank arrival | Existing late status and logical outputs unchanged |
| T04 | No prior case | Matching proof does not create a fabricated resolved case; invalid correction predecessor rejected |
| T05 | Partial correction remains unresolved | Exact residual amount/reasons and `OPEN`; provenance retained |
| T06 | Correction to tolerance boundary | Difference remains visible; reason retained; no exact-match or operator-acceptance claim |
| T07 | Identical same-attempt correction retry | Same authoritative receipt, head, proof and case counts; no duplicate effect |
| T08 | New-attempt retry after successful correction | Already published correction located; no duplicate correction application or correction case revision |
| T09 | Changed provenance under same attempt/correction ID | Rejection and unchanged authoritative inventory |
| T10 | Same source identity, changed business bytes | Existing `IDENTITY_CONFLICT`; no override through provenance |
| T11 | Missing, forged, wrong-digest, unrelated correction target | Fail admission; no authoritative mutation |
| T12 | Wrong grain, merchant, payment/settlement, source system, or currency | Exact scope rejection; unrelated keys retain previous heads |
| T13 | Invalid journal, role orientation, reference, or bank allocation | Existing reason ownership preserved; no correction exemption |
| T14 | Stale predecessor; reused/consumed correction link | Reject rather than apply against the wrong history |
| T15 | Policy-only revision | Required new policy proof; never correction; legacy historical behavior explicitly checked |
| T16 | Policy-plus-correction | Source causation proved under digest-verified predecessor policy or ambiguous request rejected; missing/tampered policy bytes reject; no tolerance-based misclassification |
| T17 | Mixed late/correction data across keys | Correct per-key classification; no batch-wide correction flag |
| T18 | Genuine second correction after partial first | Latest predecessor used; prior corrections counted once; final totals independently correct |
| T19 | Input/reference order and source-file partition variations | Same canonical logical outcomes and promised request/correction identities |
| T20 | Timestamp/mtime variations | Causal status unaffected; distinguish identity invariance from payload timestamp changes |
| T21 | Old v1 request histories under new reader | Exact historical proof/case bytes, receipts, IDs, state, and golden digests preserved |
| T22 | Mixed old/new chain; restart and `load_states` | Full state reconstructs; each request version and provenance checked |
| T23 | Tamper with provenance/request/commit/case | Readback rejects, including tampering with recomputed superficial digests that breaks causal/predecessor binding |
| T24 | Unknown request/provenance version, duplicate JSON keys, malformed shape | Fail closed before new authority; unsupported readers never silently downgrade |
| T25 | Crash after attempt/object/commit write, before HEAD | No authoritative partial proof/case; orphan content does not become truth |
| T26 | Crash after HEAD, before outcome; later commits exist | Recovery finds original committed correction; no second business effect |
| T27 | Two competing correction processes | One conditional publication winner; loser cannot overwrite; valid later retry/rebase follows explicit ownership |
| T28 | Real storage failure | Execution ownership; no disguised financial exception or successful completion |
| T29 | System requests operator-only lifecycle states | Rejected; actor and authorization boundary unchanged |
| T30 | Invalid correction in a multi-key batch | Whole authoritative commit remains unchanged; no partially finalized valid subset |
| T31 | Installed-package CLI correction and retry | Real source files → admission → reconciliation → finalization → independent readback; no direct fabricated candidate substitute |
| T32 | Existing critical financial/recovery tests on current code | All inherited financial, schema, replay, crash, concurrency, and Spark logical-parity assertions still pass |

Real subprocess crash and concurrency tests are necessary because in-process simulated success cannot prove atomicity. Existing focused fault injection may help measure branches, but cannot substitute for actual process termination, competing writers, or real filesystem failures. Keep independent expected-output generation separate from production code.

### C3. Mutation obligations

Register executable mutations against the new/changed semantics, not merely changed expected-output JSON. Each mutation must be applied, a discriminating test executed, and its failure captured. Equivalent/non-applicable mutations need an explicit technical adjudication; they cannot quietly disappear from the registry.

| Mutation family | Examples that must be killed |
|---|---|
| Causal classification | Force all matches to late; force all matches to correction; let a free-text/boolean flag authorize correction; let relaxed policy alone authorize correction |
| Provenance binding | Drop companion from request hash; ignore an original/adjustment digest; accept unrelated or missing records; accept ambiguous per-key attribution |
| Identity/replay | Accept changed correction ID payload; apply an already consumed correction twice; ignore new provenance on early recovery |
| Historical chain | Lose prior proof/case link; change initial exception identity; reinterpret v1 history under new rules; accept unsupported request versions |
| Financial boundary | Suppress residual difference; admit role/currency/reference violation; silently replace immutable records |
| Publication/recovery | Publish HEAD before complete inventory; bypass stale-head check; recover an orphan as authoritative; ignore corrupt provenance during readback |
| Actor boundary | Permit system accepted variance/write-off |
| Governance/evidence | Accept changed protected authority; missing master bullet; unowned gap; stale active state; forged CI SHA; future AWS claim |

**Package C exit:** all required scenarios implemented and passing; changed semantic surface fully covered; real failure and recovery behavior proved; no unresolved Stage 1 semantic blocker or silent compatibility change.

## 9. Package D — Historical regression, current regression, and CI evidence

### D1. Resolve historical validation correctly

`src/ledgerguard_part2_stage8_closure.py::_documentation` explicitly requires the old candidate wording. It also checks workflow markers and closure artifacts. Editing those assertions or retaining stale active wording to get green CI would both be wrong.

Add an exact immutable PR #18 worktree, following the existing historical-worktree pattern:

- Freeze commit `cb81704adcfdfac5d93879cd6c189fc2213bbe79`, tree `89689d7e32cd09e36a8456484a50c23d0192897f`, and sole parent `71b42d6622558093a2bfaced58724f2ab71e793e`.
- Run the unchanged Part 2 Stage 8 closure runner from that entire worktree. Its source, docs, workflow, locks, tests, and expected state are all historical inputs.
- Preserve all already required Part 1 and Part 2 historical regression jobs and their current protected-authority byte checks.
- Add a mandatory current-root Stage 1 validator that checks actual PR #18 closure facts, current active status, new conformance rows, current workflow constraints, and current implementation evidence.
- Run inherited financial and recovery tests against the **newly installed current wheel**, as well as the historical suites against historical wheels. A historical green run alone says nothing about modified current finalization code.
- Build an explicit test-selection manifest distinguishing historically bound governance tests from current behavioral tests. Retain every former obligation; when a historical-root assertion cannot apply to active docs, document its historical run and its new current-status equivalent. No blanket exclusions, xfails, assertion deletion, or reduced collection counts to conceal failures.

Source: [frozen closure validator](https://github.com/bhuvaneshwaranmurugan21/ledgerguard-payment-reconciliation-platform/blob/cb81704adcfdfac5d93879cd6c189fc2213bbe79/src/ledgerguard_part2_stage8_closure.py), [current CI structure](https://github.com/bhuvaneshwaranmurugan21/ledgerguard-payment-reconciliation-platform/blob/cb81704adcfdfac5d93879cd6c189fc2213bbe79/.github/workflows/ci.yml).

### D2. Current validation pipeline

1. Validate source digests, immutable authorities, ledger schemas, gate ownership, traceability, correction schema, and golden contract vectors.
2. Run Ruff lint and formatting checks, strict typing over all owned modules including new top-level entry points/runners, and schema/reference/coherence checks. Do not rely on a default mypy package selection that omits new modules.
3. Build and install the current wheel in a clean environment; prove imports resolve to that wheel rather than the source tree or an older editable installation.
4. Run the current behavioral suite and T01–T32. Run genuine bounded Spark/Parquet regression with the inherited exact runtime; describe it only as the bounded parity it proves.
5. Measure overall current production coverage against a declared complete inventory: at least the master-plan 90% overall, with no hidden new module exclusions. Require 100% statements and branches over every new/changed Stage 1 semantic and authority surface. Retain inherited stricter gates unchanged.
6. Execute registered semantic mutations; require zero survivors. Missing mutation execution or missing coverage output fails evidence validation.
7. Repeat in a second independent clean environment/output root using the same locked dependencies, separate installed wheels, distinct hash seeds, stable fixture inputs, and normalized build timestamps. Do not count two reads of one result as two runs.
8. Independently compare promised deterministic outputs and retain both raw result sets. Stop after the required evidence is sufficient; broaden testing only for a specific remaining defect or gate.

### D3. Determinism contract

| Compare byte-for-byte | Record but do not falsely require equality |
|---|---|
| Source inputs/manifest where promised; normalized authority/ledger output; correction objects; request bodies with equal declared inputs; logical proof/case output; deterministic evidence payload; reproducible wheel | Runtime, throughput, process IDs, temporary absolute paths, CI run/job IDs, captured wall-clock timestamps, raw Spark logs, physical Parquet bytes unless independently proved reproducible |

Declare deterministic versus observational fields in the evidence schema before running tests. Do not remove a fluctuating financial field after failure to make equality pass. Preserve raw observations outside the deterministic payload with their digests. A corrected-source request deliberately differs from a legacy request; equality is required only within its stated comparable-input domain.

### D4. Automatic CI controls

- Check out `github.event.pull_request.head.sha` for PRs and `github.sha` for pushes; assert actual HEAD equality. Preserve full Git history needed for topology checks.
- Use explicit read-only permissions. Keep `pull-requests: read` only where evidence lookup needs it; prohibit `id-token: write`, credential configuration actions, AWS execution, and `pull_request_target` execution of untrusted code.
- Inventory every command and action reachable from the Stage 1 jobs. Validate workflow structure, permissions, shell commands, runner subprocesses, and production dependency imports; a search for one literal `aws ` marker is insufficient evidence of the boundary.
- Use the real local implementation during validation. Where feasible, run semantic tests without outbound network access after locked dependencies are available. Record the enforced boundary and invocation log; do not claim account-wide inactivity from a local static check.
- Upload Stage 1 evidence from the actual event head with missing-file failure enabled and pinned action versions. A fork PR must not gain secrets or write authority through artifact creation.
- Require both historical and current jobs before readiness. No `continue-on-error`, blanket skip, reduced thresholds, or disabled tests.
- Keep artifact production event-aware. A PR artifact can exist before the final job conclusion, but an independent inspector must require the run to finish successfully before accepting it. Do not have a running job attest its own final success.

### D5. Evidence artifact

Proposed artifact name: `ledgerguard-part3-stage1-<exact-head-sha>`. Include:

1. An artifact member manifest with relative paths, lengths, and SHA-256 digests.
2. A schema-valid CI envelope: repository, PR/event/ref, run/attempt/job IDs where available, expected and actual commit, tree, base, workflow identity, lock digests, toolchain, installed-wheel digest, and execution boundary.
3. The baseline freeze and independently verified PR #18 artifact manifest/digest facts.
4. Normalized source index, requirement ledger, gate registry, bidirectional traceability, conformance register, and Stage 1 adjudication.
5. Correction contract/golden-vector identities and test collection manifest.
6. Both clean-run reports; exact tests passed/failed/skipped; scoped coverage JSON; mutation IDs/results; deterministic comparison and logical digest.
7. Crash/concurrency/retry/readback evidence containing before/after authority inventories and exact failure ownership.
8. Current documentation consistency verdict and immutable historical-authority comparison.
9. Redaction/sensitive-evidence and artifact-member validation results. Public evidence references the frozen target through a sanitized fingerprint, not a new raw account-ID dump.

The artifact manifest must not recursively hash itself. Define its excluded self-file and the external ZIP digest explicitly. Final GitHub success and post-merge facts are independently checked outside the producing process. Future run IDs and post-merge SHA values must never be guessed into the candidate record.

**Package D exit:** two clean current runs pass; all inherited obligations remain enforced; coverage/mutations and deterministic evidence meet their declared scopes; exact-head PR CI completes successfully; artifact is independently downloadable and verifiable.

## 10. Package E — Promotion and closure

### E1. Prepare a concrete review

Open one draft Stage 1 implementation PR when execution is authorized. Its body must lead with the actual problems: inaccurate active closure status, missing master traceability, and missing correction provenance/classification. Explain the additive compatibility strategy, G011 routing, changed behavior, and exact validation evidence.

Review the diff against the package A baseline. Reject unrelated Terraform, AWS workflow execution, generator implementation, full Spark-pipeline implementation, frozen authority edits, or new lifecycle states. Confirm every Stage 1 gate below has evidence and that downstream obligations are clearly still open.

### E2. Independently inspect the final exact-head artifact

1. Read PR head and successful CI run metadata independently.
2. Download the artifact by ID; verify head/name/run/repository binding and safe complete inventory.
3. Recompute ZIP and member digests; validate evidence schema and deterministic comparison.
4. Check all required historical and current jobs, collected test manifests, coverage scopes, mutation execution, zero survivors, and no hidden skips.
5. Confirm no new push occurred after the accepted head. If it did, invalidate readiness and inspect the replacement head's evidence.
6. Mark ready only after these checks. Prepare the manual squash instructions for that exact head.

### E3. Manual squash and independent main verification

After the established manual merge:

- Fetch the resulting squash commit; require exactly one parent equal to the admitted base and tree equality with the validated PR head. If `main` moved, update/rebase/revalidate the candidate first; do not accept evidence for a stale base.
- Require an independent successful `push` CI run on that exact squash commit, with all mandatory jobs executed.
- Record the actual main run/job, commit/tree/parent, PR head, accepted artifact ID, and independently computed digests in an external closure receipt. Stage 1 is not closed merely because the merge button was used.
- Do not insert future self-closure facts into the implementation commit. If the repository protocol requires an on-main attestation record before Stage 2, use a bounded follow-up evidence-only transaction whose claims concern the already completed implementation merge/run. Its own merge evidence remains external until it exists; do not create an infinite chain of self-attestation PRs.
- Keep the overall project in progress and the Part 3 master gates unexecuted. A local Stage 1 completion does not promote the project to `AWS_DEPLOYMENT_VERIFIED`.

If main CI fails, Stage 1 remains open. Preserve the failing evidence, diagnose the root cause, implement the correction on a new exact head, and repeat affected validation. Do not rerun until green without establishing whether the failure was transient or a code/contract defect.

**Package E exit:** verified squash topology, matching tree, independent green main CI, complete external closure receipt, and an unambiguous next owner: Part 3 Stage 2. Do not execute Stage 2 as part of Stage 1 closure.

## 11. Planned repository change inventory

These paths are proposed implementation destinations, not files created by this planning turn. Confirm naming against the live tree before execution; retain the existing flat stage-validator convention and avoid gratuitous restructuring.

| Area | Proposed files / existing touchpoints | Purpose and boundary |
|---|---|---|
| Entry authority | New `contracts/part2-part3-handoff-v1.json`; `spec/part2-stage8-external-closure-freeze-v1.json` and schemas | Exact predecessor and protected authorities; no edits to old freezes |
| Master conformance | New `spec/part2-master-conformance-correction-v1.json`; `spec/part3-source-index-v1.json`; `spec/part3-requirement-ledger-v1.json`; `spec/part3-gate-registry-v1.json`; `spec/part3-traceability-v1.json` and strict schemas | Original source coverage, G003–G006/G011 ownership, master gates |
| Stage authority | New `spec/part3-stage1-requirements-v1.json`; `spec/part3-stage1-gate-registry-v1.json`; `spec/part3-stage1-coverage-v1.json`; `spec/part3-stage1-vectors-v1.json`; `spec/part3-stage1-ci-evidence-v1.schema.json` | Stage-specific requirements, test/mutation coverage, evidence |
| Correction contract | New `contracts/correction-provenance-v1.schema.json`; new request-version schema/spec | Additive provenance; do not modify accepted domain v2 schemas |
| Production semantics | New `src/ledgerguard/reconciliation/correction.py`; narrow changes in `finalization.py`; package exports only as needed | Pure validation, causal classification, version-aware history and retry |
| Local entry point | New correction CLI module/command; shared finalization integration | Real file-based correction execution; preserve Stage 6 interface |
| Stage validation | New `src/ledgerguard_part3_stage1_validation.py`, `src/ledgerguard_part3_stage1_evidence.py`; new runner/build/validate scripts under `tools/` | Current-root checks and reproducible evidence; validators do not fabricate external success |
| Tests | New correction semantic/history/CLI tests; new Stage 1 authority/evidence tests; current behavior selection manifest | T01–T32 and governance adversaries; retain existing tests |
| Documentation | New `docs/part3-stage1-gap-audit.md`, `docs/part3-stage1-execution-contract.md`, `docs/part2-master-conformance-correction.md`, next available ADR | Explain exact compatibility and known boundaries |
| Active status | Update `README.md`, `PROJECT_STATUS.md`; clarify `docs/part2-completion.md` if treated as active | Record actual PR #18 closure; clearly separate historical candidate snapshots from current state |
| Build/CI | `.github/workflows/ci.yml`, `pyproject.toml`, `Makefile`; new Stage 1 lockfiles if needed | Historical PR #18 worktree plus current validation, exact tooling, new installed entry points |

Do not edit `docs/part2-stage8-gap-audit.md`, old requirement/gate ledgers, frozen Spark modules, or any other protected authority. If an active document is discovered to be protected by another inherited freeze, preserve it and publish a clearly linked current addendum instead. The package A inventory decides this before edits begin.

## 12. Stage 1 gates and acceptance evidence

| Gate | Acceptance criterion | Required evidence |
|---|---|---|
| P3-S1-G001 — exact entry | PR #18/head/tree/parent/main CI and artifact verified; correct resumed base | Git facts, artifact inspection, baseline freeze |
| P3-S1-G002 — immutable inheritance | Every inherited protected authority and accepted v1/v2 schema unchanged | Complete path/digest comparison; unchanged historical validators |
| P3-S1-G003 — master coverage | Every Part 3 master obligation and inherited carryover has a stable row and owner | Source coverage inventory, strict ledger and reverse traceability checks |
| P3-S1-G004 — honest conformance | G003–G006 and G011 remain explicit; old closure preserved; no blanket original-master 100% claim | Append-only record, gap statuses, active documentation checks |
| P3-S1-G005 — correction contract | Applicability, causal attribution, schemas, IDs, request version, and errors settled | ADR, strict contracts, independent golden vectors; no unresolved required mode |
| P3-S1-G006 — executable correction | Both grains support valid source correction with correct monetary results and immutable histories | T01–T18, real CLI, independently expected totals |
| P3-S1-G007 — replay/history/recovery | No duplicate correction effect or partial authority; legacy and mixed history remain valid | T07–T14 and T19–T31; actual crash/concurrency and tamper evidence |
| P3-S1-G008 — current regression | All inherited current financial behavior and Spark parity remain valid | Current installed-wheel test manifest, raw results, historical/current obligation mapping |
| P3-S1-G009 — quality | Lint/format/strict typing/schema pass; ≥90% overall coverage; 100% owned statements/branches; zero mutation survivors | Scoped coverage JSON and executed mutation registry |
| P3-S1-G010 — reproducibility | Two independent clean runs agree within declared byte/logical scopes; wheel reproducible | Both run reports, manifest, comparison, dependency/build identities |
| P3-S1-G011 — no AWS execution | Stage 1 automatic workflow cannot obtain OIDC; no AWS invocation in executed Stage 1 path | Workflow/permission/action analysis, runner invocation evidence, dependency boundary |
| P3-S1-G012 — truthful status | PR #18 completed; Stage 1 candidate/verified status matches actual evidence; all six AWS master gates still unexecuted | Active-status validator and independent GitHub facts |
| P3-S1-G013 — exact-head evidence | Final PR head has successful required CI and independently verified immutable artifact | Head/run/job/artifact identities and inspection report |
| P3-S1-G014 — external closure | Manual squash has expected sole parent and validated tree; exact main CI succeeds | Merge topology and independent main run; closure receipt |

All fourteen gates are mandatory. G001–G012 must be substantively satisfied before PR readiness; G013 certifies the exact candidate; G014 closes the stage after merge. A future-owned generator or Spark pipeline does not pass its own implementation gate at Stage 1—only its complete, enforceable ownership can pass G003/G004.

## 13. Failure and recovery register

| Failure | Root-cause response | Evidence and restart point |
|---|---|---|
| HEAD differs from recorded base | Inspect intervening commits and CI; locate existing Stage 1 work; amend baseline only with evidence | A1; preserve original observations |
| Artifact unavailable or digest differs | Obtain correct immutable content or produce a new separately attributable verification; never invent the old digest | A1 remains blocked |
| Source bullet unowned | Add its actual obligation and owner; correct normalization | A3; do not lower requirement count as a workaround |
| Protected file differs | Restore unintended change or produce an additive compatible path | A2; old bytes and validator unchanged |
| Correction cannot fit frozen semantics | Complete the required additive compatibility proposal; prove old/new behavior | B; no status-only workaround |
| Policy/source cause ambiguous | Reject ambiguous correction request; define/test deterministic rule without disabling policy revisions | B4/C; unchanged-state proof |
| Retry ignores correction provenance | Fix request/recovery identity binding at the early return, then test published and orphan cases | C; replay and mixed-history tests |
| Historical read fails after new case status | Fix version-aware request/transition verification; never bypass `verify_history` | C; byte-preserved old history plus new history proof |
| Current docs break old candidate validator | Use complete accepted historical worktree plus mandatory current-status validator | D1; prove no test obligation lost |
| Coverage misses critical branches | Add meaningful negative/recovery scenarios; correct implementation if dead/unsafe path exists | C/D; no pragma exclusions or threshold reduction |
| Mutation survives | Fix missing assertion or implementation defect; rerun that mutation and affected suite | D; retain prior failure record |
| Nondeterministic result | Find unstable inputs/order/serialization/build metadata; fix source of variance | D3; no deletion of financial fields from comparison |
| CI runtime unavailable | Provision locked exact runtime or verified offline wheelhouse | D; do not relax Python/Java/Spark versions |
| New push after artifact inspection | Invalidate readiness; validate and inspect new head | E2 |
| Merge topology or main CI fails | Keep Stage 1 open; diagnose and use corrective transaction | E3; never claim external closure prematurely |

## 14. First execution session and final handoff

The first authorized execution session should finish A1–A4: confirm the still-current base, inspect the immutable PR #18 artifact, inventory protected paths, normalize ownership, and commit a reviewable entry/conformance slice on the Stage 1 branch. It should then proceed into B's concrete contract and golden scenarios. This sequence exposes compatibility problems before changing the finalizer.

At Stage 1 completion, hand the next executor:

- The accepted Stage 1 squash SHA/tree/parent and independent main CI run.
- The verified Part 2→3 handoff and source/authority digests.
- The correction protocol, supported-mode matrix, installed-package entry point, and complete local proof/recovery evidence.
- The exact current test/coverage/mutation/artifact inventory and its independently verified digests.
- The Part 3 requirement/gate ledger, with G003/G005/G011 owned by Stage 3, G006 by Part 4, and live qualification still owned by Stage 2.
- The explicit claim boundary: Part 2 local reconciliation accepted; Stage 1 correction and entry governance locally verified; AWS identity/platform/workload/cost/performance/scale still unclaimed by this stage.

The first genuinely incomplete step after that handoff is Part 3 Stage 2 admission and qualification. Reaching it is not authorization to execute it within this Stage 1 task.

## 15. Planning verification record

This plan was checked against the newly supplied master and Part 3 plan, exact GitHub HEAD/tree/PR topology, open-PR state, current CI job steps and logs, the recursive source inventory, the 203-row Part 2 ledger, current closure/status documents, financial and case contracts, finalization/recovery code, existing finalization tests, the actual Stage 6 CLI, Spark implementation, dependency configuration, and historical freeze mechanisms.

No fresh local test execution or live AWS verification is represented as completed. The plan deliberately distinguishes observed repository facts, inherited historical evidence, implementation decisions to settle in package B, planned validation, and externally verifiable closure. The detailed execution has not begun.
