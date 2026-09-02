# Quality scorecard

The target is frozen before implementation. Documentation, design, local execution, and managed
execution are not interchangeable forms of evidence.

| Dimension | Target | Completion evidence |
|---|---:|---|
| Problem clarity | 8.5 | Two-grain problem, equations, scope, and explicit non-goals |
| Architecture quality | 8.0 | Requirement-led service choices and recorded trade-offs |
| Financial correctness | 9.0 | Executable invariants, oracle parity, property tests, and managed totals |
| Failure and recovery | 8.5 | Semantic failures, retry behavior, late-data revision, and cleanup recovery |
| Repository structure | 8.0 | Clear contracts, implementation, infrastructure, tests, evidence, and docs |
| Automated testing | 8.5 | Unit, property, contract, parity, integration, and adversarial coverage |
| Documentation and ADRs | 8.0 | Current architecture, correctness, failure, operations, cost, and decisions |
| Evidence integrity | 8.5 | Source, commit, run, environment, result, and cleanup attribution |
| Real AWS execution | 8.0 | Managed reconciliation, independent queries, failures, and teardown |
| Performance and scale | 7.5 | Comparable 100K and 1M runs with Spark and cost measurements |
| Security and cost controls | 8.0 | Bounded OIDC, least privilege, private data, scan cutoffs, and cost ceiling |
| Lifecycle ownership | 8.5 | Deploy, operate, recover, destroy, and independently prove clean inventory |

## Scoring integrity

- A dimension cannot exceed 7 from `DESIGNED/MODELED` evidence when execution is required.
- Local execution cannot raise real AWS execution above 3.
- A 1M synthetic run is a bounded scale measurement, not production-scale proof.
- Infrastructure cleanup is part of lifecycle ownership, not an optional postscript.
- Production tenure and compliance certification are explicit non-goals and are not fabricated
  scorecard dimensions.

The release audit records achieved scores and links each score to its evidence. A target is not an
achieved score.
