#!/usr/bin/env python3
"""Build immutable exact-event CI evidence for the Stage 2 closure candidate."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from hashlib import sha256
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from ledgerguard.stage2.evidence import finalize_artifact, write_json

ROOT = Path(__file__).resolve().parents[1]
QUALIFIED_COMMIT = "aa136331e44dcd181f766b42d76ee2616a22f435"


def required(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"Required CI environment variable is missing: {name}")
    return value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--local-evidence", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    arguments = parser.parse_args()
    local = json.loads(arguments.local_evidence.read_text(encoding="utf-8"))
    event = json.loads(Path(required("GITHUB_EVENT_PATH")).read_text(encoding="utf-8"))
    kind = required("GITHUB_EVENT_NAME")
    if kind not in {"pull_request", "push"}:
        raise SystemExit("closure evidence requires pull_request or main push")
    expected = (
        event["pull_request"]["head"]["sha"] if kind == "pull_request" else required("GITHUB_SHA")
    )
    if kind == "pull_request" and event["pull_request"]["base"]["sha"] != QUALIFIED_COMMIT:
        raise SystemExit("closure pull request base differs from qualified operational commit")
    if kind == "push" and required("GITHUB_REF") != "refs/heads/main":
        raise SystemExit("closure push must target main")
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    tree = subprocess.check_output(
        ["git", "show", "-s", "--format=%T", "HEAD"], cwd=ROOT, text=True
    ).strip()
    if commit != expected or commit != required("EXPECTED_SHA"):
        raise SystemExit("checked-out closure commit differs from exact event head")
    deterministic = local["deterministic_payload"]
    authority = deterministic["authority"]
    boundary = local["execution_boundary"]
    envelope: dict[str, Any] = {
        "schema_version": "1.0",
        "repository": required("GITHUB_REPOSITORY"),
        "event": kind,
        "commit": commit,
        "tree": tree,
        "qualified_operational_commit": authority["qualified_commit"],
        "run_id": required("GITHUB_RUN_ID"),
        "run_attempt": required("GITHUB_RUN_ATTEMPT"),
        "clean_run_count": local["clean_run_count"],
        "deterministic_equal": local["deterministic_equal"],
        "deterministic_payload_sha256": local["deterministic_payload_sha256"],
        "closure_candidate_digest": authority["closure_candidate_digest"],
        "wheel_sha256": deterministic["wheel_sha256"],
        "tests": deterministic["test_counts"],
        "coverage": {
            "percent": deterministic["coverage"]["percent"],
            "statements": deterministic["coverage"]["statements"],
            "branches": deterministic["coverage"]["branches"],
        },
        "mutations": {
            "checks": deterministic["mutations"]["checks"],
            "survivors": deterministic["mutations"]["survivors"],
        },
        "requirements_verified": authority["requirements_verified"],
        "stage2_gates_verified": authority["stage2_gates_verified"],
        "pending_external_gate": authority["stage2_gate_pending_external"],
        "master_gates_verified": authority["master_gates_verified"],
        "aws_api_called": boundary["aws_api_called"],
        "managed_reconciliation_started": boundary["managed_reconciliation_started"],
        "part3_complete": boundary["part3_complete"],
        "project_complete": boundary["project_complete"],
    }
    schema = json.loads(
        (ROOT / "spec/part3-stage2-closure-ci-evidence-v1.schema.json").read_text(encoding="utf-8")
    )
    Draft202012Validator.check_schema(schema)
    errors = sorted(
        Draft202012Validator(schema).iter_errors(envelope), key=lambda row: list(row.path)
    )
    if errors:
        raise SystemExit(f"closure CI evidence is invalid: {errors[0].message}")
    destination = arguments.output_directory.resolve()
    if ROOT == destination or ROOT in destination.parents:
        raise SystemExit("closure CI evidence output must be outside the repository")
    destination.mkdir(parents=True, exist_ok=False)
    write_json(destination / "closure-ci-evidence.json", envelope)
    shutil.copyfile(arguments.local_evidence, destination / "local-evidence.json")
    for relative in (
        "spec/part3-stage2-operational-freeze-v1.json",
        "spec/part3-stage2-requirement-adjudication-executed-v1.json",
        "spec/part3-stage2-gate-adjudication-v1.json",
        "spec/part3-stage2-master-gate-adjudication-v1.json",
    ):
        source = ROOT / relative
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    write_json(
        destination / "closure-authority-digests.json",
        {
            relative: sha256((ROOT / relative).read_bytes()).hexdigest()
            for relative in (
                "spec/part3-stage2-closure-ci-evidence-v1.schema.json",
                "src/ledgerguard_part3_stage2_closure.py",
                "src/ledgerguard_part3_stage2_closure_evidence.py",
                "tests/test_part3_closure_stage2.py",
                "tools/run_part3_stage2_closure.py",
                "tools/validate_part3_stage2_closure_run.py",
                "tools/build_part3_stage2_closure_ci_evidence.py",
            )
        },
    )
    finalize_artifact(destination)


if __name__ == "__main__":
    main()
