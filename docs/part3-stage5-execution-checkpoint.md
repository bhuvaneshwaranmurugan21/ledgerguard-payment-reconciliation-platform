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
mutations. Broader exact-head compatibility remains a publication gate for this
successor and is not preclaimed.

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

The current increment passed 153 tests in each of two fresh workspaces, all 12
source mutations were killed twice by assertion failures, and all 465 statements /
190 branches in the seven control modules were covered with zero exclusions.
All 387 inherited Stage 4 tests also passed when supplied the actual accepted
runtime and CI artifact. Ruff and strict mypy passed. These local results do not
replace native Terraform/TFLint/Trivy CI or complete Stage 5 acceptance.

`python -m tools.run_part3_stage5_incremental --output <new-directory>` runs two
isolated source workspaces, complete coverage of every current control module,
and twelve actual source mutations using the accepted JUnit failure verifier.
An increment receipt explicitly reports `stage5_complete: false` and records
whether its source checkout was dirty. This is not the final Stage 5 gate runner.

Remaining S5-G01 work: concrete producers/consumers for every contract; independently
validated input/expectation material; installed release provenance and adapter wiring.
Remaining S5-G02 work: real ASL/handlers; independently read Parquet financial truth;
exact bounded SQL and complete Athena proof consumption; writer ownership and race
analysis; immutable publication copies outside the seven-day `runs/` lifecycle.
Remaining S5-G03 work: operational registration/attempt AWS adapters, binding the
validated run and financial preparation to publication, complete end-to-end Part 2
replay/correction/scope semantics, AWS reader transport contracts and full recovery
qualification. Local metadata and paged financial snapshot foundations are implemented
above; they do not by themselves close S5-G03.
Remaining S5-G04 work: retries/failure ownership/recovery, packaging/SBOM, complete
critical gate-tool coverage and mutations, exact-head/main acceptance and read-only
AWS `ValidateStateMachineDefinition` receipt. Stages 6–8 remain unadmitted.

Administrator IAM installation is deferred until the final release is qualified.
Organization/SCP/session restrictions remain unknown, and effective successor
permissions remain unverified. The approved combined authorization remains in force.
