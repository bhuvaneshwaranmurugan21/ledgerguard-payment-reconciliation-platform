"""Frozen Stage 3 physical source-family mapping."""

FAMILIES = (
    "PROCESSOR_EVENTS",
    "PROCESSOR_SETTLEMENTS",
    "LEDGER_JOURNALS",
    "BANK_ENTRIES",
)

CSV_FIELDS = {
    "PROCESSOR_SETTLEMENTS": (
        "schema_version",
        "source_record_id",
        "source_batch_id",
        "processor",
        "merchant_id",
        "settlement_id",
        "settlement_cycle",
        "currency",
        "gross_minor",
        "fee_minor",
        "refund_minor",
        "chargeback_minor",
        "reserve_minor",
        "reported_net_minor",
        "occurred_at",
        "received_at",
        "payload_sha256",
    ),
    "BANK_ENTRIES": (
        "schema_version",
        "bank_record_id",
        "source_batch_id",
        "bank_account_id",
        "merchant_id",
        "settlement_reference",
        "direction",
        "amount_minor",
        "currency",
        "value_at",
        "received_at",
        "payload_sha256",
    ),
}

SOURCE_DIGEST_EXCLUSIONS = frozenset({"payload_sha256", "received_at", "source_batch_id"})
