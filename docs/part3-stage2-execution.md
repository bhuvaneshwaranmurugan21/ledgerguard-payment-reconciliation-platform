# Part 3 Stage 2 execution record

## Entry

- Stage 1 squash: `5abef1a07899bd8ecd202008f1c397890184a0d2`
- Tree: `77f13e8a68c46ccdcdae426b82c37c66d5e3ed81`
- Sole parent: `cb81704adcfdfac5d93879cd6c189fc2213bbe79`
- Stage 1 main CI: `34105604941`
- Stage 1 main artifact: `10013159831`
- Stage 1 artifact ZIP SHA-256: `f1338e2320a1113410c7a0ac6a90b5eebb73abe512fcc5a53ca6f77aafdf641f`

## Current transaction

The Stage 2 implementation is locally validated and remains in progress pending exact-head PR CI,
publication on `main`, and live AWS evidence. Two fresh CPython 3.11.13 environments each execute
all 143 registered Stage 2 scenarios with zero skips, produce 100% statement and branch coverage
for every Stage 2 source module, kill all 29 registered semantic mutations, and build identical
wheels and deterministic evidence. Repository-local validation proves only the safety and
determinism of the qualification implementation; it does not prove an AWS fact. After this exact
tree passes PR CI and is squash-merged, the user will manually dispatch the read-only workflow on
the exact main SHA. The capability workflow is admitted only by an independently accepted
read-only run and artifact. An evidence-only closure transaction follows successful cleanup.

## Claim boundary

- Stage 1: externally verified.
- Stage 2 live AWS execution: not yet executed.
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
- Stage 2 remains open. A fresh exact-main implementation, live IAM parity, read-only evidence,
  bounded capability evidence, cleanup proof, and evidence-only closure are still required.
