#!/usr/bin/env python3
"""Execute one clean, repository-local Stage 3 qualification payload."""

from __future__ import annotations

import argparse
import json
import resource
import shutil
import subprocess
import sys
import tempfile
import time
from hashlib import sha256
from pathlib import Path
from typing import Any

from ledgerguard.stage3.campaign import run_campaign
from ledgerguard.stage3.canonical import canonical_bytes
from ledgerguard.stage3.expectations import verify_assets
from ledgerguard.stage3.generator import generate_profile
from ledgerguard.stage3.job import run_local
from ledgerguard.stage3.profiles import PROFILES
from tools.build_part3_stage3_runtime import build_bundle
from tools.inspect_part3_stage3_artifact import inspect_runtime_bundle


def _file_sha(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _commit_epoch(repository: Path, source_commit: str) -> int:
    value = subprocess.check_output(
        ["git", "show", "-s", "--format=%ct", source_commit],
        cwd=repository,
        text=True,
    ).strip()
    if not value.isdigit() or int(value) < 315532800:
        raise SystemExit("source commit timestamp is invalid")
    return int(value)


def _copy_documents(source: Path, destination: Path) -> dict[str, str]:
    destination.mkdir(parents=True)
    result: dict[str, str] = {}
    for name in (
        "profile-lock.json",
        "scenario-inventory.json",
        "policy.json",
        "run-manifest.json",
        "source-bundle.json",
        "expectations.json",
        "asset-manifest.json",
        "COMPLETED.json",
    ):
        target = destination / name
        shutil.copy2(source / name, target)
        result[name] = _file_sha(target)
    return result


def execute_one(
    repository: Path, output: Path, source_commit: str, source_tree: str
) -> dict[str, Any]:
    if sys.version_info[:3] != (3, 11, 13):
        raise SystemExit("Stage 3 qualification requires exact CPython 3.11.13")
    if output.exists() and any(output.iterdir()):
        raise SystemExit("Stage 3 qualification output must be empty")
    output.mkdir(parents=True, exist_ok=True)
    profiles: dict[str, Any] = {}
    campaign: dict[str, Any] | None = None
    spark: dict[str, Any] | None = None
    spark_physical_evidence: dict[str, str] | None = None
    telemetry: dict[str, Any] = {}
    for name, profile in PROFILES.items():
        with tempfile.TemporaryDirectory(prefix=f"ledgerguard-stage3-{name}-") as temporary:
            asset = Path(temporary) / "asset"
            started = time.monotonic()
            generation = generate_profile(profile, asset, source_commit)
            readback = verify_assets(asset)
            elapsed = time.monotonic() - started
            documents = _copy_documents(asset, output / "profiles" / name)
            asset_manifest = json.loads((asset / "asset-manifest.json").read_text())
            profiles[name] = {
                "dataset_id": generation.dataset_id,
                "run_id": generation.run_id,
                "source_bundle_sha256": generation.source_bundle_sha256,
                "manifest_sha256": generation.manifest_sha256,
                "asset_manifest_sha256": generation.asset_manifest_sha256,
                "counts": generation.counts,
                "readback_logical_sha256": readback.logical_sha256,
                "verified_file_count": readback.verified_file_count,
                "inventory": asset_manifest["files"],
                "document_file_sha256": documents,
            }
            telemetry[name] = {
                "elapsed_seconds": round(elapsed, 6),
                "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            }
            if name == "correctness-small":
                campaign_result = run_campaign(asset)
                campaign = {
                    "seed": campaign_result.seed,
                    "case_count": campaign_result.case_count,
                    "campaign_sha256": campaign_result.campaign_sha256,
                    "cases": list(campaign_result.cases),
                }
                candidate = Path(temporary) / "candidate"
                spark_result = run_local(repository, asset, candidate)
                shutil.copy2(
                    candidate / "candidate-manifest.json", output / "spark-candidate-manifest.json"
                )
                shutil.copy2(candidate / "COMPLETED.json", output / "spark-COMPLETED.json")
                spark = {
                    key: spark_result[key]
                    for key in (
                        "transaction_count",
                        "settlement_count",
                        "allocation_count",
                        "logical_sha256",
                        "authoritative_proof",
                    )
                }
                spark_physical_evidence = {
                    "candidate_manifest_file_sha256": _file_sha(
                        output / "spark-candidate-manifest.json"
                    ),
                    "completion_file_sha256": _file_sha(output / "spark-COMPLETED.json"),
                }
    if campaign is None or spark is None or spark_physical_evidence is None:
        raise SystemExit("correctness qualification did not execute")
    runtime_output = output / "runtime"
    package = build_bundle(
        repository,
        Path(sys.prefix),
        runtime_output,
        source_commit,
        source_tree,
        _commit_epoch(repository, source_commit),
    )
    inspection = inspect_runtime_bundle(runtime_output / "ledgerguard-stage3-glue-runtime.zip")
    deterministic = {
        "source_commit": source_commit,
        "source_tree": source_tree,
        "profiles": profiles,
        "campaign": campaign,
        "spark": spark,
        "package": package,
        "package_inspection": inspection,
        "aws_execution": False,
        "managed_workload_execution": False,
        "authoritative_proof": False,
    }
    result = {
        "schema_version": "1.0",
        "deterministic_payload": deterministic,
        "deterministic_payload_sha256": sha256(canonical_bytes(deterministic)).hexdigest(),
        "spark_physical_evidence": spark_physical_evidence,
        "telemetry": telemetry,
        "toolchain": {
            "python": ".".join(map(str, sys.version_info[:3])),
            "spark": "3.5.6",
            "java": "17",
            "aws_glue_target": "5.1",
        },
        "verdict": "PASS",
    }
    (output / "validation-result.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--source-tree", required=True)
    arguments = parser.parse_args()
    execute_one(
        arguments.repository.resolve(),
        arguments.output.resolve(),
        arguments.source_commit,
        arguments.source_tree,
    )


if __name__ == "__main__":
    main()
