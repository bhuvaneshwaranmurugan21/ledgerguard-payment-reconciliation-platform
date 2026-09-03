from __future__ import annotations

from pathlib import Path

import pytest

import ledgerguard_part2_stage4_validation as validation
from ledgerguard_part2_stage4_evidence import parse_junit_counts, run_mutation_checks

ROOT = Path(__file__).resolve().parents[1]


def test_stage4_authority_closes_every_local_gate_without_inflation() -> None:
    result = validation.validate_stage4(ROOT)
    assert result["stage_state"] == "PART2_STAGE4_TRANSACTION_RECONCILIATION_VERIFIED_CANDIDATE"
    assert result["stage3_closure"]["state"] == "EXTERNALLY_VERIFIED"
    assert result["transaction"]["reason_codes"] == 6
    assert result["transaction"]["mutation_classes"] == 20
    assert result["transaction"]["authoritative_proofs_emitted"] == 0
    assert result["aws_execution"] is False
    assert result["master_part2_gates"]["financial_invariants_verified"] == "UNCLAIMED"


def test_stage4_semantic_mutation_registry_has_no_survivors() -> None:
    result = run_mutation_checks(ROOT)
    assert result["checks"] == 20
    assert result["survivors"] == 0
    assert result["killed"] == validation.MUTATION_CLASSES


def test_stage4_closure_rejects_changed_external_fact(monkeypatch: pytest.MonkeyPatch) -> None:
    original = validation._load

    def changed(root: Path, relative: str) -> dict[str, object]:
        value = original(root, relative)
        if relative == "spec/part2-stage3-closure-freeze-v1.json":
            value = dict(value, exact_head_ci_run=1)
        return value

    monkeypatch.setattr(validation, "_load", changed)
    with pytest.raises(validation.Stage4Error, match="exact_head_ci_run"):
        validation._closure(ROOT)


def test_stage4_contract_rejects_scope_inflation(monkeypatch: pytest.MonkeyPatch) -> None:
    original = validation._load

    def changed(root: Path, relative: str) -> dict[str, object]:
        value = original(root, relative)
        if relative == "contracts/part2-stage4-transaction-reconciliation-v1.json":
            value = dict(value)
            boundary = dict(value["implementation_boundary"])  # type: ignore[arg-type]
            boundary["spark_reconciliation_implemented"] = True
            value["implementation_boundary"] = boundary
        return value

    monkeypatch.setattr(validation, "_load", changed)
    with pytest.raises(validation.Stage4Error, match="spark_reconciliation_implemented"):
        validation._contract(ROOT)


def test_stage4_junit_parser_counts_direct_suites(tmp_path: Path) -> None:
    report = tmp_path / "pytest.xml"
    report.write_text(
        '<testsuites tests="99"><testsuite tests="2" failures="0" errors="0" skipped="0"/>'
        '<testsuite tests="3" failures="1" errors="0" skipped="1"/></testsuites>',
        encoding="utf-8",
    )
    assert parse_junit_counts(report) == {"tests": 5, "failures": 1, "errors": 0, "skipped": 1}


def test_stage4_junit_parser_rejects_missing_suite(tmp_path: Path) -> None:
    report = tmp_path / "pytest.xml"
    report.write_text("<testsuites/>", encoding="utf-8")
    with pytest.raises(ValueError, match="no test suites"):
        parse_junit_counts(report)
