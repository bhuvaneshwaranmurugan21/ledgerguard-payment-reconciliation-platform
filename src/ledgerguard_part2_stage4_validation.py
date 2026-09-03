"""Fail-closed validation for Part 2 Stage 4 transaction reconciliation."""

from __future__ import annotations

import ast
import json
from hashlib import sha256
from pathlib import Path
from typing import Any, cast

from jsonschema import Draft202012Validator

from ledgerguard.reconciliation import ContractRegistry
from ledgerguard_part2_stage3_validation import FROZEN_SCHEMA_DIGESTS, validate_stage3

PROJECT = "ledgerguard-payment-reconciliation-platform"
STAGE3_MAIN = "47e96d3f4846d55568c0b137fb3e4d41ead0eef1"
STAGE3_TREE = "a415cfc7eebafc0f512afe27cd9d3aa3418b545f"
STAGE3_PARENT = "55e78f76e76bff7562d43a3d001dbb74fd66d8fd"
STAGE3_HEAD = "0c29259539b468bfe13831d6e0a7687b113dbfa4"
STAGE3_PR_CI = 33727426463
STAGE3_MAIN_CI = 33729063294
STAGE3_ARTIFACT = 9882860664
STAGE4_REQUIREMENTS = [f"P2-S4-R{number:03d}" for number in range(1, 24)]
STAGE4_GATES = [f"P2-S4-G{number:03d}" for number in range(1, 10)]
FINANCIAL_REASONS = {
    "INVALID_ACCOUNT_ROLE",
    "UNRESOLVED_REFERENCE",
    "OVER_APPLIED_REFERENCE",
    "MISSING_LEDGER_MOVEMENT",
    "MISSING_PROCESSOR_ACTIVITY",
    "PROCESSOR_LEDGER_MISMATCH",
}
MUTATION_CLASSES = [
    "REVERSE_CAPTURE_SIGN",
    "REVERSE_NEGATIVE_SIGN",
    "DROP_EVENT_CLASS_FROM_KEY",
    "INNER_JOIN_GRAINS",
    "COLLAPSE_MISSING_TO_ZERO",
    "USE_TOTAL_JOURNAL_DEBIT",
    "REVERSE_CLEARING_ORIENTATION",
    "ALLOW_INVALID_COUNTERPART_ROLE",
    "TOLERATE_SEMANTIC_FAILURE",
    "REFERENCE_BY_PAYMENT",
    "ALLOW_NEGATIVE_REFERENCE_CHAIN",
    "CONFLATE_MULTIPLE_CAPTURES",
    "DISABLE_CUMULATIVE_CAPACITY",
    "ORDER_DEPENDENT_CAPACITY",
    "DOUBLE_APPLY_REPLAY",
    "UNCHECKED_TRANSACTION_AGGREGATION",
    "DROP_MISMATCH_REASON",
    "SETTLEMENT_CONTAMINATES_TRANSACTION",
    "NONDETERMINISTIC_RESULT_ORDER",
    "EMIT_AUTHORITATIVE_PROOF",
]
FORBIDDEN_PRODUCTION_IMPORTS = {
    "boto3",
    "botocore",
    "ledgerguard_reference_oracle",
    "pandas",
    "pyspark",
    "requests",
    "sqlalchemy",
}
STAGE4_ARTIFACTS = (
    ".github/workflows/ci.yml",
    "README.md",
    "PROJECT_STATUS.md",
    "contracts/part2-stage4-transaction-reconciliation-v1.json",
    "docs/adr/0020-transaction-reconciliation-and-reference-capacity.md",
    "docs/part2-execution-contract.md",
    "docs/part2-stage4-gap-audit.md",
    "docs/part2-stage4-transaction-reconciliation.md",
    "pyproject.toml",
    "requirements/part2-stage4-bootstrap.lock",
    "requirements/part2-stage4-py311.lock",
    "spec/part2-stage3-closure-freeze-v1.json",
    "spec/part2-stage4-ci-evidence-v1.schema.json",
    "spec/part2-stage4-coverage-v1.json",
    "spec/part2-stage4-gate-registry-v1.json",
    "spec/part2-stage4-requirements-v1.json",
    "spec/part2-stage4-traceability-v1.json",
    "spec/part2-stage4-vectors-v1.json",
    "src/ledgerguard/reconciliation/__init__.py",
    "src/ledgerguard/reconciliation/admission.py",
    "src/ledgerguard/reconciliation/transaction.py",
    "src/ledgerguard_part2_stage4.py",
    "src/ledgerguard_part2_stage4_evidence.py",
    "src/ledgerguard_part2_stage4_validation.py",
    "tests/test_part2_stage4_transaction.py",
    "tests/test_part2_stage4_validation.py",
    "tools/build_part2_stage4_ci_evidence.py",
    "tools/run_part2_stage4.py",
    "tools/validate_part2_stage3_run.py",
    "tools/validate_part2_stage4_run.py",
)


