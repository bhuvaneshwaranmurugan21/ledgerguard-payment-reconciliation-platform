"""Fail-closed validation for Part 2 Stage 5 settlement reconciliation."""

from __future__ import annotations

import ast
import json
from hashlib import sha256
from pathlib import Path
from typing import Any, cast

from jsonschema import Draft202012Validator

from ledgerguard.reconciliation import ContractRegistry
from ledgerguard_part2_stage3_validation import FROZEN_SCHEMA_DIGESTS
from ledgerguard_part2_stage4_validation import validate_stage4

PROJECT = "ledgerguard-payment-reconciliation-platform"
STAGE4_MAIN = "c423ae7e6e92d37ffa8a796b4efacbf9ba6692f1"
STAGE4_TREE = "f7c8bfc82ebd895f60d9ad26f35e9922b35c5de9"
STAGE4_PARENT = "47e96d3f4846d55568c0b137fb3e4d41ead0eef1"
STAGE4_HEAD = "f83285c2e8e6f70b597f1fc38ff1e77a2d277c03"
STAGE4_PR_CI = 33737068906
STAGE4_MAIN_CI = 33741521494
STAGE4_ARTIFACT = 9886556226
STAGE5_REQUIREMENTS = [f"P2-S5-R{number:03d}" for number in range(1, 36)]
STAGE5_GATES = [f"P2-S5-G{number:03d}" for number in range(1, 11)]
STAGE5_GATE_NAMES = [
    "verified_stage4_entry",
    "lossless_replay_and_duplicate_handoff",
    "exact_settlement_grain_and_formula",
    "checked_settlement_clearing_movement",
    "exact_bank_allocation",
    "bank_integrity_and_unallocated_visibility",
    "three_way_status_and_reason_precedence",
    "immutable_deterministic_candidate_state",
    "scope_and_oracle_independence",
    "reproducible_external_evidence",
]
FINANCIAL_REASONS = {
    "INVALID_ACCOUNT_ROLE",
    "MISSING_LEDGER_MOVEMENT",
    "MISSING_PROCESSOR_ACTIVITY",
    "MISSING_BANK_SETTLEMENT",
    "UNALLOCATED_BANK_MOVEMENT",
    "INVALID_BANK_ACCOUNT",
    "DUPLICATE_BANK_MOVEMENT",
    "SETTLEMENT_FORMULA_MISMATCH",
    "PROCESSOR_LEDGER_MISMATCH",
    "PROCESSOR_BANK_MISMATCH",
    "LEDGER_BANK_MISMATCH",
}
MUTATION_CLASSES = [
    "USE_REPORTED_NET_INSTEAD_OF_RECOMPUTED",
    "AGGREGATE_BEFORE_FORMULA_VALIDATION",
    "DROP_SETTLEMENT_CYCLE_FROM_KEY",
    "INNER_JOIN_SETTLEMENT_GRAINS",
    "COLLAPSE_SETTLEMENT_MISSING_TO_ZERO",
    "USE_TOTAL_JOURNAL_DEBIT",
    "REVERSE_SETTLEMENT_CLEARING_ORIENTATION",
    "REVERSE_BANK_CREDIT_SIGN",
    "REVERSE_BANK_DEBIT_SIGN",
    "LOWERCASE_BANK_REFERENCE",
    "DROP_BANK_REFERENCE_PUNCTUATION",
    "ALLOW_AMOUNT_DATE_HEURISTIC",
    "ALLOCATE_UNKNOWN_REFERENCE",
    "ALLOW_AMBIGUOUS_REFERENCE",
    "DOUBLE_ALLOCATE_BANK_IDENTITY",
    "DOUBLE_APPLY_PRIOR_REPLAY",
    "DROP_CURRENT_BUNDLE_DUPLICATE_REASON",
    "COUNT_CURRENT_BUNDLE_DUPLICATE_TWICE",
    "ALLOW_DISALLOWED_BANK_ACCOUNT",
    "REJECT_VALID_SPLIT_BANK_ENTRIES",
    "DROP_PROCESSOR_LEDGER_DELTA",
    "DROP_PROCESSOR_BANK_DELTA",
    "DROP_LEDGER_BANK_DELTA",
    "USE_NON_MAX_SETTLEMENT_DIFFERENCE",
    "TOLERATE_SETTLEMENT_SEMANTIC_FAILURE",
    "UNCHECKED_SETTLEMENT_AGGREGATION",
    "TRANSACTION_CONTAMINATES_SETTLEMENT",
    "NONDETERMINISTIC_SETTLEMENT_ORDER",
    "EMIT_AUTHORITATIVE_SETTLEMENT_PROOF",
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
STAGE5_ARTIFACTS = (
    ".github/workflows/ci.yml",
    "README.md",
    "PROJECT_STATUS.md",
    "contracts/part2-stage5-settlement-reconciliation-v1.json",
    "docs/adr/0021-settlement-reconciliation-and-exact-bank-allocation.md",
    "docs/part2-execution-contract.md",
    "docs/part2-stage5-gap-audit.md",
    "docs/part2-stage5-settlement-reconciliation.md",
    "pyproject.toml",
    "requirements/part2-stage5-bootstrap.lock",
    "requirements/part2-stage5-py311.lock",
    "spec/part2-stage4-closure-freeze-v1.json",
    "spec/part2-stage5-ci-evidence-v1.schema.json",
    "spec/part2-stage5-coverage-v1.json",
    "spec/part2-stage5-gate-registry-v1.json",
    "spec/part2-stage5-requirements-v1.json",
    "spec/part2-stage5-traceability-v1.json",
    "spec/part2-stage5-vectors-v1.json",
    "src/ledgerguard/reconciliation/__init__.py",
    "src/ledgerguard/reconciliation/admission.py",
    "src/ledgerguard/reconciliation/settlement.py",
    "src/ledgerguard_part2_stage5.py",
    "src/ledgerguard_part2_stage5_evidence.py",
    "src/ledgerguard_part2_stage5_validation.py",
    "tests/test_part2_stage3_admission.py",
    "tests/test_part2_stage5_settlement.py",
    "tests/test_part2_stage5_validation.py",
    "tools/build_part2_stage5_ci_evidence.py",
    "tools/run_part2_stage5.py",
    "tools/validate_part2_stage5_run.py",
)


class Stage5Error(ValueError):
    """Raised when the Stage 5 candidate is incomplete or inflated."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise Stage5Error(message)


def _load(root: Path, relative: str) -> dict[str, Any]:
    value = json.loads((root / relative).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise Stage5Error(f"JSON object required: {relative}")
    return value


def _digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _closure(root: Path) -> dict[str, Any]:
    freeze = _load(root, "spec/part2-stage4-closure-freeze-v1.json")
    expected = {
        "state": "PART2_STAGE4_TRANSACTION_RECONCILIATION_VERIFIED",
        "pull_request": 13,
        "pull_request_head": STAGE4_HEAD,
        "squash_merge_commit": STAGE4_MAIN,
        "squash_merge_tree": STAGE4_TREE,
        "squash_merge_parent": STAGE4_PARENT,
        "exact_head_ci_run": STAGE4_PR_CI,
        "postmerge_main_ci_run": STAGE4_MAIN_CI,
        "ci_artifact_id": STAGE4_ARTIFACT,
        "ci_artifact_zip_sha256": (
            "cd2068d665fef70b892b9d554bdec25dd4cb1dfea4ab080c2c764b0b1389ba46"
        ),
        "ci_evidence_sha256": ("e96c414b30e7251b63a88f1725095d3f2ce28a0e787a8f068252e453b6f17ab9"),
        "ci_test_count": 364,
        "coverage_statements": 841,
        "coverage_branches": 336,
        "coverage_percent": 100.0,
        "mutation_checks": 20,
        "mutation_survivors": 0,
        "stage4_candidate_digest": (
            "8dfecaceb7bdcfcbd503c98cda786b6cf0d7b479c8bdf9d7407a5daf213f2cff"
        ),
        "deterministic_payload_sha256": (
            "b969fffa1b939a4e1b507d1d02ce8fa2912a63c53a6171600f39f21a68ca29bc"
        ),
        "wheel_sha256": "dc5dbe506a261760b2c693841209a19343a43fe778e4ac824e0ebc73e09cfad8",
    }
    for key, value in expected.items():
        _require(freeze.get(key) == value, f"Stage 4 closure differs: {key}")
    protected = cast(dict[str, Any], freeze.get("protected_authorities"))
    _require(isinstance(protected, dict) and len(protected) == 10, "closure authority set differs")
    for relative, expected_digest in protected.items():
        _require(isinstance(relative, str) and isinstance(expected_digest, str), "bad closure row")
        _require(
            _digest(root / relative) == expected_digest, f"Stage 4 authority differs: {relative}"
        )
    return freeze


def _schemas(root: Path) -> dict[str, str]:
    observed = {relative: _digest(root / relative) for relative in FROZEN_SCHEMA_DIGESTS}
    _require(observed == FROZEN_SCHEMA_DIGESTS, "frozen v1 or accepted v2 schema differs")
    ContractRegistry.load(root)
    return observed


def _contract(root: Path) -> dict[str, Any]:
    contract = _load(root, "contracts/part2-stage5-settlement-reconciliation-v1.json")
    _require(
        {
            "schema_version": contract.get("schema_version"),
            "project": contract.get("project"),
            "part": contract.get("part"),
            "stage": contract.get("stage"),
            "state": contract.get("state"),
            "stage_state": contract.get("stage_state"),
        }
        == {
            "schema_version": "1.0",
            "project": PROJECT,
            "part": 2,
            "stage": 5,
            "state": "PART2_IN_PROGRESS",
            "stage_state": "PART2_STAGE5_SETTLEMENT_RECONCILIATION_VERIFIED_CANDIDATE",
        },
        "Stage 5 identity or state differs",
    )
    baseline = cast(dict[str, Any], contract.get("entry_baseline"))
    _require(
        baseline
        == {
            "stage4_pull_request": 13,
            "stage4_pull_request_head": STAGE4_HEAD,
            "stage4_main_commit": STAGE4_MAIN,
            "stage4_main_tree": STAGE4_TREE,
            "stage4_main_parent": STAGE4_PARENT,
            "stage4_exact_head_ci_run": STAGE4_PR_CI,
            "stage4_postmerge_main_ci_run": STAGE4_MAIN_CI,
            "stage4_ci_artifact_id": STAGE4_ARTIFACT,
        },
        "Stage 4 entry baseline differs",
    )
    _require(contract.get("stage_gates") == STAGE5_GATES, "Stage 5 gates differ")
    settlement_contract = cast(dict[str, Any], contract.get("settlement_contract"))
    _require(
        settlement_contract
        == {
            "grain": [
                "processor",
                "merchant_id",
                "settlement_id",
                "settlement_cycle",
                "currency",
            ],
            "grain_join": "FULL_OUTER_PROCESSOR_AND_LEDGER_UNION",
            "processor_net": "PER_RECORD_RECOMPUTE_THEN_CHECKED_AGGREGATE",
            "formula_mismatch_scope": "PER_SOURCE_RECORD",
            "ledger_movement": "PROCESSOR_CLEARING_CREDITS_MINUS_DEBITS",
            "bank_movement": "CREDITS_MINUS_DEBITS",
            "bank_allocation": "EXACT_NORMALIZED_SETTLEMENT_REFERENCE",
            "allocation_domain": ["merchant_id", "currency", "normalized_settlement_id"],
            "amount_or_date_heuristic": False,
            "one_bank_identity_one_disposition": True,
            "split_bank_entries_allowed": True,
            "missing_or_unknown_reference": "UNALLOCATED_BANK_MOVEMENT",
            "ambiguous_reference": "ADMISSION_REJECTED_NO_CANDIDATES",
            "arithmetic": "CHECKED_SIGNED_64_BIT",
            "result": "IMMUTABLE_NON_AUTHORITATIVE_CANDIDATE_AND_ALLOCATION_LEDGER",
        },
        "Stage 5 settlement contract differs",
    )
    boundary = cast(dict[str, Any], contract.get("implementation_boundary"))
    _require(
        boundary
        == {
            "production_admission_implemented": True,
            "transaction_engine_implemented": True,
            "settlement_engine_implemented": True,
            "bank_allocation_implemented": True,
            "authoritative_proof_store_implemented": False,
            "revision_store_implemented": False,
            "spark_reconciliation_implemented": False,
            "aws_workload_allowed": False,
            "aws_execution": False,
            "infrastructure_mutation": False,
        },
        "Stage 5 implementation boundary differs or is inflated",
    )
    master = cast(dict[str, Any], contract.get("master_part2_completion_gates"))
    _require(
        master.get("independent_oracle_verified") == "EXTERNALLY_VERIFIED", "oracle not closed"
    )
    _require(
        master.get("financial_invariants_verified") == "VERIFIED_CANDIDATE",
        "financial claim differs",
    )
    _require(
        all(
            master.get(key) == "UNCLAIMED"
            for key in (
                "spark_parity_verified",
                "failure_matrix_verified",
                "deterministic_replay_verified",
                "critical_paths_tested",
            )
        ),
        "non-Stage-5 master gate claimed",
    )
    _require(
        contract.get("external_completion")
        == {
            "exact_head_pull_request_ci_required": True,
            "immutable_ci_evidence_required": True,
            "squash_merge_required": True,
            "independent_main_ci_required": True,
            "local_success_alone_is_insufficient": True,
            "aws_execution_required": False,
        },
        "Stage 5 external completion contract differs",
    )
    _require(
        contract.get("next_stage_entry")
        == {
            "owner": "PART2_STAGE6",
            "required_stage5_state": "PART2_STAGE5_SETTLEMENT_RECONCILIATION_VERIFIED",
            "must_freeze_stage5_external_closure": True,
            "may_redefine_contracts": False,
        },
        "Stage 6 entry contract differs",
    )
    return contract


def _traceability(root: Path) -> None:
    requirements = cast(
        list[dict[str, Any]], _load(root, "spec/part2-stage5-requirements-v1.json")["requirements"]
    )
    gates = cast(
        list[dict[str, Any]], _load(root, "spec/part2-stage5-gate-registry-v1.json")["gates"]
    )
    rows = cast(
        list[dict[str, Any]], _load(root, "spec/part2-stage5-traceability-v1.json")["traceability"]
    )
    _require(
        [row["id"] for row in requirements] == STAGE5_REQUIREMENTS, "requirement order differs"
    )
    _require(
        [(row["gate_id"], row.get("name")) for row in gates]
        == list(zip(STAGE5_GATES, STAGE5_GATE_NAMES, strict=True)),
        "gate registry differs",
    )
    _require(
        [row["requirement_id"] for row in rows] == STAGE5_REQUIREMENTS, "trace inventory differs"
    )
    _require({row["gate_id"] for row in requirements} == set(STAGE5_GATES), "gate coverage differs")
    expected_gate = {row["id"]: row["gate_id"] for row in requirements}
    for row in rows:
        _require(
            row.get("gate_id") == expected_gate[row["requirement_id"]],
            "trace gate ownership differs",
        )
        _require(
            bool(row.get("authorities") and row.get("validation") and row.get("evidence")),
            "empty trace row",
        )
        for relative in row["authorities"]:
            _require((root / relative).is_file(), f"trace authority missing: {relative}")
        for relative in row["validation"]:
            _require((root / relative).is_file(), f"trace validation missing: {relative}")


def _coverage(root: Path) -> dict[str, Any]:
    coverage = _load(root, "spec/part2-stage5-coverage-v1.json")
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
    bootstrap = _locked_requirements(root / "requirements/part2-stage5-bootstrap.lock")
    runtime = _locked_requirements(root / "requirements/part2-stage5-py311.lock")
    _require(len(bootstrap) == 3, "Stage 5 bootstrap lock inventory differs")
    forbidden = ("pyspark==", "py4j==", "boto3==", "botocore==", "pandas==", "requests==")
    _require(
        not any(row.startswith(forbidden) for row in runtime), "settlement lock is not minimal"
    )
    pyproject = (root / "pyproject.toml").read_text()
    for command in (
        'ledgerguard-part2-stage5 = "ledgerguard_part2_stage5_validation:main"',
        'ledgerguard-part2-stage5-reconcile = "ledgerguard_part2_stage5:main"',
    ):
        _require(command in pyproject, f"Stage 5 command missing: {command}")
    workflow = (root / ".github/workflows/ci.yml").read_text()
    for marker in (
        "PART2_STAGE4_CLOSURE_SHA",
        "$RUNNER_TEMP/ledgerguard-part2-stage4-closure",
        "$RUNNER_TEMP/ledgerguard-part2-stage5",
        "tools/build_part2_stage5_ci_evidence.py",
        "ledgerguard-part2-stage5-${{ github.event.pull_request.head.sha }}",
    ):
        _require(marker in workflow, f"Stage 5 CI control missing: {marker}")
    schema = _load(root, "spec/part2-stage5-ci-evidence-v1.schema.json")
    Draft202012Validator.check_schema(schema)
    return {
        "bootstrap_dependencies": len(bootstrap),
        "runtime_dependencies": len(runtime),
        "ci_evidence_schema_valid": True,
    }


def validate_stage5(root: Path | None = None) -> dict[str, Any]:
    """Validate the complete local Stage 5 candidate and its claim boundary."""

    repository = (root or Path(__file__).resolve().parents[1]).resolve()
    stage4_regression = validate_stage4(repository)
    closure = _closure(repository)
    schemas = _schemas(repository)
    _contract(repository)
    _traceability(repository)
    coverage = _coverage(repository)
    imports = _production_imports(repository)
    controls = _controls(repository)
    artifact_digests: dict[str, str] = {}
    for relative in STAGE5_ARTIFACTS:
        path = repository / relative
        _require(path.is_file(), f"Stage 5 artifact missing: {relative}")
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
        "stage": 5,
        "state": "PART2_IN_PROGRESS",
        "stage_state": "PART2_STAGE5_SETTLEMENT_RECONCILIATION_VERIFIED_CANDIDATE",
        "stage4_closure": {
            "state": "EXTERNALLY_VERIFIED",
            "commit": STAGE4_MAIN,
            "tree": STAGE4_TREE,
            "parent": STAGE4_PARENT,
        },
        "stage4_regression_state": stage4_regression["stage_state"],
        "stage5_candidate_digest": sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "artifact_digests": artifact_digests,
        "settlement": {
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
            "financial_invariants_verified": "VERIFIED_CANDIDATE",
            "failure_matrix_verified": "UNCLAIMED",
            "deterministic_replay_verified": "UNCLAIMED",
            "critical_paths_tested": "UNCLAIMED",
        },
        "aws_execution": False,
        "infrastructure_mutation": False,
    }


def main() -> None:
    print(json.dumps(validate_stage5(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
