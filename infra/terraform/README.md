# Bounded AWS topology

The Terraform module creates encrypted inputs/evidence buckets, an on-demand exception ledger,
the Glue catalog namespace, CloudWatch logs, and a fail-closed orchestration contract. Actual
Glue/Athena adapters are attached by the managed lab and cannot be claimed from static validation.

