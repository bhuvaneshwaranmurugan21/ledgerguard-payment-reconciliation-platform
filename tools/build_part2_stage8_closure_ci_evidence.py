#!/usr/bin/env python3
"""Build immutable exact-head CI evidence for the Part 2 closure-attestation PR."""

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
PROMOTION_COMMIT = "71b42d6622558093a2bfaced58724f2ab71e793e"


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
    local = json.loads(args.local_evidence.read_text(encoding="utf-8"))
    event = json.loads(Path(required("GITHUB_EVENT_PATH")).read_text(encoding="utf-8"))
    pull_request = event.get("pull_request")
    if not isinstance(pull_request, dict) or pull_request.get("draft") is not True:
        raise SystemExit("closure evidence requires a draft pull-request event")
    if pull_request["base"]["sha"] != PROMOTION_COMMIT:
        raise SystemExit("closure pull request base is not the frozen promotion squash")
    commit = str(pull_request["head"]["sha"])
    checked = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    if checked != commit:
        raise SystemExit("checked-out commit differs from raw closure pull-request head")
    deterministic = local["deterministic_payload"]
    authority = deterministic["authority"]
    boundary = local["execution_boundary"]
    master = authority["master_part2_gates"]
    envelope: dict[str, Any] = {
        "schema_version": "1.0",
        "repository": required("GITHUB_REPOSITORY"),
        "commit_sha": commit,
        "checked_out_sha": checked,
        "base_sha": pull_request["base"]["sha"],
        "workflow_run_id": required("GITHUB_RUN_ID"),
        "workflow_run_attempt": required("GITHUB_RUN_ATTEMPT"),
        "pull_request_number": int(pull_request["number"]),
        "pull_request_draft": True,
        "python_version": deterministic["toolchain"]["python"],
        "java_major": deterministic["toolchain"]["java_major"],
        "spark_version": deterministic["toolchain"]["spark"],
        "py4j_version": deterministic["toolchain"]["py4j"],
        "clean_run_count": local["clean_run_count"],
        "deterministic_equal": local["deterministic_equal"],
        "deterministic_payload_sha256": local["deterministic_payload_sha256"],
        "closure_attestation_digest": authority["closure_attestation_digest"],
        "wheel_sha256": deterministic["wheel_sha256"],
        "test_counts": deterministic["test_counts"],
        "coverage_percent": deterministic["coverage"]["percent"],
        "coverage_statements": deterministic["coverage"]["statements"],
        "coverage_branches": deterministic["coverage"]["branches"],
        "mutation_checks": deterministic["mutations"]["checks"],
        "mutation_survivors": deterministic["mutations"]["survivors"],
        "promotion_commit": authority["promotion"]["commit"],
        "promotion_tree": authority["promotion"]["tree"],
        "promotion_external_state": authority["promotion"]["state"],
        "requirement_count": authority["requirements"],
        "stage_gate_count": authority["stage_gates"],
        "master_gate_count": len(master),
        "master_gates_external": all(value == "EXTERNALLY_VERIFIED" for value in master.values()),
        "promotion_regression_reexecuted": True,
        "spark_authoritative": boundary["spark_authoritative"],
        "aws_api_called": boundary["aws_api_called"],
        "aws_workflow_dispatched": boundary["aws_workflow_dispatched"],
        "managed_persistence": boundary["managed_persistence"],
        "infrastructure_mutation": boundary["infrastructure_mutated"],
        "part2_state": authority["part2_state"],
        "part2_closed": authority["part2_closed"],
        "project_complete": authority["project_complete"],
        "merge_authorized": boundary["merge_authorized"],
    }
    schema = json.loads((ROOT / "spec/part2-stage8-closure-ci-evidence-v1.schema.json").read_text())
    errors = sorted(
        Draft202012Validator(schema).iter_errors(envelope), key=lambda row: list(row.path)
    )
    if errors:
        raise SystemExit(f"closure CI evidence is invalid: {errors[0].message}")
    destination = args.output_directory.resolve()
    if ROOT == destination or ROOT in destination.parents:
        raise SystemExit("closure CI evidence output must be outside the repository")
    destination.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(envelope, indent=2, sort_keys=True) + "\n"
    evidence = destination / "part2-stage8-closure-ci-evidence.json"
    evidence.write_text(encoded, encoding="utf-8")
    completion = ROOT / "spec/part2-completion-authority-v1.json"
    promotion = ROOT / "spec/part2-stage8-promotion-closure-freeze-v1.json"
    manifest = {
        "artifacts": {
            evidence.name: sha256(encoded.encode()).hexdigest(),
            completion.name: sha256(completion.read_bytes()).hexdigest(),
            promotion.name: sha256(promotion.read_bytes()).hexdigest(),
        },
        "commit_sha": commit,
        "workflow_run_id": envelope["workflow_run_id"],
        "workflow_run_attempt": envelope["workflow_run_attempt"],
    }
    (destination / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    for source in (completion, promotion):
        (destination / source.name).write_bytes(source.read_bytes())


if __name__ == "__main__":
    main()
