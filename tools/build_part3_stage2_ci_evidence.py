#!/usr/bin/env python3
"""Build complete local-only Stage 2 CI evidence for independent inspection."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from hashlib import sha256
from pathlib import Path

from ledgerguard.stage2.control import ENTRY_COMMIT, MAIN_REF, REPOSITORY, require
from ledgerguard.stage2.evidence import finalize_artifact, write_json


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--local-evidence", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    args = parser.parse_args()
    root = Path.cwd()
    out = args.output_directory.resolve()
    out.mkdir(parents=True, exist_ok=False)
    local = json.loads(args.local_evidence.read_text())
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
    kind = os.environ["GITHUB_EVENT_NAME"]
    require(kind in {"pull_request", "push"}, "unsupported automatic CI event")
    expected = (
        event["pull_request"]["head"]["sha"] if kind == "pull_request" else os.environ["GITHUB_SHA"]
    )
    if kind == "push":
        require(os.environ["GITHUB_REF"] == MAIN_REF, "push must be main")
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    tree = subprocess.check_output(["git", "show", "-s", "--format=%T", "HEAD"], text=True).strip()
    require(commit == expected == os.environ["EXPECTED_SHA"], "CI head differs")
    subprocess.run(["git", "merge-base", "--is-ancestor", ENTRY_COMMIT, commit], check=True)
    require(
        local["clean_run_count"] == 2 and local["deterministic_equal"] is True,
        "two clean runs required",
    )
    require(local["execution_boundary"]["aws_execution"] is False, "local CI cannot claim AWS")
    envelope = {
        "schema_version": "1.0",
        "repository": REPOSITORY,
        "event": kind,
        "commit": commit,
        "tree": tree,
        "entry_commit": ENTRY_COMMIT,
        "pull_request_number": event.get("number") if kind == "pull_request" else None,
        "run_id": os.environ["GITHUB_RUN_ID"],
        "run_attempt": os.environ["GITHUB_RUN_ATTEMPT"],
        "workflow_ref": os.environ["GITHUB_WORKFLOW_REF"],
        "job": os.environ["GITHUB_JOB"],
        "local_payload_sha256": local["deterministic_payload_sha256"],
        "producer_state": "LOCAL_VALIDATION_FINISHED",
        "run_success_independently_required": True,
        "postmerge_verification_required": True,
        "aws_execution": False,
        "managed_reconciliation_started": False,
        "project_complete": False,
    }
    write_json(out / "ci-evidence.json", envelope)
    shutil.copyfile(args.local_evidence, out / "local-evidence.json")
    for number in (1, 2):
        source = args.local_evidence.parent / f"run-{number}"
        destination = out / f"run-{number}"
        destination.mkdir()
        for name in ("result.json", "collection.json", "pytest.xml", "coverage.json"):
            shutil.copyfile(source / name, destination / name)
        mutation_source = source / "mutations" / "results.json"
        shutil.copyfile(mutation_source, destination / "mutations.json")
    authority = {
        path: sha256((root / path).read_bytes()).hexdigest()
        for path in (
            "spec/part3-stage1-external-closure-v1.json",
            "spec/part3-stage2-baseline-freeze-v1.json",
            "spec/part3-stage2-requirement-adjudication-v1.json",
            "spec/part3-stage2-gate-registry-v1.json",
            "spec/part3-stage2-traceability-v1.json",
            "spec/part3-stage2-scenario-registry-v1.json",
            "spec/part3-stage2-code-mutations-v1.json",
            "spec/sources/part3-stage2-execution-plan-v1.md",
            ".github/workflows/part3-stage2-read-only.yml",
            ".github/workflows/part3-stage2-capability.yml",
            ".github/workflows/part3-stage2-recovery.yml",
            "tools/part3_stage2_extract_artifact.py",
            "tools/part3_stage2_inspect_artifact.py",
        )
    }
    write_json(out / "authority-digests.json", authority)
    write_json(
        out / "stage2-local-adjudication.json",
        {
            "schema_version": "1.0",
            "state": "IMPLEMENTATION_LOCALLY_VERIFIED_PENDING_EXTERNAL_CI_AND_AWS",
            "gates": {
                f"P3-S2-G{i:03d}": (
                    "LOCAL_VERIFIED" if i in {1, 2, 3, 4, 15} else "PENDING_EXTERNAL_VERIFICATION"
                )
                for i in range(1, 21)
            },
            "stage2_master_requirements": "22_OWNED_NOT_LIVE_VERIFIED",
            "aws_master_gates_executed": 0,
            "managed_reconciliation_started": False,
            "project_complete": False,
        },
    )
    finalize_artifact(out)


if __name__ == "__main__":
    main()
