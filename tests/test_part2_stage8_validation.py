from __future__ import annotations

import json
import runpy
import shutil
from pathlib import Path
from typing import Any, cast

import pytest
from jsonschema import Draft202012Validator

import ledgerguard_part2_stage8_validation as stage8_validation
from ledgerguard_part2_stage8_evidence import run_mutation_checks
from ledgerguard_part2_stage8_validation import Stage8Error, validate_stage8

ROOT = Path(__file__).resolve().parents[1]
IGNORED = shutil.ignore_patterns(".git", ".rsync-tmp", ".venv", "__pycache__", "*.egg-info")


def copy_repository(tmp_path: Path) -> Path:
    repository = tmp_path / "repository"
    shutil.copytree(ROOT, repository, ignore=IGNORED)
    return repository


def load(repository: Path, relative: str) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads((repository / relative).read_text(encoding="utf-8")))


def write(repository: Path, relative: str, value: object) -> None:
    (repository / relative).write_text(json.dumps(value), encoding="utf-8")


def test_p2s8_repository_contract_is_complete() -> None:
    result = validate_stage8(ROOT)
    assert result["stage7_closure"] == {
        "commit": "8fac3795ed0dac5284dd3b1595bd8fc9f6dc7344",
        "state": "EXTERNALLY_VERIFIED",
    }
    assert result["requirements"] == {"historical": 175, "total": 203}
    assert result["stage_gates"] == {"historical": 59, "total": 69}
    assert set(result["master_part2_gates"].values()) == {"EXTERNALLY_VERIFIED"}
    assert result["part2_state"] == "PART2_IN_PROGRESS"
    assert result["part2_closed"] is False


def test_p2s8_module_entrypoint_emits_candidate(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(ROOT)
    runpy.run_module("ledgerguard_part2_stage8_validation", run_name="__main__")
    assert json.loads(capsys.readouterr().out)["part2_state"] == "PART2_IN_PROGRESS"


def test_p2s8_completion_schema_has_a_non_self_referential_witness() -> None:
    schema = load(ROOT, "spec/part2-completion-authority-v1.schema.json")
    digest = "a" * 64
    witness = {
        "schema_version": "1.0",
        "project": "ledgerguard-payment-reconciliation-platform",
        "part": 2,
        "state": "LOCAL_RECONCILIATION_VERIFIED",
        "stage7_closure_sha256": digest,
        "promotion": {
            "pull_request": 17,
            "validated_head": "a" * 40,
            "validated_tree": "b" * 40,
            "squash_merge_commit": "c" * 40,
            "squash_merge_parent": "d" * 40,
            "parent_count": 1,
            "exact_head_ci_run": 1,
            "exact_head_ci_job": 2,
            "postmerge_main_ci_run": 3,
            "postmerge_main_ci_job": 4,
            "artifact_id": 5,
            "artifact_name": "ledgerguard-part2-stage8-example",
            "artifact_zip_sha256": digest,
            "manifest_sha256": digest,
            "evidence_sha256": digest,
            "deterministic_payload_sha256": digest,
            "wheel_sha256": digest,
            "conclusion": "SUCCESS",
        },
        "closure_attestation": {
            "method": "SEPARATE_CLOSURE_ATTESTATION_PULL_REQUEST",
            "promotion_base_required": True,
            "repository_record": "spec/part2-completion-authority-v1.json",
            "exact_head_ci_required": True,
            "squash_merge_required": True,
            "independent_main_ci_required": True,
        },
        "master_part2_completion_gates": {
            "independent_oracle_verified": "EXTERNALLY_VERIFIED",
            "spark_parity_verified": "EXTERNALLY_VERIFIED",
            "financial_invariants_verified": "EXTERNALLY_VERIFIED",
            "failure_matrix_verified": "EXTERNALLY_VERIFIED",
            "deterministic_replay_verified": "EXTERNALLY_VERIFIED",
            "critical_paths_tested": "EXTERNALLY_VERIFIED",
        },
        "claim_boundary": {
            "aws_execution": False,
            "aws_workflow_dispatched": False,
            "managed_persistence": False,
            "managed_reconciliation": False,
            "infrastructure_mutation": False,
            "performance_verified": False,
            "scale_verified": False,
            "production_operation": False,
            "project_complete": False,
        },
        "outcome": {
            "requirements_pass": 203,
            "stage_gates_pass": 69,
            "master_gates_pass": 6,
            "critical_findings": 0,
            "major_findings": 0,
            "remaining_part2_work": 0,
        },
    }
    assert list(Draft202012Validator(schema).iter_errors(witness)) == []


def test_p2s8_all_semantic_mutants_are_killed() -> None:
    result = run_mutation_checks(ROOT)
    assert result["checks"] == 14
    assert result["survivors"] == 0
    assert len(result["killed"]) == 14


def test_p2s8_non_object_json_fails_closed(tmp_path: Path) -> None:
    repository = copy_repository(tmp_path)
    write(repository, "spec/part2-stage8-coverage-v1.json", [])
    with pytest.raises(Stage8Error, match="JSON object required"):
        validate_stage8(repository)


def test_p2s8_invalid_stage7_authority_row_fails_closed(tmp_path: Path) -> None:
    repository = copy_repository(tmp_path)
    relative = "spec/part2-stage7-closure-freeze-v1.json"
    value = load(repository, relative)
    value["protected_authorities"] = {1: 2}
    write(repository, relative, value)
    with pytest.raises(Stage8Error, match="Stage 7 authority set differs"):
        validate_stage8(repository)


def test_p2s8_trace_authority_must_exist(tmp_path: Path) -> None:
    repository = copy_repository(tmp_path)
    relative = "spec/part2-stage8-traceability-v1.json"
    value = load(repository, relative)
    traces = cast(list[dict[str, Any]], value["traceability"])
    traces[0]["authorities"] = ["spec/does-not-exist.json"]
    write(repository, relative, value)
    with pytest.raises(Stage8Error, match="Stage 8 trace file missing"):
        validate_stage8(repository)


def test_p2s8_completion_ledger_source_error_fails_closed(tmp_path: Path) -> None:
    repository = copy_repository(tmp_path)
    relative = "spec/part2-stage1-traceability-v1.json"
    value = load(repository, relative)
    cast(list[dict[str, Any]], value["traceability"]).clear()
    write(repository, relative, value)
    with pytest.raises(Stage8Error, match="Part 2 ledger source invalid"):
        validate_stage8(repository)


def test_p2s8_master_gate_authority_must_exist(tmp_path: Path) -> None:
    repository = copy_repository(tmp_path)
    relative = "spec/part2-master-gate-adjudication-v1.json"
    value = load(repository, relative)
    rows = cast(list[dict[str, Any]], value["master_gates"])
    rows[0]["authorities"] = ["spec/does-not-exist.json"]
    write(repository, relative, value)
    with pytest.raises(Stage8Error, match="master gate authority missing"):
        validate_stage8(repository)


def test_p2s8_missing_required_artifact_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        stage8_validation,
        "STAGE8_ARTIFACTS",
        (*stage8_validation.STAGE8_ARTIFACTS, "spec/does-not-exist.json"),
    )
    with pytest.raises(Stage8Error, match="Stage 8 artifact missing"):
        validate_stage8(ROOT)
