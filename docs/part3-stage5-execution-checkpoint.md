# Part 3 Stage 5 execution checkpoint

Stage 4 is externally accepted at squash
`7036a1557f815a0aaea9d635278cc687297d6214`, tree
`ebf620bbf3a345a6b1c985820679837612805fe3` (PR #27).
Native main run 34565883871 and all six jobs in broader main run 34565883880 passed.
Both native artifacts and the broader Stage 3 producer/inspection artifacts were
downloaded and independently inspected before this Stage 5 branch was admitted.

## Current increment

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
Remaining S5-G03 work: registration, attempt/fence, fixed-size DynamoDB CAS,
full accepted Part 2 replay/correction/scope semantics, durable reader/index paging,
concurrent and process-crash qualification and ambiguous-response recovery.
Remaining S5-G04 work: retries/failure ownership/recovery, packaging/SBOM, complete
critical gate-tool coverage and mutations, exact-head/main acceptance and read-only
AWS `ValidateStateMachineDefinition` receipt. Stages 6–8 remain unadmitted.

Administrator IAM installation is deferred until the final release is qualified.
Organization/SCP/session restrictions remain unknown, and effective successor
permissions remain unverified. The approved combined authorization remains in force.
