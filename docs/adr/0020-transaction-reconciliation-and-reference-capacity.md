# ADR 0020: Transaction reconciliation and reference capacity

- Status: accepted for the Part 2 Stage 4 candidate
- Scope: local production transaction calculation only

## Decision

Stage 4 consumes Stage 3 admitted observations and produces immutable, non-authoritative
transaction candidates. The transaction grain remains processor, merchant, payment, event class,
and currency. Processor and ledger facts are grouped independently and evaluated over the full
outer union of their keys.

Admission exposes both newly accepted business effects and a current-bundle observation view.
Identical replay remains idempotent, but its canonical observation is available to resolve an
exact capture. Immutable transaction state may carry prior facts; source identity and business
digest disagreement fails before any candidate is returned.

Processor event amounts use the policy sign. Ledger movement uses only PROCESSOR_CLEARING postings
and the frozen debit-positive, credit-negative orientation. Total journal debit is never a
substitute. A wrong clearing count, wrong clearing side, or policy-disallowed counterpart role is
the existing financial reason `INVALID_ACCOUNT_ROLE`.

Negative events resolve through processor plus exact referenced capture source-record identity.
The capture must also share merchant, payment, and currency. A missing, negative, or cross-scope
target is `UNRESOLVED_REFERENCE`. Refund, chargeback, and reversal amounts are summed per exact
capture before capacity is assessed. If their total exceeds the capture, every affected negative
grain carries `OVER_APPLIED_REFERENCE`; input order cannot choose a victim. Multiple captures under
one payment remain separate capacity pools.

All arithmetic is checked signed 64-bit. Semantic reasons force `EXCEPTION` before tolerance.
Without semantic reasons, zero difference is `MATCHED`, a nonzero difference within policy
tolerance is `WITHIN_TOLERANCE`, and a larger difference is `PROCESSOR_LEDGER_MISMATCH`.

## Boundary

Stage 4 does not calculate settlements or bank allocation, finalize or persist proofs, create case
revisions, execute Spark, call a network or AWS API, or mutate infrastructure. Production code may
not import the independent oracle. Candidate output always states `authoritative_proof: false`.
