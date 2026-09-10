"""Native Spark source-to-candidate reconciliation for Stage 3.

No Python reconciliation candidates are accepted as input and no Python UDF is used.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import reduce
from hashlib import sha256
from pathlib import Path
from typing import Any

from pyspark.sql import Column, DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql import types as T
from pyspark.sql.window import Window

from .canonical import canonical_bytes
from .errors import Stage3Rejected
from .runtime_admission import RuntimeInputs

_TXN_EVENTS = ("CAPTURE", "REFUND", "CHARGEBACK", "REVERSAL")
_TXN_REASON_ORDER = (
    "INVALID_ACCOUNT_ROLE",
    "UNRESOLVED_REFERENCE",
    "OVER_APPLIED_REFERENCE",
    "MISSING_LEDGER_MOVEMENT",
    "MISSING_PROCESSOR_ACTIVITY",
    "PROCESSOR_LEDGER_MISMATCH",
)
_STL_REASON_ORDER = (
    "INVALID_ACCOUNT_ROLE",
    "MISSING_LEDGER_MOVEMENT",
    "MISSING_PROCESSOR_ACTIVITY",
    "MISSING_BANK_SETTLEMENT",
    "UNALLOCATED_BANK_MOVEMENT",
    "INVALID_BANK_ACCOUNT",
    "DUPLICATE_BANK_MOVEMENT",
    "SETTLEMENT_FORMULA_MISMATCH",
    "PROCESSOR_LEDGER_MISMATCH",
    "PROCESSOR_BANK_MISMATCH",
    "LEDGER_BANK_MISMATCH",
)
_POSTING = T.StructType(
    [
        T.StructField("line_id", T.StringType(), False),
        T.StructField("account_role", T.StringType(), False),
        T.StructField("side", T.StringType(), False),
        T.StructField("amount_minor", T.LongType(), False),
    ]
)
EVENT_SCHEMA = T.StructType(
    [
        T.StructField("schema_version", T.StringType(), False),
        T.StructField("source_record_id", T.StringType(), False),
        T.StructField("source_batch_id", T.StringType(), False),
        T.StructField("processor", T.StringType(), False),
        T.StructField("merchant_id", T.StringType(), False),
        T.StructField("payment_id", T.StringType(), False),
        T.StructField("event_type", T.StringType(), False),
        T.StructField("amount_minor", T.LongType(), False),
        T.StructField("currency", T.StringType(), False),
        T.StructField("occurred_at", T.StringType(), False),
        T.StructField("received_at", T.StringType(), False),
        T.StructField("reference_event_id", T.StringType(), True),
        T.StructField("payload_sha256", T.StringType(), False),
    ]
)
SETTLEMENT_SCHEMA = T.StructType(
    [
        T.StructField("schema_version", T.StringType(), False),
        T.StructField("source_record_id", T.StringType(), False),
        T.StructField("source_batch_id", T.StringType(), False),
        T.StructField("processor", T.StringType(), False),
        T.StructField("merchant_id", T.StringType(), False),
        T.StructField("settlement_id", T.StringType(), False),
        T.StructField("settlement_cycle", T.StringType(), False),
        T.StructField("currency", T.StringType(), False),
        T.StructField("gross_minor", T.LongType(), False),
        T.StructField("fee_minor", T.LongType(), False),
        T.StructField("refund_minor", T.LongType(), False),
        T.StructField("chargeback_minor", T.LongType(), False),
        T.StructField("reserve_minor", T.LongType(), False),
        T.StructField("reported_net_minor", T.LongType(), False),
        T.StructField("occurred_at", T.StringType(), False),
        T.StructField("received_at", T.StringType(), False),
        T.StructField("payload_sha256", T.StringType(), False),
    ]
)
JOURNAL_SCHEMA = T.StructType(
    [
        T.StructField("schema_version", T.StringType(), False),
        T.StructField("journal_id", T.StringType(), False),
        T.StructField("source_batch_id", T.StringType(), False),
        T.StructField("ledger_system", T.StringType(), False),
        T.StructField("processor", T.StringType(), False),
        T.StructField("merchant_id", T.StringType(), False),
        T.StructField("payment_id", T.StringType(), True),
        T.StructField("settlement_id", T.StringType(), True),
        T.StructField("settlement_cycle", T.StringType(), True),
        T.StructField("entry_type", T.StringType(), False),
        T.StructField("currency", T.StringType(), False),
        T.StructField("effective_at", T.StringType(), False),
        T.StructField("received_at", T.StringType(), False),
        T.StructField("postings", T.ArrayType(_POSTING, False), False),
        T.StructField("payload_sha256", T.StringType(), False),
    ]
)
BANK_SCHEMA = T.StructType(
    [
        T.StructField("schema_version", T.StringType(), False),
        T.StructField("bank_record_id", T.StringType(), False),
        T.StructField("source_batch_id", T.StringType(), False),
        T.StructField("bank_account_id", T.StringType(), False),
        T.StructField("merchant_id", T.StringType(), False),
        T.StructField("settlement_reference", T.StringType(), True),
        T.StructField("direction", T.StringType(), False),
        T.StructField("amount_minor", T.LongType(), False),
        T.StructField("currency", T.StringType(), False),
        T.StructField("value_at", T.StringType(), False),
        T.StructField("received_at", T.StringType(), False),
        T.StructField("payload_sha256", T.StringType(), False),
    ]
)
_REQUIRED_FIELDS = {
    "events": tuple(
        field.name for field in EVENT_SCHEMA.fields if field.name != "reference_event_id"
    ),
    "settlements": tuple(field.name for field in SETTLEMENT_SCHEMA.fields),
    "journals": tuple(
        field.name
        for field in JOURNAL_SCHEMA.fields
        if field.name not in {"payment_id", "settlement_id", "settlement_cycle"}
    ),
    "banks": tuple(
        field.name for field in BANK_SCHEMA.fields if field.name != "settlement_reference"
    ),
}


@dataclass(frozen=True)
class SparkCandidates:
    transactions: DataFrame
    settlements: DataFrame
    allocations: DataFrame


@dataclass(frozen=True)
class MaterializationResult:
    root: Path | str
    transaction_count: int
    settlement_count: int
    allocation_count: int
    logical_sha256: str
    candidate_manifest_sha256: str


def _candidate_manifest(
    summaries: dict[str, dict[str, Any]],
    physical: list[dict[str, Any]],
    run_id: str,
    attempt_id: str,
    control_record_identity: str,
) -> tuple[dict[str, Any], str]:
    logical_sha = sha256(canonical_bytes(summaries)).hexdigest()
    manifest = {
        "schema_version": "1.0",
        "run_id": run_id,
        "attempt_id": attempt_id,
        "control_record_identity": control_record_identity,
        "transaction_count": int(summaries["transactions"]["count"]),
        "settlement_count": int(summaries["settlements"]["count"]),
        "allocation_count": int(summaries["bank-allocations"]["count"]),
        "logical_sha256": logical_sha,
        "physical_files": physical,
        "authoritative_proof": False,
    }
    return manifest, logical_sha


def _read_sources(spark: SparkSession, inputs: RuntimeInputs) -> dict[str, DataFrame]:
    paths = {key: [str(path) for path in value] for key, value in inputs.raw_paths.items()}
    strict_json = {"mode": "FAILFAST", "multiLine": "false", "timeZone": "UTC"}
    strict_csv = {
        "header": "true",
        "mode": "FAILFAST",
        "enforceSchema": "true",
        "multiLine": "false",
        "encoding": "UTF-8",
        "lineSep": "\n",
    }
    return {
        "events": spark.read.options(**strict_json)
        .schema(EVENT_SCHEMA)
        .json(paths["PROCESSOR_EVENTS"]),
        "settlements": spark.read.options(**strict_csv)
        .schema(SETTLEMENT_SCHEMA)
        .csv(paths["PROCESSOR_SETTLEMENTS"]),
        "journals": spark.read.options(**strict_json)
        .schema(JOURNAL_SCHEMA)
        .json(paths["LEDGER_JOURNALS"]),
        "banks": spark.read.options(**strict_csv).schema(BANK_SCHEMA).csv(paths["BANK_ENTRIES"]),
    }


def _payload_json(frame: DataFrame, excluded: tuple[str, ...]) -> Column:
    """Recreate the accepted canonical business payload with Spark expressions only."""
    names = sorted(name for name in frame.columns if name not in excluded)
    columns: list[Column] = []
    for name in names:
        if name == "postings":
            columns.append(
                F.transform(
                    F.col(name),
                    lambda posting: F.struct(
                        posting["account_role"].alias("account_role"),
                        posting["amount_minor"].alias("amount_minor"),
                        posting["line_id"].alias("line_id"),
                        posting["side"].alias("side"),
                    ),
                ).alias(name)
            )
        else:
            columns.append(F.col(name).alias(name))
    return F.to_json(F.struct(*columns), {"ignoreNullFields": "true"})


def _admit_source_frames(frames: dict[str, DataFrame]) -> dict[str, DataFrame]:
    """Fail closed on nulls, payload changes, and conflicting source identities."""
    identities = {
        "events": ("processor", "source_record_id"),
        "settlements": ("processor", "source_record_id"),
        "journals": ("ledger_system", "journal_id"),
        "banks": ("bank_account_id", "bank_record_id"),
    }
    admitted: dict[str, DataFrame] = {}
    for name, frame in frames.items():
        required = _REQUIRED_FIELDS[name]
        null_predicate = reduce(
            lambda left, right: left | right,
            (F.col(column).isNull() for column in required),
            F.lit(False),
        )
        if frame.filter(null_predicate).limit(1).count():
            raise Stage3Rejected("SCHEMA_VIOLATION", f"required source field is null: {name}")
        payload = _payload_json(frame, ("payload_sha256", "received_at", "source_batch_id"))
        checked = frame.withColumn("_computed_payload_sha256", F.sha2(payload, 256))
        if (
            checked.filter(F.col("_computed_payload_sha256") != F.col("payload_sha256"))
            .limit(1)
            .count()
        ):
            raise Stage3Rejected("SOURCE_IDENTITY_MISMATCH", f"payload digest: {name}")
        identity = list(identities[name])
        conflicts = checked.groupBy(*identity).agg(
            F.countDistinct("payload_sha256").alias("payload_versions")
        )
        if conflicts.filter(F.col("payload_versions") > 1).limit(1).count():
            raise Stage3Rejected("IDENTITY_CONFLICT", f"source identity: {name}")
        if name == "banks":
            admitted[name] = checked.drop("_computed_payload_sha256")
        else:
            admitted[name] = checked.dropDuplicates([*identity, "payload_sha256"]).drop(
                "_computed_payload_sha256"
            )
    return admitted


def _reconciliation_key(prefix: str, names: tuple[str, ...]) -> Column:
    ordered = sorted(names)
    payload = F.to_json(F.struct(*(F.col(name).alias(name) for name in ordered)))
    return F.concat(F.lit(prefix), F.sha2(payload, 256))


def _reason_array(order: tuple[str, ...], predicates: dict[str, Column]) -> Column:
    return F.array_compact(F.array(*(F.when(predicates[name], F.lit(name)) for name in order)))


def _array_union(left: str, right: str) -> Column:
    empty = F.array().cast(T.ArrayType(T.ArrayType(T.StringType())))
    return F.array_sort(
        F.array_distinct(F.concat(F.coalesce(F.col(left), empty), F.coalesce(F.col(right), empty)))
    )


def _transaction_candidates(
    events: DataFrame, journals: DataFrame, policy: dict[str, Any]
) -> DataFrame:
    keys = ["processor", "merchant_id", "payment_id", "event_class", "currency"]
    event_sign = F.when(F.col("event_type") == "CAPTURE", F.lit(1)).otherwise(F.lit(-1))
    event_rows = events.select(
        "processor",
        "merchant_id",
        "payment_id",
        F.col("event_type").alias("event_class"),
        "currency",
        "source_record_id",
        "reference_event_id",
        "amount_minor",
        (F.col("amount_minor").cast(T.DecimalType(38, 0)) * event_sign).alias("signed_minor"),
        F.array(F.lit("PROCESSOR_EVENT"), "processor", "source_record_id").alias("source_identity"),
    )
    processor = event_rows.groupBy(*keys).agg(
        F.sum("signed_minor").alias("processor_minor"),
        F.count(F.lit(1)).cast("long").alias("processor_record_count"),
        F.sort_array(F.collect_set("source_identity")).alias("processor_sources"),
    )
    captures = events.filter(F.col("event_type") == "CAPTURE").select(
        F.col("processor").alias("capture_processor"),
        F.col("source_record_id").alias("capture_id"),
        F.col("merchant_id").alias("capture_merchant"),
        F.col("payment_id").alias("capture_payment"),
        F.col("currency").alias("capture_currency"),
        F.col("amount_minor").alias("capture_amount"),
    )
    negatives = event_rows.filter(F.col("event_class") != "CAPTURE").join(
        captures,
        (F.col("processor") == F.col("capture_processor"))
        & (F.col("reference_event_id") == F.col("capture_id")),
        "left",
    )
    unresolved = (
        negatives.withColumn(
            "unresolved_reference",
            F.col("capture_id").isNull()
            | (F.col("merchant_id") != F.col("capture_merchant"))
            | (F.col("payment_id") != F.col("capture_payment"))
            | (F.col("currency") != F.col("capture_currency")),
        )
        .groupBy(*keys)
        .agg(F.max(F.col("unresolved_reference").cast("int")).alias("unresolved"))
    )
    applied = negatives.filter(F.col("capture_id").isNotNull()).withColumn(
        "application_minor", F.col("amount_minor").cast(T.DecimalType(38, 0))
    )
    over = applied.withColumn(
        "applied_total",
        F.sum("application_minor").over(Window.partitionBy("capture_processor", "capture_id")),
    ).withColumn("over_applied", F.col("applied_total") > F.col("capture_amount"))
    over = over.groupBy(*keys).agg(F.max(F.col("over_applied").cast("int")).alias("over"))
    posting_rows = journals.filter(F.col("entry_type").isin(*_TXN_EVENTS)).select(
        "processor",
        "merchant_id",
        "payment_id",
        F.col("entry_type").alias("event_class"),
        "currency",
        "journal_id",
        "ledger_system",
        F.explode("postings").alias("posting"),
    )
    allowed_roles = tuple(policy["transaction_rules"]["allowed_counterpart_roles"])
    journal_rows = (
        posting_rows.groupBy(*keys, "journal_id", "ledger_system")
        .agg(
            F.sum(
                F.when(F.col("posting.side") == "DEBIT", F.col("posting.amount_minor")).otherwise(0)
            ).alias("debit"),
            F.sum(
                F.when(F.col("posting.side") == "CREDIT", F.col("posting.amount_minor")).otherwise(
                    0
                )
            ).alias("credit"),
            F.sum(
                F.when(F.col("posting.account_role") == "PROCESSOR_CLEARING", 1).otherwise(0)
            ).alias("clearing_count"),
            F.sum(
                F.when(
                    F.col("posting.account_role") == "PROCESSOR_CLEARING",
                    F.col("posting.amount_minor").cast(T.DecimalType(38, 0))
                    * F.when(F.col("posting.side") == "DEBIT", 1).otherwise(-1),
                ).otherwise(0)
            ).alias("movement"),
            F.max(
                F.when(
                    (F.col("posting.account_role") == "PROCESSOR_CLEARING")
                    & (
                        ((F.col("event_class") == "CAPTURE") & (F.col("posting.side") != "DEBIT"))
                        | (
                            (F.col("event_class") != "CAPTURE")
                            & (F.col("posting.side") != "CREDIT")
                        )
                    ),
                    1,
                ).otherwise(0)
            ).alias("wrong_clearing_side"),
            F.max(
                F.when(
                    (F.col("posting.account_role") != "PROCESSOR_CLEARING")
                    & (~F.col("posting.account_role").isin(*allowed_roles)),
                    1,
                ).otherwise(0)
            ).alias("bad_counterpart"),
        )
        .withColumn(
            "invalid_role",
            (F.col("debit") != F.col("credit"))
            | (F.col("clearing_count") != 1)
            | (F.col("wrong_clearing_side") != 0)
            | (F.col("bad_counterpart") != 0),
        )
        .withColumn(
            "source_identity",
            F.array(F.lit("LEDGER_JOURNAL"), "ledger_system", "journal_id"),
        )
    )
    ledger = journal_rows.groupBy(*keys).agg(
        F.sum("movement").alias("ledger_minor"),
        F.count(F.lit(1)).cast("long").alias("ledger_journal_count"),
        F.max(F.col("invalid_role").cast("int")).alias("invalid_role"),
        F.sort_array(F.collect_set("source_identity")).alias("ledger_sources"),
    )
    joined = (
        processor.join(ledger, keys, "full_outer")
        .join(unresolved, keys, "left")
        .join(over, keys, "left")
    )
    joined = (
        joined.fillna(
            0,
            [
                "processor_record_count",
                "ledger_journal_count",
                "invalid_role",
                "unresolved",
                "over",
            ],
        )
        .withColumn(
            "processor_minor", F.coalesce("processor_minor", F.lit(0).cast(T.DecimalType(38, 0)))
        )
        .withColumn("ledger_minor", F.coalesce("ledger_minor", F.lit(0).cast(T.DecimalType(38, 0))))
        .withColumn(
            "processor_ledger_delta_minor", F.col("processor_minor") - F.col("ledger_minor")
        )
        .withColumn("difference_minor", F.abs("processor_ledger_delta_minor"))
    )
    tolerance_map = F.create_map(
        *[
            item
            for currency, rule in sorted(policy["currency_rules"].items())
            for item in (F.lit(currency), F.lit(int(rule["transaction_tolerance_minor"])))
        ]
    )
    owned = (
        (F.col("invalid_role") != 0)
        | (F.col("unresolved") != 0)
        | (F.col("over") != 0)
        | (F.col("processor_record_count") == 0)
        | (F.col("ledger_journal_count") == 0)
    )
    mismatch = (~owned) & (F.col("difference_minor") > tolerance_map[F.col("currency")])
    predicates = {
        "INVALID_ACCOUNT_ROLE": F.col("invalid_role") != 0,
        "UNRESOLVED_REFERENCE": F.col("unresolved") != 0,
        "OVER_APPLIED_REFERENCE": F.col("over") != 0,
        "MISSING_LEDGER_MOVEMENT": F.col("ledger_journal_count") == 0,
        "MISSING_PROCESSOR_ACTIVITY": F.col("processor_record_count") == 0,
        "PROCESSOR_LEDGER_MISMATCH": mismatch,
    }
    reasons = _reason_array(_TXN_REASON_ORDER, predicates)
    status = (
        F.when(owned | mismatch, "EXCEPTION")
        .when(F.col("difference_minor") == 0, "MATCHED")
        .otherwise("WITHIN_TOLERANCE")
    )
    reasons = F.when(
        (~owned) & (~mismatch) & (F.col("difference_minor") != 0),
        F.array(F.lit("TOLERATED_DIFFERENCE")),
    ).otherwise(reasons)
    key_names = tuple(keys)
    return joined.select(
        _reconciliation_key("txn:", key_names).alias("reconciliation_key"),
        F.struct(*(F.col(name).alias(name) for name in key_names)).alias("key_components"),
        F.struct(
            F.col("processor_minor").cast("long").alias("processor_minor"),
            F.col("ledger_minor").cast("long").alias("ledger_minor"),
            F.col("processor_ledger_delta_minor")
            .cast("long")
            .alias("processor_ledger_delta_minor"),
            F.col("difference_minor").cast("long").alias("difference_minor"),
            F.col("processor_record_count"),
            F.col("ledger_journal_count"),
        ).alias("totals"),
        status.alias("status"),
        reasons.alias("reason_codes"),
        _array_union("processor_sources", "ledger_sources").alias("source_identities"),
        F.lit(False).alias("authoritative_proof"),
    )


def _permitted_expression(policy: dict[str, Any]) -> Column:
    rows = policy["settlement_rules"]["permitted_bank_accounts"]
    predicates = [
        (F.col("merchant_id") == row["merchant_id"])
        & (F.col("currency") == row["currency"])
        & (F.col("bank_account_id").isin(*row["bank_account_ids"]))
        for row in rows
    ]
    return reduce(lambda left, right: left | right, predicates, F.lit(False))


def _settlement_candidates(
    settlements: DataFrame, journals: DataFrame, banks: DataFrame, policy: dict[str, Any]
) -> tuple[DataFrame, DataFrame]:
    keys = ["processor", "merchant_id", "settlement_id", "settlement_cycle", "currency"]
    processor_rows = settlements.withColumn(
        "recomputed_net",
        F.col("gross_minor").cast(T.DecimalType(38, 0))
        - F.col("fee_minor")
        - F.col("refund_minor")
        - F.col("chargeback_minor")
        - F.col("reserve_minor"),
    ).withColumn(
        "source_identity",
        F.array(F.lit("PROCESSOR_SETTLEMENT"), "processor", "source_record_id"),
    )
    processor = processor_rows.groupBy(*keys).agg(
        F.sum("recomputed_net").alias("processor_net_minor"),
        F.count(F.lit(1)).cast("long").alias("processor_settlement_count"),
        F.max((F.col("recomputed_net") != F.col("reported_net_minor")).cast("int")).alias(
            "formula_bad"
        ),
        F.sort_array(F.collect_set("source_identity")).alias("processor_sources"),
    )
    posting_rows = journals.filter(F.col("entry_type") == "SETTLEMENT").select(
        *keys,
        "journal_id",
        "ledger_system",
        F.explode("postings").alias("posting"),
    )
    journal_rows = (
        posting_rows.groupBy(*keys, "journal_id", "ledger_system")
        .agg(
            F.sum(
                F.when(F.col("posting.side") == "DEBIT", F.col("posting.amount_minor")).otherwise(0)
            ).alias("debit"),
            F.sum(
                F.when(F.col("posting.side") == "CREDIT", F.col("posting.amount_minor")).otherwise(
                    0
                )
            ).alias("credit"),
            F.sum(
                F.when(F.col("posting.account_role") == "PROCESSOR_CLEARING", 1).otherwise(0)
            ).alias("clearing_count"),
            F.sum(
                F.when(
                    F.col("posting.account_role") == "PROCESSOR_CLEARING",
                    F.col("posting.amount_minor").cast(T.DecimalType(38, 0))
                    * F.when(F.col("posting.side") == "CREDIT", 1).otherwise(-1),
                ).otherwise(0)
            ).alias("movement"),
        )
        .withColumn(
            "invalid_role",
            (F.col("debit") != F.col("credit")) | (F.col("clearing_count") != 1),
        )
        .withColumn(
            "source_identity",
            F.array(F.lit("LEDGER_JOURNAL"), "ledger_system", "journal_id"),
        )
    )
    ledger = journal_rows.groupBy(*keys).agg(
        F.sum("movement").alias("ledger_clearing_minor"),
        F.count(F.lit(1)).cast("long").alias("ledger_journal_count"),
        F.max(F.col("invalid_role").cast("int")).alias("invalid_role"),
        F.sort_array(F.collect_set("source_identity")).alias("ledger_sources"),
    )
    targets = (
        processor.select(*keys)
        .unionByName(ledger.select(*keys))
        .distinct()
        .withColumn("settlement_reconciliation_key", _reconciliation_key("stl:", tuple(keys)))
    )
    duplicate_banks = banks.groupBy("bank_account_id", "bank_record_id").agg(
        F.count(F.lit(1)).alias("identity_count")
    )
    bank_rows = (
        banks.join(duplicate_banks, ["bank_account_id", "bank_record_id"], "left")
        .withColumn("normalized_reference", F.trim("settlement_reference"))
        .withColumn(
            "signed_minor",
            F.col("amount_minor").cast(T.DecimalType(38, 0))
            * F.when(F.col("direction") == "CREDIT", 1).otherwise(-1),
        )
        .withColumn("account_permitted", _permitted_expression(policy))
        .withColumn(
            "source_identity",
            F.array(F.lit("BANK_ENTRY"), "bank_account_id", "bank_record_id"),
        )
    )
    joined_bank = bank_rows.alias("bank").join(
        targets.alias("target"),
        (F.col("bank.merchant_id") == F.col("target.merchant_id"))
        & (F.col("bank.currency") == F.col("target.currency"))
        & (F.col("bank.normalized_reference") == F.col("target.settlement_id")),
        "left",
    )
    ambiguity = joined_bank.groupBy("bank_account_id", "bank_record_id").agg(
        F.count("settlement_reconciliation_key").alias("targets")
    )
    if ambiguity.filter(F.col("targets") > 1).limit(1).count():
        raise Stage3Rejected("AMBIGUOUS_BANK_ALLOCATION", "reference has multiple targets")
    allocations = joined_bank.select(
        "source_identity",
        F.col("bank.merchant_id").alias("merchant_id"),
        F.col("bank.currency").alias("currency"),
        F.col("normalized_reference").alias("normalized_settlement_reference"),
        F.when(F.col("settlement_reconciliation_key").isNull(), "UNALLOCATED_UNKNOWN_REFERENCE")
        .otherwise("ALLOCATED")
        .alias("disposition"),
        "settlement_reconciliation_key",
        F.col("signed_minor").cast("long").alias("signed_minor"),
        F.when(F.col("settlement_reconciliation_key").isNull(), F.lit(None).cast("boolean"))
        .otherwise(F.col("account_permitted"))
        .alias("account_permitted"),
        (F.col("identity_count") > 1).alias("duplicate_current_bundle"),
        _reason_array(
            ("UNALLOCATED_BANK_MOVEMENT", "INVALID_BANK_ACCOUNT", "DUPLICATE_BANK_MOVEMENT"),
            {
                "UNALLOCATED_BANK_MOVEMENT": F.col("settlement_reconciliation_key").isNull(),
                "INVALID_BANK_ACCOUNT": F.col("settlement_reconciliation_key").isNotNull()
                & (~F.col("account_permitted")),
                "DUPLICATE_BANK_MOVEMENT": F.col("identity_count") > 1,
            },
        ).alias("reason_codes"),
    )
    allocated = (
        joined_bank.filter(F.col("settlement_reconciliation_key").isNotNull())
        .select(
            *[F.col(f"target.{name}").alias(name) for name in keys],
            "signed_minor",
            "source_identity",
            "account_permitted",
            (F.col("identity_count") > 1).alias("duplicate_bank"),
        )
        .groupBy(*keys)
        .agg(
            F.sum("signed_minor").alias("bank_minor"),
            F.count(F.lit(1)).cast("long").alias("allocated_bank_entry_count"),
            F.max((~F.col("account_permitted")).cast("int")).alias("invalid_bank"),
            F.max(F.col("duplicate_bank").cast("int")).alias("duplicate_bank"),
            F.sort_array(F.collect_set("source_identity")).alias("bank_sources"),
        )
    )
    joined = processor.join(ledger, keys, "full_outer").join(allocated, keys, "left")
    joined = joined.fillna(
        0,
        [
            "processor_settlement_count",
            "ledger_journal_count",
            "allocated_bank_entry_count",
            "formula_bad",
            "invalid_role",
            "invalid_bank",
            "duplicate_bank",
        ],
    )
    zero = F.lit(0).cast(T.DecimalType(38, 0))
    joined = (
        joined.withColumn("processor_net_minor", F.coalesce("processor_net_minor", zero))
        .withColumn("ledger_clearing_minor", F.coalesce("ledger_clearing_minor", zero))
        .withColumn("bank_minor", F.coalesce("bank_minor", zero))
        .withColumn(
            "processor_ledger_delta_minor",
            F.col("processor_net_minor") - F.col("ledger_clearing_minor"),
        )
        .withColumn(
            "processor_bank_delta_minor", F.col("processor_net_minor") - F.col("bank_minor")
        )
        .withColumn("ledger_bank_delta_minor", F.col("ledger_clearing_minor") - F.col("bank_minor"))
        .withColumn(
            "difference_minor",
            F.greatest(
                F.abs("processor_ledger_delta_minor"),
                F.abs("processor_bank_delta_minor"),
                F.abs("ledger_bank_delta_minor"),
            ),
        )
    )
    tolerance_map = F.create_map(
        *[
            item
            for currency, rule in sorted(policy["currency_rules"].items())
            for item in (F.lit(currency), F.lit(int(rule["settlement_tolerance_minor"])))
        ]
    )
    owned = (
        (F.col("invalid_role") != 0)
        | (F.col("formula_bad") != 0)
        | (F.col("invalid_bank") != 0)
        | (F.col("duplicate_bank") != 0)
        | (F.col("processor_settlement_count") == 0)
        | ((F.col("ledger_journal_count") == 0) & (F.col("processor_net_minor") != 0))
        | ((F.col("allocated_bank_entry_count") == 0) & (F.col("processor_net_minor") != 0))
    )
    outside = (~owned) & (F.col("difference_minor") > tolerance_map[F.col("currency")])
    predicates = {
        "INVALID_ACCOUNT_ROLE": F.col("invalid_role") != 0,
        "MISSING_LEDGER_MOVEMENT": (F.col("ledger_journal_count") == 0)
        & (F.col("processor_net_minor") != 0),
        "MISSING_PROCESSOR_ACTIVITY": F.col("processor_settlement_count") == 0,
        "MISSING_BANK_SETTLEMENT": (F.col("allocated_bank_entry_count") == 0)
        & (F.col("processor_net_minor") != 0),
        "UNALLOCATED_BANK_MOVEMENT": F.lit(False),
        "INVALID_BANK_ACCOUNT": F.col("invalid_bank") != 0,
        "DUPLICATE_BANK_MOVEMENT": F.col("duplicate_bank") != 0,
        "SETTLEMENT_FORMULA_MISMATCH": F.col("formula_bad") != 0,
        "PROCESSOR_LEDGER_MISMATCH": outside & (F.col("processor_ledger_delta_minor") != 0),
        "PROCESSOR_BANK_MISMATCH": outside & (F.col("processor_bank_delta_minor") != 0),
        "LEDGER_BANK_MISMATCH": outside & (F.col("ledger_bank_delta_minor") != 0),
    }
    reasons = _reason_array(_STL_REASON_ORDER, predicates)
    reasons = F.when(
        (~owned) & (~outside) & (F.col("difference_minor") != 0),
        F.array(F.lit("TOLERATED_DIFFERENCE")),
    ).otherwise(reasons)
    status = (
        F.when(owned | outside, "EXCEPTION")
        .when(F.col("difference_minor") == 0, "MATCHED")
        .otherwise("WITHIN_TOLERANCE")
    )
    sources = _array_union("processor_sources", "ledger_sources")
    empty = F.array().cast(T.ArrayType(T.ArrayType(T.StringType())))
    sources = F.array_sort(F.array_distinct(F.concat(sources, F.coalesce("bank_sources", empty))))
    candidates = joined.select(
        _reconciliation_key("stl:", tuple(keys)).alias("reconciliation_key"),
        F.struct(*(F.col(name).alias(name) for name in keys)).alias("key_components"),
        F.struct(
            *(
                F.col(name).cast("long").alias(name)
                for name in (
                    "processor_net_minor",
                    "ledger_clearing_minor",
                    "bank_minor",
                    "processor_ledger_delta_minor",
                    "processor_bank_delta_minor",
                    "ledger_bank_delta_minor",
                    "difference_minor",
                    "processor_settlement_count",
                    "ledger_journal_count",
                    "allocated_bank_entry_count",
                )
            )
        ).alias("totals"),
        status.alias("status"),
        reasons.alias("reason_codes"),
        sources.alias("source_identities"),
        F.lit(False).alias("authoritative_proof"),
    )
    return candidates, allocations


def reconcile_sources(spark: SparkSession, inputs: RuntimeInputs) -> SparkCandidates:
    ansi = spark.conf.get("spark.sql.ansi.enabled")
    if ansi is None or ansi.lower() != "true":
        raise Stage3Rejected("RUNTIME_VIOLATION", "Spark ANSI mode is required")
    if spark.conf.get("spark.sql.session.timeZone") != "UTC":
        raise Stage3Rejected("RUNTIME_VIOLATION", "Spark UTC session is required")
    frames = _admit_source_frames(_read_sources(spark, inputs))
    transactions = _transaction_candidates(frames["events"], frames["journals"], inputs.policy)
    settlements, allocations = _settlement_candidates(
        frames["settlements"], frames["journals"], frames["banks"], inputs.policy
    )
    return SparkCandidates(transactions, settlements, allocations)


def _logical_summary(frame: DataFrame) -> dict[str, Any]:
    encoded = frame.select(
        F.sha2(F.to_json(F.struct(*(F.col(name) for name in sorted(frame.columns)))), 256).alias(
            "row_sha"
        )
    )
    fields: list[Column] = [
        F.count(F.lit(1)).alias("count"),
        F.min("row_sha").alias("min"),
        F.max("row_sha").alias("max"),
    ]
    for index in range(5):
        start = index * 12 + 1
        fields.append(
            F.sum(
                F.conv(F.substring("row_sha", start, 12), 16, 10).cast(T.DecimalType(38, 0))
            ).alias(f"sum_{index}")
        )
    row = encoded.agg(*fields).first()
    assert row is not None
    return {
        key: str(value) if value is not None and key.startswith("sum_") else value
        for key, value in row.asDict(recursive=True).items()
    }


def _file_identity(path: Path) -> tuple[int, str]:
    size = 0
    digest = sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            size += len(chunk)
            digest.update(chunk)
    return size, digest.hexdigest()


def _managed_relative(prefix: str, path: str) -> str | None:
    if not path.startswith(prefix):
        raise Stage3Rejected("CANDIDATE_VIOLATION", "managed output escaped destination")
    relative = path[len(prefix) :]
    if any(part.startswith((".", "_")) for part in relative.split("/")):
        return None
    return relative


def _physical_inventory(prefix: str, rows: list[Any]) -> list[dict[str, Any]]:
    physical: list[dict[str, Any]] = []
    for row in sorted(rows, key=lambda value: str(value["path"])):
        relative = _managed_relative(prefix, str(row["path"]))
        if relative is not None:
            physical.append(
                {
                    "path": relative,
                    "size_bytes": int(row["size_bytes"]),
                    "sha256": row["sha256"],
                }
            )
    return physical


def materialize_candidates(
    candidates: SparkCandidates,
    destination: Path,
    run_id: str,
    attempt_id: str,
    control_record_identity: str,
) -> MaterializationResult:
    destination = destination.resolve()
    if destination.exists():
        raise Stage3Rejected("CANDIDATE_VIOLATION", "candidate destination already exists")
    partial = destination.with_name(f".{destination.name}.partial")
    if partial.exists():
        raise Stage3Rejected("CANDIDATE_VIOLATION", "partial candidate destination exists")
    partial.mkdir(parents=True)
    frames = {
        "transactions": candidates.transactions,
        "settlements": candidates.settlements,
        "bank-allocations": candidates.allocations,
    }
    summaries: dict[str, dict[str, Any]] = {}
    for name, frame in frames.items():
        frame.write.mode("errorifexists").parquet(str(partial / name))
        summaries[name] = _logical_summary(frame.sparkSession.read.parquet(str(partial / name)))
    physical = []
    for path in sorted(
        value
        for value in partial.rglob("*")
        if value.is_file()
        and not any(part.startswith((".", "_")) for part in value.relative_to(partial).parts)
    ):
        size, digest = _file_identity(path)
        physical.append(
            {"path": path.relative_to(partial).as_posix(), "size_bytes": size, "sha256": digest}
        )
    manifest, logical_sha = _candidate_manifest(
        summaries, physical, run_id, attempt_id, control_record_identity
    )
    transaction_count = int(manifest["transaction_count"])
    settlement_count = int(manifest["settlement_count"])
    allocation_count = int(manifest["allocation_count"])
    raw = canonical_bytes(manifest) + b"\n"
    with (partial / "candidate-manifest.json").open("xb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    manifest_sha = sha256(raw).hexdigest()
    completion = {
        "schema_version": "1.0",
        "candidate_manifest_file_sha256": manifest_sha,
        "logical_sha256": logical_sha,
        "authoritative_proof": False,
        "state": "COMPLETE_NON_AUTHORITATIVE_CANDIDATE",
    }
    with (partial / "COMPLETED.json").open("xb") as handle:
        handle.write(canonical_bytes(completion) + b"\n")
        handle.flush()
        os.fsync(handle.fileno())
    partial.rename(destination)
    return MaterializationResult(
        destination,
        transaction_count,
        settlement_count,
        allocation_count,
        logical_sha,
        manifest_sha,
    )


def materialize_candidates_uri(
    candidates: SparkCandidates,
    destination: str,
    run_id: str,
    attempt_id: str,
    control_record_identity: str,
) -> MaterializationResult:
    """Write a managed immutable candidate bundle and its marker last using Spark I/O."""
    if not destination.startswith("s3://") or destination.endswith("/"):
        raise Stage3Rejected("CANDIDATE_VIOLATION", "managed destination is not canonical")
    frames = {
        "transactions": candidates.transactions,
        "settlements": candidates.settlements,
        "bank-allocations": candidates.allocations,
    }
    summaries: dict[str, dict[str, Any]] = {}
    data_locations: list[str] = []
    for name, frame in frames.items():
        location = f"{destination}/{name}"
        frame.write.mode("errorifexists").parquet(location)
        summaries[name] = _logical_summary(frame.sparkSession.read.parquet(location))
        data_locations.append(location)
    spark = candidates.transactions.sparkSession
    file_rows = (
        spark.read.format("binaryFile")
        .load(data_locations)
        .select("path", F.col("length").alias("size_bytes"), F.sha2("content", 256).alias("sha256"))
        .collect()
    )
    physical = _physical_inventory(destination + "/", file_rows)
    manifest, logical_sha = _candidate_manifest(
        summaries, physical, run_id, attempt_id, control_record_identity
    )
    manifest_raw = canonical_bytes(manifest).decode("utf-8")
    manifest_sha = sha256((manifest_raw + "\n").encode()).hexdigest()
    spark.range(1).select(F.lit(manifest_raw).alias("value")).coalesce(1).write.mode(
        "errorifexists"
    ).text(f"{destination}/candidate-manifest")
    completion = {
        "schema_version": "1.0",
        "candidate_manifest_file_sha256": manifest_sha,
        "logical_sha256": logical_sha,
        "authoritative_proof": False,
        "state": "COMPLETE_NON_AUTHORITATIVE_CANDIDATE",
    }
    spark.range(1).select(
        F.lit(canonical_bytes(completion).decode("utf-8")).alias("value")
    ).coalesce(1).write.mode("errorifexists").text(f"{destination}/completion")
    return MaterializationResult(
        destination,
        int(manifest["transaction_count"]),
        int(manifest["settlement_count"]),
        int(manifest["allocation_count"]),
        logical_sha,
        manifest_sha,
    )
