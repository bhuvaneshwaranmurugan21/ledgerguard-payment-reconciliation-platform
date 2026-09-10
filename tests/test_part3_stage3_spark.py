from __future__ import annotations

import ast
import json
from dataclasses import replace
from pathlib import Path

import pytest
from pyspark.sql import DataFrame, SparkSession

from ledgerguard.reconciliation import (
    admit_bundle,
    load_local_object_bytes,
    reconcile_settlements,
    reconcile_transactions,
)
from ledgerguard.stage3.errors import Stage3Rejected
from ledgerguard.stage3.formats import CSV_FIELDS, SOURCE_DIGEST_EXCLUSIONS
from ledgerguard.stage3.generator import _csv_line, generate_profile
from ledgerguard.stage3.profiles import get_profile
from ledgerguard.stage3.runtime_admission import admit_runtime_bundle
from ledgerguard.stage3.spark_pipeline import (
    _managed_relative,
    _physical_inventory,
    materialize_candidates,
    materialize_candidates_uri,
    reconcile_sources,
)

ROOT = Path(__file__).resolve().parents[1]
SOURCE_COMMIT = "d0fb01392f7f975909229f418c13a9c73ba8395e"


@pytest.fixture(scope="module")
def spark() -> SparkSession:
    session = (
        SparkSession.builder.master("local[2]")
        .appName("ledgerguard-part3-stage3-tests")
        .config("spark.ui.enabled", "false")
        .config("spark.sql.ansi.enabled", "true")
        .config("spark.sql.session.timeZone", "UTC")
        .getOrCreate()
    )
    session.sparkContext.setLogLevel("ERROR")
    yield session
    session.stop()


@pytest.fixture()
def small_asset(tmp_path: Path) -> Path:
    root = tmp_path / "asset"
    generate_profile(get_profile("correctness-small"), root, SOURCE_COMMIT)
    return root


