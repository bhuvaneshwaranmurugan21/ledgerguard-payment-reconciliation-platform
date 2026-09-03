# ADR 0017: Part 2 execution authority and local toolchain

## Status

Accepted.

## Context

Part 1 froze financial meaning and contract structure but intentionally implemented no
reconciliation runtime. Starting Part 2 directly with engine code would leave ownership,
traceability, failure coverage, dependency reproducibility, and the boundary between historical
closure validation and active development ambiguous.

The rehearsal also demonstrated that an exact Python 3.11 driver can silently launch a host Python
3.12 Spark worker unless both interpreter variables are explicit. It also showed that the Stage 6
runner correctly rejects evidence output inside the repository.

## Decision

Establish a Stage 1 execution authority before runtime implementation. Bind entry to the exact Part
1 squash-merge and independent `main` CI evidence. Validate Part 1 from an immutable separate
checkout, and validate active Part 2 work from independent clean environments.

Use CPython 3.11.13, Java 17, Apache Spark 3.5.6, and Py4J 0.10.9.7. Bind Spark driver and worker to
the same interpreter, enable ANSI mode and UTC, and prove exact long/decimal Parquet behavior twice.
Use a minimal, fully hash-locked dependency set; pandas and PyArrow are not introduced until a
later requirement needs their execution paths.

Keep every master Part 2 completion gate and runtime deliverable unclaimed in Stage 1. Retain
read-only automatic CI and the manual-only AWS identity workflow.

## Consequences

Later implementation stages have exact owners and immutable inputs. Runtime or evidence drift fails
closed before financial code is accepted. CI performs additional clean-environment work, and the
PySpark source distribution increases installation time, but these costs buy reproducibility and
prevent ambient-runtime success.
