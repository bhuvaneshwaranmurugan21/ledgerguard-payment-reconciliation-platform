"""Fail-closed validation for Part 2 Stage 6 proof finalization."""

from __future__ import annotations

import ast
import json
from hashlib import sha256
from pathlib import Path
from typing import Any, cast

from jsonschema import Draft202012Validator

from ledgerguard.reconciliation import ContractRegistry
from ledgerguard_part2_stage3_validation import FROZEN_SCHEMA_DIGESTS
from ledgerguard_part2_stage5_validation import validate_stage5

PROJECT = "ledgerguard-payment-reconciliation-platform"
STAGE5_MAIN = "89373adf968ff7071693f8cce5d12901fd9b1e69"
STAGE5_TREE = "41bdd1fb8209f44dbbc21a5737f0e28eebab904b"
STAGE5_PARENT = "c423ae7e6e92d37ffa8a796b4efacbf9ba6692f1"
STAGE5_HEAD = "f8cfcd33531ac91f8bba2babce37f741fe116a7a"
STAGE5_PR_CI = 33753674472
STAGE5_MAIN_CI = 33777351580
STAGE5_ARTIFACT = 9893049530
STAGE6_REQUIREMENTS = [f"P2-S6-R{number:03d}" for number in range(1, 31)]
STAGE6_GATES = [f"P2-S6-G{number:03d}" for number in range(1, 11)]
STAGE6_GATE_NAMES = [
    "verified_stage5_entry",
    "atomic_conditional_authority",
    "immutable_content_integrity",
    "append_only_proof_revisions",
    "append_only_case_revisions",
    "failure_ownership_and_no_partial_authority",
    "idempotent_replay_and_crash_recovery",
    "durable_cross_batch_state_handoff",
    "local_scope_and_dependency_boundary",
    "reproducible_external_evidence",
]
MUTATION_CLASSES = [
    "PUBLISH_HEAD_BEFORE_OBJECTS",
    "PUBLISH_HEAD_BEFORE_COMMIT",
    "ALLOW_STALE_EXPECTED_HEAD",
    "ALLOW_MULTIPLE_CONCURRENT_WINNERS",
    "OVERWRITE_IMMUTABLE_OBJECT",
    "TRUST_OBJECT_PATH_WITHOUT_DIGEST",
    "TRUST_NONCANONICAL_OBJECT",
    "TRUST_PROOF_WITHOUT_SCHEMA",
    "DROP_PROOF_SELF_DIGEST_CHECK",
    "DROP_PROOF_PREDECESSOR",
    "REWRITE_PROOF_REVISION",
    "DROP_EXCEPTION_CASE",
    "CREATE_CASE_FOR_INITIAL_MATCH",
    "DROP_CASE_PREDECESSOR",
    "FAIL_TO_RESOLVE_LATE_MATCH",
    "MISCLASSIFY_STORAGE_FAILURE_AS_FINANCIAL",
    "RETURN_PARTIAL_AUTHORITY_ON_FAILURE",
    "REUSE_ATTEMPT_WITH_DIFFERENT_REQUEST",
    "DUPLICATE_EXACT_RETRY",
    "LOSE_HISTORICAL_RETRY",
    "LOSE_AFTER_HEAD_RECOVERY",
    "DROP_PERSISTED_RECONCILIATION_STATE",
    "ALLOW_PRIOR_HISTORY_REMOVAL",
    "NONDETERMINISTIC_FINALIZATION_BYTES",
]
FORBIDDEN_PRODUCTION_IMPORTS = {
    "boto3",
    "botocore",
    "ledgerguard_reference_oracle",
    "pandas",
    "pyarrow",
    "pyspark",
    "requests",
    "sqlalchemy",
}
STAGE6_ARTIFACTS = (
    ".github/workflows/ci.yml",
    "README.md",
    "PROJECT_STATUS.md",
    "contracts/part2-stage6-proof-finalization-v1.json",
    "docs/adr/0022-atomic-proof-finalization-and-recovery.md",
    "docs/part2-execution-contract.md",
    "docs/part2-stage6-gap-audit.md",
    "docs/part2-stage6-proof-finalization.md",
    "pyproject.toml",
    "requirements/part2-stage6-bootstrap.lock",
    "requirements/part2-stage6-py311.lock",
    "spec/part2-stage5-closure-freeze-v1.json",
    "spec/part2-stage6-ci-evidence-v1.schema.json",
    "spec/part2-stage6-coverage-v1.json",
    "spec/part2-stage6-gate-registry-v1.json",
    "spec/part2-stage6-requirements-v1.json",
    "spec/part2-stage6-traceability-v1.json",
    "spec/part2-stage6-vectors-v1.json",
    "src/ledgerguard/reconciliation/__init__.py",
    "src/ledgerguard/reconciliation/finalization.py",
    "src/ledgerguard/reconciliation/identity.py",
    "src/ledgerguard_part2_stage6.py",
    "src/ledgerguard_part2_stage6_evidence.py",
    "src/ledgerguard_part2_stage6_validation.py",
    "tests/test_part2_stage6_finalization.py",
    "tests/test_part2_stage6_validation.py",
    "tools/build_part2_stage6_ci_evidence.py",
    "tools/run_part2_stage6.py",
    "tools/validate_part2_stage6_run.py",
)