class Stage4Error(ValueError):
    """Raised when the Stage 4 candidate is incomplete or inflated."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise Stage4Error(message)


def _load(root: Path, relative: str) -> dict[str, Any]:
    value = json.loads((root / relative).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise Stage4Error(f"JSON object required: {relative}")
    return value


def _digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _closure(root: Path) -> dict[str, Any]:
    freeze = _load(root, "spec/part2-stage3-closure-freeze-v1.json")
    expected = {
        "state": "PART2_STAGE3_ADMISSION_NORMALIZATION_VERIFIED",
        "pull_request": 12,
        "pull_request_head": STAGE3_HEAD,
        "squash_merge_commit": STAGE3_MAIN,
        "squash_merge_tree": STAGE3_TREE,
        "squash_merge_parent": STAGE3_PARENT,
        "exact_head_ci_run": STAGE3_PR_CI,
        "postmerge_main_ci_run": STAGE3_MAIN_CI,
        "ci_artifact_id": STAGE3_ARTIFACT,
        "ci_test_count": 337,
        "coverage_statements": 596,
        "coverage_branches": 238,
        "coverage_percent": 100.0,
        "mutation_checks": 15,
        "mutation_survivors": 0,
        "stage3_candidate_digest": (
            "b0a2e17de3af089b640476477ba3d1ad3fb3f1cf4270a84ec93db11bb27553fc"
        ),
    }
    for key, value in expected.items():
        _require(freeze.get(key) == value, f"Stage 3 closure differs: {key}")
    protected = cast(dict[str, Any], freeze.get("protected_authorities"))
    _require(isinstance(protected, dict) and len(protected) == 10, "closure authority set differs")
    for relative, expected_digest in protected.items():
        _require(isinstance(relative, str) and isinstance(expected_digest, str), "bad closure row")
        _require(
            _digest(root / relative) == expected_digest, f"Stage 3 authority differs: {relative}"
        )
    return freeze


def _schemas(root: Path) -> dict[str, str]:
    observed = {relative: _digest(root / relative) for relative in FROZEN_SCHEMA_DIGESTS}
    _require(observed == FROZEN_SCHEMA_DIGESTS, "frozen v1 or accepted v2 schema differs")
    ContractRegistry.load(root)
    return observed


def _contract(root: Path) -> dict[str, Any]:
    contract = _load(root, "contracts/part2-stage4-transaction-reconciliation-v1.json")
    baseline = cast(dict[str, Any], contract.get("entry_baseline"))
    _require(
        baseline
        == {
            "stage3_pull_request": 12,
            "stage3_pull_request_head": STAGE3_HEAD,
            "stage3_main_commit": STAGE3_MAIN,
            "stage3_main_tree": STAGE3_TREE,
            "stage3_main_parent": STAGE3_PARENT,
            "stage3_exact_head_ci_run": STAGE3_PR_CI,
            "stage3_postmerge_main_ci_run": STAGE3_MAIN_CI,
            "stage3_ci_artifact_id": STAGE3_ARTIFACT,
        },
        "Stage 3 entry baseline differs",
    )
    _require(contract.get("stage_gates") == STAGE4_GATES, "Stage 4 gates differ")
    boundary = cast(dict[str, Any], contract.get("implementation_boundary"))
    _require(boundary.get("transaction_engine_implemented") is True, "engine claim missing")
    for field in (
        "settlement_engine_implemented",
        "bank_allocation_implemented",
        "authoritative_proof_store_implemented",
        "revision_store_implemented",
        "spark_reconciliation_implemented",
        "aws_workload_allowed",
        "aws_execution",
        "infrastructure_mutation",
    ):
        _require(boundary.get(field) is False, f"implementation boundary inflated: {field}")
    master = cast(dict[str, Any], contract.get("master_part2_completion_gates"))
    _require(
        master.get("independent_oracle_verified") == "EXTERNALLY_VERIFIED", "oracle not closed"
    )
    _require(
        all(
            value == "UNCLAIMED"
            for key, value in master.items()
            if key != "independent_oracle_verified"
        ),
        "non-Stage-4 master gate claimed",
    )
    return contract


def _traceability(root: Path) -> None:
    requirements = cast(
        list[dict[str, Any]], _load(root, "spec/part2-stage4-requirements-v1.json")["requirements"]
    )
    gates = cast(
        list[dict[str, Any]], _load(root, "spec/part2-stage4-gate-registry-v1.json")["gates"]
    )
    rows = cast(
        list[dict[str, Any]], _load(root, "spec/part2-stage4-traceability-v1.json")["traceability"]
    )
    _require(
        [row["id"] for row in requirements] == STAGE4_REQUIREMENTS, "requirement order differs"
    )
    _require([row["gate_id"] for row in gates] == STAGE4_GATES, "gate order differs")
    _require(
        [row["requirement_id"] for row in rows] == STAGE4_REQUIREMENTS, "trace inventory differs"
    )
    _require({row["gate_id"] for row in requirements} == set(STAGE4_GATES), "gate coverage differs")
    for row in rows:
        _require(
            bool(row.get("authorities") and row.get("validation") and row.get("evidence")),
            "empty trace row",
        )
        for relative in row["authorities"]:
            _require((root / relative).is_file(), f"trace authority missing: {relative}")


def _coverage(root: Path) -> dict[str, Any]:
    coverage = _load(root, "spec/part2-stage4-coverage-v1.json")
    _require(
        set(coverage.get("financial_reason_codes", [])) == FINANCIAL_REASONS,
        "reason domain differs",
    )
    _require(coverage.get("mutation_classes") == MUTATION_CLASSES, "mutation registry differs")
    _require(coverage.get("minimum_statement_percent") == 100.0, "statement threshold differs")
    _require(coverage.get("minimum_branch_percent") == 100.0, "branch threshold differs")
    return coverage


def _production_imports(root: Path) -> list[str]:
    observed: set[str] = set()
    for path in sorted((root / "src/ledgerguard/reconciliation").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                observed.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                observed.add(node.module.split(".")[0])
    _require(
        not observed.intersection(FORBIDDEN_PRODUCTION_IMPORTS),
        "production import boundary differs",
    )
    return sorted(observed)


def _locked_requirements(path: Path) -> list[str]:
    rows = [
        line.strip()
        for line in path.read_text().splitlines()
        if line.strip() and not line.startswith("#")
    ]
    _require(bool(rows), f"dependency lock is empty: {path.name}")
    _require(
        all("==" in row and "--hash=sha256:" in row for row in rows),
        f"dependency is not hash-locked: {path.name}",
    )
    return rows


def _controls(root: Path) -> dict[str, Any]:
    bootstrap = _locked_requirements(root / "requirements/part2-stage4-bootstrap.lock")
    runtime = _locked_requirements(root / "requirements/part2-stage4-py311.lock")
    _require(len(bootstrap) == 3, "Stage 4 bootstrap lock inventory differs")
    forbidden = ("pyspark==", "py4j==", "boto3==", "botocore==", "pandas==", "requests==")
    _require(
        not any(row.startswith(forbidden) for row in runtime), "transaction lock is not minimal"
    )
    pyproject = (root / "pyproject.toml").read_text()
    for command in (
        'ledgerguard-part2-stage4 = "ledgerguard_part2_stage4_validation:main"',
        'ledgerguard-part2-stage4-reconcile = "ledgerguard_part2_stage4:main"',
    ):
        _require(command in pyproject, f"Stage 4 command missing: {command}")
    workflow = (root / ".github/workflows/ci.yml").read_text()
    for marker in (
        "PART2_STAGE3_CLOSURE_SHA",
        "$RUNNER_TEMP/ledgerguard-part2-stage3-closure",
        "$RUNNER_TEMP/ledgerguard-part2-stage4",
        "tools/build_part2_stage4_ci_evidence.py",
        "ledgerguard-part2-stage4-${{ github.event.pull_request.head.sha }}",
    ):
        _require(marker in workflow, f"Stage 4 CI control missing: {marker}")
    schema = _load(root, "spec/part2-stage4-ci-evidence-v1.schema.json")
    Draft202012Validator.check_schema(schema)
    return {
        "bootstrap_dependencies": len(bootstrap),
        "runtime_dependencies": len(runtime),
        "ci_evidence_schema_valid": True,
    }


def validate_stage4(root: Path | None = None) -> dict[str, Any]:
    """Validate the complete local Stage 4 candidate and its claim boundary."""

    repository = (root or Path(__file__).resolve().parents[1]).resolve()
    stage3_regression = validate_stage3(repository)
    closure = _closure(repository)
    schemas = _schemas(repository)
    _contract(repository)
    _traceability(repository)
    coverage = _coverage(repository)
    imports = _production_imports(repository)
    controls = _controls(repository)
    artifact_digests: dict[str, str] = {}
    for relative in STAGE4_ARTIFACTS:
        path = repository / relative
        _require(path.is_file(), f"Stage 4 artifact missing: {relative}")
        artifact_digests[relative] = _digest(path)
    payload = {
        "artifacts": artifact_digests,
        "closure": closure,
        "schemas": schemas,
        "coverage": coverage,
        "imports": imports,
        "controls": controls,
    }
    return {
        "project": PROJECT,
        "part": 2,
        "stage": 4,
        "state": "PART2_IN_PROGRESS",
        "stage_state": "PART2_STAGE4_TRANSACTION_RECONCILIATION_VERIFIED_CANDIDATE",
        "stage3_closure": {
            "state": "EXTERNALLY_VERIFIED",
            "commit": STAGE3_MAIN,
            "tree": STAGE3_TREE,
            "parent": STAGE3_PARENT,
        },
        "stage3_regression_state": stage3_regression["stage_state"],
        "stage4_candidate_digest": sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "artifact_digests": artifact_digests,
        "transaction": {
            "reason_codes": len(FINANCIAL_REASONS),
            "mutation_classes": len(MUTATION_CLASSES),
            "frozen_schemas": len(schemas),
            "production_imports": imports,
            **controls,
            "authoritative_proofs_emitted": 0,
        },
        "master_part2_gates": {
            "independent_oracle_verified": "EXTERNALLY_VERIFIED",
            "spark_parity_verified": "UNCLAIMED",
            "financial_invariants_verified": "UNCLAIMED",
            "failure_matrix_verified": "UNCLAIMED",
            "deterministic_replay_verified": "UNCLAIMED",
            "critical_paths_tested": "UNCLAIMED",
        },
        "aws_execution": False,
        "infrastructure_mutation": False,
    }


def main() -> None:
    print(json.dumps(validate_stage4(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
