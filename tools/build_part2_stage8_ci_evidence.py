#!/usr/bin/env python3
"""Build immutable exact-head CI evidence for a draft Stage 8 promotion PR."""

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
STAGE7_MAIN = "8fac3795ed0dac5284dd3b1595bd8fc9f6dc7344"


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
        raise SystemExit("Stage 8 evidence requires a draft pull-request event")
    if pull_request["base"]["sha"] != STAGE7_MAIN:
        raise SystemExit("Stage 8 pull request base is not the frozen Stage 7 closure")
    commit = str(pull_request["head"]["sha"])
    checked = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    if checked != commit:
        raise SystemExit("Checked-out commit differs from raw pull-request head")
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
        "stage8_candidate_digest": authority["stage8_candidate_digest"],
        "wheel_sha256": deterministic["wheel_sha256"],
        "test_counts": deterministic["test_counts"],
        "coverage_percent": deterministic["coverage"]["percent"],
        "coverage_statements": deterministic["coverage"]["statements"],
        "coverage_branches": deterministic["coverage"]["branches"],
        "mutation_checks": deterministic["mutations"]["checks"],
        "mutation_survivors": deterministic["mutations"]["survivors"],
        "stage7_closure_commit": authority["stage7_closure"]["commit"],
        "stage7_external_state": authority["stage7_closure"]["state"],
        "requirement_count": authority["requirements"]["total"],
        "stage_gate_count": authority["stage_gates"]["total"],
        "master_gate_count": len(master),
        "master_gates_external": all(value == "EXTERNALLY_VERIFIED" for value in master.values()),
        "spark_reexecuted": boundary["spark_reexecuted"],
        "spark_authoritative": boundary["spark_authoritative"],
        "aws_api_called": boundary["aws_api_called"],
        "aws_workflow_dispatched": boundary["aws_workflow_dispatched"],
        "managed_persistence": boundary["managed_persistence"],
        "infrastructure_mutation": boundary["infrastructure_mutated"],
        "part2_closed": boundary["part2_closed"],
        "closure_attestation_required": boundary["closure_attestation_required"],
        "merge_authorized": boundary["merge_authorized"],
    }
    schema = json.loads((ROOT / "spec/part2-stage8-ci-evidence-v1.schema.json").read_text())
    errors = sorted(
        Draft202012Validator(schema).iter_errors(envelope), key=lambda row: list(row.path)
    )
    if errors:
        raise SystemExit(f"Stage 8 CI evidence is invalid: {errors[0].message}")
    destination = args.output_directory.resolve()
    if ROOT == destination or ROOT in destination.parents:
        raise SystemExit("CI evidence output must be outside the repository")
    destination.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(envelope, indent=2, sort_keys=True) + "\n"
    evidence = destination / "part2-stage8-ci-evidence.json"
    evidence.write_text(encoded, encoding="utf-8")
    ledger = ROOT / "spec/part2-requirement-ledger-v1.json"
    gates = ROOT / "spec/part2-gate-adjudication-v1.json"
    manifest = {
        "artifacts": {
            evidence.name: sha256(encoded.encode()).hexdigest(),
            ledger.name: sha256(ledger.read_bytes()).hexdigest(),
            gates.name: sha256(gates.read_bytes()).hexdigest(),
        },
        "commit_sha": commit,
        "workflow_run_id": envelope["workflow_run_id"],
        "workflow_run_attempt": envelope["workflow_run_attempt"],
    }
    (destination / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    shutil_targets = ((ledger, destination / ledger.name), (gates, destination / gates.name))
    for source, target in shutil_targets:
        target.write_bytes(source.read_bytes())


if __name__ == "__main__":
    main()
