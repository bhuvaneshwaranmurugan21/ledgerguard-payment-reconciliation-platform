# Part 2 Stage 7 Spark parity contract

The Spark lane consumes immutable local transaction and settlement candidates. Typed Spark columns
recompute financial deltas in `decimal(38,0)`, compute exact maximum absolute differences, apply
semantic-reason precedence, and preserve counts, keys, source identities, and ordered reason codes.
The result is non-authoritative until the already accepted Stage 6 finalizer commits it.

Parquet evidence is compared by canonical logical content. Physical file names, row-group layout,
compression bytes, task identifiers, and file ordering are deliberately excluded because Spark does
not promise them to be byte-stable. Each clean run must nevertheless produce the same canonical
logical digest after an independent read.

The runtime is exact: CPython 3.11.13, Temurin Java 17, Spark 3.5.6, Py4J 0.10.9.7, `local[2]`, ANSI
SQL enabled, UTC session timezone, and identical driver and worker interpreters. Version or session
drift fails before evidence is accepted.

The failure matrix remains governed by `docs/failure-model-v2.md`. Admission failures create no
proof, financial disagreement creates an exception proof, and execution failure creates no partial
authority. Every frozen scenario and reason must have an executable test; missing or additional
taxonomy members fail closed.
