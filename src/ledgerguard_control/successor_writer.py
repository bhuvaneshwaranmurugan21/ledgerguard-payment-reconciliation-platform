"""Stage 5 managed candidate writer with terminal Glue identity binding.

The accepted Stage 3 implementation stays byte-frozen.  This explicitly versioned
successor retains its Spark computation and strengthens only the managed marker
contract needed for cross-service ownership proof.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from hashlib import sha256
from typing import Any

from ledgerguard.stage3.canonical import canonical_bytes
from ledgerguard.stage3.errors import Stage3Rejected

_JOB_RUN = re.compile(r"jr_[0-9a-f]{64}")


@dataclass(frozen=True)
class MaterializationResult:
    root: str
    transaction_count: int
    settlement_count: int
    allocation_count: int
    logical_sha256: str
    candidate_manifest_sha256: str


def candidate_manifest(
    summaries: dict[str, dict[str, Any]],
    physical: list[dict[str, Any]],
    run_id: str,
    attempt_id: str,
    control_record_identity: str,
    glue_job_run_id: str,
) -> tuple[dict[str, Any], str]:
    if _JOB_RUN.fullmatch(glue_job_run_id) is None:
        raise Stage3Rejected("CANDIDATE_VIOLATION", "invalid Glue job run identity")
    logical_sha = sha256(canonical_bytes(summaries)).hexdigest()
    manifest = {
        "schema_version": "2.0",
        "run_id": run_id,
        "attempt_id": attempt_id,
        "control_record_identity": control_record_identity,
        "glue_job_run_id": glue_job_run_id,
        "transaction_count": int(summaries["transactions"]["count"]),
        "settlement_count": int(summaries["settlements"]["count"]),
        "allocation_count": int(summaries["bank-allocations"]["count"]),
        "logical_sha256": logical_sha,
        "physical_files": physical,
        "authoritative_proof": False,
    }
    return manifest, logical_sha


def materialize_candidates_uri(
    candidates: Any,
    destination: str,
    run_id: str,
    attempt_id: str,
    control_record_identity: str,
    glue_job_run_id: str,
) -> MaterializationResult:
    """Write data then a v2 manifest and completion marker last."""
    from pyspark.sql import functions as functions

    from ledgerguard.stage3.spark_pipeline import _logical_summary, _physical_inventory

    if not destination.startswith("s3://") or destination.endswith("/"):
        raise Stage3Rejected("CANDIDATE_VIOLATION", "managed destination is not canonical")
    frames = {
        "transactions": candidates.transactions,
        "settlements": candidates.settlements,
        "bank-allocations": candidates.allocations,
    }
    summaries: dict[str, dict[str, Any]] = {}
    locations: list[str] = []
    for name, frame in frames.items():
        location = f"{destination}/{name}"
        frame.write.mode("errorifexists").parquet(location)
        summaries[name] = _logical_summary(frame.sparkSession.read.parquet(location))
        locations.append(location)
    spark = candidates.transactions.sparkSession
    rows = (
        spark.read.format("binaryFile")
        .load(locations)
        .select(
            "path",
            functions.col("length").alias("size_bytes"),
            functions.sha2("content", 256).alias("sha256"),
        )
        .collect()
    )
    physical = _physical_inventory(destination + "/", rows)
    manifest, logical_sha = candidate_manifest(
        summaries,
        physical,
        run_id,
        attempt_id,
        control_record_identity,
        glue_job_run_id,
    )
    manifest_text = canonical_bytes(manifest).decode("utf-8")
    manifest_sha = sha256((manifest_text + "\n").encode()).hexdigest()
    spark.range(1).select(functions.lit(manifest_text).alias("value")).coalesce(1).write.mode(
        "errorifexists"
    ).text(f"{destination}/candidate-manifest")
    completion = {
        "schema_version": "2.0",
        "glue_job_run_id": glue_job_run_id,
        "candidate_manifest_file_sha256": manifest_sha,
        "logical_sha256": logical_sha,
        "authoritative_proof": False,
        "state": "COMPLETE_NON_AUTHORITATIVE_CANDIDATE",
    }
    spark.range(1).select(
        functions.lit(canonical_bytes(completion).decode("utf-8")).alias("value")
    ).coalesce(1).write.mode("errorifexists").text(f"{destination}/completion")
    return MaterializationResult(
        destination,
        int(manifest["transaction_count"]),
        int(manifest["settlement_count"]),
        int(manifest["allocation_count"]),
        logical_sha,
        manifest_sha,
    )
