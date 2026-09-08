# ADR 0027: Exact-main AWS qualification boundary

## Status

Accepted for the Part 3 Stage 2 implementation transaction.

## Decision

Stage 2 qualifies the frozen account, region, GitHub OIDC role, live IAM policy, shared control
plane, budget headroom, service visibility, and clean inventory before workload infrastructure is
implemented. Automatic CI has no OIDC permission. Live checks use only manually dispatched
workflows on `refs/heads/main`, require an exact 40-character commit input equal to the workflow
and checkout commit, and use short-lived OIDC credentials.

GitHub's immutable default OIDC subject is required. The subject binds both the immutable owner ID
`276895096` and repository ID `1333030396`, in addition to their human-readable names and the exact
`refs/heads/main` ref. The legacy name-only subject is rejected. This preserves the original
repository-and-main-only trust boundary while preventing namespace reuse from transferring the
role trust to a different owner or repository.

The Terraform backend is an encrypted, versioned S3 bucket with S3 lockfiles (`use_lockfile =
true`). DynamoDB backend locking is not introduced. A separate DynamoDB table provides the
account-side operation lease. The desired names and security controls are recorded in
`contracts/part3-stage2-control-plane-v1.json`. If those resources do not exist or fail their
controls, the result is `BLOCKED_BOOTSTRAP_REQUIRED`; local state or a business table cannot be
substituted.

Stage 2 may write only isolated, run-derived S3 probe versions, run-derived conditional lease
items, and one inert Glue job definition. It deletes exact versions and markers, releases only an
owner-matched lease, verifies zero Glue runs, and proves final absence. Glue, Step Functions, and
Athena workload-start APIs are absent from the command adapter and permission contract.

## Consequences

Live IAM must equal the checked-in semantic policy. Missing and excess permissions both fail.
Administrator-side remediation or bootstrap requires a separately reviewed transaction and a new
exact-main qualification run. Stage 2 evidence can support only environment and definition-probe
claims; it cannot support deployment, managed reconciliation, scale, production, or project
completion claims.
