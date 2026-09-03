# Part 2 Stage 5 settlement-reconciliation gap audit

## Entry conclusion

PR #13 closed Stage 4 by squash commit
`c423ae7e6e92d37ffa8a796b4efacbf9ba6692f1`. Its exact-head run `33737068906`, immutable artifact
`9886556226`, artifact digests, and independent main run `33741521494` passed. The closure is frozen
in `spec/part2-stage4-closure-freeze-v1.json`.

## Gaps at entry

Stage 4 calculates transaction-grain candidates and negative-event reference capacity only.
Settlement processor formula validation, settlement clearing movement, the processor-ledger-bank
full comparison, exact bank allocation, permitted-account enforcement, bank disposition
diagnostics, settlement state, and Stage 5 evidence were absent.

Stage 3 already derives settlement keys and normalized bank references, but its unique observation
view intentionally collapses identical source identities. Stage 5 needs an additive occurrence
view to distinguish a duplicate bank movement in one manifest from a prior-state replay. Its
current-bundle ambiguity check also cannot see targets already carried in settlement state, so
Stage 5 must revalidate the complete target index before allocation.

An unknown bank record has merchant and currency but no processor or settlement cycle. Stage 5
therefore owns it once in a deterministic allocation ledger instead of assigning it to an
unrelated settlement. A nonzero known settlement without allocated bank evidence independently
retains `MISSING_BANK_SETTLEMENT`.

## Closure boundary

Stage 5 closes local financial-invariant implementation across both reconciliation grains. It does
not finalize or persist proofs, create immutable revisions, claim deterministic recovery, execute
Spark, use AWS, or mutate infrastructure. Its candidate is promoted only after exact-head CI,
immutable artifact inspection, squash merge, and independent post-merge main CI.
