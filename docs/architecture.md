# Architecture decisions

## Decision: three truths, one proof

Processor, internal ledger, and bank settlement records are stored independently. Reconciliation
creates a versioned proof; it does not mutate source records to make them agree.

## Money and journals

Money is represented in integer minor units with an explicit currency. Every journal is balanced
before it can participate in reconciliation. Capture contributes positive business amount;
refund and reversal contribute negative amount. Bank settlements can be split across multiple
records and are compared by explicit policy version.

## Case lifecycle

```text
NEW -> EXCEPTION -> INVESTIGATING -> REPAIRED -> MATCHED
                       |                         |
                       +------> WRITTEN_OFF <----+
```

The executable kernel demonstrates `NEW -> EXCEPTION -> MATCHED`. Production adapters must add
actor identity and disposition approval before any write-off capability.

## Bounded workload

The AWS lab uses synthetic feeds and controlled mismatches. It measures records per second,
exception ageing, unexplained monetary difference, recovery time, and cost per million records.
It does not claim PCI certification or production financial custody.

