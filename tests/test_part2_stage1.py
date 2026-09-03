from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from ledgerguard_part2_stage1 import Stage1Error, validate_stage1
from ledgerguard_part2_stage1_evidence import parse_junit_counts

ROOT = Path(__file__).resolve().parents[1]


def _copy(tmp_path: Path) -> Path:
    destination = tmp_path / "repository"
    shutil.copytree(
        ROOT,
        destination,
        ignore=shutil.ignore_patterns(".git", ".venv", "__pycache__", ".pytest_cache"),
    )
    return destination


def _mutate_json(root: Path, relative: str, callback: Callable[[dict[str, Any]], None]) -> None:
    path = root / relative
    value = json.loads(path.read_text(encoding="utf-8"))
    callback(value)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def test_p2s1_t001_candidate_is_complete_and_deterministic() -> None:
    first = validate_stage1(ROOT)
    second = validate_stage1(ROOT)
    assert first == second
    assert first["state"] == "PART2_IN_PROGRESS"
    assert first["stage_state"] == "PART2_STAGE1_EXECUTION_CONTRACT_ESTABLISHED"
    assert first["inventories"] == {
        "master_completion_gates": 6,
        "inherited_authorities": 8,
        "runtime_responsibilities": 11,
        "forbidden_redefinitions": 8,
        "runtime_invariants": 18,
        "behavioral_scenarios": 21,
        "closed_reason_codes": 21,
        "stage1_requirements": 26,
        "stage1_gates": 6,
    }
    assert set(first["master_part2_gates"].values()) == {"UNCLAIMED"}
    assert first["aws_execution"] is False
    assert first["infrastructure_mutation"] is False


def test_p2s1_t002_closure_commit_mutation_fails_closed(tmp_path: Path) -> None:
    root = _copy(tmp_path)
    _mutate_json(
        root,
        "evidence/part1-stage7-postmerge-closure-v1.json",
        lambda value: value["merge"].update({"main_sha": "0" * 40}),
    )
    with pytest.raises(Stage1Error, match="merge topology differs"):
        validate_stage1(root)


def test_p2s1_t003_non_squash_topology_fails_closed(tmp_path: Path) -> None:
    root = _copy(tmp_path)
    _mutate_json(
        root,
        "evidence/part1-stage7-postmerge-closure-v1.json",
        lambda value: value["merge"].update({"parent_count": 2}),
    )
    with pytest.raises(Stage1Error, match="merge topology differs"):
        validate_stage1(root)


def test_p2s1_t004_missing_master_gate_fails_closed(tmp_path: Path) -> None:
    root = _copy(tmp_path)
    _mutate_json(
        root,
        "spec/part2-stage1-authority-v1.json",
        lambda value: value["master_completion_gates"].pop(),
    )
    with pytest.raises(Stage1Error, match="owned master gate order differs"):
        validate_stage1(root)


def test_p2s1_t005_missing_inherited_authority_fails_closed(tmp_path: Path) -> None:
    root = _copy(tmp_path)
    _mutate_json(
        root,
        "spec/part2-stage1-authority-v1.json",
        lambda value: value["inherited_authorities"].pop("financial_semantics"),
    )
    with pytest.raises(Stage1Error, match="inherited authority map differs"):
        validate_stage1(root)


def test_p2s1_t006_missing_runtime_owner_fails_closed(tmp_path: Path) -> None:
    root = _copy(tmp_path)
    _mutate_json(
        root,
        "spec/part2-stage1-authority-v1.json",
        lambda value: value["runtime_responsibility_ownership"].pop(),
    )
    with pytest.raises(Stage1Error, match="runtime responsibility inventory differs"):
        validate_stage1(root)


def test_p2s1_t007_missing_forbidden_redefinition_fails_closed(tmp_path: Path) -> None:
    root = _copy(tmp_path)
    _mutate_json(
        root,
        "spec/part2-stage1-authority-v1.json",
        lambda value: value["forbidden_redefinitions"].pop(),
    )
    with pytest.raises(Stage1Error, match="forbidden redefinition inventory differs"):
        validate_stage1(root)


def test_p2s1_t008_missing_invariant_fails_closed(tmp_path: Path) -> None:
    root = _copy(tmp_path)
    _mutate_json(
        root,
        "spec/part2-stage1-authority-v1.json",
        lambda value: value["runtime_invariant_ids"].pop(),
    )
    with pytest.raises(Stage1Error, match="owned invariants differ"):
        validate_stage1(root)


def test_p2s1_t009_missing_scenario_fails_closed(tmp_path: Path) -> None:
    root = _copy(tmp_path)
    _mutate_json(
        root,
        "spec/part2-stage1-authority-v1.json",
        lambda value: value["required_behavioral_scenarios"].pop(),
    )
    with pytest.raises(Stage1Error, match="owned scenarios differ"):
        validate_stage1(root)


def test_p2s1_t010_aws_scope_inflation_fails_closed(tmp_path: Path) -> None:
    root = _copy(tmp_path)
    _mutate_json(
        root,
        "contracts/part2-stage1-execution-contract-v1.json",
        lambda value: value["implementation_boundary"].update({"aws_execution": True}),
    )
    with pytest.raises(Stage1Error, match="implementation claim is inflated"):
        validate_stage1(root)


