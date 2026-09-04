#!/usr/bin/env python3
"""Build immutable exact-head CI evidence for a draft Stage 7 pull request."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from hashlib import sha256
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]


def required(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"Required CI environment variable is missing: {name}")
    return value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--local-evidence", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    args = parser.parse_args()
    local = json.loads(args.local_evidence.read_text())
    event = json.loads(Path(required("GITHUB_EVENT_PATH")).read_text())
    pr = event.get("pull_request")
    if not isinstance(pr, dict) or pr.get("draft") is not True:
        raise SystemExit("Stage 7 evidence requires a draft pull-request event")
    if pr["base"]["sha"] != "376e686813e6271e2d6787467a5500ba0827dfcb":
        raise SystemExit("Stage 7 pull request base is not the frozen Stage 6 closure")
    commit = str(pr["head"]["sha"])
    checked = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    if checked != commit:
        raise SystemExit("Checked-out commit differs from raw pull-request head")
    deterministic = local["deterministic_payload"]
    authority = deterministic["authority"]
    boundary = local["execution_boundary"]
    envelope: dict[str, Any] = {
        "schema_version": "1.0",
        "repository": required("GITHUB_REPOSITORY"),
        "commit_sha": commit,
        "checked_out_sha": checked,
        "base_sha": pr["base"]["sha"],
        "workflow_run_id": required("GITHUB_RUN_ID"),
        "workflow_run_attempt": required("GITHUB_RUN_ATTEMPT"),
        "pull_request_number": int(pr["number"]),
        "pull_request_draft": True,
        "python_version": deterministic["toolchain"]["python"],
        "java_major": deterministic["toolchain"]["java_major"],
        "spark_version": deterministic["toolchain"]["spark"],
        "py4j_version": deterministic["toolchain"]["py4j"],
        "clean_run_count": local["clean_run_count"],
        "deterministic_equal": local["deterministic_equal"],
        "deterministic_payload_sha256": local["deterministic_payload_sha256"],
        "stage7_candidate_digest": authority["stage7_candidate_digest"],
        "wheel_sha256": deterministic["wheel_sha256"],
        "test_counts": deterministic["test_counts"],
        "coverage_percent": deterministic["coverage"]["percent"],
        "coverage_statements": deterministic["coverage"]["statements"],
        "coverage_branches": deterministic["coverage"]["branches"],
        "mutation_checks": deterministic["mutations"]["checks"],
        "mutation_survivors": deterministic["mutations"]["survivors"],
        "stage6_closure_commit": authority["stage6_closure"]["commit"],
        "stage6_external_state": authority["stage6_closure"]["state"],
        "scenario_count": authority["failure_matrix"]["scenarios"],
        "reason_code_count": authority["failure_matrix"]["reason_codes"],
        "critical_path_count": authority["critical_paths"],
        "spark_execution": boundary["spark_executed"],
        "parquet_written_and_read": boundary["parquet_written_and_read"],
        "spark_authoritative": boundary["spark_authoritative"],
        "aws_api_called": boundary["aws_api_called"],
        "aws_workflow_dispatched": boundary["aws_workflow_dispatched"],
        "managed_persistence": boundary["managed_persistence"],
        "infrastructure_mutation": boundary["infrastructure_mutated"],
        "merge_authorized": boundary["merge_authorized"],
    }
    schema = json.loads((ROOT / "spec/part2-stage7-ci-evidence-v1.schema.json").read_text())
    errors = sorted(
        Draft202012Validator(schema).iter_errors(envelope), key=lambda row: list(row.path)
    )
    if errors:
        raise SystemExit(f"Stage 7 CI evidence is invalid: {errors[0].message}")
    destination = args.output_directory.resolve()
    if ROOT == destination or ROOT in destination.parents:
        raise SystemExit("CI evidence output must be outside the repository")
    destination.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(envelope, indent=2, sort_keys=True) + "\n"
    evidence = destination / "part2-stage7-ci-evidence.json"
    evidence.write_text(encoded)
    (destination / "manifest.json").write_text(
        json.dumps(
            {
                "artifact": evidence.name,
                "commit_sha": commit,
                "workflow_run_id": envelope["workflow_run_id"],
                "workflow_run_attempt": envelope["workflow_run_attempt"],
                "sha256": sha256(encoded.encode()).hexdigest(),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
