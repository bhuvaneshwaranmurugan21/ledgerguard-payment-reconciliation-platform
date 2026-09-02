# Quality scorecard authority

The target is frozen before implementation. Documentation, design, local execution, and managed
execution are not interchangeable forms of evidence.

The exact machine-readable fields and remaining evidence are in the
[active completion authority](../contracts/part1-completion-authority-v2.json).

| Dimension | Target | Current evidence | Part 1 contributes | Current scope | Remaining evidence |
|---|---:|---|---|---|---|
| Problem clarity | 8.5 | `LOCAL_VERIFIED` | Yes | Two-grain problem, equations, non-goals and original requirement authority | Stage 5 consistency and final C7 adjudication |
| Architecture quality | 8.0 | `DESIGNED/MODELED` | Yes | Requirement-led managed design and Part 1 trade-offs | Local implementation parity and managed deployment evidence |
| Financial correctness | 9.0 | `LOCAL_VERIFIED` | Yes | Contract semantics and specification examples; no runtime claim | Part 2 engine parity and managed reconciliation proof |
| Failure and recovery | 8.5 | `DESIGNED/MODELED` | Yes | Failure ownership, atomicity and revision design | Local failure execution and managed recovery execution |
| Repository structure | 8.0 | `LOCAL_VERIFIED` | Yes | Part 1 contracts, specifications, validators, tests, evidence and history | Parts 2–4 surfaces and final release audit |
| Automated testing | 8.5 | `LOCAL_VERIFIED` | Yes | Part 1 schema, semantic, coherence, governance and traceability tests | Coverage/mutation hardening and runtime/managed suites |
| Documentation and ADRs | 8.0 | `LOCAL_VERIFIED` | Yes | Part 1 architecture, correctness, failure, contract and decision documents | Stage 5 consistency and Parts 2–5 operational documentation |
| Evidence integrity | 8.5 | `LOCAL_VERIFIED` | Yes | Digest-bound local evidence and historical checkpoint reproduction | C5 reproducibility and C6–C7 promotion evidence |
| Real AWS execution | 8.0 | `UNCLAIMED` | No | Historical wrong-target identity execution is not reconciliation evidence | Part 3 deployment and Part 4 workload/teardown evidence |
| Performance and scale | 7.5 | `UNCLAIMED` | No | No performance or scale execution claimed | Part 4 bounded scale measurements |
| Security and cost controls | 8.0 | `DESIGNED/MODELED` | Yes | Frozen OIDC target, workflow boundary and cost ceiling | Managed IAM and measured cost-control evidence |
| Lifecycle ownership | 8.5 | `DESIGNED/MODELED` | No | Lifecycle requirements are designed; operation is unclaimed | Parts 3–4 lifecycle execution and final release audit |

## Scoring integrity

- A dimension cannot exceed 7 from `DESIGNED/MODELED` evidence when execution is required.
- Local execution cannot raise real AWS execution above 3.
- A 1M synthetic run is a bounded scale measurement, not production-scale proof.
- Infrastructure cleanup is part of lifecycle ownership, not an optional postscript.
- Production tenure and compliance certification are explicit non-goals and are not fabricated
  scorecard dimensions.

The release audit records achieved scores and links each score to its evidence. A target is not an
achieved score.