def test_p2s1_t011_premature_completion_claim_fails_closed(tmp_path: Path) -> None:
    root = _copy(tmp_path)
    status = root / "PROJECT_STATUS.md"
    status.write_text(
        status.read_text(encoding="utf-8") + "\nLOCAL_RECONCILIATION_VERIFIED\n", encoding="utf-8"
    )
    with pytest.raises(Stage1Error, match="completion claimed early"):
        validate_stage1(root)


def test_p2s1_t012_spark_version_drift_fails_closed(tmp_path: Path) -> None:
    root = _copy(tmp_path)
    _mutate_json(
        root,
        "spec/part2-stage1-toolchain-v1.json",
        lambda value: value["local_validation"].update({"apache_spark": "3.5.5"}),
    )
    with pytest.raises(Stage1Error, match="local toolchain profile differs"):
        validate_stage1(root)


def test_p2s1_t013_worker_python_pin_removal_fails_closed(tmp_path: Path) -> None:
    root = _copy(tmp_path)
    runner = root / "tools/run_part2_stage1.py"
    runner.write_text(
        runner.read_text(encoding="utf-8").replace("PYSPARK_PYTHON", "REMOVED_WORKER_PYTHON"),
        encoding="utf-8",
    )
    with pytest.raises(Stage1Error, match="Spark Python binding missing"):
        validate_stage1(root)


def test_p2s1_t014_unhashed_dependency_fails_closed(tmp_path: Path) -> None:
    root = _copy(tmp_path)
    lock = root / "requirements/part2-stage1-py311.lock"
    lock.write_text(
        lock.read_text(encoding="utf-8").replace(
            "py4j==0.10.9.7 --hash=sha256:"
            "85defdfd2b2376eb3abf5ca6474b51ab7e0de341c75a02f46dc9b5976f5a5c1b",
            "py4j==0.10.9.7",
        ),
        encoding="utf-8",
    )
    with pytest.raises(Stage1Error, match="unhashed dependency"):
        validate_stage1(root)


def test_p2s1_t015_master_gate_cannot_be_claimed(tmp_path: Path) -> None:
    root = _copy(tmp_path)
    _mutate_json(
        root,
        "contracts/part2-stage1-execution-contract-v1.json",
        lambda value: value["master_part2_completion_gates"].update(
            {"independent_oracle_verified": "PASS"}
        ),
    )
    with pytest.raises(Stage1Error, match="master gate claimed early"):
        validate_stage1(root)


def test_p2s1_t016_traceability_gap_fails_closed(tmp_path: Path) -> None:
    root = _copy(tmp_path)
    _mutate_json(
        root, "spec/part2-stage1-traceability-v1.json", lambda value: value["traceability"].pop()
    )
    with pytest.raises(Stage1Error, match="traceability inventory differs"):
        validate_stage1(root)


def test_p2s1_t017_protected_part1_authority_mutation_fails_closed(tmp_path: Path) -> None:
    root = _copy(tmp_path)
    path = root / "spec/financial-semantics-v1.json"
    path.write_text(path.read_text(encoding="utf-8") + " ", encoding="utf-8")
    with pytest.raises(Stage1Error, match="protected authority digest differs"):
        validate_stage1(root)


def test_p2s1_t018_automatic_aws_capability_fails_closed(tmp_path: Path) -> None:
    root = _copy(tmp_path)
    workflow = root / ".github/workflows/ci.yml"
    workflow.write_text(
        workflow.read_text(encoding="utf-8") + "\n# id-token: write\n", encoding="utf-8"
    )
    with pytest.raises(Stage1Error, match="automatic CI includes AWS capability"):
        validate_stage1(root)


def test_p2s1_t019_ci_evidence_schema_is_closed() -> None:
    schema = json.loads(
        (ROOT / "spec/part2-stage1-ci-evidence-v1.schema.json").read_text(encoding="utf-8")
    )
    Draft202012Validator.check_schema(schema)
    valid = {
        "schema_version": "1.0",
        "repository": "bhuvaneshwaranmurugan21/ledgerguard-payment-reconciliation-platform",
        "commit_sha": "a" * 40,
        "checked_out_sha": "a" * 40,
        "base_sha": "b" * 40,
        "workflow_run_id": "1",
        "workflow_run_attempt": "1",
        "pull_request_number": 10,
        "pull_request_draft": True,
        "python_version": "3.11.13",
        "java_major": 17,
        "spark_version": "3.5.6",
        "py4j_version": "0.10.9.7",
        "clean_run_count": 2,
        "deterministic_equal": True,
        "deterministic_payload_sha256": "c" * 64,
        "stage1_candidate_digest": "d" * 64,
        "part1_closure_commit": "3ef17666e3fe3bc655ba1c8733beb3cb00acdbec",
        "spark_logical_digest": "e" * 64,
        "test_counts": {"tests": 260, "failures": 0, "errors": 0, "skipped": 0},
        "aws_execution": False,
        "infrastructure_mutation": False,
    }
    validator = Draft202012Validator(schema)
    assert list(validator.iter_errors(valid)) == []
    valid["unknown"] = True
    assert list(validator.iter_errors(valid))


def test_p2s1_t020_junit_summary_aggregates_direct_suites(tmp_path: Path) -> None:
    report = tmp_path / "pytest.xml"
    report.write_text(
        '<testsuites><testsuite tests="130" failures="0" errors="0" skipped="0"/>'
        '<testsuite tests="132" failures="1" errors="2" skipped="3"/></testsuites>',
        encoding="utf-8",
    )
    assert parse_junit_counts(report) == {
        "tests": 262,
        "failures": 1,
        "errors": 2,
        "skipped": 3,
    }
