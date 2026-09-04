#!/usr/bin/env python3
"""Build immutable exact-head CI evidence for a draft Stage 6 pull request."""

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


def required_environment(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"Required CI environment variable is missing: {name}")
    return value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--local-evidence", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    arguments = parser.parse_args()
    local = json.loads(arguments.local_evidence.read_text())
    event = json.loads(Path(required_environment("GITHUB_EVENT_PATH")).read_text())
    pull_request = event.get("pull_request")
    if not isinstance(pull_request, dict):
        raise SystemExit("Stage 6 CI evidence requires a pull_request event")
    if pull_request.get("draft") is not True:
        raise SystemExit("Stage 6 evidence must be built while the pull request is draft")
    if pull_request["base"]["sha"] != "89373adf968ff7071693f8cce5d12901fd9b1e69":
        raise SystemExit("Stage 6 pull request base is not the frozen Stage 5 closure")
    commit_sha = str(pull_request["head"]["sha"])
    checked_out_sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    if checked_out_sha != commit_sha:
        raise SystemExit("Checked-out commit differs from the raw pull-request head")
    deterministic = local["deterministic_payload"]
    authority = deterministic["authority"]
    mutations = deterministic["mutations"]
    coverage = deterministic["coverage"]
    execution_boundary = local["execution_boundary"]
    envelope: dict[str, Any] = {
        "schema_version": "1.0",
        "repository": required_environment("GITHUB_REPOSITORY"),
        "commit_sha": commit_sha,
        "checked_out_sha": checked_out_sha,
        "base_sha": str(pull_request["base"]["sha"]),
        "workflow_run_id": required_environment("GITHUB_RUN_ID"),
        "workflow_run_attempt": required_environment("GITHUB_RUN_ATTEMPT"),
        "pull_request_number": int(pull_request["number"]),
        "pull_request_draft": True,
        "python_version": deterministic["toolchain"]["python"],
        "clean_run_count": local["clean_run_count"],
        "deterministic_equal": local["deterministic_equal"],
        "deterministic_payload_sha256": local["deterministic_payload_sha256"],
        "stage6_candidate_digest": authority["stage6_candidate_digest"],
        "wheel_sha256": deterministic["wheel_sha256"],
        "test_counts": deterministic["test_counts"],
        "coverage_percent": coverage["percent"],
        "coverage_statements": coverage["statements"],
        "coverage_branches": coverage["branches"],
        "mutation_checks": mutations["checks"],
        "mutation_survivors": mutations["survivors"],
        "stage5_closure_commit": authority["stage5_closure"]["commit"],
        "stage5_external_state": authority["stage5_closure"]["state"],
        "stage6_recovery_state": "VERIFIED_CANDIDATE",
        "deterministic_replay_state": authority["master_part2_gates"][
            "deterministic_replay_verified"
        ],
        "aws_execution": authority["aws_execution"],
        "aws_api_called": execution_boundary["aws_api_called"],
        "aws_workflow_dispatched": execution_boundary["aws_workflow_dispatched"],
        "spark_execution": execution_boundary["spark_executed"],
        "managed_persistence": execution_boundary["managed_persistence"],
        "infrastructure_mutation": execution_boundary["infrastructure_mutated"],
        "authoritative_local_proof_persisted": execution_boundary[
            "authoritative_local_proof_persisted"
        ],
        "merge_authorized": execution_boundary["merge_authorized"],
    }
    schema = json.loads((ROOT / "spec/part2-stage6-ci-evidence-v1.schema.json").read_text())
    Draft202012Validator.check_schema(schema)
    errors = sorted(
        Draft202012Validator(schema).iter_errors(envelope), key=lambda row: list(row.path)
    )
    if errors:
        raise SystemExit(f"Stage 6 CI evidence is invalid: {errors[0].message}")
    destination = arguments.output_directory.resolve()
    if ROOT == destination or ROOT in destination.parents:
        raise SystemExit("CI evidence output must be outside the repository")
    destination.mkdir(parents=True, exist_ok=True)
    evidence_path = destination / "part2-stage6-ci-evidence.json"
    encoded = json.dumps(envelope, indent=2, sort_keys=True) + "\n"
    evidence_path.write_text(encoded)
    manifest = {
        "artifact": evidence_path.name,
        "commit_sha": commit_sha,
        "workflow_run_id": envelope["workflow_run_id"],
        "workflow_run_attempt": envelope["workflow_run_attempt"],
        "sha256": sha256(encoded.encode()).hexdigest(),
    }
    (destination / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )


if __name__ == "__main__":
    main()
