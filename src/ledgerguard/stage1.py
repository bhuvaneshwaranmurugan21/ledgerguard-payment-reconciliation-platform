"""Fail-closed validation for the Part 1 Stage 1 financial-semantics freeze."""

from __future__ import annotations

import json
from collections.abc import Mapping
from hashlib import sha256
from pathlib import Path
from typing import Any

from .stage0 import validate_stage0

PROJECT = "ledgerguard-payment-reconciliation-platform"
STAGE_STATE = "PART1_FINANCIAL_SEMANTICS_FROZEN"
PART1_STATE = "PART1_FOUNDATION_CORRECTION_IN_PROGRESS"
BASELINE = {
    "main_sha": "9a920a300b50fe46bb534e7fc9f32ad5eda1224c",
    "main_tree_sha": "738221ba63364837f12c2ce3279b0514db08f2e5",
    "stage0_foundation_sha256": "4d7bf84f88b7cd0826a637aa9da74cb5e5ffc5d4dc0f390c82340ef083a7dc60",
    "stage0_sha256": "3da80eb91b0948f50c5080c7198e78a0a1716a36c7ca7267ec205099b981282b",
}
DECISION_TOPICS = [
    "financial_truth_independence",
    "integer_minor_unit_money",
    "currency_isolation",
    "canonical_business_digest",
    "source_identity_and_replay",
    "transaction_grain",
    "transaction_event_signs",
    "negative_event_references",
    "journal_validity",
    "transaction_ledger_orientation",
    "settlement_grain",
    "settlement_formula",
    "settlement_ledger_orientation",
    "exact_bank_allocation",
    "tolerance_and_status",
    "grain_specific_proofs",
    "immutable_case_revisions",
    "failure_ownership_and_atomicity",
]
CLAIM_BOUNDARY = {
    "semantic_design": "DESIGNED/MODELED",
    "semantic_acceptance_examples": "LOCAL_VERIFIED",
    "stage0_baseline_governance": "LOCAL_VERIFIED",
    "reconciliation_execution": "UNCLAIMED",
    "aws_execution": False,
}
FORBIDDEN_RUNTIME = {"aws_evidence.py", "cli.py", "engine.py", "model.py", "simulator.py"}


class Stage1Error(ValueError):
    """Raised when the Stage 1 contract or evidence fails closed."""


def _load(path: Path) -> dict[str, Any]:
    try:
        value: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise Stage1Error(f"cannot load {path}: {error}") from error
    if not isinstance(value, dict):
        raise Stage1Error(f"JSON object required: {path}")
    return value


