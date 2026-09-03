from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from ledgerguard_part2_stage3_evidence import parse_junit_counts, run_mutation_checks
from ledgerguard_part2_stage3_validation import Stage3Error, validate_stage3
from tests.test_part2_stage3_admission import build_bundle

ROOT = Path(__file__).resolve().parents[1]


def test_p2s3_v001_complete_candidate_authority() -> None:
    result = validate_stage3(ROOT)
    assert result["stage2_closure"]["state"] == "EXTERNALLY_VERIFIED"
    assert result["stage_state"] == "PART2_STAGE3_ADMISSION_NORMALIZATION_VERIFIED_CANDIDATE"
    assert result["admission"]["authoritative_proofs_emitted"] == 0
    assert result["master_part2_gates"]["independent_oracle_verified"] == "EXTERNALLY_VERIFIED"
    assert result["master_part2_gates"]["financial_invariants_verified"] == "UNCLAIMED"


def test_p2s3_v002_targeted_mutations_have_no_survivors() -> None:
    result = run_mutation_checks(ROOT)
    assert result["checks"] == 15
    assert result["survivors"] == 0


def test_p2s3_v003_closure_authority_mutation_fails(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    shutil.copytree(ROOT, repository, ignore=shutil.ignore_patterns(".git"))
    target = repository / "docs/part2-stage2-reference-oracle.md"
    target.write_text(target.read_text() + "changed\n")
    with pytest.raises(Stage3Error, match="Stage 2 authority differs"):
        validate_stage3(repository)


def test_p2s3_v004_frozen_schema_mutation_fails(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    shutil.copytree(ROOT, repository, ignore=shutil.ignore_patterns(".git"))
    target = repository / "contracts/processor-event-v1.schema.json"
    target.write_text(target.read_text() + " ")
    with pytest.raises(Stage3Error, match="frozen v1 or accepted v2 schema differs"):
        validate_stage3(repository)


def test_p2s3_v005_junit_parser(tmp_path: Path) -> None:
    report = tmp_path / "pytest.xml"
    report.write_text(
        '<testsuites><testsuite tests="3" failures="0" errors="0" skipped="0"/>'
        '<testsuite tests="2" failures="1" errors="0" skipped="0"/></testsuites>'
    )
    assert parse_junit_counts(report) == {
        "tests": 5,
        "failures": 1,
        "errors": 0,
        "skipped": 0,
    }
    report.write_text("<testsuites/>")
    with pytest.raises(ValueError, match="no test suites"):
        parse_junit_counts(report)
    report.write_text('<testsuite tests="1" failures="2" errors="0" skipped="0"/>')
    with pytest.raises(ValueError, match="inconsistent"):
        parse_junit_counts(report)


def test_p2s3_v006_local_cli_success_and_owned_failure(tmp_path: Path) -> None:
    policy_bytes, manifest_bytes, supplied, manifest = build_bundle()
    policy_path = tmp_path / "policy.json"
    manifest_path = tmp_path / "manifest.json"
    object_root = tmp_path / "objects"
    object_root.mkdir()
    policy_path.write_bytes(policy_bytes)
    manifest_path.write_bytes(manifest_bytes)
    for descriptor in manifest["objects"]:
        relative = descriptor["relative_path"]
        (object_root / relative).write_bytes(supplied[f"local:{relative}"])
    command = [
        sys.executable,
        "-m",
        "ledgerguard_part2_stage3",
        "--repository",
        str(ROOT),
        "--policy",
        str(policy_path),
        "--manifest",
        str(manifest_path),
        "--input-root",
        str(object_root),
    ]
    environment = dict(os.environ, PYTHONPATH=str(ROOT / "src"))
    success = subprocess.run(
        command, cwd=ROOT, env=environment, check=True, text=True, capture_output=True
    )
    result = json.loads(success.stdout)
    assert result["outcome"] == "ADMITTED"
    assert result["authoritative_proof"] is False
    manifest_path.write_bytes(b"[]")
    rejected = subprocess.run(
        command, cwd=ROOT, env=environment, check=False, text=True, capture_output=True
    )
    assert rejected.returncode == 2
    assert json.loads(rejected.stdout)["reason_code"] == "SCHEMA_VIOLATION"
    command[command.index(str(policy_path))] = str(tmp_path / "missing-policy.json")
    missing = subprocess.run(
        command, cwd=ROOT, env=environment, check=False, text=True, capture_output=True
    )
    assert missing.returncode == 2
    assert json.loads(missing.stdout)["reason_code"] == "SOURCE_IDENTITY_MISMATCH"
