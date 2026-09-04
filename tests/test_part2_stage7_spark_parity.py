from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from pyspark.sql import SparkSession

from ledgerguard.reconciliation import (
    SettlementCandidate,
    SettlementKey,
    TransactionCandidate,
    TransactionKey,
)
from ledgerguard_part2_stage7_spark import SparkParityError, verify_spark_parity


def transaction_candidates() -> tuple[TransactionCandidate, ...]:
    key1 = TransactionKey("stripe", "merchant-1", "payment-1", "CAPTURE", "INR")
    key2 = TransactionKey("stripe", "merchant-1", "payment-2", "REFUND", "INR")
    key3 = TransactionKey("stripe", "merchant-1", "payment-3", "CAPTURE", "INR")
    return (
        TransactionCandidate(
            key1.reconciliation_key,
            key1,
            9007199254740991,
            9007199254740991,
            0,
            0,
            1,
            1,
            "MATCHED",
            (),
            (("processor", "1"),),
            False,
        ),
        TransactionCandidate(
            key2.reconciliation_key,
            key2,
            -2500,
            -2400,
            -100,
            100,
            1,
            1,
            "EXCEPTION",
            ("PROCESSOR_LEDGER_MISMATCH",),
            (("processor", "2"), ("journal", "2")),
            False,
        ),
        TransactionCandidate(
            key3.reconciliation_key,
            key3,
            10000,
            9999,
            1,
            1,
            1,
            1,
            "WITHIN_TOLERANCE",
            ("TOLERATED_DIFFERENCE",),
            (("processor", "3"),),
            False,
        ),
    )


def settlement_candidates() -> tuple[SettlementCandidate, ...]:
    key1 = SettlementKey("stripe", "merchant-1", "settlement-1", "2026-09-04", "INR")
    key2 = SettlementKey("stripe", "merchant-1", "settlement-2", "2026-09-04", "INR")
    key3 = SettlementKey("stripe", "merchant-1", "settlement-3", "2026-09-04", "INR")
    return (
        SettlementCandidate(
            key1.reconciliation_key,
            key1,
            5000,
            5000,
            5000,
            0,
            0,
            0,
            0,
            1,
            1,
            1,
            "MATCHED",
            (),
            (("settlement", "1"),),
            False,
        ),
        SettlementCandidate(
            key2.reconciliation_key,
            key2,
            9007199254740991,
            9007199254740000,
            9007199254739000,
            991,
            1991,
            1000,
            1991,
            1,
            1,
            1,
            "EXCEPTION",
            ("PROCESSOR_BANK_MISMATCH", "LEDGER_BANK_MISMATCH"),
            (("settlement", "2"), ("bank", "2")),
            False,
        ),
        SettlementCandidate(
            key3.reconciliation_key,
            key3,
            100,
            100,
            99,
            0,
            1,
            1,
            1,
            1,
            1,
            1,
            "WITHIN_TOLERANCE",
            ("TOLERATED_DIFFERENCE",),
            (("settlement", "3"),),
            False,
        ),
    )


@pytest.fixture(scope="module")
def spark() -> SparkSession:
    session = (
        SparkSession.builder.master("local[2]")
        .appName("ledgerguard-part2-stage7-tests")
        .config("spark.ui.enabled", "false")
        .config("spark.sql.ansi.enabled", "true")
        .config("spark.sql.session.timeZone", "UTC")
        .getOrCreate()
    )
    session.sparkContext.setLogLevel("ERROR")
    yield session
    session.stop()


def test_p2s7_genuine_spark_parquet_logical_parity(spark: SparkSession, tmp_path: Path) -> None:
    assert spark.sparkContext.master == "local[2]"
    result = verify_spark_parity(
        spark, transaction_candidates(), settlement_candidates(), tmp_path / "parity"
    )
    assert result.transaction_rows == 3
    assert result.settlement_rows == 3
    assert len(result.logical_sha256) == 64
    assert len(result.parquet_sha256) == 64


def test_p2s7_partition_and_input_order_are_logically_invariant(
    spark: SparkSession, tmp_path: Path
) -> None:
    first = verify_spark_parity(
        spark, transaction_candidates(), settlement_candidates(), tmp_path / "first"
    )
    second = verify_spark_parity(
        spark,
        tuple(reversed(transaction_candidates())),
        tuple(reversed(settlement_candidates())),
        tmp_path / "second",
    )
    assert first.logical_sha256 == second.logical_sha256


def test_p2s7_existing_output_and_local_drift_fail_closed(
    spark: SparkSession, tmp_path: Path
) -> None:
    existing = tmp_path / "existing"
    existing.mkdir()
    with pytest.raises(SparkParityError, match="already exists"):
        verify_spark_parity(spark, transaction_candidates(), settlement_candidates(), existing)
    transaction = list(transaction_candidates())
    transaction[0] = replace(transaction[0], difference_minor=1)
    with pytest.raises(SparkParityError, match="transaction parity differs"):
        verify_spark_parity(
            spark, transaction, settlement_candidates(), tmp_path / "transaction-drift"
        )
    settlement = list(settlement_candidates())
    settlement[0] = replace(settlement[0], processor_bank_delta_minor=1)
    with pytest.raises(SparkParityError, match="settlement parity differs"):
        verify_spark_parity(
            spark, transaction_candidates(), settlement, tmp_path / "settlement-drift"
        )


def test_p2s7_session_drift_fails_closed(spark: SparkSession, tmp_path: Path) -> None:
    spark.conf.set("spark.sql.ansi.enabled", "false")
    with pytest.raises(SparkParityError, match="ANSI mode"):
        verify_spark_parity(
            spark, transaction_candidates(), settlement_candidates(), tmp_path / "ansi"
        )
    spark.conf.set("spark.sql.ansi.enabled", "true")
    spark.conf.set("spark.sql.session.timeZone", "Asia/Kolkata")
    with pytest.raises(SparkParityError, match="timezone"):
        verify_spark_parity(
            spark, transaction_candidates(), settlement_candidates(), tmp_path / "timezone"
        )
    spark.conf.set("spark.sql.session.timeZone", "UTC")
