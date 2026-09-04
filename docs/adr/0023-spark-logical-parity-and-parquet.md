# ADR 0023: Spark logical parity and Parquet evidence

## Decision

Use Spark as an independently evaluated, typed projection of accepted reconciliation candidates.
Recompute owned financial arithmetic with decimal expressions and compare canonical logical rows
after a real Parquet write/read cycle. Do not compare physical Parquet bytes and do not allow Spark
output to become authoritative without the Stage 6 conditional finalizer.

## Rationale

Spark physical files contain execution-specific layout details. Logical projection comparison proves
the relevant contract while remaining deterministic. Decimal arithmetic prevents IEEE-754 loss and
ANSI mode turns overflow or invalid operations into failures.

## Consequences

CI requires the exact locked Spark and Java toolchain. Evidence records runtime configuration, row
counts, logical digests, matrix coverage, critical paths, and the explicit non-AWS boundary. Part 2
still requires Stage 8 closure.
