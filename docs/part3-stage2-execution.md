# Part 3 Stage 2 execution record

## Entry

- Stage 1 squash: `5abef1a07899bd8ecd202008f1c397890184a0d2`
- Tree: `77f13e8a68c46ccdcdae426b82c37c66d5e3ed81`
- Sole parent: `cb81704adcfdfac5d93879cd6c189fc2213bbe79`
- Stage 1 main CI: `34105604941`
- Stage 1 main artifact: `10013159831`
- Stage 1 artifact ZIP SHA-256: `f1338e2320a1113410c7a0ac6a90b5eebb73abe512fcc5a53ca6f77aafdf641f`

## Current transaction

Stage 2 is an evidence-only closure candidate. The qualified operational commit is
`aa136331e44dcd181f766b42d76ee2616a22f435` with tree
`184d8d7ff8d1172ec863060d4be7132339eaba49`. Its post-merge CI run `34327726113` passed, and
artifact `10094502981` was independently accepted with ZIP SHA-256
`846162348f77eee8e248dc815859989ee80253ff11c69c9be6b86f8c2c1e3cdd`.

Exact-main read-only run `34337121587` verified the AWS target, live IAM parity, backend, lease,
cost headroom, service visibility, Step Functions definition validation, Glue probe role, and clean
starting inventory. Bounded capability run `34337699794` exercised S3, conditional lease, and
definition-only Glue behavior under three injected cleanup faults plus a normal case. All four
cases cleaned successfully; final probe residue is zero. The independent receipts bind the
downloaded ZIP, manifest, journal, run-binding, and inspection digests.

All 22 Stage 2 source requirements and gates G001–G019 are verified. P3-S2-G020 remains pending
the closure PR's exact-head CI, single-parent squash, and post-merge main CI. The repository does
not self-attest those future facts.

## Claim boundary

- Stage 1: externally verified.
- Stage 2 live AWS qualification: externally verified on the recorded exact-main SHA.
- Stage 2 closure publication: candidate; G020 pending.
- Managed reconciliation: not started.
- Workload infrastructure: not implemented.
- Part 3 and project completion: false.

## Live correction history

- Implementation squash `b53ed30a38a5cd7f4c25097cb250371f7b5f0e10` and S3 IAM-action
  correction squash `46eb21434ca45363055acf9ac29b7ddd7e7191b5` are on `main` with green
  post-merge CI.
- Read-only run `34200956511` assumed the role and then failed closed at `iam:GetRole`, proving
  that the role had no qualification identity policy. No Stage 2 mutation occurred.
- After administrator permission remediation, run `34207057507` failed before qualification at
  `sts:AssumeRoleWithWebIdentity`. GitHub's repository OIDC settings prove that immutable subject
  claims are automatically enabled; the desired contract is therefore corrected to the exact
  owner-ID/repository-ID/main-ref subject.
- Immutable-subject correction squash `184e3bab3ae510c559536141525ef5ac49827c62` is on `main`;
  post-merge CI run `34215625919` passed all three required jobs and its independently inspected
  artifact ZIP has SHA-256 `a117909649afbb0457da37d64e5c6610c52a10c0331cb036caa1568619c30663`.
- Read-only run `34222243371` passed OIDC and exact IAM parity, then failed closed on the absent
  backend bucket. After separate administrator bootstrap, run `34225326864` fully verified the S3
  backend and DynamoDB lease table, then failed closed because the definition-only Glue probe role
  was absent. Neither run performed a Stage 2 mutation.
- Cost-classification correction squash `f6ab976e7efaa67d5b60e6d5270198c652f4cae5` passed main CI
  `34318941922`. Its first capability run failed at tagged Glue definition creation because
  `glue:TagResource` was absent. Dedicated recovery run `34323066627` proved complete cleanup.
- The narrow Glue-tag permission correction was reviewed in PR #24, whose validated head and squash
  share tree `184d8d7ff8d1172ec863060d4be7132339eaba49`. The correction added only
  `glue:TagResource` for `ledgerguard-stage2-*` job definitions and kept `glue:StartJobRun`
  forbidden.
- Fresh read-only run `34337121587` and corrected capability run `34337699794` succeeded and
  were independently accepted. The capability artifact records 123 API calls, 42 run-scoped
  mutation-journal entries, four complete cleanup cases, no workload start, and zero residue.
- P3-S2-G020 remains pending the evidence-only closure publication transaction.
- Read-only run `34264552202` passed the target, IAM, backend, lease, Glue-role, Step Functions,
  Athena, CloudWatch, and quota checks, then failed closed because Cost Explorer's ungrouped
  monthly total was negative after credits. The correction groups `UnblendedCost` by
  `RECORD_TYPE`, sums only positive period/group amounts as charge-side gross, records excluded
  negative offsets without netting them into headroom, and preserves the strict nonnegative
  budget guard. The failed run performed no Stage 2 mutation.

## Allowed completion claim

The exact LedgerGuard AWS target, desired/live IAM parity, shared control-plane prerequisites,
bounded definition/capability probes, and clean starting state were independently verified on the
recorded main SHA. No managed reconciliation workload ran, and all probe residue was removed.
