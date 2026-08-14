# Threat model

| Threat | Design control | Remaining managed proof |
|---|---|---|
| Financial feed disclosure | Encrypted, private S3 | Config and role evidence |
| Amount mutation on replay | Immutable identity and payload digest | Managed conflict trace |
| Fabricated match | Three independent totals and exact difference | Independent source proof |
| Unauthorized case closure | Explicit lifecycle and actor boundary | Adapter authorization test |
| Partial reconciliation | Atomic feed processing and fail-closed gate | Failure/restart trace |
| Evidence leakage | Synthetic data and redacted identifiers | Bundle review |

No PCI, banking, or compliance certification is claimed.

