from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import ledgerguard_part2_stage5_validation as validation
from ledgerguard_part2_stage5_evidence import parse_junit_counts, run_mutation_checks

ROOT = Path(__file__).resolve().parents[1]


def test_stage5_authority_closes_every_local_gate_without_inflation() -> None:
    result = validation.validate_stage5(ROOT)
    assert result["stage"] == 5
    assert result["stage_state"] == "PART2_STAGE5_SETTLEMENT_RECONCILIATION_VERIFIED_CANDIDATE"
    assert result["stage4_closure"]["state"] == "EXTERNALLY_VERIFIED"
    assert result["settlement"]["reason_codes"] == 11
    assert result["settlement"]["mutation_classes"] == 29
    assert result["settlement"]["authoritative_proofs_emitted"] == 0
    assert result["aws_execution"] is False
    assert result["master_part2_gates"]["financial_invariants_verified"] == "VERIFIED_CANDIDATE"


def test_stage5_semantic_mutation_registry_has_no_survivors() -> None:
    result = run_mutation_checks(ROOT)
    assert result["checks"] == 29
    assert result["survivors"] == 0
    assert result["killed"] == validation.MUTATION_CLASSES


def test_stage5_closure_rejects_changed_external_fact(monkeypatch: pytest.MonkeyPatch) -> None:
    original = validation._load

    def changed(root: Path, relative: str) -> dict[str, Any]:
        value = original(root, relative)
        if relative == "spec/part2-stage4-closure-freeze-v1.json":
            value = dict(value, exact_head_ci_run=1)
        return value

    monkeypatch.setattr(validation, "_load", changed)
    with pytest.raises(validation.Stage5Error, match="exact_head_ci_run"):
        validation._closure(ROOT)


def test_stage5_closure_rejects_changed_protected_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = validation._digest

    def changed(path: Path) -> str:
        if path.name == "part2-stage4-coverage-v1.json":
            return "0" * 64
        return original(path)

    monkeypatch.setattr(validation, "_digest", changed)
    with pytest.raises(validation.Stage5Error, match="authority differs"):
        validation._closure(ROOT)


def test_stage5_contract_rejects_scope_inflation(monkeypatch: pytest.MonkeyPatch) -> None:
    original = validation._load

    def changed(root: Path, relative: str) -> dict[str, Any]:
        value = original(root, relative)
        if relative == "contracts/part2-stage5-settlement-reconciliation-v1.json":
            value = dict(value)
            boundary = dict(value["implementation_boundary"])
            boundary["spark_reconciliation_implemented"] = True
            value["implementation_boundary"] = boundary
        return value

    monkeypatch.setattr(validation, "_load", changed)
    with pytest.raises(validation.Stage5Error, match="implementation boundary"):
        validation._contract(ROOT)


def test_stage5_contract_rejects_master_gate_inflation(monkeypatch: pytest.MonkeyPatch) -> None:
    original = validation._load

    def changed(root: Path, relative: str) -> dict[str, Any]:
        value = original(root, relative)
        if relative == "contracts/part2-stage5-settlement-reconciliation-v1.json":
            value = dict(value)
            gates = dict(value["master_part2_completion_gates"])
            gates["spark_parity_verified"] = "VERIFIED_CANDIDATE"
            value["master_part2_completion_gates"] = gates
        return value

    monkeypatch.setattr(validation, "_load", changed)
    with pytest.raises(validation.Stage5Error, match="master gate"):
        validation._contract(ROOT)


def test_stage5_traceability_rejects_missing_requirement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = validation._load

    def changed(root: Path, relative: str) -> dict[str, Any]:
        value = original(root, relative)
        if relative == "spec/part2-stage5-traceability-v1.json":
            value = dict(value)
            value["traceability"] = list(value["traceability"])[:-1]
        return value

    monkeypatch.setattr(validation, "_load", changed)
    with pytest.raises(validation.Stage5Error, match="trace inventory"):
        validation._traceability(ROOT)


def test_stage5_coverage_rejects_mutation_registry_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = validation._load

    def changed(root: Path, relative: str) -> dict[str, Any]:
        value = original(root, relative)
        if relative == "spec/part2-stage5-coverage-v1.json":
            value = dict(value)
            value["mutation_classes"] = list(value["mutation_classes"])[:-1]
        return value

    monkeypatch.setattr(validation, "_load", changed)
    with pytest.raises(validation.Stage5Error, match="mutation registry"):
        validation._coverage(ROOT)


def test_stage5_validator_artifact_inventory_is_complete() -> None:
    for relative in validation.STAGE5_ARTIFACTS:
        assert (ROOT / relative).is_file(), relative


def test_stage5_junit_parser_counts_direct_suites(tmp_path: Path) -> None:
    report = tmp_path / "pytest.xml"
    report.write_text(
        '<testsuites tests="99"><testsuite tests="2" failures="0" errors="0" skipped="0"/>'
        '<testsuite tests="3" failures="1" errors="0" skipped="1"/></testsuites>',
        encoding="utf-8",
    )
    assert parse_junit_counts(report) == {"tests": 5, "failures": 1, "errors": 0, "skipped": 1}


def test_stage5_junit_parser_rejects_missing_suite(tmp_path: Path) -> None:
    report = tmp_path / "pytest.xml"
    report.write_text("<testsuites/>", encoding="utf-8")
    with pytest.raises(ValueError, match="no test suites"):
        parse_junit_counts(report)