def _accepted(
    root: Path,
) -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
    policy = (root / "policy.json").read_bytes()
    manifest_bytes = (root / "run-manifest.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    batch = admit_bundle(ROOT, policy, manifest_bytes, load_local_object_bytes(manifest, root))
    transactions = [row.value() for row in reconcile_transactions(batch).candidates]
    settlements = reconcile_settlements(batch)
    return (
        transactions,
        [row.value() for row in settlements.candidates],
        [row.value() for row in settlements.bank_allocations],
    )


def _rows(frame: DataFrame) -> list[dict[str, object]]:
    return sorted(
        (row.asDict(recursive=True) for row in frame.collect()),
        key=lambda row: json.dumps(row, sort_keys=True),
    )


def test_native_spark_matches_accepted_engine_on_all_candidate_surfaces(
    spark: SparkSession, small_asset: Path
) -> None:
    inputs = admit_runtime_bundle(ROOT, small_asset)
    actual = reconcile_sources(spark, inputs)
    expected_transactions, expected_settlements, expected_allocations = _accepted(small_asset)
    assert _rows(actual.transactions) == sorted(
        expected_transactions, key=lambda row: json.dumps(row, sort_keys=True)
    )
    assert _rows(actual.settlements) == sorted(
        expected_settlements, key=lambda row: json.dumps(row, sort_keys=True)
    )
    assert _rows(actual.allocations) == sorted(
        expected_allocations, key=lambda row: json.dumps(row, sort_keys=True)
    )
    assert all(not row["authoritative_proof"] for row in _rows(actual.transactions))


def test_spark_input_path_and_partition_order_are_logically_invariant(
    spark: SparkSession, small_asset: Path
) -> None:
    inputs = admit_runtime_bundle(ROOT, small_asset)
    first = reconcile_sources(spark, inputs)
    reversed_inputs = replace(
        inputs, raw_paths={key: tuple(reversed(value)) for key, value in inputs.raw_paths.items()}
    )
    second = reconcile_sources(spark, reversed_inputs)
    assert _rows(first.transactions.repartition(3)) == _rows(second.transactions.repartition(2))
    assert _rows(first.settlements.repartition(3)) == _rows(second.settlements.repartition(2))
    assert _rows(first.allocations.repartition(3)) == _rows(second.allocations.repartition(2))


def test_spark_payload_digest_tamper_fails_closed(spark: SparkSession, small_asset: Path) -> None:
    inputs = admit_runtime_bundle(ROOT, small_asset)
    path = next((small_asset / "raw/processor-events").glob("*.jsonl"))
    rows = path.read_text(encoding="utf-8").splitlines()
    value = json.loads(rows[0])
    value["amount_minor"] += 1
    rows[0] = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    with pytest.raises(Stage3Rejected, match="payload digest: events"):
        reconcile_sources(spark, inputs)


def test_spark_required_null_and_ambiguous_allocation_fail_closed(
    spark: SparkSession, small_asset: Path, tmp_path: Path
) -> None:
    from ledgerguard.stage3.canonical import canonical_bytes, canonical_digest

    inputs = admit_runtime_bundle(ROOT, small_asset)
    source = next((small_asset / "raw/processor-events").glob("*.jsonl"))
    event = json.loads(source.read_text(encoding="utf-8").splitlines()[0])
    event.pop("processor")
    event["payload_sha256"] = canonical_digest(
        {key: value for key, value in event.items() if key not in SOURCE_DIGEST_EXCLUSIONS}
    )
    invalid = tmp_path / "required-null.jsonl"
    invalid.write_bytes(canonical_bytes(event) + b"\n")
    null_inputs = replace(inputs, raw_paths={**inputs.raw_paths, "PROCESSOR_EVENTS": (invalid,)})
    with pytest.raises(Stage3Rejected, match="required source field is null"):
        reconcile_sources(spark, null_inputs)

    settlement_path = next((small_asset / "canonical/processor-settlements").glob("*.jsonl"))
    settlement = json.loads(settlement_path.read_text(encoding="utf-8").splitlines()[0])
    settlement["source_record_id"] = "settlement-record-ambiguous"
    settlement["processor"] = "processor-b"
    settlement["settlement_cycle"] = "cycle-ambiguous"
    settlement["payload_sha256"] = canonical_digest(
        {key: value for key, value in settlement.items() if key not in SOURCE_DIGEST_EXCLUSIONS}
    )
    ambiguous = tmp_path / "ambiguous.csv"
    ambiguous.write_bytes(
        (",".join(CSV_FIELDS["PROCESSOR_SETTLEMENTS"]) + "\n").encode()
        + _csv_line(settlement, CSV_FIELDS["PROCESSOR_SETTLEMENTS"])
    )
    ambiguous_inputs = replace(
        inputs,
        raw_paths={
            **inputs.raw_paths,
            "PROCESSOR_SETTLEMENTS": (*inputs.raw_paths["PROCESSOR_SETTLEMENTS"], ambiguous),
        },
    )
    with pytest.raises(Stage3Rejected, match="AMBIGUOUS_BANK_ALLOCATION"):
        reconcile_sources(spark, ambiguous_inputs)


def test_identical_event_replay_is_idempotent_in_native_spark(
    spark: SparkSession, small_asset: Path, tmp_path: Path
) -> None:
    inputs = admit_runtime_bundle(ROOT, small_asset)
    original = reconcile_sources(spark, inputs)
    source = next((small_asset / "raw/processor-events").glob("*.jsonl"))
    replay = tmp_path / "replay.jsonl"
    replay.write_bytes(source.read_bytes().splitlines(keepends=True)[0])
    mutated = replace(
        inputs,
        raw_paths={
            **inputs.raw_paths,
            "PROCESSOR_EVENTS": (*inputs.raw_paths["PROCESSOR_EVENTS"], replay),
        },
    )
    repeated = reconcile_sources(spark, mutated)
    assert _rows(original.transactions) == _rows(repeated.transactions)


def test_conflicting_event_identity_is_rejected_in_native_spark(
    spark: SparkSession, small_asset: Path, tmp_path: Path
) -> None:
    from ledgerguard.stage3.canonical import canonical_digest
    from ledgerguard.stage3.formats import SOURCE_DIGEST_EXCLUSIONS

    inputs = admit_runtime_bundle(ROOT, small_asset)
    source = next((small_asset / "raw/processor-events").glob("*.jsonl"))
    value = json.loads(source.read_text(encoding="utf-8").splitlines()[0])
    value["amount_minor"] += 1
    value["payload_sha256"] = canonical_digest(
        {key: item for key, item in value.items() if key not in SOURCE_DIGEST_EXCLUSIONS}
    )
    conflict = tmp_path / "conflict.jsonl"
    conflict.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    mutated = replace(
        inputs,
        raw_paths={
            **inputs.raw_paths,
            "PROCESSOR_EVENTS": (*inputs.raw_paths["PROCESSOR_EVENTS"], conflict),
        },
    )
    with pytest.raises(Stage3Rejected, match="IDENTITY_CONFLICT"):
        reconcile_sources(spark, mutated)


def test_spark_session_drift_fails_before_reconciliation(
    spark: SparkSession, small_asset: Path
) -> None:
    inputs = admit_runtime_bundle(ROOT, small_asset)
    spark.conf.set("spark.sql.ansi.enabled", "false")
    with pytest.raises(Stage3Rejected, match="ANSI mode"):
        reconcile_sources(spark, inputs)
    spark.conf.set("spark.sql.ansi.enabled", "true")
    spark.conf.set("spark.sql.session.timeZone", "Asia/Kolkata")
    with pytest.raises(Stage3Rejected, match="UTC session"):
        reconcile_sources(spark, inputs)
    spark.conf.set("spark.sql.session.timeZone", "UTC")


def test_candidate_materialization_is_immutable_digest_bound_and_non_authoritative(
    spark: SparkSession, small_asset: Path, tmp_path: Path
) -> None:
    candidates = reconcile_sources(spark, admit_runtime_bundle(ROOT, small_asset))
    destination = tmp_path / "candidate"
    result = materialize_candidates(
        candidates, destination, "run-00000001", "attempt-00000001", "control-00000001"
    )
    assert (destination / "COMPLETED.json").is_file()
    manifest = json.loads((destination / "candidate-manifest.json").read_text())
    completion = json.loads((destination / "COMPLETED.json").read_text())
    assert manifest["authoritative_proof"] is False
    assert completion["authoritative_proof"] is False
    assert completion["state"] == "COMPLETE_NON_AUTHORITATIVE_CANDIDATE"
    assert completion["candidate_manifest_file_sha256"] == result.candidate_manifest_sha256
    assert not any(
        path.name.casefold() in {"latest", "current", "active"} for path in destination.rglob("*")
    )
    with pytest.raises(Stage3Rejected, match="already exists"):
        materialize_candidates(
            candidates, destination, "run-00000001", "attempt-00000002", "control-00000001"
        )
    partial_destination = tmp_path / "partial-candidate"
    (tmp_path / ".partial-candidate.partial").mkdir()
    with pytest.raises(Stage3Rejected, match="partial candidate destination"):
        materialize_candidates(
            candidates,
            partial_destination,
            "run-00000001",
            "attempt-00000002",
            "control-00000001",
        )


def test_distributed_candidate_materialization_uses_physical_inventory_and_marker_last(
    spark: SparkSession, small_asset: Path, tmp_path: Path
) -> None:
    candidates = reconcile_sources(spark, admit_runtime_bundle(ROOT, small_asset))
    with pytest.raises(Stage3Rejected, match="managed destination is not canonical"):
        materialize_candidates_uri(
            candidates,
            str(tmp_path / "invalid"),
            "run-00000001",
            "attempt-00000001",
            "control-00000001",
        )

    class LocalUri(str):
        def startswith(self, prefix: str, start: int = 0, end: int | None = None) -> bool:
            if prefix == "s3://":
                return True
            return super().startswith(prefix, start, len(self) if end is None else end)

    uri = LocalUri(f"file:{tmp_path / 'managed'}")
    result = materialize_candidates_uri(
        candidates, uri, "run-00000001", "attempt-00000001", "control-00000001"
    )
    assert result.transaction_count == 16
    manifest_files = sorted((tmp_path / "managed/candidate-manifest").glob("part-*"))
    completion_files = sorted((tmp_path / "managed/completion").glob("part-*"))
    assert len(manifest_files) == len(completion_files) == 1
    manifest = json.loads(manifest_files[0].read_text())
    completion = json.loads(completion_files[0].read_text())
    assert manifest["physical_files"]
    assert all(row["size_bytes"] > 0 for row in manifest["physical_files"])
    assert completion["candidate_manifest_file_sha256"] == result.candidate_manifest_sha256
    assert (
        _managed_relative("s3://bucket/root/", "s3://bucket/root/data/part.parquet")
        == "data/part.parquet"
    )
    assert _managed_relative("s3://bucket/root/", "s3://bucket/root/data/_SUCCESS") is None
    rows = [
        {"path": "s3://bucket/root/data/_SUCCESS", "size_bytes": 0, "sha256": "0" * 64},
        {"path": "s3://bucket/root/data/part.parquet", "size_bytes": 1, "sha256": "1" * 64},
    ]
    assert _physical_inventory("s3://bucket/root/", rows) == [
        {"path": "data/part.parquet", "size_bytes": 1, "sha256": "1" * 64}
    ]
    with pytest.raises(Stage3Rejected, match="escaped destination"):
        _managed_relative("s3://bucket/root/", "s3://other/root/data.parquet")


def test_production_spark_source_has_no_candidate_input_or_python_udf() -> None:
    path = ROOT / "src/ledgerguard/stage3/spark_pipeline.py"
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert "ledgerguard_reference_oracle" not in imported
    assert "ledgerguard.stage3.generator" not in imported
    assert "reconcile_transactions" not in source
    assert "reconcile_settlements" not in source
    assert ".udf(" not in source and "pandas_udf" not in source
