# ADR 0001: Reconcile transactions and settlements separately

## Status

Accepted.

## Context

Processor payment events and bank cash movement do not normally share a one-to-one grain. A payout
can aggregate many payments and deductions and can appear as multiple bank entries. Joining all
three truths by payment identifier creates false confidence and unrealistic fixtures.

## Decision

LedgerGuard performs transaction reconciliation between processor events and ledger movement, then
settlement reconciliation among processor payout reports, clearing-account movement, and aggregate
bank cash. Each proof names its grain and reconciliation key.

## Consequences

The model requires processor payout records and explicit ledger account roles. It gains realistic
split and aggregate settlement behavior and avoids inventing payment identifiers in bank data.
