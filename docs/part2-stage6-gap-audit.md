# Part 2 Stage 6 gap audit

## Entry conclusion

PR #14 closed Stage 5 at squash commit `89373adf968ff7071693f8cce5d12901fd9b1e69`.
Its exact-head CI, immutable evidence, squash topology, and independent post-merge `main` CI are
frozen in `spec/part2-stage5-closure-freeze-v1.json`. The accepted system can admit source bytes and
produce deterministic transaction and settlement candidates, but those candidates deliberately
remain non-authoritative.

## Gaps owned by Stage 6

1. There is no durable operation that promotes a whole candidate batch atomically.
2. There is no conditional authority pointer that makes stale writers lose deterministically.
3. Reconciliation proofs and exception cases have schemas and identities but no append-only store.
4. A restart cannot distinguish an abandoned request, orphaned content, a durable commit, or a
   published head.
5. Exact and historical retries have no persisted receipt or recovery rule.
6. Later batches cannot reconstruct the admission and both grain states solely from authoritative
   history.
7. Storage and concurrency failures have no executable ownership boundary guaranteeing that a
   partial financial result is never authoritative.

## Required closure

Stage 6 closes these gaps with one local content-addressed store. It writes the canonical request,
proof and case objects, and commit before conditionally replacing one authoritative `HEAD`; the
receipt follows the head and is recoverable from history. Every read verifies content digests,
canonical bytes, schemas, self-digests, inventories, predecessor chains, and case bindings.

Real process termination is exercised after the request, objects, commit, and head. Competing
processes use the same expected head and must yield exactly one winner. Repeated attempts either
return the original authoritative receipt or reject changed inputs. The store persists the complete
admitted state required for cross-batch replay and rejects removed or conflicting history.

## Explicit non-goals

Stage 6 does not execute Spark, write Parquet, access AWS, dispatch workflows, mutate
infrastructure, or claim managed persistence. It does not complete Stage 7 Spark parity, the full
cross-runtime failure matrix, or critical-path validation, and it does not close Part 2.

## Exit criteria

All thirty Stage 6 requirements must trace to one of ten gates. The full suite, exact owned 100%
statement and branch coverage, 24 semantic mutation checks with zero survivors, wheel installation,
two clean CPython 3.11.13 runs, exact-head draft-PR CI, and immutable artifact inspection must pass.
Only then may the PR become ready for manual squash merge.
