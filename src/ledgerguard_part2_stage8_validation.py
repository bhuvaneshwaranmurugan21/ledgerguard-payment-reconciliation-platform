"""Fail-closed promotion validation for LedgerGuard Part 2 Stage 8."""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
from typing import Any, cast

from jsonschema import Draft202012Validator

from ledgerguard_part2_stage3_validation import FROZEN_SCHEMA_DIGESTS
from ledgerguard_part2_stage8_ledger import (
    GATE_COUNTS,
    STAGE_COUNTS,
    build_gate_adjudication,
    build_requirement_ledger,
)

PROJECT = "ledgerguard-payment-reconciliation-platform"
STAGE7_MAIN = "8fac3795ed0dac5284dd3b1595bd8fc9f6dc7344"
STAGE7_HEAD = "e008f890c895f7fedc782bde3da7c293cfa35cbf"
STAGE7_PARENT = "376e686813e6271e2d6787467a5500ba0827dfcb"
STAGE7_TREE = "6ae471cd73a1255df99edd953b8d0e0850790362"
STAGE8_REQUIREMENTS = [f"P2-S8-R{number:03d}" for number in range(1, 29)]
STAGE8_GATES = [f"P2-S8-G{number:03d}" for number in range(1, 11)]
STAGE8_GATE_NAMES = [
    "verified_stage7_entry",
    "immutable_authority_chain",
    "complete_requirement_audit",
    "complete_gate_and_ownership_audit",
    "six_master_gates_adjudicated",
    "full_system_reproducibility",
    "coverage_and_mutation_quality",
    "documentation_and_claim_integrity",
    "read_only_exact_head_promotion",
    "terminal_closure_publication",
]
MASTER_GATES = [
    "independent_oracle_verified",
    "spark_parity_verified",
    "financial_invariants_verified",
    "failure_matrix_verified",
    "deterministic_replay_verified",
    "critical_paths_tested",
]
MASTER_OWNERS = {
    "independent_oracle_verified": "PART2_STAGE2",
    "spark_parity_verified": "PART2_STAGE7",
    "financial_invariants_verified": "PART2_STAGES3_TO_5",
    "failure_matrix_verified": "PART2_STAGE6",
    "deterministic_replay_verified": "PART2_STAGE6",
    "critical_paths_tested": "PART2_STAGE7",
}
MUTATION_CLASSES = [
    "ACCEPT_STAGE7_COMMIT_DRIFT",
    "ACCEPT_STAGE7_TREE_DRIFT",
    "ACCEPT_NON_SQUASH_STAGE7",
    "ACCEPT_STAGE7_ARTIFACT_DRIFT",
    "ALLOW_MISSING_REQUIREMENT",
    "ALLOW_DUPLICATE_REQUIREMENT",
    "ALLOW_MISSING_GATE",
    "PROMOTE_UNSUPPORTED_MASTER_GATE",
    "ALLOW_FAILURE_OWNER_REASSIGNMENT",
    "CLAIM_PART2_COMPLETE_PREMERGE",
    "CLAIM_AWS_EXECUTION",
    "ALLOW_STALE_ACTIVE_DOCUMENTATION",
    "WEAKEN_COVERAGE_THRESHOLD",
    "DROP_TERMINAL_PUBLICATION",
]
STAGE8_ARTIFACTS = (
    ".github/workflows/ci.yml",
    "Makefile",
    "pyproject.toml",
    "README.md",
    "PROJECT_STATUS.md",
    "contracts/part2-stage8-promotion-v1.json",
    "docs/adr/0024-part2-terminal-promotion-and-closure.md",
    "docs/part2-completion.md",
    "docs/part2-execution-contract.md",
    "docs/part2-stage8-gap-audit.md",
    "requirements/part2-stage8-bootstrap.lock",
    "requirements/part2-stage8-py311.lock",
    "spec/part2-completion-authority-v1.schema.json",
    "spec/part2-gate-adjudication-v1.json",
    "spec/part2-master-gate-adjudication-v1.json",
    "spec/part2-requirement-ledger-v1.json",
    "spec/part2-stage7-closure-freeze-v1.json",
    "spec/part2-stage8-ci-evidence-v1.schema.json",
    "spec/part2-stage8-coverage-v1.json",
    "spec/part2-stage8-gate-registry-v1.json",
    "spec/part2-stage8-requirements-v1.json",
    "spec/part2-stage8-traceability-v1.json",
    "src/ledgerguard_part2_stage8_evidence.py",
    "src/ledgerguard_part2_stage8_ledger.py",
    "src/ledgerguard_part2_stage8_validation.py",
    "tests/test_part2_stage8_validation.py",
    "tools/build_part2_completion_ledgers.py",
    "tools/build_part2_stage8_ci_evidence.py",
    "tools/run_part2_stage8.py",
    "tools/validate_part2_stage8_run.py",
)


