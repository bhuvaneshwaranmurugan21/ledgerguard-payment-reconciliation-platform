# Part 3 Stage 2 gap audit

Stage 1 is externally closed at `5abef1a07899bd8ecd202008f1c397890184a0d2`. Its producer files
remain unchanged; `spec/part3-stage1-external-closure-v1.json` imports the later PR, topology, main
CI, job, artifact, test, coverage, and mutation facts append-only.

The first open Part 3 control is `LG-P3-G001`: exact-target AWS identity and IAM qualification.
The historical AWS identity result remains `AWS_VERIFIED_WRONG_TARGET` and is not reused. All 22
Stage 2 master requirements are owned once in the Stage 2 adjudication and remain incomplete until
the exact-main read-only and bounded-capability artifacts are independently accepted.

The implementation transaction supplies the missing desired OIDC/IAM state, backend and lease
contracts, cost equation, inventory rules, qualification fixtures, narrow AWS adapter, three
manual workflows, evidence schema, independent inspector, negative tests, and recovery behavior.
The live account may still lack the desired backend bucket, lease table, Glue probe role, or IAM
policy. That is an expected hard branch: read-only evidence must identify the exact gap before any
administrator bootstrap or permission change occurs.

Stage 2 excludes workload Terraform, business DynamoDB state, production Step Functions, managed
reconciliation, and all Stage 3 work.
