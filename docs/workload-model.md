# Workload and capacity model

The bounded lab uses deterministic processor records, balanced journals, bank settlement files,
split settlements, and controlled mismatches. It records records/s, monetary totals, exception
rate, exception age, reconciliation runtime, recovery time, and cost.

Production sizing is driven by payment volume, settlement-file cadence, late-arrival distribution,
and exception investigation workload. Row count alone is insufficient: one unexplained monetary
difference has greater operational importance than thousands of matched rows.