class Stage6Error(ValueError):
    """Raised when the Stage 6 candidate is incomplete or inflated."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise Stage6Error(message)


def _load(root: Path, relative: str) -> dict[str, Any]:
    value = json.loads((root / relative).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise Stage6Error(f"JSON object required: {relative}")
    return value


def _digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _closure(root: Path) -> dict[str, Any]:
    freeze = _load(root, "spec/part2-stage5-closure-freeze-v1.json")
    expected = {
        "state": "PART2_STAGE5_SETTLEMENT_RECONCILIATION_VERIFIED",
        "pull_request": 14,
        "pull_request_head": STAGE5_HEAD,
        "squash_merge_commit": STAGE5_MAIN,
        "squash_merge_tree": STAGE5_TREE,
        "squash_merge_parent": STAGE5_PARENT,
        "exact_head_ci_run": STAGE5_PR_CI,
        "postmerge_main_ci_run": STAGE5_MAIN_CI,
        "ci_artifact_id": STAGE5_ARTIFACT,
        "ci_artifact_zip_sha256": (
            "43563a99d649d99773c5851918e682dd1e13c50b2846efc78544b64344a2666d"
        ),
        "ci_evidence_sha256": ("54131047abe8fd05e8d8c3077cddeae5c4f999c075752eee4e23d0c10fcc58c1"),
        "ci_test_count": 425,
        "coverage_statements": 1182,
        "coverage_branches": 468,
        "coverage_percent": 100.0,
        "mutation_checks": 29,
        "mutation_survivors": 0,
        "stage5_candidate_digest": (
            "a230fdfbcffcda993b1aebc72638257f8102f1eab02a492a52af11001c326d8a"
        ),
        "deterministic_payload_sha256": (
            "d89f7ddc5338d7e7eebf15e840d99a0d7bd9c604cbeb5267d17d0acfbbe02b2c"
        ),
        "wheel_sha256": "883a691c6f23f8d088afc87e60e3ff79f744acb35903bead65ff170728516652",
    }
    for key, value in expected.items():
        _require(freeze.get(key) == value, f"Stage 5 closure differs: {key}")
    protected = cast(dict[str, Any], freeze.get("protected_authorities"))
    _require(isinstance(protected, dict) and len(protected) == 10, "closure authority set differs")
    for relative, expected_digest in protected.items():
        _require(isinstance(relative, str) and isinstance(expected_digest, str), "bad closure row")
        _require(
            _digest(root / relative) == expected_digest, f"Stage 5 authority differs: {relative}"
        )
    return freeze


def _schemas(root: Path) -> dict[str, str]:
    observed = {relative: _digest(root / relative) for relative in FROZEN_SCHEMA_DIGESTS}
    _require(observed == FROZEN_SCHEMA_DIGESTS, "frozen v1 or accepted v2 schema differs")
    ContractRegistry.load(root)
    return observed


def _contract(root: Path) -> dict[str, Any]:
    contract = _load(root, "contracts/part2-stage6-proof-finalization-v1.json")
    identity = {key: contract.get(key) for key in ("schema_version", "project", "part", "stage")}
    _require(
        identity == {"schema_version": "1.0", "project": PROJECT, "part": 2, "stage": 6},
        "Stage 6 identity differs",
    )
    _require(contract.get("state") == "PART2_IN_PROGRESS", "Stage 6 project state differs")
    _require(
        contract.get("stage_state") == "PART2_STAGE6_PROOF_FINALIZATION_VERIFIED_CANDIDATE",
        "Stage 6 state differs",
    )
    _require(contract.get("stage_gates") == STAGE6_GATES, "Stage 6 gates differ")
    finalization = cast(dict[str, Any], contract.get("finalization_contract"))
    _require(
        finalization.get("authority_pointer") == "ONE_CONDITIONAL_CONTENT_ADDRESSED_HEAD"
        and finalization.get("atomicity_scope") == "TRANSACTION_AND_SETTLEMENT_CANDIDATE_BATCH"
        and finalization.get("durability_order")
        == ["REQUEST", "OBJECTS", "COMMIT", "HEAD", "OUTCOME"]
        and finalization.get("failure_ownership")
        == "EXECUTION_FAILURE_NO_AUTHORITATIVE_PARTIAL_PROOF",
        "Stage 6 finalization contract differs",
    )
    boundary = cast(dict[str, Any], contract.get("implementation_boundary"))
    _require(
        all(
            boundary.get(key) is True
            for key in (
                "authoritative_local_proof_store_implemented",
                "proof_revision_store_implemented",
                "case_revision_store_implemented",
                "crash_recovery_implemented",
                "conditional_authority_implemented",
            )
        )
        and all(
            boundary.get(key) is False
            for key in (
                "spark_reconciliation_implemented",
                "managed_parquet_persistence_implemented",
                "aws_workload_allowed",
                "aws_execution",
                "infrastructure_mutation",
            )
        ),
        "Stage 6 implementation boundary differs or is inflated",
    )
    master = cast(dict[str, Any], contract.get("master_part2_completion_gates"))
    _require(master.get("independent_oracle_verified") == "EXTERNALLY_VERIFIED", "oracle differs")
    _require(
        master.get("financial_invariants_verified") == "EXTERNALLY_VERIFIED", "finance differs"
    )
    _require(master.get("failure_matrix_verified") == "UNCLAIMED", "failure gate differs")
    _require(
        master.get("deterministic_replay_verified") == "VERIFIED_CANDIDATE",
        "replay gate differs",
    )
    _require(
        master.get("spark_parity_verified") == "UNCLAIMED"
        and master.get("critical_paths_tested") == "UNCLAIMED",
        "non-Stage-6 master gate claimed",
    )
    return contract


def _traceability(root: Path) -> None:
    requirements = cast(
        list[dict[str, Any]], _load(root, "spec/part2-stage6-requirements-v1.json")["requirements"]
    )
    gates = cast(
        list[dict[str, Any]], _load(root, "spec/part2-stage6-gate-registry-v1.json")["gates"]
    )
    rows = cast(
        list[dict[str, Any]], _load(root, "spec/part2-stage6-traceability-v1.json")["traceability"]
    )
    _require([row.get("id") for row in requirements] == STAGE6_REQUIREMENTS, "requirements differ")
    _require(
        [(row.get("gate_id"), row.get("name")) for row in gates]
        == list(zip(STAGE6_GATES, STAGE6_GATE_NAMES, strict=True)),
        "gate registry differs",
    )
    _require([row.get("gate_id") for row in rows] == STAGE6_GATES, "trace gates differ")
    traced = [item for row in rows for item in cast(list[str], row.get("requirement_ids"))]
    _require(traced == STAGE6_REQUIREMENTS, "trace requirement ownership differs")
    expected_gate = {str(row["id"]): str(row["gate_id"]) for row in requirements}
    for row in rows:
        _require(
            all(expected_gate[item] == row["gate_id"] for item in row["requirement_ids"]),
            "trace gate ownership differs",
        )
        for field in ("authorities", "validation", "evidence"):
            _require(bool(row.get(field)), f"empty trace {field}")
        for relative in row["authorities"] + row["validation"]:
            _require((root / relative).is_file(), f"trace file missing: {relative}")


def _coverage(root: Path) -> dict[str, Any]:
    coverage = _load(root, "spec/part2-stage6-coverage-v1.json")
    _require(coverage.get("production_surface") == "ledgerguard.reconciliation", "surface differs")
    _require(
        coverage.get("minimum_statement_percent") == 100.0
        and coverage.get("minimum_branch_percent") == 100.0,
        "coverage threshold differs",
    )
    _require(coverage.get("mutation_classes") == MUTATION_CLASSES, "mutation registry differs")
    return coverage


def _production_imports(root: Path) -> list[str]:
    observed: set[str] = set()
    for relative in (
        "src/ledgerguard/reconciliation/finalization.py",
        "src/ledgerguard_part2_stage6.py",
    ):
        tree = ast.parse((root / relative).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                observed.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                observed.add(node.module.split(".")[0])
    _require(not (observed & FORBIDDEN_PRODUCTION_IMPORTS), "production import boundary differs")
    return sorted(observed)


def _locked_requirements(path: Path) -> list[str]:
    rows = [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]
    _require(bool(rows), f"dependency lock is empty: {path.name}")
    _require(
        all("==" in row and "--hash=sha256:" in row for row in rows),
        f"dependency is not hash-locked: {path.name}",
    )
    return rows


def _controls(root: Path) -> dict[str, Any]:
    bootstrap = _locked_requirements(root / "requirements/part2-stage6-bootstrap.lock")
    runtime = _locked_requirements(root / "requirements/part2-stage6-py311.lock")
    _require(len(bootstrap) == 3, "Stage 6 bootstrap lock inventory differs")
    forbidden = ("pyspark==", "py4j==", "boto3==", "botocore==", "pandas==", "requests==")
    _require(
        not any(row.startswith(forbidden) for row in runtime), "Stage 6 lock is not local-only"
    )
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    for command in (
        'ledgerguard-part2-stage6 = "ledgerguard_part2_stage6_validation:main"',
        'ledgerguard-part2-stage6-finalize = "ledgerguard_part2_stage6:main"',
    ):
        _require(command in pyproject, f"Stage 6 command missing: {command}")
    workflow = (root / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    for marker in (
        "PART2_STAGE5_CLOSURE_SHA",
        "$RUNNER_TEMP/ledgerguard-part2-stage5-closure",
        "$RUNNER_TEMP/ledgerguard-part2-stage6",
        "tools/build_part2_stage6_ci_evidence.py",
        "ledgerguard-part2-stage6-${{ github.event.pull_request.head.sha }}",
    ):
        _require(marker in workflow, f"Stage 6 CI control missing: {marker}")
    schema = _load(root, "spec/part2-stage6-ci-evidence-v1.schema.json")
    Draft202012Validator.check_schema(schema)
    return {
        "bootstrap_dependencies": len(bootstrap),
        "runtime_dependencies": len(runtime),
        "ci_evidence_schema_valid": True,
    }


def validate_stage6(root: Path | None = None) -> dict[str, Any]:
    """Validate the complete local Stage 6 candidate and its claim boundary."""

    repository = (root or Path(__file__).resolve().parents[1]).resolve()
    stage5_regression = validate_stage5(repository)
    closure = _closure(repository)
    schemas = _schemas(repository)
    _contract(repository)
    _traceability(repository)
    _coverage(repository)
    imports = _production_imports(repository)
    controls = _controls(repository)
    artifact_digests: dict[str, str] = {}
    for relative in STAGE6_ARTIFACTS:
        path = repository / relative
        _require(path.is_file(), f"Stage 6 artifact missing: {relative}")
        artifact_digests[relative] = _digest(path)
    payload = {
        "artifacts": artifact_digests,
        "closure": closure,
        "schemas": schemas,
        "imports": imports,
        "controls": controls,
    }
    return {
        "project": PROJECT,
        "part": 2,
        "stage": 6,
        "state": "PART2_IN_PROGRESS",
        "stage_state": "PART2_STAGE6_PROOF_FINALIZATION_VERIFIED_CANDIDATE",
        "stage5_closure": {"state": "EXTERNALLY_VERIFIED", "commit": STAGE5_MAIN},
        "stage5_regression_state": stage5_regression["stage_state"],
        "stage6_candidate_digest": sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "artifact_digests": artifact_digests,
        "finalization": {
            "mutation_classes": len(MUTATION_CLASSES),
            "frozen_schemas": len(schemas),
            "production_imports": imports,
            **controls,
        },
        "master_part2_gates": {
            "independent_oracle_verified": "EXTERNALLY_VERIFIED",
            "spark_parity_verified": "UNCLAIMED",
            "financial_invariants_verified": "EXTERNALLY_VERIFIED",
            "failure_matrix_verified": "UNCLAIMED",
            "deterministic_replay_verified": "VERIFIED_CANDIDATE",
            "critical_paths_tested": "UNCLAIMED",
        },
        "aws_execution": False,
        "spark_execution": False,
        "managed_persistence": False,
        "infrastructure_mutation": False,
    }


def main() -> None:
    print(json.dumps(validate_stage6(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