class Stage8Error(ValueError):
    """Raised when Part 2 promotion evidence is incomplete or inflated."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise Stage8Error(message)


def _load(root: Path, relative: str) -> dict[str, Any]:
    value = json.loads((root / relative).read_text(encoding="utf-8"))
    _require(isinstance(value, dict), f"JSON object required: {relative}")
    return cast(dict[str, Any], value)


def _digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _closure(root: Path) -> dict[str, Any]:
    freeze = _load(root, "spec/part2-stage7-closure-freeze-v1.json")
    expected: dict[str, Any] = {
        "state": "PART2_STAGE7_SPARK_PARITY_VERIFIED",
        "pull_request": 16,
        "pull_request_head": STAGE7_HEAD,
        "squash_merge_commit": STAGE7_MAIN,
        "squash_merge_tree": STAGE7_TREE,
        "squash_merge_parent": STAGE7_PARENT,
        "exact_head_ci_run": 33857511781,
        "exact_head_ci_job": 100974118004,
        "postmerge_main_ci_run": 33863399041,
        "postmerge_main_ci_job": 100992706340,
        "ci_artifact_id": 9931633631,
        "ci_artifact_name": f"ledgerguard-part2-stage7-{STAGE7_HEAD}",
        "ci_artifact_zip_sha256": (
            "721c2021c13821fd33b01e2796de22aa9d1ef744280dd6215d45e44bc47f5f0f"
        ),
        "ci_manifest_sha256": ("97f29734b208e3f87569cbe191bfd915d6312389c255905944f847c601ad44ef"),
        "ci_evidence_sha256": ("df03491bfe03fc1cc8b4ac14d3bc962109e5f33f1663d291813b19d2d92633c1"),
        "stage7_candidate_digest": (
            "7f2290159b1b578682b395b03737d886448d907e3bd2f603e9d8fe580b9e608c"
        ),
        "deterministic_payload_sha256": (
            "29c80df2222df32af08f1080e1931c829dd57c843f771264ea4622cfd273bd36"
        ),
        "wheel_sha256": "0ab6dabb3c837cd7e27b12a23bfaa109430af9d013e894b0aff847fb4212b794",
        "ci_test_count": 504,
        "coverage_statements": 68,
        "coverage_branches": 14,
        "coverage_percent": 100.0,
        "mutation_checks": 16,
        "mutation_survivors": 0,
        "behavioral_scenarios": 21,
        "closed_reason_codes": 21,
        "critical_paths": 8,
        "spark_version": "3.5.6",
        "py4j_version": "0.10.9.7",
        "python_version": "3.11.13",
        "java_major": 17,
        "spark_authoritative": False,
        "aws_execution": False,
        "managed_persistence": False,
        "infrastructure_mutation": False,
    }
    for key, value in expected.items():
        _require(freeze.get(key) == value, f"Stage 7 closure differs: {key}")
    protected = freeze.get("protected_authorities")
    _require(isinstance(protected, dict) and len(protected) == 15, "Stage 7 authority set differs")
    protected_authorities = cast(dict[object, object], protected)
    for relative, expected_digest in protected_authorities.items():
        _require(
            isinstance(relative, str) and isinstance(expected_digest, str),
            "invalid Stage 7 authority row",
        )
        relative_text = cast(str, relative)
        expected_text = cast(str, expected_digest)
        _require(
            _digest(root / relative_text) == expected_text,
            f"Stage 7 authority differs: {relative_text}",
        )
    return freeze


def _schemas(root: Path) -> None:
    for relative, expected in FROZEN_SCHEMA_DIGESTS.items():
        _require(_digest(root / relative) == expected, f"frozen schema differs: {relative}")


def _contract(root: Path) -> dict[str, Any]:
    contract = _load(root, "contracts/part2-stage8-promotion-v1.json")
    identity = {key: contract.get(key) for key in ("schema_version", "project", "part", "stage")}
    _require(
        identity == {"schema_version": "1.0", "project": PROJECT, "part": 2, "stage": 8},
        "Stage 8 identity differs",
    )
    _require(contract.get("state") == "PART2_IN_PROGRESS", "Part 2 completed before promotion")
    _require(
        contract.get("stage_state") == "PART2_STAGE8_PROMOTION_VERIFIED_CANDIDATE",
        "Stage 8 candidate state differs",
    )
    _require(
        contract.get("required_final_state") == "LOCAL_RECONCILIATION_VERIFIED",
        "Part 2 final state differs",
    )
    _require(contract.get("stage_gates") == STAGE8_GATES, "Stage 8 gate inventory differs")
    master = contract.get("master_part2_completion_gates")
    _require(
        isinstance(master, dict)
        and list(master) == MASTER_GATES
        and all(master[gate] == "EXTERNALLY_VERIFIED" for gate in MASTER_GATES),
        "Stage 8 master gate state differs",
    )
    inventory = contract.get("completion_inventory")
    _require(
        inventory
        == {
            "historical_requirements": 175,
            "stage8_requirements": 28,
            "total_requirements": 203,
            "historical_stage_gates": 59,
            "stage8_gates": 10,
            "total_stage_gates": 69,
            "runtime_responsibilities": 11,
            "runtime_invariants": 18,
            "behavioral_scenarios": 21,
            "closed_reason_codes": 21,
            "critical_paths": 8,
            "historical_semantic_mutations": 116,
        },
        "Stage 8 completion inventory differs",
    )
    protocol = cast(dict[str, Any], contract.get("promotion_protocol"))
    promotion = cast(dict[str, Any], protocol.get("promotion_pull_request"))
    attestation = cast(dict[str, Any], protocol.get("closure_attestation_pull_request"))
    _require(
        promotion
        == {
            "exact_head_ci_required": True,
            "draft_evidence_required": True,
            "squash_merge_required": True,
            "validated_tree_equality_required": True,
            "independent_main_ci_required": True,
        }
        and attestation
        == {
            "repository_record_required": True,
            "exact_head_ci_required": True,
            "squash_merge_required": True,
            "independent_main_ci_required": True,
        }
        and protocol.get("candidate_may_claim_part2_complete") is False,
        "terminal publication protocol differs",
    )
    boundary = contract.get("implementation_boundary")
    _require(
        isinstance(boundary, dict) and bool(boundary) and not any(boundary.values()),
        "Stage 8 claim boundary is inflated",
    )
    return contract


def _stage8_traceability(root: Path) -> None:
    requirements = cast(
        list[dict[str, Any]], _load(root, "spec/part2-stage8-requirements-v1.json")["requirements"]
    )
    gates = cast(
        list[dict[str, Any]], _load(root, "spec/part2-stage8-gate-registry-v1.json")["gates"]
    )
    traces = cast(
        list[dict[str, Any]], _load(root, "spec/part2-stage8-traceability-v1.json")["traceability"]
    )
    _require(
        [row.get("id") for row in requirements] == STAGE8_REQUIREMENTS,
        "Stage 8 requirements differ",
    )
    _require(
        [(row.get("gate_id"), row.get("name")) for row in gates]
        == list(zip(STAGE8_GATES, STAGE8_GATE_NAMES, strict=True)),
        "Stage 8 gates differ",
    )
    _require([row.get("gate_id") for row in traces] == STAGE8_GATES, "Stage 8 trace gates differ")
    traced = [item for row in traces for item in cast(list[str], row.get("requirement_ids"))]
    _require(traced == STAGE8_REQUIREMENTS, "Stage 8 trace requirement ownership differs")
    requirement_gates = {str(row["id"]): str(row["gate_id"]) for row in requirements}
    for trace in traces:
        _require(
            all(requirement_gates[item] == trace["gate_id"] for item in trace["requirement_ids"]),
            "Stage 8 trace gate ownership differs",
        )
        for field in ("authorities", "validation", "evidence"):
            _require(bool(trace.get(field)), f"empty Stage 8 trace {field}")
        for relative in trace["authorities"] + trace["validation"]:
            _require((root / relative).is_file(), f"Stage 8 trace file missing: {relative}")


def _completion_ledgers(root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        expected_requirements = build_requirement_ledger(root)
        expected_gates = build_gate_adjudication(root)
    except (KeyError, TypeError, ValueError) as error:
        raise Stage8Error(f"Part 2 ledger source invalid: {error}") from error
    requirements = _load(root, "spec/part2-requirement-ledger-v1.json")
    gates = _load(root, "spec/part2-gate-adjudication-v1.json")
    _require(requirements == expected_requirements, "Part 2 requirement ledger differs")
    _require(gates == expected_gates, "Part 2 gate adjudication differs")
    _require(
        requirements.get("historical_requirement_count") == 175
        and requirements.get("total_requirement_count") == 203
        and requirements.get("stage_counts")
        == {str(key): value for key, value in STAGE_COUNTS.items()},
        "Part 2 requirement totals differ",
    )
    _require(
        gates.get("historical_gate_count") == 59
        and gates.get("total_gate_count") == 69
        and gates.get("stage_counts") == {str(key): value for key, value in GATE_COUNTS.items()}
        and all(
            gates.get(key) == 0 for key in ("critical_findings", "major_findings", "open_findings")
        ),
        "Part 2 gate totals or findings differ",
    )
    return requirements, gates


def _master_gates(root: Path) -> dict[str, str]:
    authority = _load(root, "spec/part2-stage1-authority-v1.json")
    original = cast(list[dict[str, Any]], authority.get("master_completion_gates"))
    _require(
        {str(row["gate"]): str(row["owner"]) for row in original} == MASTER_OWNERS,
        "frozen master gate ownership differs",
    )
    adjudication = _load(root, "spec/part2-master-gate-adjudication-v1.json")
    rows = cast(list[dict[str, Any]], adjudication.get("master_gates"))
    _require([row.get("gate") for row in rows] == MASTER_GATES, "master gate inventory differs")
    for row in rows:
        gate = str(row["gate"])
        _require(
            row.get("implementation_owner") == MASTER_OWNERS[gate], f"master owner differs: {gate}"
        )
        _require(row.get("state") == "EXTERNALLY_VERIFIED", f"master gate unsupported: {gate}")
        authorities = cast(list[str], row.get("authorities"))
        _require(bool(authorities), f"master gate evidence missing: {gate}")
        for relative in authorities:
            _require((root / relative).is_file(), f"master gate authority missing: {relative}")
    findings = adjudication.get("findings")
    _require(findings == {"critical": 0, "major": 0, "open": 0}, "master gate findings remain")
    return {str(row["gate"]): str(row["state"]) for row in rows}


def _coverage(root: Path) -> None:
    coverage = _load(root, "spec/part2-stage8-coverage-v1.json")
    _require(
        coverage.get("production_surface") == "ledgerguard_part2_stage8_validation",
        "Stage 8 coverage surface differs",
    )
    _require(
        coverage.get("minimum_statement_percent") == 100.0
        and coverage.get("minimum_branch_percent") == 100.0,
        "Stage 8 coverage threshold weakened",
    )
    _require(
        coverage.get("historical_semantic_mutation_checks") == 116, "historical mutations differ"
    )
    _require(
        coverage.get("mutation_classes") == MUTATION_CLASSES, "Stage 8 mutation registry differs"
    )


def _completion_schema(root: Path) -> None:
    schema = _load(root, "spec/part2-completion-authority-v1.schema.json")
    Draft202012Validator.check_schema(schema)
    _require(
        schema["properties"]["state"] == {"const": "LOCAL_RECONCILIATION_VERIFIED"},
        "completion state schema differs",
    )


def _controls(root: Path) -> None:
    _require(
        (root / "requirements/part2-stage8-bootstrap.lock").read_bytes()
        == (root / "requirements/part2-stage7-bootstrap.lock").read_bytes(),
        "Stage 8 bootstrap lock differs from exact Spark closure",
    )
    _require(
        (root / "requirements/part2-stage8-py311.lock").read_bytes()
        == (root / "requirements/part2-stage7-py311.lock").read_bytes(),
        "Stage 8 runtime lock differs from exact Spark closure",
    )
    workflow = (root / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    for marker in (
        "PART2_STAGE7_CLOSURE_SHA",
        "ledgerguard-part2-stage7-closure",
        "tools/run_part2_stage8.py",
        "tools/build_part2_stage8_ci_evidence.py",
        "ledgerguard-part2-stage8-${{ github.event.pull_request.head.sha }}",
    ):
        _require(marker in workflow, f"Stage 8 CI control missing: {marker}")
    _require("id-token: write" not in workflow, "automatic CI can request an OIDC token")
    stage8_block = workflow.split("Run Part 2 Stage 8 validation twice", 1)[-1]
    _require(
        "aws-actions/" not in stage8_block and "aws " not in stage8_block, "Stage 8 CI can call AWS"
    )
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    _require(
        'ledgerguard-part2-stage8 = "ledgerguard_part2_stage8_validation:main"' in pyproject,
        "Stage 8 command missing",
    )


def _documentation(root: Path) -> None:
    status = (root / "PROJECT_STATUS.md").read_text(encoding="utf-8")
    readme = (root / "README.md").read_text(encoding="utf-8")
    execution = (root / "docs/part2-execution-contract.md").read_text(encoding="utf-8")
    completion = (root / "docs/part2-completion.md").read_text(encoding="utf-8")
    _require("Stage: 8 — Promotion and closure" in status, "active Stage 8 status missing")
    _require("State: `PART2_IN_PROGRESS`" in status, "Part 2 candidate state missing")
    _require(
        "Stage state: `PART2_STAGE8_PROMOTION_VERIFIED_CANDIDATE`" in status,
        "Stage 8 candidate status missing",
    )
    _require("Stage 7 external closure: `EXTERNALLY_VERIFIED`" in status, "Stage 7 closure missing")
    _require("Part 2 Stage 8 promotion candidate" in readme, "README Stage 8 status missing")
    _require("Stage 6 is now the local" not in readme, "README retains stale Stage 6 claim")
    _require(
        "| Spark reconciliation parity | `UNCLAIMED` |" not in readme,
        "README retains stale Spark claim",
    )
    _require(
        "## Stage 8 promotion and closure boundary" in execution, "execution contract lacks Stage 8"
    )
    _require("two pull requests" in completion, "terminal closure procedure missing")
    _require("Part 2 is not yet complete" in completion, "candidate boundary is not explicit")


def validate_stage8(root: Path) -> dict[str, Any]:
    """Validate the complete repository-resident Stage 8 promotion candidate."""
    root = root.resolve()
    closure = _closure(root)
    _schemas(root)
    contract = _contract(root)
    _stage8_traceability(root)
    requirements, gates = _completion_ledgers(root)
    master = _master_gates(root)
    _coverage(root)
    _completion_schema(root)
    _controls(root)
    _documentation(root)
    for relative in STAGE8_ARTIFACTS:
        _require((root / relative).is_file(), f"Stage 8 artifact missing: {relative}")
    artifact_digest = sha256(
        "".join(
            f"{relative}:{_digest(root / relative)}\n" for relative in STAGE8_ARTIFACTS
        ).encode()
    ).hexdigest()
    return {
        "stage7_closure": {
            "commit": closure["squash_merge_commit"],
            "state": "EXTERNALLY_VERIFIED",
        },
        "stage8_candidate_digest": artifact_digest,
        "requirements": {
            "historical": requirements["historical_requirement_count"],
            "total": requirements["total_requirement_count"],
        },
        "stage_gates": {
            "historical": gates["historical_gate_count"],
            "total": gates["total_gate_count"],
        },
        "master_part2_gates": master,
        "stage_state": contract["stage_state"],
        "part2_state": contract["state"],
        "aws_execution": False,
        "part2_closed": False,
    }


def main() -> None:
    print(json.dumps(validate_stage8(Path.cwd()), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
