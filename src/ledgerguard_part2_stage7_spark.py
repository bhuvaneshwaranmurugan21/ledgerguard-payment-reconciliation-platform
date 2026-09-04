"""Typed Spark projection and parity checks for reconciliation candidates."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

from ledgerguard.reconciliation.canonical import canonical_json_bytes
from ledgerguard.reconciliation.settlement import SettlementCandidate
from ledgerguard.reconciliation.transaction import TransactionCandidate


class SparkParityError(ValueError):
    """Raised when Spark output is not logically identical to the local engine."""


@dataclass(frozen=True)
class SparkParityResult:
    transaction_rows: int
    settlement_rows: int
    logical_sha256: str
    parquet_sha256: str


def _transaction_rows(candidates: Sequence[TransactionCandidate]) -> list[dict[str, Any]]:
    return [
        candidate.value()
        for candidate in sorted(candidates, key=lambda row: row.reconciliation_key)
    ]


def _settlement_rows(candidates: Sequence[SettlementCandidate]) -> list[dict[str, Any]]:
    return [
        candidate.value()
        for candidate in sorted(candidates, key=lambda row: row.reconciliation_key)
    ]


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest_files(root: Path) -> str:
    inventory = [
        {"path": path.relative_to(root).as_posix(), "sha256": sha256(path.read_bytes()).hexdigest()}
        for path in sorted(root.rglob("*"))
        if path.is_file() and not path.name.startswith(".") and not path.name.startswith("_")
    ]
    return sha256(canonical_json_bytes(inventory)).hexdigest()


def verify_spark_parity(
    spark: Any,
    transaction_candidates: Sequence[TransactionCandidate],
    settlement_candidates: Sequence[SettlementCandidate],
    output: Path,
) -> SparkParityResult:
    """Recompute owned arithmetic in Spark, persist Parquet, and compare logical results."""
    from pyspark.sql import functions as functions
    from pyspark.sql.types import (
        ArrayType,
        BooleanType,
        LongType,
        StringType,
        StructField,
        StructType,
    )

    if spark.conf.get("spark.sql.ansi.enabled") != "true":
        raise SparkParityError("Spark ANSI mode is disabled")
    if spark.conf.get("spark.sql.session.timeZone") != "UTC":
        raise SparkParityError("Spark session timezone differs from UTC")
    if output.exists():
        raise SparkParityError("parity output already exists")
    output.mkdir(parents=True)
    decimal = "decimal(38,0)"
    base_fields = [
        StructField("reconciliation_key", StringType(), False),
        StructField("key_components_json", StringType(), False),
        StructField("reason_codes", ArrayType(StringType(), False), False),
        StructField("source_identities_json", StringType(), False),
        StructField("authoritative_proof", BooleanType(), False),
    ]
    transaction_schema = StructType(
        [
            *base_fields,
            StructField("processor_minor", LongType(), False),
            StructField("ledger_minor", LongType(), False),
            StructField("processor_record_count", LongType(), False),
            StructField("ledger_journal_count", LongType(), False),
            StructField("local_status", StringType(), False),
        ]
    )
    transaction_input = [
        (
            row.reconciliation_key,
            _json(row.key_components.value()),
            list(row.reason_codes),
            _json([list(identity) for identity in row.source_identities]),
            row.authoritative_proof,
            row.processor_minor,
            row.ledger_minor,
            row.processor_record_count,
            row.ledger_journal_count,
            row.status,
        )
        for row in transaction_candidates
    ]
    transaction = spark.createDataFrame(transaction_input, transaction_schema)
    transaction = (
        transaction.withColumn(
            "processor_ledger_delta_minor_decimal",
            functions.col("processor_minor").cast(decimal)
            - functions.col("ledger_minor").cast(decimal),
        )
        .withColumn(
            "difference_minor_decimal", functions.abs("processor_ledger_delta_minor_decimal")
        )
        .withColumn(
            "spark_status",
            functions.when(
                functions.size(
                    functions.array_except(
                        functions.col("reason_codes"),
                        functions.array(functions.lit("TOLERATED_DIFFERENCE")),
                    )
                )
                > 0,
                functions.lit("EXCEPTION"),
            )
            .when(functions.col("difference_minor_decimal") == 0, functions.lit("MATCHED"))
            .otherwise(functions.col("local_status")),
        )
        .orderBy("reconciliation_key")
    )

    settlement_schema = StructType(
        [
            *base_fields,
            StructField("processor_net_minor", LongType(), False),
            StructField("ledger_clearing_minor", LongType(), False),
            StructField("bank_minor", LongType(), False),
            StructField("processor_settlement_count", LongType(), False),
            StructField("ledger_journal_count", LongType(), False),
            StructField("allocated_bank_entry_count", LongType(), False),
            StructField("local_status", StringType(), False),
        ]
    )
    settlement_input = [
        (
            row.reconciliation_key,
            _json(row.key_components.value()),
            list(row.reason_codes),
            _json([list(identity) for identity in row.source_identities]),
            row.authoritative_proof,
            row.processor_net_minor,
            row.ledger_clearing_minor,
            row.bank_minor,
            row.processor_settlement_count,
            row.ledger_journal_count,
            row.allocated_bank_entry_count,
            row.status,
        )
        for row in settlement_candidates
    ]
    settlement = spark.createDataFrame(settlement_input, settlement_schema)
    settlement = (
        settlement.withColumn(
            "processor_ledger_delta_minor_decimal",
            functions.col("processor_net_minor").cast(decimal)
            - functions.col("ledger_clearing_minor").cast(decimal),
        )
        .withColumn(
            "processor_bank_delta_minor_decimal",
            functions.col("processor_net_minor").cast(decimal)
            - functions.col("bank_minor").cast(decimal),
        )
        .withColumn(
            "ledger_bank_delta_minor_decimal",
            functions.col("ledger_clearing_minor").cast(decimal)
            - functions.col("bank_minor").cast(decimal),
        )
        .withColumn(
            "difference_minor_decimal",
            functions.greatest(
                functions.abs("processor_ledger_delta_minor_decimal"),
                functions.abs("processor_bank_delta_minor_decimal"),
                functions.abs("ledger_bank_delta_minor_decimal"),
            ),
        )
        .withColumn(
            "spark_status",
            functions.when(
                functions.size(
                    functions.array_except(
                        functions.col("reason_codes"),
                        functions.array(functions.lit("TOLERATED_DIFFERENCE")),
                    )
                )
                > 0,
                functions.lit("EXCEPTION"),
            )
            .when(functions.col("difference_minor_decimal") == 0, functions.lit("MATCHED"))
            .otherwise(functions.col("local_status")),
        )
        .orderBy("reconciliation_key")
    )
    transaction_path = output / "transaction"
    settlement_path = output / "settlement"
    transaction.write.mode("errorifexists").parquet(str(transaction_path))
    settlement.write.mode("errorifexists").parquet(str(settlement_path))
    observed_transaction = (
        spark.read.parquet(str(transaction_path)).orderBy("reconciliation_key").collect()
    )
    observed_settlement = (
        spark.read.parquet(str(settlement_path)).orderBy("reconciliation_key").collect()
    )

    expected_transaction = _transaction_rows(transaction_candidates)
    expected_settlement = _settlement_rows(settlement_candidates)
    for observed, expected in zip(observed_transaction, expected_transaction, strict=True):
        totals = expected["totals"]
        actual = {
            "delta": int(observed["processor_ledger_delta_minor_decimal"]),
            "difference": int(observed["difference_minor_decimal"]),
            "status": observed["spark_status"],
            "reasons": list(observed["reason_codes"]),
        }
        wanted = {
            "delta": totals["processor_ledger_delta_minor"],
            "difference": totals["difference_minor"],
            "status": expected["status"],
            "reasons": expected["reason_codes"],
        }
        if actual != wanted:
            raise SparkParityError(f"transaction parity differs: {expected['reconciliation_key']}")
    for observed, expected in zip(observed_settlement, expected_settlement, strict=True):
        totals = expected["totals"]
        actual = {
            "processor_ledger": int(observed["processor_ledger_delta_minor_decimal"]),
            "processor_bank": int(observed["processor_bank_delta_minor_decimal"]),
            "ledger_bank": int(observed["ledger_bank_delta_minor_decimal"]),
            "difference": int(observed["difference_minor_decimal"]),
            "status": observed["spark_status"],
            "reasons": list(observed["reason_codes"]),
        }
        wanted = {
            "processor_ledger": totals["processor_ledger_delta_minor"],
            "processor_bank": totals["processor_bank_delta_minor"],
            "ledger_bank": totals["ledger_bank_delta_minor"],
            "difference": totals["difference_minor"],
            "status": expected["status"],
            "reasons": expected["reason_codes"],
        }
        if actual != wanted:
            raise SparkParityError(f"settlement parity differs: {expected['reconciliation_key']}")
    logical = {"transaction": expected_transaction, "settlement": expected_settlement}
    return SparkParityResult(
        transaction_rows=len(observed_transaction),
        settlement_rows=len(observed_settlement),
        logical_sha256=sha256(canonical_json_bytes(logical)).hexdigest(),
        parquet_sha256=_digest_files(output),
    )
