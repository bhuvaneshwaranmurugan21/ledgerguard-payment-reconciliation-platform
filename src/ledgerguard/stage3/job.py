"""Thin Glue 5.1 entrypoint; business logic remains in DataFrame modules."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from ledgerguard.reconciliation.contracts import ContractRegistry

from .arguments import JobArguments, parse_job_arguments
from .canonical import canonical_digest
from .errors import Stage3Rejected
from .runtime_admission import RuntimeInputs, admit_runtime_bundle
from .spark_pipeline import materialize_candidates, materialize_candidates_uri, reconcile_sources


def _spark() -> Any:
    from pyspark import __version__ as spark_version
    from pyspark.sql import SparkSession

    if sys.version_info[:2] != (3, 11):
        raise Stage3Rejected("RUNTIME_VIOLATION", "Python 3.11 is required")
    if spark_version != "3.5.6":
        raise Stage3Rejected("RUNTIME_VIOLATION", "Spark 3.5.6 is required")
    return (
        SparkSession.builder.appName("ledgerguard-stage3")
        .config("spark.sql.ansi.enabled", "true")
        .config("spark.sql.session.timeZone", "UTC")
        .getOrCreate()
    )


def run_local(repository: Path, bundle_root: Path, output: Path) -> dict[str, Any]:
    """Run the installed-artifact correctness smoke without AWS access."""
    inputs = admit_runtime_bundle(repository, bundle_root)
    spark = _spark()
    try:
        candidates = reconcile_sources(spark, inputs)
        result = materialize_candidates(
            candidates,
            output,
            str(inputs.manifest["run_id"]),
            "attempt-local",
            "control-local",
        )
        return {
            "transaction_count": result.transaction_count,
            "settlement_count": result.settlement_count,
            "allocation_count": result.allocation_count,
            "logical_sha256": result.logical_sha256,
            "authoritative_proof": False,
        }
    finally:
        spark.stop()


def _read_document(spark: Any, uri: str) -> dict[str, Any]:
    rows = spark.read.format("binaryFile").load(uri).select("content").take(2)
    if len(rows) != 1:
        raise Stage3Rejected("ADMISSION_FAILURE", f"document identity is not singular: {uri}")
    try:
        value = json.loads(bytes(rows[0]["content"]))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise Stage3Rejected("ADMISSION_FAILURE", f"invalid document: {uri}") from error
    if not isinstance(value, dict):
        raise Stage3Rejected("ADMISSION_FAILURE", f"document is not an object: {uri}")
    return value


def _source_identity(spark: Any, uri: str) -> tuple[int, str]:
    from pyspark.sql import functions as F

    rows = (
        spark.read.format("binaryFile")
        .load(uri)
        .select(F.col("length").alias("size_bytes"), F.sha2("content", 256).alias("sha256"))
        .take(2)
    )
    if len(rows) != 1:
        raise Stage3Rejected("ADMISSION_FAILURE", f"source object identity is not singular: {uri}")
    return int(rows[0]["size_bytes"]), str(rows[0]["sha256"])


def _managed_inputs(spark: Any, arguments: JobArguments) -> RuntimeInputs:
    documents = {
        name: _read_document(spark, f"{arguments.input_prefix}/{name}.json")
        for name in ("policy", "run-manifest", "source-bundle")
    }
    policy = documents["policy"]
    manifest = documents["run-manifest"]
    source = documents["source-bundle"]
    registry = ContractRegistry.load_packaged()
    registry.validate("RECONCILIATION_POLICY", policy)
    registry.validate("RUN_MANIFEST", manifest)
    bindings = (
        (policy, "policy_sha256", arguments.policy_sha256),
        (manifest, "manifest_sha256", arguments.manifest_sha256),
        (source, "source_bundle_sha256", arguments.source_bundle_sha256),
    )
    for document, field, expected in bindings:
        actual = document.get(field)
        computed = canonical_digest({key: value for key, value in document.items() if key != field})
        if actual != expected or computed != expected:
            raise Stage3Rejected("SOURCE_IDENTITY_MISMATCH", field)
    if manifest.get("run_id") != arguments.run_id or source.get("run_id") != arguments.run_id:
        raise Stage3Rejected("SOURCE_IDENTITY_MISMATCH", "run_id")
    if manifest.get("source_commit") != arguments.source_commit:
        raise Stage3Rejected("SOURCE_IDENTITY_MISMATCH", "source_commit")
    if (
        source.get("policy_sha256") != arguments.policy_sha256
        or source.get("manifest_sha256") != arguments.manifest_sha256
    ):
        raise Stage3Rejected("SOURCE_IDENTITY_MISMATCH", "document binding")
    rows = source.get("objects")
    if not isinstance(rows, list):
        raise Stage3Rejected("ADMISSION_FAILURE", "source objects unavailable")
    raw: dict[str, list[str]] = {}
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("relative_path"), str):
            raise Stage3Rejected("ADMISSION_FAILURE", "invalid source object")
        relative = str(row["relative_path"])
        if not relative.startswith("raw/") or ".." in relative.split("/") or relative in seen:
            raise Stage3Rejected("ADMISSION_FAILURE", "unsafe source object path")
        seen.add(relative)
        family = str(row.get("family"))
        if family not in {
            "PROCESSOR_EVENTS",
            "PROCESSOR_SETTLEMENTS",
            "LEDGER_JOURNALS",
            "BANK_ENTRIES",
        }:
            raise Stage3Rejected("ADMISSION_FAILURE", "unknown source family")
        uri = f"{arguments.input_prefix}/{relative}"
        size, digest = _source_identity(spark, uri)
        if size != row.get("size_bytes") or digest != row.get("sha256"):
            raise Stage3Rejected("SOURCE_IDENTITY_MISMATCH", f"source object: {relative}")
        raw.setdefault(family, []).append(uri)
    if set(raw) != {
        "PROCESSOR_EVENTS",
        "PROCESSOR_SETTLEMENTS",
        "LEDGER_JOURNALS",
        "BANK_ENTRIES",
    }:
        raise Stage3Rejected("ADMISSION_FAILURE", "source family set incomplete")
    return RuntimeInputs(
        Path("."),
        policy,
        manifest,
        source,
        {key: tuple(value) for key, value in raw.items()},
    )


def main(argv: list[str] | None = None) -> int:
    arguments = parse_job_arguments(list(sys.argv[1:] if argv is None else argv))
    spark = _spark()
    try:
        inputs = _managed_inputs(spark, arguments)
        candidates = reconcile_sources(spark, inputs)
        materialize_candidates_uri(
            candidates,
            arguments.candidate_output_prefix,
            arguments.run_id,
            arguments.attempt_id,
            arguments.control_record_identity,
        )
    finally:
        spark.stop()
    return 0
