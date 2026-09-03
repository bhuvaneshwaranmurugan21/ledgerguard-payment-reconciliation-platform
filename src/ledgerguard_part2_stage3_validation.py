"""Fail-closed validation for Part 2 Stage 3 admission and normalization."""

from __future__ import annotations

import ast
import json
from hashlib import sha256
from pathlib import Path
from typing import Any, cast

from jsonschema import Draft202012Validator

from ledgerguard.reconciliation import (
    ContractRegistry,
    business_digest,
    canonical_json_bytes,
    canonical_timestamp,
    checked_add,
    checked_i64,
    source_identity,
)

PROJECT = "ledgerguard-payment-reconciliation-platform"
STAGE2_MAIN = "55e78f76e76bff7562d43a3d001dbb74fd66d8fd"
STAGE2_TREE = "417245f6369c3d2b08ede20c35502b612b5eb3a4"
STAGE2_PARENT = "95b7e2a1c6a1dd758a8ce43c73bdea80117b6d91"
STAGE2_HEAD = "e9813d86ae6b1848a982051b9a2f0a8a1c80acd4"
STAGE2_PR_CI = 33717504782
STAGE2_MAIN_CI = 33718490292
STAGE2_ARTIFACT = 9879187613
STAGE3_REQUIREMENTS = [f"P2-S3-R{number:03d}" for number in range(1, 23)]
STAGE3_GATES = [f"P2-S3-G{number:03d}" for number in range(1, 10)]
ADMISSION_REASONS = {
    "AMBIGUOUS_BANK_ALLOCATION",
    "CURRENCY_DOMAIN_VIOLATION",
    "IDENTITY_CONFLICT",
    "POLICY_MISMATCH",
    "SCHEMA_VIOLATION",
    "SOURCE_IDENTITY_MISMATCH",
    "UNBALANCED_JOURNAL",
}
MUTATION_CLASSES = [
    "ALLOW_DUPLICATE_JSON_KEY",
    "ALLOW_FLOAT_MONEY",
    "TRUST_ACTIVE_REGISTRY_PATH",
    "TRUST_POLICY_DIGEST",
    "TRUST_MANIFEST_DIGEST",
    "TRUST_OBJECT_DIGEST",
    "ALLOW_IDENTITY_CONFLICT",
    "ALLOW_UNBALANCED_JOURNAL",
    "ALLOW_I64_OVERFLOW",
    "ALLOW_CURRENCY_CONFLICT",
    "HEURISTIC_BANK_ALLOCATION",
    "ALLOW_LOCAL_PATH_ESCAPE",
    "PARTIAL_STATE_ON_FAILURE",
    "IMPORT_REFERENCE_ORACLE",
    "EMIT_AUTHORITATIVE_PROOF",
]
FROZEN_SCHEMA_DIGESTS = {
    "contracts/bank-entry-v1.schema.json": (
        "2e166412e617bbd4456eeb69b6804861c6f0e40d433f9376253f4a9f13f996b5"
    ),
    "contracts/case-revision-v1.schema.json": (
        "b754befa40ab11f0d1ef6cc310e4b5df00378f779693a4c2c47bae2f8f5989a9"
    ),
    "contracts/journal-v1.schema.json": (
        "0a663eab588c7389a9a01566e05965a390ed19c469933ae265e5e1ac8c67556d"
    ),
    "contracts/processor-event-v1.schema.json": (
        "abdb7c1a29042d5a1c8a092ca3b0dfbf61d67f6a9449fbcb6cbd5bbfd2e00420"
    ),
    "contracts/processor-settlement-v1.schema.json": (
        "9fdef0259b580f799fc93878231ddeb9af8d663ff8bb32ac26e8ecb471a4e53f"
    ),
    "contracts/reconciliation-policy-v1.schema.json": (
        "6d460f9336a8c546097813ff8888dc89243f7fa8c89114c48f7d48549d75fa19"
    ),
    "contracts/reconciliation-proof-v1.schema.json": (
        "9b3705bd4bb79b19804bee530c44e705755a04c6904fc7beaed4a8e9233c0e4f"
    ),
    "contracts/run-manifest-v1.schema.json": (
        "409aaf6e889e18cca1b7c040df65b5df7f095c8bba6cad3d5d4ea9c893449dd6"
    ),
    "contracts/v2/bank-entry-v2.schema.json": (
        "3e1a69488ceb91bc8d8e894b58c782aa28dd6e721e78f3ceb5ab51270f1e0470"
    ),
    "contracts/v2/case-revision-v2.schema.json": (
        "029463cad2665db74ae247640d6a6fcc044fcef900a6c19c2dbfb312b90dc3e1"
    ),
    "contracts/v2/common-v2.schema.json": (
        "1d7f57a165e52b1c3ca3a4c8d9321ae18dd364928ce181570fb2377c51bf5ddd"
    ),
    "contracts/v2/journal-v2.schema.json": (
        "8fe2a989f13263fded0b0a645de64c299283c3698c3de821326950d2578e123f"
    ),
    "contracts/v2/processor-event-v2.schema.json": (
        "648cdb70cd5693f505d650440913e2ab95f419c0be384122fb0ed0e7d537b91f"
    ),
    "contracts/v2/processor-settlement-v2.schema.json": (
        "aeb2fb8828eddf95118700fd9b55072b68da54a60652064214dfba0a7bad35ca"
    ),
    "contracts/v2/reconciliation-policy-v2.schema.json": (
        "f908528f2a727f4c50f23791d3e1df4cb0ba73ec4babd80d559947e211813b70"
    ),
    "contracts/v2/reconciliation-proof-v2.schema.json": (
        "6abe1e8caf86781cc68ee8c60e90c1ad3bb3a63ad820bdcc179d321ac0005f41"
    ),
    "contracts/v2/run-manifest-v2.schema.json": (
        "f795ba6241b24ff0d2c8338abbd8c043a7312e881b6480154ca69a9beef31e64"
    ),
}
STAGE3_ARTIFACTS = (
    ".github/workflows/ci.yml",
    "README.md",
    "PROJECT_STATUS.md",
    "contracts/part2-stage3-admission-normalization-v1.json",
    "docs/adr/0019-production-admission-and-normalization.md",
    "docs/part2-execution-contract.md",
    "docs/part2-stage3-admission-normalization.md",
    "docs/part2-stage3-gap-audit.md",
    "pyproject.toml",
    "requirements/part2-stage3-bootstrap.lock",
    "requirements/part2-stage3-py311.lock",
    "spec/part2-stage2-closure-freeze-v1.json",
    "spec/part2-stage3-ci-evidence-v1.schema.json",
    "spec/part2-stage3-coverage-v1.json",
    "spec/part2-stage3-gate-registry-v1.json",
    "spec/part2-stage3-requirements-v1.json",
    "spec/part2-stage3-traceability-v1.json",
    "spec/part2-stage3-vectors-v1.json",
    "src/ledgerguard/reconciliation/__init__.py",
    "src/ledgerguard/reconciliation/admission.py",
    "src/ledgerguard/reconciliation/arithmetic.py",
    "src/ledgerguard/reconciliation/canonical.py",
    "src/ledgerguard/reconciliation/contracts.py",
    "src/ledgerguard/reconciliation/errors.py",
    "src/ledgerguard/reconciliation/identity.py",
    "src/ledgerguard_part2_stage3.py",
    "src/ledgerguard_part2_stage3_evidence.py",
    "src/ledgerguard_part2_stage3_validation.py",
    "tests/test_part2_stage3_admission.py",
    "tests/test_part2_stage3_validation.py",
    "tools/build_part2_stage3_ci_evidence.py",
    "tools/run_part2_stage3.py",
    "tools/validate_part2_stage3_run.py",
)
FORBIDDEN_PRODUCTION_IMPORTS = {
    "boto3",
    "botocore",
    "ledgerguard_reference_oracle",
    "pandas",
    "pyspark",
    "requests",
    "sqlalchemy",
}


