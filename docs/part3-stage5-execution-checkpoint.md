# Part 3 Stage 5 execution checkpoint

Stage 4 is externally accepted at squash
`7036a1557f815a0aaea9d635278cc687297d6214`, tree
`ebf620bbf3a345a6b1c985820679837612805fe3` (PR #27).
Native main run 34565883871 and all six jobs in broader main run 34565883880 passed.
Both native artifacts and the broader Stage 3 producer/inspection artifacts were
downloaded and independently inspected before this Stage 5 branch was admitted.

## Current continuation — metadata authority and financial snapshots

The next increment adds durable immutable run registration, active attempt ownership,
monotonic fencing, namespace predecessor CAS, a fixed four-item DynamoDB publication
request, and exact persisted replay verification beyond service token windows.
The local metadata transaction covers the namespace root, immutable commit, terminal
run pointer and attempt status together. These are actual SQLite transactions;
the DynamoDB request builder is a transport contract, not live AWS evidence.

Financial snapshots now seal and restore the actual accepted `FinalizationStore`:
requests, commit ancestry, proofs, cases, outcomes and source history are retained.
Readers resolve one committed metadata root before restoring and verifying its entire
financial history. Snapshot bodies are content-addressed under `publications/`, outside
the seven-day `runs/` lifecycle. Atomic create-or-verify rejects overwrite/deletion
history. Objects are at most 64 KiB; index pages contain at most 32 entries or children.
The tree grows across levels without enlarging the four-item publication transaction.

Tests exercise 1,000 actual finalized exception cases, index page boundaries, durable
reopen, accepted balanced-journal correction and exact correction replay, malformed
and missing snapshot identities, concurrent creation and predecessor publication,
stale fences, and process termination during preparation and atomic publication.
These local snapshot tests do not establish independently computed Parquet truth,
managed job ownership, effective AWS permissions or a complete production handler.
The handler must still bind the admitted run and validation evidence to the prepared
financial snapshot and preserve complete correction/scope behavior end to end.

Local qualification passed 215 tests in each of two fresh workspaces, with all 803
statements and 332 branches covered, zero exclusions, and all 23 actual source
mutations killed twice. Ruff and strict mypy passed. The raw source-bound receipt is
`evidence/part3-stage5/snapshot-local.json`; it truthfully records a dirty working
tree based on the first published head. Exact successor CI is still required.
Both full clean baselines include every Stage 5 test,
including the 1,000-case test; the critical coverage threshold remains 100% for all
control source with zero exclusions. The mutation campaign retains all original
mutations and adds authority/snapshot faults. Each mutant stops at its first failure;
acceptance still requires an actual assertion failure, zero collection/runtime errors,
and zero skipped tests. Stopping a killed mutant does not truncate either baseline.
The CI timeout is increased to accommodate the larger real financial-store campaign.

The first published head `1983ceb37ea36ee92bb131c4552f9ad62ee769ff` passed broader run
34571572450 (all six jobs), native run 34571572578 (both artifacts independently
inspected), and incremental run 34571572570 (raw tests, executable-source coverage
inventory and all source mutations independently inspected). Its fresh native scans
retain the existing exact four source-bound applicability decisions. Broader Stage 3
producer/inspection ZIP digests are respectively
`5afd4fbf42de8e3f5fdc38ac87492d3b669e64307291b5a95f1b826d58221bd1` and
`f9504c869aa4dc090a4bc69e729838dd1c7d3fa2688abba4de08516f31cd9f64`.
Those receipts establish the first increment's compatibility, not this successor's
exact-head CI or full Stage 5 acceptance. PR #28 remains draft.

## Independently compared Parquet increment

The exact published snapshot head `80e81d249d10f8d47b277f59a25133ef2f2b3c57`
passed all three workflows. Broader run 34576410961 passed all six jobs; native run
34576410960 produced two independently equal payloads with 387 tests, 26 killed
mutations, 478/226 control statements/branches and 742/292 critical
statements/branches all at 100%. Incremental run 34576411110 independently bound
215 tests, 803 statements, 332 branches and 23 killed mutations to the exact source.
The broader Stage 3 producer artifact and its CI inspection were downloaded, parsed
independently and matched byte-for-byte. No AWS workload or mutation occurred.

The successor adds an independent disk-backed exact row comparison of real Arrow
Parquet transaction, settlement and bank-allocation data against externally admitted
canonical JSONL evidence. It verifies the trusted expectation digest, exact family
inventory, physical member digests/sizes before and after streaming, strict Arrow
schemas, complete row counts, canonical types, int64 arithmetic, currency, grain,
reconciliation identities, status/reason consistency and both directions of set
equality. A 256-row batch bound and SQLite temporary store avoid unbounded in-memory
materialization. Candidate rows cannot claim financial authority. Tests include
values above 2^53, offsetting cross-currency errors, omissions, extras, duplicates,
file substitution, schema changes and every semantic rejection boundary.

The CPython 3.11 dependency closure admits only the hashed manylinux2014 x86_64
`numpy 2.1.3` and `pyarrow 17.0.0` wheels and was installed successfully in a fresh
environment with no index or source build. The two-workspace driver now snapshots
every source, test, spec and contract byte once before either run, closing a discovered
copy-time race. Its complete local qualification passed 251 tests in each workspace,
all 984 statements and 434 branches at 100% with zero exclusions, and all 28 source
mutations were killed twice. `evidence/part3-stage5/financial-parquet-local.json`
retains the source-bound LOCAL_VERIFIED receipt; `stage5_complete` remains false and
`aws_calls` remains zero. Exact successor CI and independent artifact inspection are
still required.

## Bounded Athena proof increment

The published financial head `e353f5744f69b4eb07c60642f01a7404c95293db`,
tree `c3a4dc22fd59e001373cc034f0d0513471aabf65`, passed its native and
incremental workflows. Both native artifacts were independently equal with 387 tests,
26 mutations and complete control/critical coverage. The incremental artifact was
independently bound to 251 tests, 984 statements, 434 branches and 28 killed
mutations. Its broader compatibility was cleared before the Athena successor was
published; the exact Athena-head gate is recorded below.

The next successor renders exactly three SELECT-only Athena summaries from closed
database/run/attempt identifiers. Every query is confined to both injected partitions,
groups by currency/status-or-disposition/reasons, uses DECIMAL(38,0) sums exposed as
canonical strings, and has a source-derived SQL digest. Verification binds the exact
query, workgroup, engine, result location, expected owner, SSE-S3, terminal success,
100 MiB scan maximum and five-minute execution maximum. It consumes the complete
request/next-token chain with explicit 128-page, 4,096-row and expectation-document
bounds, rejects null/header/type/order errors, and compares exact aggregate rows to
an independently digest-pinned canonical input. No query is started by this code.

Two immutable-input local workspaces each passed 290 tests, all 1,136 statements and
510 branches at 100% with zero exclusions, and all 33 source mutations were killed.
`evidence/part3-stage5/athena-local.json` is LOCAL_VERIFIED, records zero AWS calls and
keeps `stage5_complete` false. AWS response normalization, candidate version recheck,
query-proof object persistence and handler/ASL integration remain required.

The exact published Athena head `4d3f36960da3bcc072087abe9c861ab55251935c`,
tree `2416891cec9748538eed9c761e462c27750eb4c5`, passed native run 34584138876,
incremental run 34584139024 and all six jobs in broader run 34584138945. The broader
Stage 3 artifact 10193604829 (SHA-256
`7a53a92d080368c04f7467c44f1d0a2e3de8c25663de46c1eaeef21d6ef9e33a`)
and its independent-inspection artifact 10193628393 (SHA-256
`ba481092a93ccc22ad942001b80fe8967942abbbd8ebe1b09c83148cb6f78228`)
were downloaded and independently re-evaluated. The retained manifest binds all 167
members; two Stage 3 payloads are equal, 166 focused and 219 compatibility tests pass,
all 1,924 statements and 614 branches are covered, and all 24 mutations fail by
assertion. `evidence/part3-stage5/athena-head-broader-inspection.json` records the
admission gate. This evidence admits the Glue successor increment; it does not prove
that successor before exact-head CI.

## Glue successor and terminal ownership increment

The next successor keeps the accepted Stage 3 business computation byte-frozen and
adds an explicit Stage 5 Glue entrypoint and candidate writer. Terraform supplies the
complete release identity as non-overridable job arguments: source commit and tree,
release-manifest and runtime-package digests, script key/digest, and both dependency
wheel keys/digests. The adapter requires every value, rejects duplicates and unknown
arguments, binds the workload bucket and operation-derived job name, and keeps the
presence-only metrics flag correction described below.

Candidate manifest and completion-marker schema version 2 bind the exact Glue job-run
identity. The control-plane verifier requires the retained start arguments, first
attempt, no predecessor, `SUCCEEDED`, no error, exact effective Glue 5.1/G.1X/two-worker
configuration, bounded wall/execution/DPU use, and the candidate's identical job-run
identity. Ambiguous start recovery only discovers one existing exact-argument run in
a five-minute window with bounded pagination; it never authorizes a blind second
start. This increment performs no Glue run and makes no AWS call.

Two immutable-input local workspaces each passed 359 tests, all 1,380 statements and
584 branches at 100% with zero exclusions, and all 42 source mutations were killed by
assertion. `evidence/part3-stage5/glue-ownership-local.json` retains the source-bound
LOCAL_VERIFIED receipt and truthfully records the dirty pre-commit working tree.
An initial trial exposed mutation-process module reuse when equal-size source writes
shared a filesystem timestamp; every mutant now receives a new byte-identical
workspace and deterministic hash seed. Both full campaigns then produced identical
test, coverage and mutation results without changing an acceptance threshold.

The exact published Glue successor head
`5aac335cea1700b4d6f848ba5a175e6d730cfdf9`, tree
`29889ede103b4ad2b373ffe2d95946c7c774e401`, passed all three pull-request
workflows. Native run 34591074547 passed both independent jobs. Its artifacts
10195703295 (SHA-256
`95400d58debb395ba06598ddbfbd593dc48b5f8794051d9e869eb98d77f3b9a8`) and
10195688900 (SHA-256
`db32ab130b4476516daf3aeaac60a11bd287b2a33b187f0d0f9a9e3e8f3d9f43`)
were independently downloaded and revalidated: Terraform 1.13.1 validation,
zero TFLint issues, 388 tests, 26 killed mutations, complete control and critical
coverage, equal normalized payloads, and all four source-bound Trivy decisions
with zero unreviewed findings. Incremental run 34591074560 artifact 10196328385
(SHA-256
`99debdcb7158747bb9565ec31db3f49bd0ee261fc49895f48e06b4b0deecca8e`)
independently binds two clean 359-test, 1,380-statement, 584-branch and
42-mutation campaigns to that head. Broader run 34591074564 passed all six jobs;
its Stage 3 producer and inspection artifacts were independently re-evaluated at
SHA-256 `b9b240fa1bf3a9ff98224592796bfd4693e7cc083ed5d3a77ea00569a376f82a`
and `f9d7bea7e7771d23b057546888239a68dc093bd80dd0ed9bb3c09034345e8c9c`.

## AWS Athena observation and retained proof increment

The next successor strictly normalizes an already-started Athena execution and
consumes its complete bounded result-page token chain. It neither starts a query
nor calls AWS during qualification. Missing, mistyped, substituted and unknown
execution/result fields fail closed; response identity must match the requested
query execution exactly.

The persisted query proof is canonical and content-addressed under
`publications/query-proofs/`, outside transient run lifecycle. It independently
binds the exact query bytes and digest, family, execution identity, engine,
workgroup, result URI, expected AWS account owner, SSE-S3 encryption, terminal
success, scanned bytes, execution time, result bytes, exact aggregate rows and
both candidate version inventories. Repeated persistence is idempotent, while
any body difference creates a distinct immutable identity.

Two immutable-input local workspaces each passed 405 tests. All 1,495 statements
and 636 branches are covered at 100% with zero exclusions, and all 53 source
mutations were killed by assertion in both campaigns. The first strengthened
trial correctly rejected a redundant SQL comparison mutation; the gate now
targets the single SHA-256 exact-byte binding instead of accepting an equivalent,
untestable branch. `evidence/part3-stage5/athena-aws-local.json` retains the final
source-bound LOCAL_VERIFIED receipt, records zero AWS calls and keeps
`stage5_complete` false. Exact successor CI and independent artifact inspection
remain required.

## Exact Athena-proof head and production workflow increment

The exact published Athena-proof head
`9afb0570ba26ab5ba1c939c79be414d7b3092cfb`, tree
`53a3980ea495aedac572817be99ca4969e994377`, passed all three pull-request
workflows. Native run 34602995559 passed both independent jobs. Artifacts
10265515905 (SHA-256
`e4bcf67a55004f4303dc803e7d76dad6bc18a4c7c8d8e2da82d44c90239676d1`)
and 10265675836 (SHA-256
`72947316e228211fe6496d6e724c0b32554d1fdbb1bdaaffed478bf6075dd080`)
were independently downloaded and revalidated: exact commit/tree binding,
Terraform 1.13.1 validation, zero TFLint issues, 388 tests, 26 killed
mutations, complete 478/226 control and 742/292 critical statement/branch
coverage, equal normalized payloads, and all four source-bound Trivy decisions
with zero unreviewed findings.

Incremental run 34602995189 artifact 10264734895 (SHA-256
`3262fc991f68a7bd36ca396244d11f7f193d7155fb9268d0e097d27d125063c0`)
independently binds two clean 405-test, 1,495-statement, 636-branch and
53-mutation campaigns to that exact head. Broader run 34602995168 passed all
six jobs. Its Stage 3 producer artifact 10265439362 (SHA-256
`80673837aed47615bf350cd65decb3a92b37c291ed596812d392c982b9e4df5b`)
and inspection artifact 10264804887 (SHA-256
`c2a4628e63b5ad78448a487b35a932d9a5e96cba04d25db6d03e2ad1ae458318`)
were independently checked: 167 manifest-bound members, equal two-run
payloads, 166 focused and 219 compatibility tests, 1,924 statements and 614
branches at 100%, and all 24 mutations killed. No AWS call or mutation occurred.

The next successor renders the real Standard Workflow for one closed operation
identity in the frozen account and region. It uses exact direct Lambda ARNs,
optimized `StartJobRun.sync`, and three separately partition-confined
`StartQueryExecution.sync` tasks with deterministic idempotency tokens. The
ordered success path cannot bypass input validation, durable registration,
Glue, physical/financial candidate validation, all three query proofs,
preparation or conditional authority publication. A committed replay terminates
without running a workload.

Lambda and Athena retries are limited to named transient service errors with
capped exponential backoff. Glue start has no blind retry because Glue exposes
no start idempotency token. Every task catches its original error and cause into
the untouched pointer-only state before the dedicated failure recorder; early
failure handling deliberately does not select optional paths that do not yet
exist. Static admission proves complete reachability, exact task resources,
bounded retries, explicit failure ownership and the exact success chain.

Two immutable-input local workspaces each passed 431 tests. All 1,623 statements
and 698 branches are covered at 100% with zero exclusions, and all 57 source
mutations were killed by assertion in both campaigns. The exact receipt is
`evidence/part3-stage5/workflow-local.json` (SHA-256
`abee8a4aafc0f3b1b706c6aa5fa453c4a04dd2363ca071b5bf8b8c468a1c904d`).
It truthfully records zero AWS calls, a dirty pre-commit tree and
`stage5_complete: false`. AWS definition validation, concrete controller and
validator entrypoints, installed release/SBOM qualification, operational AWS
authority transports and the complete final gate remain outstanding.

## Historical first increment

The control package now implements bounded strict JSON and seven draft versioned
control-document shapes; execution/release admission; an enumerated Glue argument
adapter; canonical managed marker and physical inventory checks; durable local
object versions; and a paginated, streaming, version-specific S3 read adapter.

Source input `source_commit` preserves the frozen manifest's provenance.
`runtime.source_commit` independently identifies the runtime release; the adapter
requires `--runtime-source-commit` to agree with trusted release provenance.
The existing `source_tree` and runtime package digest bind the runtime release.
The external release manifest is hash-pinned by deployment authority and verifies
actual script/archive bytes, avoiding a self-referential archive hash. This does
not yet qualify the release archive contents, SBOM, installed modules or handlers.

Candidate checks reject unknown/hidden files, missing or multiple markers,
noncanonical marker bytes, wrong attempt identities, wrong completion links,
extra/missing physical files, size/digest differences and all overwrite/deletion
history in the attempt. Version-specific references survive latest-version changes.
Repeated inventories expose overwrite-and-restore events. These are physical
integrity checks; independently computed financial truth, terminal Glue ownership,
query comparisons and protected publication remain mandatory and unimplemented.
Opaque byte test vectors are not represented as Parquet or live reconciliation.

The local backend commits actual SQLite transactions with FULL synchronization;
it is not an AWS persistence emulator. AWS transport tests are request/response
contract tests only. No new managed workload or AWS mutation has occurred.

## Glue metrics correction and scoped review

The inherited Terraform default encoded `--enable-metrics` with value `true`.
The [AWS job-parameter reference](https://docs.aws.amazon.com/glue/latest/dg/aws-glue-programming-etl-glue-arguments.html)
states that this is a presence-based flag and should have no value. The successor
keeps the flag enabled with an empty map value; the adapter accepts the standalone
flag or that empty value, and rejects `true`, `false`, duplicates and omission.
Other configured metrics/observability settings and all resource/IAM/budget limits
are unchanged. The resource expectation is corrected to enforce this exact service
encoding. No resource control is removed and the 33-address scope remains intact.

The compute/resource-contract source bindings in the security review are renewed
for this reviewed one-value correction. All four existing finding decisions,
scanner identity, invalidation rules and full native scanning gates remain intact.
Fresh native CI scanning is required before acceptance; historical raw scanner
output is not presented as a fresh scan of this successor.

## Qualification and outstanding work

The current authority-transport successor passed the 465-test, 1,848-statement,
790-branch and 64-mutation two-workspace qualification recorded below. All 388 inherited Stage 4
tests also passed when supplied the actual accepted runtime and CI artifact; the
additional test enforces the expanded non-overridable release identity. Ruff and
strict mypy passed. These local results do not replace native Terraform/TFLint/Trivy
CI or complete Stage 5 acceptance.

`python -m tools.run_part3_stage5_incremental --output <new-directory>` runs two
isolated source workspaces, complete coverage of every current control module,
and 64 actual source mutations using the accepted JUnit failure verifier. Every
mutant runs in its own newly populated workspace to prevent interpreter/import
state from one fault from affecting the next.
An increment receipt explicitly reports `stage5_complete: false` and records
whether its source checkout was dirty. This is not the final Stage 5 gate runner.

Remaining S5-G01 work: build and qualify the installable release, provenance/SBOM and
the final producer/consumer inventory against those exact release bytes.
Remaining S5-G02 work: concrete handlers and binding the independently compared
Parquet truth, terminal Glue receipt and complete Athena proofs to publication.
Remaining S5-G03 work: connect the operational DynamoDB/S3 transports through the
handlers, preserve complete end-to-end Part 2 replay/correction/scope semantics,
and complete process-crash, concurrency, ambiguous-response and effective-permission
qualification. Local and AWS transport contracts do not by themselves close S5-G03.
Remaining S5-G04 work: retries/failure ownership/recovery, packaging/SBOM, complete
critical gate-tool coverage and mutations, exact-head/main acceptance and read-only
AWS `ValidateStateMachineDefinition` receipt. Stages 6–8 remain unadmitted.

Administrator IAM installation is deferred until the final release is qualified.
Organization/SCP/session restrictions remain unknown, and effective successor
permissions remain unverified. The approved combined authorization remains in force.

## Exact workflow head and AWS authority transport increment

The production-workflow head `04650344e709281339322c1c5c9a8f70b061eb99`,
tree `86c95387e9ae639abf5597ce152598b3e31e2960`, passed all three
pull-request workflows. Native run 34610710910 produced independently equal
artifacts 10268410667 (SHA-256
`25b73676117cdee0f91697f29ed15bb0f137f4d228d4269d092974a47ad9c48c`)
and 10268810387 (SHA-256
`837a7b5aa149fa23ee18cf95f8e44a1777a095817d16dc5003ee0be487452d1c`).
Independent inspection bound Terraform 1.13.1 validation, zero TFLint issues,
388 tests, 26 killed mutations, 478/226 control and 742/292 critical
statement/branch coverage at 100%, and the four exact source-bound Trivy
applicability decisions with zero unreviewed findings.

Incremental run 34610710948 artifact 10270085641 (SHA-256
`e118ae0349749a7924264b0f889e1c481c1f782c04fb46bf3d2dc840806e913f`)
independently binds two clean 431-test, 1,623-statement, 698-branch and
57-mutation campaigns. Broader run 34610710929 passed all six jobs. Its Stage 3
producer artifact 10268979087 (SHA-256
`163b867671d2738473d7f3a0d70e4a29280f40743bc96d467d3adc1c28b41e40`)
and inspection artifact 10269530464 (SHA-256
`3f84346ceb03df4c684b351852b083d0269a6b1b4c32a9ac0d8a81b9fefda05a`)
were independently checked: 167 manifest-bound members, equal two-run payloads,
166 focused and 219 compatibility tests, 1,924 statements and 614 branches at
100%, and all 24 mutations killed. No AWS call or mutation occurred.

The next successor supplies fail-closed transport adapters for immutable S3
publication objects and DynamoDB authority state. S3 publication uses conditional
creation, SHA-256 checksum binding, bounded version-history inspection, exact
version reads and byte-for-byte replay verification. DynamoDB registration,
attempt admission, monotonically increasing fences, failure ownership and the
fixed four-item namespace-root publication transaction use conditional writes and
strongly consistent reads. Ambiguous outcomes are accepted only after exact
terminal-run and reachable-commit verification. Stateful transport tests are
contract tests, not managed-service evidence.

This work exposed a real least-privilege defect: the controller table policy
permitted item operations but omitted `dynamodb:TransactWriteItems`, which the
already accepted four-item protocol requires. The action is added only to the
existing control-table resource statement, and the resource-control and
security-review hash bindings are renewed. This does not install or prove the
separate administrator IAM boundary; final release and administrator qualification
remain required.

Two immutable-input local workspaces each passed 465 tests, all 1,848 statements
and 790 branches at 100% with zero exclusions, and all 64 non-equivalent source
mutations were killed by assertion in both campaigns. An initial trial correctly
identified an equivalent deletion-history mutation because independent size/latest
checks rejected the same states; it was replaced with a distinct AWS read-back
byte-integrity mutation. No production check or acceptance threshold was removed.
`evidence/part3-stage5/aws-authority-local.json` retains the LOCAL_VERIFIED receipt
(SHA-256
`e2c825688894e4dae542fde742e2ffac2a82e089e0be810cb7ae31ef047f5ca3`),
records zero AWS calls and keeps `stage5_complete` false. Exact successor CI and
independent artifact inspection remain required.

## Exact authority head and first concrete handler transitions

The exact published authority head
`e0bfaf7aef1888c4c227dbd65561445191ec0a16`, tree
`7ff8a370a1dfa115e7a2bc3f2f09ef31cd5079fa`, passed all three pull-request
workflows. Native run 34685612622 passed both independent jobs. Its artifacts
10295591371 (SHA-256
`b38b6d7ff4ea2c1f4087e0cc14d2e111215182ab7a10b6bc265686992e3ef034`)
and 10295671196 (SHA-256
`b27ce1bcc35301453ae537bca6b0b1418bfd450446a7dce7c36803e59f440528`)
were independently downloaded and revalidated: exact commit/tree binding,
Terraform 1.13.1 validation, zero TFLint issues, 388 tests, 26 killed
mutations, 478/226 control and 742/292 critical statement/branch coverage at
100%, equal normalized payloads, and all four source-bound Trivy decisions
with zero unreviewed findings.

Incremental run 34685612621 artifact 10295987461 (SHA-256
`ecd723814e3f79a65da673190048c4b12469d65531cfe91788676171ce60c00c`)
independently binds two clean 465-test, 1,848-statement, 790-branch and
64-mutation campaigns to that exact head. Broader run 34685612631 passed all
six jobs. Its Stage 3 producer artifact 10296046508 (SHA-256
`c2dd14ea46f789a9269063900f06e179834644e0e8b8905c45bc8730615a1666`)
and inspection artifact 10296135246 (SHA-256
`d1234887aea2e3c34245d3ba25334cf448436d78b4ea3b516a923b8371d81734`)
were independently checked: 167 manifest-bound members, equal two-run
payloads, 166 focused and 219 compatibility tests, 1,924 statements and 614
branches at 100%, and all 24 mutations killed by assertion. No AWS call or
mutation occurred.

The next successor adds the first concrete controller transitions. The handler
configuration is deployment-digest-bound to one versioned execution input and
one qualified runtime release. Validation streams and verifies that exact input,
reuses the accepted admission boundary, rejects a different operation bucket,
and renders the closed Glue start plus three separately confined Athena requests
with distinct deterministic service tokens. Registration accepts only the
validated pointer state, creates a durable owner/fence through the authority
interface, and terminates exact committed replays before any managed workload.
These transitions use genuine durable SQLite versions and authority in local
qualification; they are not presented as live AWS evidence or as complete Lambda
entrypoints.

Two immutable-input local campaigns each passed 480 tests. All 1,964 statements
and 832 branches are covered at 100% with zero exclusions, and all 69 source
mutations were killed by assertion in both campaigns. The complete campaigns
finished before a vanished external Git-worktree administration directory caused
the receipt writer's final metadata lookup to fail. Their raw JUnit, coverage and
mutation outputs were independently compared; the retained
`evidence/part3-stage5/execution-handlers-local.json` binds the verified GitHub
base head/tree and truthfully records the successor workspace as dirty. The
incident did not alter test inputs, results or gates. Exact successor CI and
independent artifact inspection remain mandatory; Stage 5 is not complete.

## Exact handler head and independently derived Athena expectations

The exact published handler head
`94a185d0a3b76a967ddecb2b5dc497413b3cf6ab`, tree
`426595ed747863c3e0f35d9e3e80d1472877e167`, passed all three pull-request
workflows. Native run 34688818944 passed both independent jobs. Its artifacts
10297180433 (SHA-256
`e87a74538539e002324d2871c38af913d9a1e5361035612f4decd22d468e575e`)
and 10296620897 (SHA-256
`ba2f45f743a7b1969d0eced47138c3f04da37b3c71017fa626692bce7c7413c6`)
were independently downloaded and revalidated: exact commit/tree binding,
Terraform 1.13.1 validation, zero TFLint issues, 388 tests, 26 killed
mutations, complete 478/226 control and 742/292 critical statement/branch
coverage, equal normalized payloads, and all four source-bound Trivy decisions
with zero unreviewed findings.

Incremental run 34688818943 artifact 10296638330 (SHA-256
`eff9549d7142e74ae1cf579e868f8faaf775af38489f759feefd2c085b02a0b7`)
independently binds two clean 480-test, 1,964-statement, 832-branch and
69-mutation campaigns to that exact head. Broader run 34688818947 passed all
six jobs. Its Stage 3 producer artifact 10296956781 (SHA-256
`bbd3cecfc73b2aa2893f41079a96129256e72af75bfda725012f55e948cf22dd`)
and inspection artifact 10296936869 (SHA-256
`fc7b7778bdba5fda8017ddcaebed23253a97e97d87707bea9ad9fbbd7e8a7523`)
were independently checked: 167 manifest-bound members, equal two-run
payloads, 166 focused and 219 compatibility tests, 1,924 statements and 614
branches at 100%, and all 24 mutations killed by assertion. This exact head is
therefore admitted for the next Stage 5 increment.

The successor now derives each expected Athena summary directly from the same
externally admitted canonical financial-row evidence used for exact Parquet
comparison. It streams and validates the entire mixed-family file, including
non-selected families, and verifies its complete trusted digest before success.
Grouping follows the fixed SQL currency/status-or-disposition/reason dimensions;
all counts and amounts remain exact integers and bank-allocation naming is mapped
explicitly. The 1,000,000-row, 256 MiB input and 4,096-group bounds fail closed.
Tests include values above 2^53, complete-inventory substitution, family filtering,
bank allocation mapping and every new input bound.

Two immutable-input local campaigns each passed 492 tests. All 2,014 statements
and 854 branches are covered at 100% with zero exclusions, and all 71 source
mutations were killed by assertion in both campaigns. The recovered worktree's
Git administration path was unavailable, so the qualifier now accepts an explicit
pair of independently verified full base commit/tree object IDs for local successor
trials, records such a trial as dirty, and retains unchanged exact-Git discovery in
CI. Its fail-closed metadata contract is tested. The source-bound receipt is
`evidence/part3-stage5/expected-summary-local.json`; it records zero AWS calls and
keeps `stage5_complete` false. Exact successor CI remains required.

## Exact expected-summary head and initial Lambda entrypoints

The exact published expected-summary head
`e6228bfe9c2a9073bf05f7f741fad59e0db5bfc4`, tree
`124689500195d297b2b50543b9e1eb789ba06792`, passed all three pull-request
workflows. Native run 34692144685 passed both independently inspected jobs. Its
artifacts 10298070423 (SHA-256
`684af95493443f431ed2929277faea9130d01689a57191e64aca25be1cd92adc`)
and 10297730229 (SHA-256
`2c7598529306b5355c1573c2439fad6a4202e0c80643a9e76d3ff96a053e254c`)
were independently downloaded and revalidated: exact commit/tree binding,
Terraform 1.13.1 validation, zero TFLint issues, 388 tests, 26 killed
mutations, complete 478/226 control and 742/292 critical statement/branch
coverage, equal normalized payloads, and all four source-bound Trivy decisions
with zero unreviewed findings.

Incremental run 34692144669 artifact 10297762673 (SHA-256
`4c94353475c5512261f8f6f2d9ccfc1eeb0275af9d2cca212b68d1665d987f81`)
independently binds two clean 492-test, 2,014-statement, 854-branch and
71-mutation campaigns to that exact head. Broader run 34692144672 passed all
six jobs. Its Stage 3 producer artifact 10297372015 (SHA-256
`6e6e3f65209f55d5f77e4c3695d67e87cec1e9aa305032155ed999199683c9d7`)
and inspection artifact 10297926849 (SHA-256
`771a4316318a9da8c0cfabc8658fb4cb3dcb916bdf5b963385445262c32d6d36`)
were independently checked: 167 manifest-bound members, equal two-run
payloads, 166 focused and 219 compatibility tests, 1,924 statements and 614
branches at 100%, and all 24 mutations killed by assertion. No AWS call or
mutation occurred. This exact head is admitted for the next Stage 5 increment.

The successor adds the initial concrete Lambda module entrypoints. Deployment
configuration is read only from canonical JSON with its independent SHA-256,
then cross-checked against the operation-derived workload bucket and control
table. AWS client construction is confined to S3 or DynamoDB in
`ap-southeast-2`. The validator accepts only the implemented
`validate-execution` action and uses the paginated immutable S3 adapter; the
controller accepts only `register-run` and uses the durable DynamoDB authority.
All other actions fail before configuration or transport access. These are real
entrypoints for the two implemented transitions, not a claim that the remaining
workflow actions or release package are complete.

Two immutable-input local campaigns each passed 509 tests. All 2,069 statements
and 866 branches are covered at 100% with zero exclusions, and all 76 source
mutations were killed by assertion in both campaigns. Ruff and strict mypy pass.
The source-bound receipt is
`evidence/part3-stage5/lambda-entrypoints-local.json`; it records zero AWS calls,
the admitted base commit/tree, a dirty successor workspace, and keeps
`stage5_complete` false. Fresh exact-head CI and independent artifact inspection
remain mandatory.

## Exact entrypoint head and separate attempt admission

The exact published entrypoint head
`97c0578cb5a5ca6e29e0edfe1946da4347fcea29`, tree
`c398b7e124ebb6327e969864fd3023f1fd80b9e4`, passed all three pull-request
workflows. Native run 34695749249 passed both independent jobs. Its artifacts
10299170341 (SHA-256
`a23dd25a1e90b9be5b4ae9152e2397aebf5e496df4afe76a62c00a41c2fcaae9`)
and 10297803965 (SHA-256
`56db0324f58eb0e91cf30700f0981d2235fcb367f7a948e6db3d805461f6fcd5`)
were independently downloaded and revalidated: exact commit/tree binding,
Terraform 1.13.1 validation, zero TFLint issues, 388 tests, 26 killed
mutations, complete 478/226 control and 742/292 critical statement/branch
coverage, equal normalized payloads, and all four source-bound Trivy decisions
with zero unreviewed findings.

Incremental run 34695749236 artifact 10298504697 (SHA-256
`c0218de65e40f5f013e3effbe19b2d1c54f8c479a83c43a72d4b49c06602169b`)
independently binds two clean 509-test, 2,069-statement, 866-branch and
76-mutation campaigns. Broader run 34695749247 passed all six jobs. Its Stage 3
producer artifact 10298369630 (SHA-256
`ae359cdd4a0c3a2e8a5eb3147163578859b5f3ece8a0698ef4f4314c7b7be39e`)
and inspection artifact 10298164800 (SHA-256
`755cbdaee6a7a279a8dc440e11711d304a5b34217eea31c118efadafd43879b0`)
were independently checked: 167 manifest-bound members, equal two-run
payloads, 166 focused and 219 compatibility tests, 1,924 statements and 614
branches at 100%, and all 24 mutations killed. No AWS call or mutation occurred.
This exact head is admitted for the next Stage 5 increment.

The successor separates immutable run registration from attempt admission as
required by the approved workflow contract. `RegisterRun` now only creates or
verifies the immutable run identity and predecessor, or proves an existing
committed replay. Its choice state terminates that replay before any managed
work. A distinct `AdmitAttempt` Lambda action then allocates or replays the exact
execution-owned fence before Glue. It rejects committed replays, substituted
namespace/predecessor values and states that already contain an attempt. This
preserves same-step redelivery while preventing a registration result from
silently performing the separately ordered authority transition.

Two immutable-input local campaigns each passed 510 tests. All 2,090 statements
and 876 branches are covered at 100% with zero exclusions, and all 79 source
mutations were killed by assertion in both campaigns. Ruff and strict mypy pass.
The source-bound receipt is
`evidence/part3-stage5/attempt-admission-local.json`; it records zero AWS calls,
the admitted base commit/tree, a dirty successor workspace, and keeps
`stage5_complete` false. Fresh exact-head CI and independent artifact inspection
remain mandatory.

## Complete candidate-validation transition

The successor implements the production `ValidateCandidate` Lambda boundary.
It re-reads and re-admits the deployment-pinned execution input before trusting
workflow state, requires the exact `StartJobRun` response shape and execution-owned
attempt fence, and then independently observes the terminal Glue run. The terminal
receipt binds the job name, run ID, exact start arguments, effective Glue 5.1/G.1X
configuration, timestamps, execution seconds and DPU seconds. The handler performs
only Glue and S3 control-plane reads; it cannot start a job.

The same transition reopens the complete candidate version history, rejects
overwrites, deletion history, hidden objects and physical inventories over 256 MiB,
and streams each exact Parquet version into an isolated workspace. Real Arrow
schemas, every financial row, exact integers above 2^53, row identities, deltas and
family inventories are compared against the independently admitted canonical
financial JSONL. The candidate version inventory is checked again after comparison,
closing the read/compare race. Canonical physical-inventory and validation-receipt
objects are created or exactly replayed under `publications/validation-receipts/`,
outside the transient `runs/` lifecycle. This is local and transport evidence, not
a claim of live workload execution or effective AWS permission.

Two immutable-input local campaigns each passed 535 tests. All 2,204 statements
and 916 branches are covered at 100% with zero exclusions, and all 86 source
mutations were killed by assertion in both campaigns. Ruff and strict mypy pass.
The source-bound receipt is
`evidence/part3-stage5/candidate-validation-local.json`; it records zero AWS calls,
the admitted base commit/tree, a dirty successor workspace, and keeps
`stage5_complete` false. Fresh exact-head CI and independent artifact inspection
remain mandatory.

## Complete ordered Athena-query validation transitions

The successor now implements all three production query-validation Lambda
boundaries. Each transition re-reads and re-admits the deployment-pinned
execution input, immutable registration, terminal Glue validation receipt and
complete physical candidate inventory before it trusts workflow state. Query
families must arrive once and in the fixed transactions, settlements and
bank-allocations order; every earlier retained proof is reopened and its exact
identity is reverified before the next query can be admitted.

The validator only observes an already-completed Athena execution. It derives
the expected aggregate rows independently from the admitted canonical financial
JSONL, then verifies the fixed SQL, workgroup, engine, account owner, SSE-S3
configuration, terminal status, scan/time bounds and every bounded result page.
The exact versioned result CSV must be the sole non-deleted object at its
deterministic result URI, remain at or below 8 MiB and retain unchanged version
history before and after streaming. Candidate versions are also checked again
after observation. The canonical proof body is content-addressed below
`publications/query-proofs/`, outside the transient run lifecycle. No query is
started by this code.

Two immutable-input local campaigns each passed 552 tests. All 2,351 statements
and 978 branches are covered at 100% with zero exclusions, and all 93 source
mutations were killed by assertion in both campaigns. The mutation runner merely
places each mutation's detecting test file first while retaining the exact full
17-file test inventory; it rejects any missing or changed inventory. One prior
local attempt was externally terminated after 78 killed mutations and emitted no
receipt, so it was not admitted. The complete source-bound receipt is
`evidence/part3-stage5/query-validation-local.json` (SHA-256
`afe8fe88e5b426cd0d635500e44513ba5273368262c88b48202bd1ccbdffd5d7`).
It records zero AWS calls, the admitted base commit/tree, a dirty successor
workspace and `stage5_complete: false`. Fresh exact-head native, incremental and
broader compatibility CI plus independent artifact inspection remain mandatory.

## Attempt-owned terminal failure transition

The successor now implements the production `RecordFailure` Lambda boundary for
the seven states that execute after attempt admission: `StartGlue`,
`ValidateCandidate`, the three ordered query states, `PreparePublication` and
`PublishAuthority`. Failures before a fence exists still terminate through the
workflow's explicit `FailureEvidenceUnavailable` path and cannot fabricate
attempt-owned evidence.

The handler re-reads and re-admits the deployment-pinned execution input before
trusting workflow state. It requires the exact caught error, cause, failed state,
immutable registration identity, execution-owned attempt fence, managed Glue
identity and fixed-family Athena identities already present at the failure point.
It creates or exactly replays a canonical content-addressed
`ledgerguard.failure-record.v1` below `publications/failure-records/`, outside the
transient `runs/` lifecycle, before it performs the fenced authority transition.
The local and DynamoDB authorities accept a retry after an ambiguous response only
when strongly consistent reads prove the exact failed attempt and released run
postcondition; every mismatch is rejected.

Two immutable-input local campaigns each passed 573 tests. All 2,460 statements
and 1,018 branches are covered at 100% with zero exclusions, and all 97 source
mutations were killed by assertion in both campaigns. Ruff and strict mypy pass.
The source-bound receipt is
`evidence/part3-stage5/failure-ownership-local.json` (SHA-256
`3090f63d8a669a65ff3df6e0ea78682878dd614c1d663a4f200be55df2759d64`).
It records zero AWS calls, admitted base head
`8eeca0a0f9001cb5855e560d9bfbab5c8908a292`, base tree
`ea070ed4abeef4fba57cfbc7c6e766d8169ca307`, a dirty successor workspace and
`stage5_complete: false`. Fresh exact-head native, incremental and broader
compatibility CI plus independent artifact inspection remain mandatory.

## Installable release and deployment wiring increment

The successor now has one deterministic release builder and an independent release
inspector. The builder first verifies every installed distribution file against its
wheel `RECORD`, then emits a project wheel, an offline Glue 5.x wheel bundle, and a
root-layout Lambda runtime. The Glue bundle contains the project wheel plus the exact
six `jsonschema` dependency wheels. The Lambda runtime contains the project,
`jsonschema`, NumPy 2.1.3 and PyArrow 17.0.0, including the native Parquet extension.
The release excludes tests, generators, reference-oracle code and qualification
expectations. A clean isolated import test installs only the offline Glue bundle; a
separate `python -S` test imports only the Lambda runtime and writes and reads genuine
Parquet containing an integer above 2^53.

The release manifest binds every package digest and size, the handler configuration,
exact Standard Workflow definition and Terraform deployment inputs. SPDX 2.3,
license inventory and SLSA-style provenance are emitted alongside the artifacts and
cross-bound by the release bundle. Terraform passes the complete digest-pinned
handler configuration to both Lambda functions. Validation limits the environment
payload and binds its hash, operation identity, exact versioned input reference and
release package identities. The CI workflow builds and inspects the release twice,
compares every output byte, and retains a separate exact-head release artifact.

The cross-installer local qualification release is 45,431,809 bytes. Its Lambda runtime
is 45,068,343 compressed bytes, 150,325,765 expanded bytes and 629 members, within
the AWS deployment limits. The release-bundle SHA-256 is
`c157fbb7e700724ee0211a54de97b6e89c4ff466ae46702e0836a473a26c30d3`;
the runtime SHA-256 is
`29195652dc66ab6b2c32b1559f023c17d82811f7fba21e006cdb71002b2c13ee`.
These hashes bind the local synthetic qualification input and are not yet final
exact-head release identities.

The production archives exclude generated bytecode and installer-specific metadata;
independent pip- and uv-created environments produced byte-identical release bytes.
Two immutable-input local campaigns each passed 626 tests. All 2,710 statements and
1,104 branches are covered at 100% with zero exclusions, and all 111 source mutations
were killed by assertion in both campaigns. Ruff and strict mypy pass. The source-
bound receipt is `evidence/part3-stage5/installable-release-local.json`; it records
zero AWS calls, the admitted base head `d8cf72d778078a1793e3c18a7892cbe8eb233f64`,
base tree `37f1acffc108d64c9c2e986a38f92f8550f64ae3`, a dirty successor
workspace and `stage5_complete: false`. Exact-head native, Stage 5 and broader CI,
independent inspection of every raw artifact, final squash merge, exact-main CI and
the exact-main read-only `ValidateStateMachineDefinition` receipt remain mandatory.

## Complete successful preparation and authority transitions

The successor now implements the two production controller actions on the
workflow's successful path. `PreparePublication` first re-admits the deployment-
pinned execution, terminal Glue receipt, all three ordered Athena proofs, exact
versioned input inventory and every Part 2 source byte. It independently runs the
accepted transaction and settlement reconciliation over those inputs and requires
the resulting financial rows to equal the previously admitted expected evidence
before advancing the accepted `FinalizationStore`. Any accepted correction is
passed through with its exact source context. The full requests, outcomes, commit
ancestry, proofs, cases and source states are sealed into an immutable paged
snapshot without selecting it as authority.

`PublishAuthority` re-admits the complete successful state, final Athena proof,
input inventory and canonical preparation receipt. Before its four-item metadata
CAS it restores the exact candidate snapshot into a fresh directory, verifies all
financial history and checks the attempt outcome, financial head and proof/case
counts. It then publishes using the existing fenced namespace-predecessor CAS,
requires the exact strongly read metadata commit, and restores the snapshot again
through the committed root. Exact redelivery returns the same commit and immutable
publication receipt. Substituted phase state, proofs, input inventory, preparation
identity, snapshot history and either postcondition fail closed. The controller
uses only the packaged digest-bound contract root and the scoped S3/DynamoDB
adapters. These tests use durable local transports; they do not claim live AWS
permission or mutation.

Two immutable-input local campaigns each passed 619 tests. All 2,710 statements
and 1,104 branches are covered at 100% with zero exclusions, and all 111 source
mutations were killed by assertion in both campaigns. Ruff and strict mypy pass.
The source-bound receipt is
`evidence/part3-stage5/success-publication-local.json` (SHA-256
`868e03881d8f90a62b7b0496a2e448a226529a8e763e29949f5a377b40d6da4b`);
it records zero AWS calls,
admitted base head `17e47689e47a4c28f6deb1cc33ca6b93d38b00d8`, base tree
`aa4fdd03f2ac117c03abdda565582e3157cfe271`, a dirty successor workspace and
`stage5_complete: false`. Fresh exact-head native, incremental and broader
compatibility CI plus independent artifact inspection remain mandatory.
