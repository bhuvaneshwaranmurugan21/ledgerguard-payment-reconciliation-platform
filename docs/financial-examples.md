# Financial acceptance examples

These examples are the human-readable counterparts of
[`financial-examples-v1.json`](../spec/financial-examples-v1.json). The calculations are executed by
the Stage 1 specification tests. They demonstrate semantics, not a completed reconciliation engine.

## 1. Matched capture

```text
Processor CAPTURE                         +10,000 INR minor units

Ledger
Dr PROCESSOR_CLEARING                      10,000
Cr MERCHANT_PAYABLE                        10,000

Transaction ledger movement               +10,000
Processor-ledger delta                           0
Status                                     MATCHED
```

## 2. Matched partial refund

The refund references a capture with sufficient remaining capacity.

```text
Processor REFUND                           -2,500

Ledger
Dr MERCHANT_PAYABLE                         2,500
Cr PROCESSOR_CLEARING                       2,500

Transaction ledger movement                -2,500
Processor-ledger delta                           0
Status                                     MATCHED
```

## 3. Balanced journal with the wrong role

```text
Processor CAPTURE                         +10,000

Ledger
Dr BANK_CASH                               10,000
Cr MERCHANT_PAYABLE                        10,000

Journal balance                            VALID
Required PROCESSOR_CLEARING role            ABSENT
Status                                     EXCEPTION
Reason                                     INVALID_ACCOUNT_ROLE
```

Equal totals and journal balance cannot override the missing financial role.

## 4. Out-of-order refund

```text
Processor REFUND                           -2,500
Referenced capture                         ABSENT
Ledger refund movement                     -2,500
Monetary difference                             0
Status                                     EXCEPTION
Reason                                     UNRESOLVED_REFERENCE
```

The monetary values happen to agree, but the reference is not valid. When the capture later arrives,
complete reconciliation may create a new proof revision. The earlier exception remains immutable.

## 5. Currency contamination

```text
Processor CAPTURE                          10,000 INR
Ledger movement                            10,000 USD
Numeric difference                              0
Outcome                          ADMISSION_REJECTED
Authoritative proof                          NONE
Reason                                     CURRENCY_DOMAIN_VIOLATION
```

Numeric equality across currencies has no financial meaning. This is an admission failure, not a
finalized financial-exception proof.

## 6. Matched split-bank settlement

```text
Gross                                     100,000
Fee                                         3,000
Refund                                     10,000
Chargeback                                  5,000
Reserve                                     2,000
Expected net                               80,000

Ledger clearing movement                   80,000
Bank credit 1                              50,000
Bank credit 2                              30,000
Allocated bank total                       80,000

Processor-ledger delta                          0
Processor-bank delta                            0
Ledger-bank delta                               0
Status                                     MATCHED
```

Both bank entries carry the exact settlement reference and each identity is allocated once.

## 7. Matched zero-net settlement

```text
Gross                                      10,000
Fee                                         1,000
Refund                                      9,000
Expected net                                    0
Clearing records                                0
Bank records                                    0
Status                                     MATCHED
```

The missing clearing and bank records are valid only because the expected net is exactly zero and no
other semantic error exists.

## 8. Matched negative-net settlement

```text
Gross                                       5,000
Fee                                         1,000
Refund                                      7,000
Expected net                               -3,000

Clearing debit normalized                  -3,000
Bank debit normalized                      -3,000
Status                                     MATCHED
```

Expected net is signed. Ledger and bank directions must reproduce the negative economic movement.

## 9. Within-tolerance settlement

```text
Processor net                              10,000
Ledger clearing                             9,999
Bank                                       10,000
Tolerance                                       1

Processor-ledger delta                          1
Processor-bank delta                            0
Ledger-bank delta                              -1
Maximum absolute difference                     1
Status                                     WITHIN_TOLERANCE
Reason                                     TOLERATED_DIFFERENCE
```

This is not `MATCHED`; the one-unit difference remains visible.

## 10. Settlement formula mismatch

```text
Recomputed expected net                    80,000
Processor-reported net                     81,000
Ledger clearing                            80,000
Bank                                       80,000
Monetary pairwise difference                    0
Status                                     EXCEPTION
Reason                                     SETTLEMENT_FORMULA_MISMATCH
```

Matching ledger and bank totals cannot erase an internally inconsistent processor settlement.

## 11. Unallocated bank movement

```text
Expected settlement                        80,000
Ledger clearing                            80,000
Bank entry amount                          80,000
Bank reference                       settlement-unknown
Required reference                   settlement-expected

Allocated bank total                            0
Status                                     EXCEPTION
Reasons                                    MISSING_BANK_SETTLEMENT
                                           UNALLOCATED_BANK_MOVEMENT
```

LedgerGuard does not force-match an equal amount using proximity or date.

## 12. Capture-capacity counterexample

```text
Referenced capture                         10,000
Cumulative negative application            11,000
Status                                     EXCEPTION
Reason                                     OVER_APPLIED_REFERENCE
```

The negative events cannot consume more than their referenced capture.

## 13. Ambiguous bank allocation counterexample

```text
Normalized bank reference              settlement-shared
Matching settlement candidates                         2
Outcome                          ADMISSION_REJECTED
Authoritative proof                          NONE
Reason                            AMBIGUOUS_BANK_ALLOCATION
```

An exact reference is insufficient when it identifies more than one settlement candidate. The bank
entry is allocated to neither candidate, and the unsafe source set cannot authorize a proof.
