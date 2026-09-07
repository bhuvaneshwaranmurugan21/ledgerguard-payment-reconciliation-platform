#!/usr/bin/env python3
"""Bundle complete local evidence from the actual GitHub event checkout."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from hashlib import sha256
from pathlib import Path
from typing import Any, cast

from jsonschema import Draft202012Validator

from ledgerguard_part3_stage1_evidence import build_manifest, envelope, verify_manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--local-evidence", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    args = parser.parse_args()
    root = Path.cwd()
    out = args.output_directory.resolve()
    out.mkdir(parents=True, exist_ok=False)
    local = cast(dict[str, Any], json.loads(args.local_evidence.read_text()))
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    tree = subprocess.check_output(["git", "show", "-s", "--format=%T", "HEAD"], text=True).strip()
    subprocess.run(
        ["git", "merge-base", "--is-ancestor", "cb81704adcfdfac5d93879cd6c189fc2213bbe79", "HEAD"],
        check=True,
    )
    result = envelope(dict(os.environ), event, local, commit, tree)
    result.update(
        expected_commit=os.environ["EXPECTED_SHA"],
        event_ref=os.environ["GITHUB_REF"],
        workflow_ref=os.environ["GITHUB_WORKFLOW_REF"],
        workflow_sha=os.environ["GITHUB_WORKFLOW_SHA"],
        job=os.environ["GITHUB_JOB"],
        toolchain=local["deterministic_payload"]["toolchain"],
        input_identities=local["deterministic_payload"]["deterministic"]["input_identities"],
    )
    schema = json.loads((root / "contracts/part3/ci-evidence-v1.schema.json").read_text())
    Draft202012Validator(schema).validate(result)
    (out / "ci-evidence.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    shutil.copyfile(args.local_evidence, out / "local-evidence.json")
    for i in (1, 2):
        run = args.local_evidence.parent / f"run-{i}"
        destination = out / f"run-{i}"
        destination.mkdir()
        report = json.loads((run / "result.json").read_bytes())
        if {k: report[k] for k in ("deterministic", "toolchain", "wheel_sha256")} != local[
            "deterministic_payload"
        ]:
            raise ValueError("raw clean run differs from aggregate evidence")
        if report["execution_boundary"]["aws_execution"] is not False:
            raise ValueError("raw clean run claims AWS execution")
        for name, digest in report["observations"]["reports"].items():
            if sha256((run / "observations" / name).read_bytes()).hexdigest() != digest:
                raise ValueError("raw observation differs")
        shutil.copytree(run / "observations", destination / "observations")
        for name in (
            "result.json",
            "collection.json",
            "execution-selection.json",
            "pytest.xml",
            "coverage.json",
            "coverage-scope.json",
            "mutations.json",
        ):
            shutil.copyfile(run / name, destination / name)
        for path in sorted((run / "mutations").glob("*/pytest.xml")):
            target = destination / "mutations" / path.parent.name
            target.mkdir(parents=True)
            for name in ("pytest.xml", "stdout.log", "stderr.log"):
                shutil.copyfile(path.parent / name, target / name)
    sources = [
        ".github/workflows/ci.yml",
        "requirements/part2-stage8-bootstrap.lock",
        "requirements/part2-stage8-py311.lock",
        "pyproject.toml",
        "contracts/part3/correction-provenance-v1.schema.json",
        "spec/part3-stage1-correction-golden-v1.json",
        "contracts/part2-part3-handoff-v1.json",
        "spec/part2-stage8-external-closure-freeze-v1.json",
        "spec/part2-master-conformance-addendum-v1.json",
        "spec/part3-requirements-v1.json",
        "spec/part3-source-index-v1.json",
        "spec/part3-master-gates-v1.json",
        "spec/part3-traceability-v1.json",
        "spec/part3-stage1-test-execution-v1.json",
        "spec/part3-stage1-code-mutations-v1.json",
        "spec/part3-stage1-coverage.ini",
        "spec/part3-stage1-gate-registry-v1.json",
        "spec/part3-stage1-scenario-traceability-v1.json",
        "docs/adr/0026-append-only-source-correction.md",
    ]
    for name in sources:
        target = out / "authority" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / name, target)
    registry = json.loads((root / "spec/part3-stage1-gate-registry-v1.json").read_bytes())
    if [row["gate_id"] for row in registry["gates"]] != [f"P3-S1-G{i:03d}" for i in range(1, 15)]:
        raise ValueError("Stage 1 gate inventory differs")
    adjudication = {
        "schema_version": "1.0",
        "commit": commit,
        "stage_state": "IN_PROGRESS_PENDING_EXTERNAL_CLOSURE",
        "gates": [
            dict(row, state=("LOCAL_VERIFIED" if i < 12 else "PENDING_EXTERNAL_VERIFICATION"))
            for i, row in enumerate(registry["gates"])
        ],
        "local_evidence": "local-evidence.json",
        "raw_runs": ["run-1/result.json", "run-2/result.json"],
        "source_gate_registry": "authority/spec/part3-stage1-gate-registry-v1.json",
        "stage1_carryovers": {
            key: "LOCAL_VERIFIED_PENDING_EXTERNAL_CLOSURE" for key in ("LG-P3-G002", "LG-P3-G004")
        },
        "aws_master_gates_executed": 0,
        "project_complete": False,
    }
    (out / "stage1-adjudication.json").write_text(
        json.dumps(adjudication, sort_keys=True, indent=2) + "\n"
    )
    # Evidence contains synthetic local cases and frozen target fingerprints only.
    for path in out.rglob("*"):
        if path.is_file():
            raw = path.read_bytes()
            if b"-----BEGIN PRIVATE KEY-----" in raw or b"-----BEGIN RSA PRIVATE KEY-----" in raw:
                raise ValueError("sensitive evidence forbidden")
    (out / "evidence-review.json").write_text(
        json.dumps(
            {
                "synthetic_case_evidence": True,
                "private_key_scan_passed": True,
                "target_identity": "frozen authority fingerprint; no new account identifier",
                "external_member_and_sensitive_evidence_inspection_required": True,
            },
            sort_keys=True,
            indent=2,
        )
        + "\n"
    )
    manifest = build_manifest(out)
    verify_manifest(out, manifest)
    (out / "manifest.json").write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n")


if __name__ == "__main__":
    main()