def _mapping(value: object, message: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise Stage1Error(message)
    return value


def _list(value: object, message: str) -> list[Any]:
    if not isinstance(value, list):
        raise Stage1Error(message)
    return value


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise Stage1Error(message)


def _artifact_digests(root: Path, artifacts: Mapping[str, Any]) -> dict[str, str]:
    digests: dict[str, str] = {}
    for name, artifact_value in artifacts.items():
        artifact = _mapping(artifact_value, f"artifact {name} must be an object")
        relative = artifact.get("path")
        expected = artifact.get("sha256")
        if not isinstance(relative, str) or not relative:
            raise Stage1Error(f"artifact path missing: {name}")
        relative_path = Path(relative)
        _require(
            not relative_path.is_absolute() and ".." not in relative_path.parts,
            f"artifact path escapes repository: {name}",
        )
        path = root / relative_path
        _require(path.is_file(), f"artifact missing: {relative}")
        actual = sha256(path.read_bytes()).hexdigest()
        _require(expected == actual, f"artifact digest differs: {relative}")
        digests[name] = actual
    return digests


def _validate_decisions(semantics: Mapping[str, Any]) -> None:
    decisions = _list(semantics.get("decisions"), "semantic decisions must be a list")
    _require(len(decisions) == len(DECISION_TOPICS), "semantic decision count differs")
    for number, (decision_value, topic) in enumerate(
        zip(decisions, DECISION_TOPICS, strict=True), start=1
    ):
        decision = _mapping(decision_value, "every semantic decision must be an object")
        _require(decision.get("id") == f"SEM-{number:03d}", "semantic decision ID differs")
        _require(decision.get("topic") == topic, "semantic decision topic differs")
        _require(decision.get("state") == "FROZEN", "semantic decision must be frozen")
    _require(semantics.get("unresolved_decisions") == [], "unresolved semantic decisions remain")


def _validate_failure_ownership(semantics: Mapping[str, Any]) -> None:
    ownership = _mapping(semantics.get("failure_ownership"), "failure ownership missing")
    admission = set(_list(ownership.get("ADMISSION"), "admission reasons missing"))
    financial = set(
        _list(ownership.get("FINANCIAL_EXCEPTION"), "financial-exception reasons missing")
    )
    execution = set(_list(ownership.get("EXECUTION"), "execution reasons missing"))
    _require(admission.isdisjoint(financial), "admission and financial reasons overlap")
    _require(admission.isdisjoint(execution), "admission and execution reasons overlap")
    _require(financial.isdisjoint(execution), "financial and execution reasons overlap")
    _require("CURRENCY_DOMAIN_VIOLATION" in admission, "currency failure must belong to admission")
    _require("AMBIGUOUS_BANK_ALLOCATION" in admission, "ambiguous allocation must fail admission")
    _require("OVER_APPLIED_REFERENCE" in financial, "capture over-application ownership differs")
    _require(
        ownership.get("admission_failure_authoritative_proof") == "FORBIDDEN",
        "admission failures must not authorize proofs",
    )
    _require(
        ownership.get("execution_failure_authoritative_partial_proof") == "FORBIDDEN",
        "execution failures must not authorize partial proofs",
    )


def _validate_examples(examples: Mapping[str, Any], inventory: Mapping[str, Any]) -> None:
    transaction_cases = _list(examples.get("transaction_cases"), "transaction cases missing")
    settlement_cases = _list(examples.get("settlement_cases"), "settlement cases missing")
    identity_cases = _mapping(examples.get("identity_cases"), "identity cases missing")
    _require(
        len(transaction_cases) == inventory.get("transaction_case_count"),
        "transaction case count differs",
    )
    _require(
        len(
            set(
                str(_mapping(case, "transaction case invalid").get("name"))
                for case in transaction_cases
            )
        )
        == len(transaction_cases),
        "transaction case names must be unique",
    )
    _require(
        len(
            set(
                str(_mapping(case, "settlement case invalid").get("name"))
                for case in settlement_cases
            )
        )
        == len(settlement_cases),
        "settlement case names must be unique",
    )
    _require(
        len(settlement_cases) == inventory.get("settlement_case_count"),
        "settlement case count differs",
    )
    _require(len(identity_cases) == inventory.get("identity_rule_count"), "identity count differs")
    cross_currency = next(
        (
            _mapping(case, "transaction case invalid")
            for case in transaction_cases
            if _mapping(case, "transaction case invalid").get("name")
            == "cross-currency-contamination"
        ),
        None,
    )
    if cross_currency is None:
        raise Stage1Error("cross-currency counterexample missing")
    expected = _mapping(cross_currency.get("expected"), "cross-currency outcome missing")
    _require(expected.get("outcome") == "ADMISSION_REJECTED", "currency outcome differs")
    _require(expected.get("authoritative_proof") is False, "currency failure authorizes proof")
    ambiguous = _mapping(
        examples.get("ambiguous_bank_allocation_case"),
        "ambiguous bank-allocation counterexample missing",
    )
    _require(
        ambiguous.get("expected_outcome") == "ADMISSION_REJECTED", "allocation outcome differs"
    )
    _require(
        ambiguous.get("expected_reason") == "AMBIGUOUS_BANK_ALLOCATION",
        "allocation reason differs",
    )


def validate_stage1(root: Path) -> dict[str, Any]:
    """Validate Stage 1 and return a deterministic evidence summary."""

    contract_path = root / "contracts/part1-stage1-completion-v1.json"
    evidence_path = root / "evidence/part1-stage1-local.json"
    contract = _load(contract_path)
    evidence = _load(evidence_path)
    semantics = _load(root / "spec/financial-semantics-v1.json")
    examples = _load(root / "spec/financial-examples-v1.json")
    stage0 = validate_stage0(root)

    _require(contract.get("project") == PROJECT, "contract project differs")
    _require(contract.get("part") == 1 and contract.get("stage") == 1, "contract stage differs")
    _require(contract.get("state") == STAGE_STATE, "contract Stage 1 state differs")
    _require(contract.get("overall_part1_state") == PART1_STATE, "contract Part 1 state differs")
    baseline = _mapping(contract.get("baseline"), "contract baseline missing")
    for key, expected_value in BASELINE.items():
        _require(baseline.get(key) == expected_value, f"contract baseline {key} differs")
    _require(
        baseline.get("stage0_state") == "PART1_STAGE0_BASELINE_AUDIT_COMPLETE",
        "Stage 0 state differs",
    )
    _require(stage0.get("stage0_sha256") == BASELINE["stage0_sha256"], "Stage 0 digest differs")

    semantic_baseline = _mapping(semantics.get("baseline"), "semantic baseline missing")
    _require(
        semantic_baseline.get("main_sha") == BASELINE["main_sha"],
        "semantic baseline SHA differs",
    )
    _require(
        semantic_baseline.get("main_tree_sha") == BASELINE["main_tree_sha"],
        "semantic baseline tree differs",
    )
    _require(
        semantic_baseline.get("foundation_sha256") == BASELINE["stage0_foundation_sha256"],
        "semantic foundation digest differs",
    )
    _require(
        semantic_baseline.get("stage0_sha256") == BASELINE["stage0_sha256"],
        "semantic Stage 0 digest differs",
    )
    _require(semantics.get("state") == STAGE_STATE, "semantic state differs")
    _require(semantics.get("claim_boundary") == CLAIM_BOUNDARY, "semantic claim boundary differs")
    _validate_decisions(semantics)
    _validate_failure_ownership(semantics)

    inventory = _mapping(contract.get("acceptance_inventory"), "acceptance inventory missing")
    _require(
        inventory.get("decision_count") == len(DECISION_TOPICS), "contract decision count differs"
    )
    _require(inventory.get("unresolved_decision_count") == 0, "contract unresolved count differs")
    _validate_examples(examples, inventory)

    artifacts = _mapping(contract.get("semantic_artifacts"), "semantic artifacts missing")
    artifact_digests = _artifact_digests(root, artifacts)
    required_gates = _list(contract.get("required_gates"), "required gates missing")
    _require(len(required_gates) == len(set(required_gates)), "required gates must be unique")
    _require("POST_MERGE_MAIN_CI_SUCCESS" in required_gates, "post-merge CI gate missing")

    boundary = _mapping(contract.get("execution_boundary"), "execution boundary missing")
    for field in (
        "schema_mutation",
        "reconciliation_engine_added",
        "aws_execution",
        "infrastructure_mutation",
        "managed_evidence_claimed",
    ):
        _require(boundary.get(field) is False, f"{field} must be false")

    contract_digest = sha256(contract_path.read_bytes()).hexdigest()
    _require(evidence.get("project") == PROJECT, "evidence project differs")
    _require(evidence.get("part") == 1 and evidence.get("stage") == 1, "evidence stage differs")
    _require(evidence.get("stage_state") == STAGE_STATE, "evidence Stage 1 state differs")
    _require(evidence.get("overall_state") == PART1_STATE, "evidence Part 1 state differs")
    _require(evidence.get("baseline") == dict(baseline), "evidence baseline differs")
    _require(
        evidence.get("completion_contract_sha256") == contract_digest, "contract digest differs"
    )
    semantic_evidence = _mapping(
        evidence.get("semantic_specification"), "semantic evidence missing"
    )
    example_evidence = _mapping(evidence.get("acceptance_examples"), "example evidence missing")
    _require(
        semantic_evidence.get("sha256") == artifact_digests["specification"],
        "semantic evidence digest differs",
    )
    _require(
        example_evidence.get("sha256") == artifact_digests["examples"],
        "example evidence digest differs",
    )
    _require(
        semantic_evidence.get("decision_count") == len(DECISION_TOPICS),
        "evidence decision count differs",
    )
    _require(
        semantic_evidence.get("unresolved_decision_count") == 0, "evidence unresolved count differs"
    )
    _require(
        evidence.get("claim_boundary") == CLAIM_BOUNDARY | {"aws_infrastructure_mutated": False},
        "evidence claim boundary differs",
    )
    schema_boundary = _mapping(evidence.get("schema_boundary"), "schema boundary missing")
    _require(schema_boundary.get("schemas_changed") is False, "evidence claims schema mutation")
    implementation = _mapping(
        evidence.get("implementation_boundary"), "implementation boundary missing"
    )
    _require(
        implementation.get("reconciliation_engine_added") is False,
        "evidence claims reconciliation engine",
    )
    local_validation = _mapping(evidence.get("local_validation"), "local validation missing")
    _require(local_validation.get("test_count") == 59, "local test count differs")
    for field in ("ruff_format", "ruff_lint", "strict_mypy", "pytest", "diff_check", "determinism"):
        _require(local_validation.get(field) == "PASS", f"local validation {field} differs")
    _require(
        local_validation.get("stage0_validator_sha256") == stage0["stage0_sha256"],
        "evidence Stage 0 validator digest differs",
    )

    package_files = {path.name for path in (root / "src/ledgerguard").glob("*.py")}
    _require(not package_files.intersection(FORBIDDEN_RUNTIME), "forbidden runtime present")

    payload: dict[str, Any] = {
        "project": PROJECT,
        "part": 1,
        "stage": 1,
        "stage_state": STAGE_STATE,
        "overall_part1_state": PART1_STATE,
        "baseline_main_sha": BASELINE["main_sha"],
        "baseline_main_tree_sha": BASELINE["main_tree_sha"],
        "stage0_sha256": stage0["stage0_sha256"],
        "completion_contract_sha256": contract_digest,
        "semantic_specification_sha256": artifact_digests["specification"],
        "acceptance_examples_sha256": artifact_digests["examples"],
        "decision_count": len(DECISION_TOPICS),
        "unresolved_decision_count": 0,
        "aws_execution": False,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    payload["stage1_sha256"] = sha256(canonical).hexdigest()
    _require(
        local_validation.get("stage1_validator_sha256") == payload["stage1_sha256"],
        "evidence Stage 1 validator digest differs",
    )
    return payload
