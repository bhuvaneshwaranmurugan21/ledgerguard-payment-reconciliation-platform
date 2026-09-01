# Stage 1 semantic decision register

## Status

- Stage: Part 1, Stage 1
- State: `PART1_FINANCIAL_SEMANTICS_FROZEN`
- Baseline main commit: `9a920a300b50fe46bb534e7fc9f32ad5eda1224c`
- Baseline main tree: `738221ba63364837f12c2ce3279b0514db08f2e5`
- Baseline foundation digest:
  `4d7bf84f88b7cd0826a637aa9da74cb5e5ffc5d4dc0f390c82340ef083a7dc60`
- Unresolved semantic decisions: zero
- AWS execution: no
- AWS infrastructure mutation: no

This register freezes meaning. It does not claim an implemented reconciliation engine.

## Decisions

| ID | Decision | Consequence |
|---|---|---|
| `SEM-001` | Processor, ledger, and bank are independent truths | Missing evidence remains visible and no source silently wins |
| `SEM-002` | Money uses signed integer minor units | Floating-point money is forbidden |
| `SEM-003` | Currency is part of every key | Cross-currency aggregation fails admission without an authoritative proof |
| `SEM-004` | Business digests use canonical UTF-8 JSON, NFC, UTC, ordered keys, and SHA-256 | Equivalent payloads are stable and digest fields are non-circular |
| `SEM-005` | Source identity is separate from business identity | Identical replay is idempotent; changed payload is a conflict |
| `SEM-006` | Transaction grain includes processor, merchant, payment, event class, and currency | Transaction proof cannot contain placeholder bank totals |
| `SEM-007` | Capture is positive; refund, chargeback, and reversal are negative | Raw positive amounts gain direction from event type |
| `SEM-008` | Negative events reference one exact capture and cannot over-apply it | Missing and excessive references remain explicit exceptions |
| `SEM-009` | Journal balance, unique lines, entry type, processor, currency, and one grain key are mandatory | Structurally uninterpretable journals cannot authorize proofs |
| `SEM-010` | Transaction clearing movement is debit minus credit | Capture clearing debits are positive; negative-event credits are negative |
| `SEM-011` | Settlement grain includes processor, merchant, settlement, cycle, and currency | Payout aggregation remains separate from payment grain |
| `SEM-012` | Expected settlement net is recomputed from five explicit components | Reported formula mismatch remains an exception |
| `SEM-013` | Settlement clearing movement is credit minus debit | Positive, zero, and negative settlements have consistent signs |
| `SEM-014` | Bank allocation requires exact normalized settlement reference and permitted account | Amount/date heuristics and double allocation are forbidden |
| `SEM-015` | Tolerance applies only to complete, semantically valid evidence | A tolerated difference remains visible and is not `MATCHED` |
| `SEM-016` | Proof totals and deltas are grain-specific | Settlement preserves three pairwise differences |
| `SEM-017` | Proof and case revisions are immutable and predecessor-linked | Late evidence resolves by adding history, never rewriting it |
| `SEM-018` | Admission, financial, and execution failures have disjoint ownership | Partial or mislabeled evidence cannot become authoritative |

The machine-readable register is
[`financial-semantics-v1.json`](../spec/financial-semantics-v1.json). The decision inventory and
unresolved count are checked by `tests/test_financial_semantics_spec.py`.

## Deliberate bounded choices

- Multiple captures may share one payment, but each negative event references one exact capture.
- Cumulative negative application cannot exceed the referenced capture.
- Settlement IDs are unique for merchant and currency in the bounded domain.
- Bank reference matching is case-sensitive after NFC normalization and outer-whitespace trimming.
- Punctuation is significant.
- No amount/date heuristic is available as a fallback.
- Zero-net settlements may legitimately have no clearing or bank record.
- Expected net may be negative.
- Automatic actors cannot accept variance or write off cases.

These choices reduce ambiguity without claiming every payment-processor feature or an operator
workflow that is outside the current foundation.

## Contract corrections required after this semantic freeze

The current schemas predate these decisions. They must later encode, rather than reinterpret:

- non-null negative-event references;
- required journal entry type and processor;
- exactly one applicable journal grain key;
- complete policy role, sign, reference, and bank rules;
- grain-specific proof totals and settlement deltas;
- case grain and closed reason taxonomy;
- honest local and object-storage manifest identity; and
- canonical digest scope.

Until those corrections are validated, the overall Part 1 foundation remains a correction candidate.
