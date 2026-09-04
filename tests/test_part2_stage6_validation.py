from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import ledgerguard_part2_stage6_validation as validation
from ledgerguard_part2_stage6_evidence import parse_junit_counts, run_mutation_checks

ROOT = Path(__file__).resolve().parents[1]


def test_stage6_authority_closes_every_local_gate_without_inflation() -> None:
    result = validation.validate_stage6(ROOT)
    assert result["stage"] == 6
    assert result["stage_state"] == "PART2_STAGE6_PROOF_FINALIZATION_VERIFIED_CANDIDATE"
    assert result["stage5_closure"]["state"] == "EXTERNALLY_VERIFIED"
    assert result["finalization"]["mutation_classes"] == 24
    assert result["aws_execution"] is False
    assert result["spark_execution"] is False
    assert result["managed_persistence"] is False
    assert result["master_part2_gates"]["financial_invariants_verified"] == "EXTERNALLY_VERIFIED"
    assert result["master_part2_gates"]["failure_matrix_verified"] == "UNCLAIMED"
    assert result["master_part2_gates"]["deterministic_replay_verified"] == "VERIFIED_CANDIDATE"
    assert result["master_part2_gates"]["critical_paths_tested"] == "UNCLAIMED"


def test_stage6_semantic_mutation_registry_has_no_survivors() -> None:
    result = run_mutation_checks(ROOT)
    assert result == {"checks": 24, "survivors": 0, "killed": validation.MUTATION_CLASSES}


def test_stage6_closure_rejects_changed_external_fact(monkeypatch: pytest.MonkeyPatch) -> None:
    original = validation._load

    def changed(root: Path, relative: str) -> dict[str, Any]:
        value = original(root, relative)
        if relative == "spec/part2-stage5-closure-freeze-v1.json":
            value = dict(value, exact_head_ci_run=1)
        return value

    monkeypatch.setattr(validation, "_load", changed)
    with pytest.raises(validation.Stage6Error, match="exact_head_ci_run"):
        validation._closure(ROOT)


def test_stage6_closure_rejects_changed_protected_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = validation._digest

    def changed(path: Path) -> str:
        if path.name == "part2-stage5-coverage-v1.json":
            return "0" * 64
        return original(path)

    monkeypatch.setattr(validation, "_digest", changed)
    with pytest.raises(validation.Stage6Error, match="authority differs"):
        validation._closure(ROOT)


def test_stage6_contract_rejects_scope_and_master_gate_inflation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = validation._load

    def changed(root: Path, relative: str) -> dict[str, Any]:
        value = original(root, relative)
        if relative == "contracts/part2-stage6-proof-finalization-v1.json":
            value = dict(value)
            boundary = dict(value["implementation_boundary"])
            boundary["spark_reconciliation_implemented"] = True
            value["implementation_boundary"] = boundary
        return value

    monkeypatch.setattr(validation, "_load", changed)
    with pytest.raises(validation.Stage6Error, match="implementation boundary"):
        validation._contract(ROOT)

    def inflated(root: Path, relative: str) -> dict[str, Any]:
        value = original(root, relative)
        if relative == "contracts/part2-stage6-proof-finalization-v1.json":
            value = dict(value)
            master = dict(value["master_part2_completion_gates"])
            master["spark_parity_verified"] = "VERIFIED_CANDIDATE"
            value["master_part2_completion_gates"] = master
        return value

    monkeypatch.setattr(validation, "_load", inflated)
    with pytest.raises(validation.Stage6Error, match="non-Stage-6 master gate"):
        validation._contract(ROOT)


def test_stage6_traceability_and_coverage_reject_registry_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = validation._load

    def missing(root: Path, relative: str) -> dict[str, Any]:
        value = original(root, relative)
        if relative == "spec/part2-stage6-traceability-v1.json":
            value = dict(value)
            value["traceability"] = list(value["traceability"])[:-1]
        return value

    monkeypatch.setattr(validation, "_load", missing)
    with pytest.raises(validation.Stage6Error, match="trace gates differ"):
        validation._traceability(ROOT)

    def mutation_drift(root: Path, relative: str) -> dict[str, Any]:
        value = original(root, relative)
        if relative == "spec/part2-stage6-coverage-v1.json":
            value = dict(value)
            value["mutation_classes"] = list(value["mutation_classes"])[:-1]
        return value

    monkeypatch.setattr(validation, "_load", mutation_drift)
    with pytest.raises(validation.Stage6Error, match="mutation registry"):
        validation._coverage(ROOT)


def test_stage6_validator_artifact_inventory_is_complete() -> None:
    for relative in validation.STAGE6_ARTIFACTS:
        assert (ROOT / relative).is_file(), relative


def test_stage6_junit_parser_counts_and_rejects_invalid_reports(tmp_path: Path) -> None:
    report = tmp_path / "pytest.xml"
    report.write_text(
        '<testsuites tests="99"><testsuite tests="2" failures="0" errors="0" skipped="0"/>'
        '<testsuite tests="3" failures="1" errors="0" skipped="1"/></testsuites>',
        encoding="utf-8",
    )
    assert parse_junit_counts(report) == {"tests": 5, "failures": 1, "errors": 0, "skipped": 1}
    report.write_text("<testsuites/>", encoding="utf-8")
    with pytest.raises(ValueError, match="no test suites"):
        parse_junit_counts(report)
    report.write_text(
        '<testsuite tests="1" failures="1" errors="1" skipped="0"/>', encoding="utf-8"
    )
    with pytest.raises(ValueError, match="inconsistent"):
        parse_junit_counts(report)
