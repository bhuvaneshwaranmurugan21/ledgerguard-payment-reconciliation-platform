# Part 3 Stage 3 execution contract

The execution order is fixed: import and append-only-correct Stage 2 closure; freeze requirements,
profiles, formats, paths, runtime, and package boundaries; generate deterministic bounded-memory
assets; independently recompute expectations; execute seeded properties; derive both reconciliation
grains and bank allocation from typed source DataFrames; materialize only immutable candidate
Parquet; build and install the exact offline runtime; then qualify twice and publish exact-head CI
evidence.

The production runtime contains the accepted reconciliation package, native Stage 3 argument,
path, admission, Spark, output, and job modules, plus digest-bound active schemas. Generator,
expectation reader, campaign, tests, historical AWS tooling, and the reference oracle are excluded
by an explicit package allowlist and independently inspected wheel records.

Python is pinned to 3.11.13 for qualification. The managed target is Glue 5.1 with Python 3.11,
Spark 3.5.6, and Java 17. Runtime dependencies are exact wheels with hash-locked offline install;
sdists and network resolution are not accepted. Package and source identities exclude paths and
wall time and are compared across two isolated builds.

Failures are evidence, not success: malformed contracts, source or manifest drift, identity
conflicts, arithmetic overflow, unsafe or mutable S3 paths, ambiguous allocation, incomplete
output, package leakage, non-reproducibility, coverage/mutation failures, or any AWS execution stop
the transaction. No pointer named latest/current/active and no authoritative proof or case head may
be produced by Stage 3.
