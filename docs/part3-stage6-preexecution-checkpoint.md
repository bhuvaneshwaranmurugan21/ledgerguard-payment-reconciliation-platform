# Part 3 Stage 6 pre-execution checkpoint

## Exact entry

Preparation starts from the accepted Stage 5 main commit
`38576ff8b0592b53cd65fe3cf4241e077484afd8`, tree
`d789912c580bc4fd7f8059dd5e0ea766cd251750`. The user-supplied Git bundle has
SHA-256 `34209a93f60bdee29d3a0469ac4d7784508031d88f22cb475b2f95898aa7f989`;
`git bundle verify` reports a complete history, and detached checkout independently
reproduces the exact commit and tree with a clean worktree.

## Completed preparation increment

`spec/part3-stage6-preparation-v1.json` freezes the only three Stage 6-owned
requirements, gates `S6-G01` through `S6-G04`, every accepted Stage 5 release
identity, the exact account/region, the 33-address inventory and control digests,
the Python/Terraform/TFLint and provider locks, cost ceiling, workflow boundary,
prohibited Terraform/workload activity, sensitive evidence boundary and terminal
`plan_only_verified` claim.

The freeze deliberately records all six dependencies as false. Source preparation
cannot claim that successor IAM is installed, effective permissions or restrictions
are verified, fresh target admission exists, an exact Stage 6 main source exists, or
a saved plan exists.

`tools/validate_part3_stage6_preparation.py` re-derives the Stage 6 requirement
ownership and 33-address identity from repository authorities, verifies every
referenced source digest and every accepted Stage 5 digest, and rejects weakened
workflow, cost, action, publication or closure semantics.
`tools/part3_stage6/plan_policy.py` also implements the fail-closed structural half
of saved-plan admission: exact Terraform/format versions, exact 33-create action
graph, empty prior workload state, no drift, moves, imports, replacements, deposed
objects, generated configuration, module calls, failed checks or security-critical
unknowns. It explicitly cannot replace the property-level resource/control evaluator
or satisfy `S6-G02` by itself.

Two hundred eighty-three focused tests pass. The fifteen owned modules contain
1,134 statements and 566 branches at 100%, with no exclusions. Twenty-four isolated
source mutations are all killed by real tests. They cover administrator admission,
private-packet substitution, fresh preflight, conditional lease ownership, provider
and Terraform locking, create-only actions, provisioner rejection, property policy,
strict budget equality, quota visibility, inventory completeness, backend version
semantics, recovery and the independent-inspection boundary.

The complete property layer checks encryption, public access, TLS-only policy,
versioning, exact lifecycle bodies, durable publication prefixes, IAM boundary/trust
and source-derived policy documents, Glue 5.1 settings and immutable arguments,
Lambda runtime/environment/concurrency, Standard Workflow logging, Glue Catalog
schemas and locations, Athena engine/result encryption/scan cutoff, alarms and tags.
Legitimate provider-computed values are admitted only at exact paths and their
Terraform expression relationships are independently required; arbitrary critical
unknowns remain terminal failures.

The live controller now composes separately admitted administrator, identity/IAM,
restriction, backend, lease, budget, quota and fully paged multi-service inventory
proofs; runs only pinned `version`, immutable-lock `init`, `validate`, create-only
saved `plan`, and JSON `show`; then conditionally releases the owner lease and proves
the exact state, lock and workload inventory remain absent. Recovery derives the
owner token from the failed run identity and can remove only that owner’s lease after
fresh state/inventory proof. Force unlock and all workload starts remain unavailable.

The sanitized artifact boundary retains only evidence, command journal and a
byte-bound manifest. It binds workflow run/attempt, exact source, administrator
packet and receipt, Stage 5 release identities, every dependency lock, Terraform and
provider versions, backend-key fingerprint, saved plan digests, policy verdict,
honestly classified delayed billing and explicit zero-standing-cost assumptions. It
rejects raw plans/state/locks, unsafe or duplicate ZIP members, apply/workload/resource
creation calls, incomplete preflight, and producer attempts to self-admit `S6-G04`.
Only the separate inspector can emit terminal `plan_only_verified` after revalidating
every member. Ruff, workflow policy and `git diff --check` pass locally.
No AWS call, IAM mutation, workflow dispatch, Terraform operation or workload occurs.

## Toolchain finding and resolution boundary

The rehearsal environment contained only CPython 3.12, while the accepted repository
intentionally pins CPython 3.11.13. Its retained Python 3.11 virtual environments had
lost their interpreter. A local attempt to acquire exact CPython 3.11.13 failed at
network download before installation. A Python 3.12 resolver selected a different
platform artifact for `regex==2025.9.1`, so its digest correctly failed the Python
3.11 lock.

The repository lock is not weakened or rewritten. Native HCL/Terraform validation,
strict mypy, and full qualification must run in the accepted exact CPython 3.11.13
GitHub lane. This local checkpoint makes no claim that those checks passed.

## Remaining pre-execution sequence

1. Run the two exact-head CPython 3.11.13 source campaigns, inherited Stage 4/5 and
   broader compatibility workflows, then independently inspect every artifact.
2. Squash-merge only the unchanged qualified head and require fresh exact-main source
   qualification with tree/parent verification.
3. Regenerate the exact-main successor administrator packet and complete the separate
   protected administrator installation, restriction adjudication, effective allow/
   deny probes, rollback capture and sanitized receipt.
4. Dispatch the plan-only workflow from that exact main source, inspect its artifact,
   and record the three requirement receipts in a separate Stage 6 closure transaction.

Stage 6 and Part 3 remain incomplete. This checkpoint is not authorization to install
IAM, merge, dispatch, plan, apply or execute a workload.