class Stage3Error(ValueError):
    """Raised when the Stage 3 candidate is incomplete or inflated."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise Stage3Error(message)


def _load(root: Path, relative: str) -> dict[str, Any]:
    value = json.loads((root / relative).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise Stage3Error(f"JSON object required: {relative}")
    return value


def _digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _closure(root: Path) -> dict[str, Any]:
    freeze = _load(root, "spec/part2-stage2-closure-freeze-v1.json")
    expected = {
        "state": "PART2_STAGE2_REFERENCE_ORACLE_VERIFIED",
        "pull_request": 11,
        "pull_request_head": STAGE2_HEAD,
        "squash_merge_commit": STAGE2_MAIN,
        "squash_merge_tree": STAGE2_TREE,
        "squash_merge_parent": STAGE2_PARENT,
        "exact_head_ci_run": STAGE2_PR_CI,
        "postmerge_main_ci_run": STAGE2_MAIN_CI,
        "ci_artifact_id": STAGE2_ARTIFACT,
        "ci_test_count": 305,
        "oracle_test_count": 43,
        "coverage_percent": 100.0,
        "mutation_checks": 12,
        "mutation_survivors": 0,
    }
    for key, value in expected.items():
        _require(freeze.get(key) == value, f"Stage 2 closure differs: {key}")
    protected = cast(dict[str, Any], freeze.get("protected_authorities"))
    _require(isinstance(protected, dict) and len(protected) == 9, "closure authority set differs")
    for relative, expected_digest in protected.items():
        _require(isinstance(relative, str) and isinstance(expected_digest, str), "bad closure row")
        _require(
            _digest(root / relative) == expected_digest, f"Stage 2 authority differs: {relative}"
        )
    return freeze


def _schemas(root: Path) -> dict[str, str]:
    observed = {relative: _digest(root / relative) for relative in FROZEN_SCHEMA_DIGESTS}
    _require(observed == FROZEN_SCHEMA_DIGESTS, "frozen v1 or accepted v2 schema differs")
    ContractRegistry.load(root)
    return observed


def _contract(root: Path) -> dict[str, Any]:
    contract = _load(root, "contracts/part2-stage3-admission-normalization-v1.json")
    baseline = cast(dict[str, Any], contract.get("entry_baseline"))
    _require(
        baseline
        == {
            "stage2_pull_request": 11,
            "stage2_pull_request_head": STAGE2_HEAD,
            "stage2_main_commit": STAGE2_MAIN,
            "stage2_main_tree": STAGE2_TREE,
            "stage2_main_parent": STAGE2_PARENT,
            "stage2_exact_head_ci_run": STAGE2_PR_CI,
            "stage2_postmerge_main_ci_run": STAGE2_MAIN_CI,
            "stage2_ci_artifact_id": STAGE2_ARTIFACT,
        },
        "Stage 2 entry baseline differs",
    )
    _require(contract.get("stage_gates") == STAGE3_GATES, "Stage 3 gates differ")
    master = cast(dict[str, Any], contract.get("master_part2_completion_gates"))
    _require(len(master) == 6, "master gate inventory differs")
    _require(
        master.get("independent_oracle_verified") == "EXTERNALLY_VERIFIED", "oracle not closed"
    )
    _require(
        all(
            value == "UNCLAIMED"
            for key, value in master.items()
            if key != "independent_oracle_verified"
        ),
        "non-Stage-3 master gate claimed",
    )
    boundary = cast(dict[str, Any], contract.get("implementation_boundary"))
    _require(boundary.get("production_admission_implemented") is True, "admission claim missing")
    for field in (
        "transaction_engine_implemented",
        "settlement_engine_implemented",
        "authoritative_proof_store_implemented",
        "revision_store_implemented",
        "spark_reconciliation_implemented",
        "aws_workload_allowed",
        "aws_execution",
        "infrastructure_mutation",
    ):
        _require(boundary.get(field) is False, f"implementation boundary inflated: {field}")
    return contract


def _traceability(root: Path) -> None:
    requirements = cast(
        list[dict[str, Any]], _load(root, "spec/part2-stage3-requirements-v1.json")["requirements"]
    )
    gates = cast(
        list[dict[str, Any]], _load(root, "spec/part2-stage3-gate-registry-v1.json")["gates"]
    )
    rows = cast(
        list[dict[str, Any]], _load(root, "spec/part2-stage3-traceability-v1.json")["traceability"]
    )
    _require(
        [row["id"] for row in requirements] == STAGE3_REQUIREMENTS, "requirement order differs"
    )
    _require([row["gate_id"] for row in gates] == STAGE3_GATES, "gate order differs")
    _require(
        [row["requirement_id"] for row in rows] == STAGE3_REQUIREMENTS, "trace inventory differs"
    )
    _require({row["gate_id"] for row in requirements} == set(STAGE3_GATES), "gate coverage differs")
    for row in rows:
        _require(
            bool(row.get("authorities") and row.get("validation") and row.get("evidence")),
            "empty trace row",
        )
        for relative in row["authorities"]:
            _require((root / relative).is_file(), f"trace authority missing: {relative}")


def _coverage(root: Path) -> dict[str, Any]:
    coverage = _load(root, "spec/part2-stage3-coverage-v1.json")
    _require(
        set(coverage.get("admission_reason_codes", [])) == ADMISSION_REASONS,
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
    bootstrap = _locked_requirements(root / "requirements/part2-stage3-bootstrap.lock")
    runtime = _locked_requirements(root / "requirements/part2-stage3-py311.lock")
    _require(len(bootstrap) == 3, "Stage 3 bootstrap lock inventory differs")
    forbidden = ("pyspark==", "py4j==", "boto3==", "botocore==", "pandas==", "requests==")
    _require(not any(row.startswith(forbidden) for row in runtime), "admission lock is not minimal")
    pyproject = (root / "pyproject.toml").read_text()
    for command in (
        'ledgerguard-part2-stage3 = "ledgerguard_part2_stage3_validation:main"',
        'ledgerguard-part2-stage3-admit = "ledgerguard_part2_stage3:main"',
    ):
        _require(command in pyproject, f"Stage 3 command missing: {command}")
    workflow = (root / ".github/workflows/ci.yml").read_text()
    for marker in (
        "PART2_STAGE2_CLOSURE_SHA",
        "$RUNNER_TEMP/ledgerguard-part2-stage2-closure",
        "$RUNNER_TEMP/ledgerguard-part2-stage3",
        "tools/build_part2_stage3_ci_evidence.py",
        "ledgerguard-part2-stage3-${{ github.event.pull_request.head.sha }}",
    ):
        _require(marker in workflow, f"Stage 3 CI control missing: {marker}")
    schema = _load(root, "spec/part2-stage3-ci-evidence-v1.schema.json")
    Draft202012Validator.check_schema(schema)
    return {
        "bootstrap_dependencies": len(bootstrap),
        "runtime_dependencies": len(runtime),
        "ci_evidence_schema_valid": True,
    }


def _coherence(root: Path) -> dict[str, int]:
    vectors = _load(root, "spec/contract-coherence-vectors-v1.json")
    source = cast(dict[str, Any], vectors["source_digest"])
    _require(
        business_digest(source["record"]) == source["expected_sha256"], "business digest differs"
    )
    transaction = cast(dict[str, Any], source["record"])
    _require(bool(source_identity("PROCESSOR_EVENT", transaction)), "source identity missing")
    for row in vectors["timestamp_vectors"]:
        _require(canonical_timestamp(row["input"]) == row["expected"], "timestamp differs")
    _require(checked_i64(2**63 - 1) == 2**63 - 1, "i64 boundary differs")
    _require(checked_add(7, 9) == 16, "checked addition differs")
    _require(
        canonical_json_bytes({"value": "e\u0301"}) == canonical_json_bytes({"value": "é"}),
        "NFC differs",
    )
    return {"timestamp_vectors": len(vectors["timestamp_vectors"]), "canonical_source_vectors": 1}


def validate_stage3(root: Path | None = None) -> dict[str, Any]:
    """Validate the complete local Stage 3 candidate and its claim boundary."""

    repository = (root or Path(__file__).resolve().parents[1]).resolve()
    closure = _closure(repository)
    schemas = _schemas(repository)
    _contract(repository)
    _traceability(repository)
    coverage = _coverage(repository)
    imports = _production_imports(repository)
    controls = _controls(repository)
    coherence = _coherence(repository)
    artifact_digests: dict[str, str] = {}
    for relative in STAGE3_ARTIFACTS:
        path = repository / relative
        _require(path.is_file(), f"Stage 3 artifact missing: {relative}")
        artifact_digests[relative] = _digest(path)
    payload = {
        "artifacts": artifact_digests,
        "closure": closure,
        "schemas": schemas,
        "coverage_authority": coverage,
        "production_imports": imports,
        "controls": controls,
        "coherence": coherence,
    }
    return {
        "project": PROJECT,
        "part": 2,
        "stage": 3,
        "state": "PART2_IN_PROGRESS",
        "stage_state": "PART2_STAGE3_ADMISSION_NORMALIZATION_VERIFIED_CANDIDATE",
        "stage2_closure": {
            "state": "EXTERNALLY_VERIFIED",
            "commit": STAGE2_MAIN,
            "tree": STAGE2_TREE,
            "parent": STAGE2_PARENT,
        },
        "stage3_candidate_digest": sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            )
        ).hexdigest(),
        "artifact_digests": artifact_digests,
        "admission": {
            "production_statements_minimum": 596,
            "production_branches_minimum": 238,
            "reason_codes": len(ADMISSION_REASONS),
            "mutation_classes": len(MUTATION_CLASSES),
            "frozen_schemas": len(schemas),
            "production_imports": imports,
            **controls,
            **coherence,
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
    print(json.dumps(validate_stage3(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
