# Part 3 administrator handoff

This is the successor design and execution order for S4-G04. Generated JSON must be
bound to its exact source commit and reviewed operation identity. It is not evidence
of installed IAM, effective permissions, Stage 4 closure or permission to start a workload.

## Exact bootstrap identities

Account `857229544428`, region `ap-southeast-2`. All three identities use the unchanged
trust document in `contracts/part3-stage2-oidc-trust-v1.json`, including the stable
repository/user IDs, `refs/heads/main`, STS audience and 3,600-second maximum session.
Deploy trust is retained; the same trust is proposed for the two new roles.

| Role name, path `/` | Exact attachments from the generated packet | Responsibility |
| --- | --- | --- |
| `LedgerGuardGitHubOidcRole` | `deploy_policies` | Admitted plan, canary and normal teardown |
| `LedgerGuardPart3ReadOnlyRole` | `read_policies` | Separate non-mutating observation |
| `LedgerGuardPart3RecoveryRole` | `deploy_policies` plus `rescue_delta_policies` | Owned failed-operation cleanup and narrowly scoped stop actions |

The two new roles and all administrator-managed policy documents are separate bootstrap
resources, excluded from the 33 Terraform workload addresses. They are not silently
adopted if they already exist. Account policy/attachment quotas must be observed before
installation. The local ten-attachment envelope is not proof of account quota headroom.
No administrator role receives authority to change its own or another bootstrap identity.
Reader and deployment policy sets can inspect all three identities and the bounded
read/deploy/rescue policy partition names. They cannot create policy versions or attachments.

The generated `identity_contract` requires exactly the listed attachments, no inline
policies and no permissions boundary on these three bootstrap identities. An existing
boundary is drift to diagnose; do not remove it to make this design pass. Four workload
roles still require their separate administrator-controlled runtime boundaries, including
the explicit Part 3 workload/business-write denials. Recovery receives the deployment
permissions plus exact owned Glue/SFN/Athena stop actions, never workload start permission.

## Backend and release binding

The observed backend is `ledgerguard-tfstate-857229544428-ap-southeast-2`; its AWS-managed
S3 KMS key is `arn:aws:kms:ap-southeast-2:857229544428:key/f1298457-395b-4e16-8c11-50ee669be834`.
The console observation shows Bucket Key enabled. The packet requires the exact key,
S3 ViaService and caller account constraints; it does not edit the AWS-managed key policy.
State writes target one reviewed operation key, while deletion targets its `.tflock` only.
The bootstrap bucket and shared lease table survive workload teardown.

The current runtime policy/boundary render binds the actual accepted Stage 3 transport.
Stage 5's qualified adapter/package changes require regeneration against the real successor
release before cloud admission. No placeholder Lambda archive, ASL or future digest may be
used. The operation name is a proposed review input until an admitted live operation owns it.

## Administrator transaction and rollback

1. Freeze the generated packet manifest, exact source/tree and operation identity. Verify
   current PR qualification. Keep PR #27 draft until the remaining Stage 4 gates are accepted.
2. With a separate administrator session, export current role/trust, all inline policies,
   attachments, boundaries, policy metadata/default versions and complete tag inventories.
   Keep raw responses private. Read-only run `34559335116` proves normalized equivalence
   of the historical deploy policy/trust, not a raw live JSON backup or perpetual freshness.
3. Compare the fresh old policy/trust with the accepted baseline. Check that the two new
   role names and all new policy names are absent, or stop to review their existing ownership
   and full documents. Inspect account quotas and applicable SCP, boundary, resource-policy
   and session restrictions. Record unknown visibility explicitly; it cannot admit deployment.
4. Run IAM Access Analyzer `ValidatePolicy` on every generated policy and runtime boundary.
   Preserve every finding, severity and exact document hash. Resolve errors/security findings
   or document a precise supported applicability decision; never suppress a finding globally.
   Validation does not prove live capability. Review the literal old/new policy diff.
5. Only after review and administrator authorization, create the exact new policies and
   reader/recovery roles, with approved trust/tags/session duration. Attach only the listed
   sets. Install the four exact runtime boundaries separately. Existing name collisions or
   changed default versions are not permission to overwrite an unrelated resource.
6. Replace the deploy role's sole historical inline qualification policy with its exact
   reviewed managed-policy set in a controlled administrator change window. Do not run old
   Stage 2 qualification/probe workflows while this transition occurs. Do not attach the new
   set and claim parity while the old inline policy is still present. Keep rollback authority
   in the separate administrator session; the executor must not repair its own IAM.
7. Independently collect all three identities and each attached policy's actual current
   default version. Reject incomplete pagination, any read error, missing/excess attachments,
   changed trust/path/session/boundary, policy drift and stale/non-default policy documents.
   `admit_identity_snapshot` checks this exact projection; preserve the raw journal and source
   binding separately. Its successful result is document parity, not effective permission.
8. Before Stage 6/7, use fresh controlled role sessions and the source-bound operational
   collector to verify required capabilities, KMS/backend, all service inventories, shared
   lease ownership, restrictions and gross budget. Renew expiring evidence at admission.
   A denied read is UNKNOWN, not an empty inventory. No workload invocation is a probe.
9. If installation fails before any platform operation, use the raw backup to restore the
   exact original deploy inline policy and attachments; detach only this transaction's new
   attachments. Verify exact old trust/policy composition. Remove only bootstrap objects
   created by this transaction after confirming no attachment or boundary reference remains.
   Preserve the failure and rollback journals; do not call this successor qualification.
10. If any platform operation has begun, reconcile live lease, state and owned resources
    first. Keep recovery permissions until independently verified cleanup. Never roll back
    IAM in a way that strands resources. Bootstrap deletion is a separate administrator
    transaction, not ordinary `terraform destroy`; never remove the shared backend or lease.

## Continuing without repeated approval prompts

Repository implementation, tests, repairs, evidence preparation and already-authorized draft
publication continue without another permission request. Current user instructions retain
PR #27 as draft. The combined plan §12 reserves administrator changes, stage squash merges
and AWS workflow dispatches for the user; no ordinary successful check requires reauthorization.

A single conditional authorization may cover remaining Part 3 publication, bounded cloud
operations and exact owned cleanup. It must name whether manual merges remain user-owned or
are delegated after exact-head acceptance. It does not provide missing AWS access, validate
future artifacts, override failed gates or extend resource/cost/workload scope. Dynamic
source/run/package identities are filled after they exist and must be checked automatically.
The total gross USD 10 ceiling, no workload execution, reviewed 33-address graph, failure
cleanup and separate Stage 8 promotion/closure transactions remain mandatory.

AWS references: [default policy versions](https://docs.aws.amazon.com/IAM/latest/APIReference/API_GetPolicyVersion.html),
[policy validation](https://docs.aws.amazon.com/IAM/latest/UserGuide/access-analyzer-policy-validation.html),
[effective permissions and boundaries](https://docs.aws.amazon.com/IAM/latest/UserGuide/access_policies_boundaries.html).
