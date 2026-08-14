# Interview defense

## Two-minute explanation

LedgerGuard reconciles three independent financial truths: processor events, balanced internal
journals, and bank settlements. It uses integer minor units, validates balanced postings, supports
split settlements, keeps exact monetary differences visible, and moves an exception to matched
only after repaired input is replayed. Matching row counts is never treated as settlement proof.

## Questions to expect

1. **Why integer money?** Floating point cannot represent all decimal amounts exactly.
2. **Why three-way reconciliation?** Any two systems can agree while both differ from cash movement.
3. **How are split settlements handled?** Records are grouped by payment/currency and explicitly summed.
4. **What makes replay safe?** External and journal IDs are immutable and digest-checked.
5. **How is repair audited?** The mismatch remains a case and transitions only after a new proof.
6. **What ran on AWS?** Only a bundle passing `validate_aws_lab_evidence` supports an AWS-lab claim.

