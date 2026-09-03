"""Fail-closed validation for the Part 2 Stage 2 reference oracle."""

from __future__ import annotations

import ast
import json
from hashlib import sha256
from pathlib import Path
from typing import Any, cast

from jsonschema import Draft202012Validator

from ledgerguard_reference_oracle import (
    AdmissionRejected,
    business_digest,
    canonical_json_bytes,
    canonical_sha256,
    canonical_timestamp,
    case_id,
    checked_abs,
    checked_add,
    checked_i64,
    checked_subtract,
    classify_replay,
    evaluate_capture_capacity,
    evaluate_settlement,
    evaluate_transaction,
    parse_strict_json,
    proof_id,
    settlement_key,
    transaction_key,
)

PROJECT = "ledgerguard-payment-reconciliation-platform"
STAGE1_MAIN = "95b7e2a1c6a1dd758a8ce43c73bdea80117b6d91"
STAGE1_TREE = "668e2e89473b026d9857d162fb9e45a3c8f465a1"
STAGE1_PARENT = "3ef17666e3fe3bc655ba1c8733beb3cb00acdbec"
STAGE1_PR_CI = 33657002427
STAGE1_MAIN_CI = 33710867915
STAGE2_REQUIREMENTS = [f"P2-S2-R{number:03d}" for number in range(1, 16)]
STAGE2_GATES = [f"P2-S2-G{number:03d}" for number in range(1, 8)]
INVARIANTS = [f"CTR-{number:03d}" for number in range(1, 19)]
STAGE2_ARTIFACTS = (
    ".github/workflows/ci.yml",
    "README.md",
    "PROJECT_STATUS.md",
    "contracts/part2-stage2-reference-oracle-v1.json",
    "spec/part2-stage2-requirements-v1.json",
    "spec/part2-stage2-gate-registry-v1.json",
    "spec/part2-stage2-traceability-v1.json",
    "spec/part2-stage2-oracle-vectors-v1.json",
    "spec/part2-stage2-coverage-v1.json",
    "spec/part2-stage2-ci-evidence-v1.schema.json",
    "docs/adr/0018-independent-reference-oracle.md",
    "docs/part2-stage2-gap-audit.md",
    "docs/part2-stage2-reference-oracle.md",
    "docs/part2-execution-contract.md",
    "pyproject.toml",
    "requirements/part2-stage2-bootstrap.lock",
    "requirements/part2-stage2-py311.lock",
    "src/ledgerguard_part2_stage2.py",
    "src/ledgerguard_part2_stage2_evidence.py",
    "src/ledgerguard_part2_stage1.py",
    "src/ledgerguard_reference_oracle/__init__.py",
    "src/ledgerguard_reference_oracle/canonical.py",
    "src/ledgerguard_reference_oracle/oracle.py",
    "tests/test_part2_stage2_oracle.py",
    "tools/build_part2_stage2_ci_evidence.py",
    "tools/run_part2_stage2.py",
    "tools/validate_part2_stage2_run.py",
)
FORBIDDEN_ORACLE_IMPORTS = {
    "boto3",
    "botocore",
    "ledgerguard",
    "pandas",
    "pyspark",
    "requests",
    "sqlalchemy",
}


class Stage2Error(ValueError):
    """Raised when the Stage 2 candidate is incomplete or inflated."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise Stage2Error(message)


def _load(root: Path, relative: str) -> dict[str, Any]:
    value = json.loads((root / relative).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise Stage2Error(f"JSON object required: {relative}")
    return value


def _digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _authority(root: Path) -> dict[str, Any]:
    stage1 = _load(root, "spec/part2-stage1-authority-v1.json")
    inherited = stage1.get("inherited_authorities")
    _require(isinstance(inherited, dict) and len(inherited) == 8, "inherited authority set differs")
    inherited = cast(dict[str, Any], inherited)
    digests: dict[str, str] = {}
    for name, binding in inherited.items():
        _require(isinstance(binding, dict), f"authority binding is invalid: {name}")
        relative = binding.get("path")
        expected = binding.get("sha256")
        _require(
            isinstance(relative, str) and isinstance(expected, str), "authority binding differs"
        )
        path = root / relative
        _require(path.is_file(), f"inherited authority missing: {relative}")
        observed = _digest(path)
        _require(observed == expected, f"inherited authority digest differs: {relative}")
        digests[relative] = observed
    return digests


def _contract(root: Path) -> dict[str, Any]:
    contract = _load(root, "contracts/part2-stage2-reference-oracle-v1.json")
    baseline = contract.get("entry_baseline")
    _require(
        baseline
        == {
            "stage1_pull_request": 10,
            "stage1_main_commit": STAGE1_MAIN,
            "stage1_main_tree": STAGE1_TREE,
            "stage1_main_parent": STAGE1_PARENT,
            "stage1_exact_head_ci_run": STAGE1_PR_CI,
            "stage1_postmerge_main_ci_run": STAGE1_MAIN_CI,
        },
        "Stage 1 entry baseline differs",
    )
    _require(contract.get("state") == "PART2_IN_PROGRESS", "Part 2 state differs")
    _require(
        contract.get("stage_state") == "PART2_STAGE2_REFERENCE_ORACLE_VERIFIED_CANDIDATE",
        "Stage 2 candidate state differs",
    )
    _require(contract.get("stage_gates") == STAGE2_GATES, "Stage 2 gates differ")
    master = contract.get("master_part2_completion_gates")
    _require(isinstance(master, dict) and len(master) == 6, "master gate inventory differs")
    master = cast(dict[str, Any], master)
    _require(
        master.get("independent_oracle_verified")
        == "LOCAL_VERIFIED_CANDIDATE_PENDING_EXTERNAL_CLOSURE",
        "oracle master gate candidate differs",
    )
    _require(
        all(
            value == "UNCLAIMED"
            for key, value in master.items()
            if key != "independent_oracle_verified"
        ),
        "non-Stage-2 master gate claimed",
    )
    boundary = contract.get("implementation_boundary")
    _require(isinstance(boundary, dict), "implementation boundary missing")
    boundary = cast(dict[str, Any], boundary)
    _require(boundary.get("independent_reference_oracle_implemented") is True, "oracle missing")
    for field in (
        "production_admission_implemented",
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
        list[dict[str, Any]],
        _load(root, "spec/part2-stage2-requirements-v1.json")["requirements"],
    )
    gates = cast(
        list[dict[str, Any]], _load(root, "spec/part2-stage2-gate-registry-v1.json")["gates"]
    )
    traceability = cast(
        list[dict[str, Any]],
        _load(root, "spec/part2-stage2-traceability-v1.json")["traceability"],
    )
    _require(
        [row["id"] for row in requirements] == STAGE2_REQUIREMENTS, "requirement order differs"
    )
    _require([row["gate_id"] for row in gates] == STAGE2_GATES, "gate order differs")
    _require(
        [row["requirement_id"] for row in traceability] == STAGE2_REQUIREMENTS,
        "traceability inventory differs",
    )
    _require(
        {row["gate_id"] for row in requirements} == set(STAGE2_GATES),
        "requirement-to-gate coverage differs",
    )
    for row in traceability:
        _require(
            bool(row.get("authorities") and row.get("validation") and row.get("evidence")),
            "trace row empty",
        )
        for relative in row["authorities"]:
            _require((root / relative).is_file(), f"trace authority missing: {relative}")


def _coverage(root: Path) -> dict[str, int]:
    coverage = _load(root, "spec/part2-stage2-coverage-v1.json")
    failures = _load(root, "spec/part1-stage5-documentation-authority-v1.json")
    _require(coverage.get("invariant_ids") == INVARIANTS, "invariant coverage differs")
    expected_scenarios = [row["scenario"] for row in failures["failure_scenarios"]]
    _require(
        coverage.get("behavioral_scenarios") == expected_scenarios, "scenario coverage differs"
    )
    reason_codes = coverage.get("reason_codes")
    _require(isinstance(reason_codes, dict), "reason coverage missing")
    reason_codes = cast(dict[str, list[str]], reason_codes)
    expected_domains = cast(dict[str, list[str]], failures["reason_domains"])
    for domain in ("ADMISSION", "FINANCIAL", "EXECUTION"):
        _require(
            set(reason_codes[domain]) == set(expected_domains[domain]), f"{domain} reasons differ"
        )
    _require(
        reason_codes.get("NON_FAILURE") == ["TOLERATED_DIFFERENCE"], "tolerance reason differs"
    )
    groups = coverage.get("coverage_groups")
    _require(isinstance(groups, dict), "coverage groups missing")
    groups = cast(dict[str, list[str]], groups)
    flattened = {item for values in groups.values() for item in values}
    _require(flattened == set(INVARIANTS), "invariant group coverage differs")
    return {
        "invariants": len(INVARIANTS),
        "scenarios": len(expected_scenarios),
        "reason_codes": sum(len(reason_codes[name]) for name in reason_codes),
    }


def _imports(root: Path) -> list[str]:
    observed: set[str] = set()
    for path in sorted((root / "src/ledgerguard_reference_oracle").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                observed.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                observed.add(node.module.split(".")[0])
    _require(
        not observed.intersection(FORBIDDEN_ORACLE_IMPORTS), "oracle imports forbidden runtime"
    )
    for path in sorted((root / "src/ledgerguard").rglob("*.py")):
        _require(
            "ledgerguard_reference_oracle" not in path.read_text(encoding="utf-8"),
            f"production imports reference oracle: {path.relative_to(root)}",
        )
    return sorted(observed)


def _locked_requirements(path: Path) -> list[str]:
    lines = [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    _require(bool(lines), f"dependency lock is empty: {path.name}")
    _require(
        all("==" in line and "--hash=sha256:" in line for line in lines),
        f"dependency is not hash-locked: {path.name}",
    )
    return lines


def _controls(root: Path) -> dict[str, Any]:
    bootstrap = _locked_requirements(root / "requirements/part2-stage2-bootstrap.lock")
    runtime = _locked_requirements(root / "requirements/part2-stage2-py311.lock")
    _require(len(bootstrap) == 3, "Stage 2 bootstrap lock inventory differs")
    forbidden = ("pyspark==", "py4j==", "boto3==", "botocore==", "pandas==", "requests==")
    _require(not any(line.startswith(forbidden) for line in runtime), "oracle lock is not minimal")
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    _require(
        'ledgerguard-part2-stage2 = "ledgerguard_part2_stage2:main"' in pyproject,
        "Stage 2 console command missing",
    )
    runner = (root / "tools/run_part2_stage2.py").read_text(encoding="utf-8")
    for required in (
        "sys.version_info[:3] != (3, 11, 13)",
        'SOURCE_DATE_EPOCH = "1788405487"',
        "arguments.clean_runs < 2",
        "repository in workspace.parents",
        "wheel_sha256",
    ):
        _require(required in runner, f"Stage 2 runner control missing: {required}")
    workflow = (root / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    for required in (
        "PART2_STAGE1_CLOSURE_SHA",
        "$RUNNER_TEMP/ledgerguard-part2-stage1-closure",
        "python tools/run_part2_stage2.py",
        "tools/build_part2_stage2_ci_evidence.py",
        "ledgerguard-part2-stage2-${{ github.event.pull_request.head.sha }}",
    ):
        _require(required in workflow, f"Stage 2 CI control missing: {required}")
    status = (root / "PROJECT_STATUS.md").read_text(encoding="utf-8")
    _require(
        "PART2_STAGE2_REFERENCE_ORACLE_VERIFIED_CANDIDATE" in status,
        "Stage 2 status missing",
    )
    _require("LOCAL_RECONCILIATION_VERIFIED" not in status, "Part 2 completion claimed early")
    schema = _load(root, "spec/part2-stage2-ci-evidence-v1.schema.json")
    Draft202012Validator.check_schema(schema)
    return {
        "bootstrap_dependencies": len(bootstrap),
        "runtime_dependencies": len(runtime),
        "ci_evidence_schema_valid": True,
    }


def _goldens(root: Path) -> dict[str, Any]:
    examples = _load(root, "spec/financial-examples-v1.json")
    outcomes: dict[str, Any] = {}
    for row in examples["transaction_cases"]:
        observed = evaluate_transaction(row["input"])
        _require(observed == row["expected"], f"transaction oracle differs: {row['name']}")
        outcomes[row["name"]] = observed
    for row in examples["settlement_cases"]:
        observed = evaluate_settlement(row["input"])
        _require(observed == row["expected"], f"settlement oracle differs: {row['name']}")
        outcomes[row["name"]] = observed
    capacity = examples["capture_capacity_case"]
    _require(
        evaluate_capture_capacity(capacity["captured_minor"], capacity["negative_applied_minor"])
        == capacity["expected"],
        "capture capacity oracle differs",
    )
    ambiguous = examples["ambiguous_bank_allocation_case"]
    settlement_input = dict(examples["settlement_cases"][0]["input"])
    settlement_input["settlement_reference"] = ambiguous["bank_reference"]
    settlement_input["candidate_settlement_references"] = ambiguous[
        "candidate_settlement_references"
    ]
    rejected = evaluate_settlement(settlement_input)
    _require(
        rejected
        == {
            "outcome": "ADMISSION_REJECTED",
            "authoritative_proof": False,
            "reason_codes": ["AMBIGUOUS_BANK_ALLOCATION"],
        },
        "ambiguous allocation did not fail admission",
    )
    vectors = _load(root, "spec/contract-coherence-vectors-v1.json")
    digest_vector = vectors["source_digest"]
    _require(
        business_digest(digest_vector["record"]) == digest_vector["expected_sha256"],
        "source digest differs",
    )
    _require(
        classify_replay(
            "PROCESSOR_EVENT",
            digest_vector["record"],
            dict(digest_vector["record"], **digest_vector["equivalent_redelivery"]),
        )
        == "IDENTICAL_REPLAY",
        "replay differs",
    )
    _require(
        classify_replay(
            "PROCESSOR_EVENT",
            digest_vector["record"],
            dict(digest_vector["record"], **digest_vector["conflicting_redelivery"]),
        )
        == "IDENTITY_CONFLICT",
        "conflict differs",
    )
    _require(
        transaction_key(vectors["transaction_key"]["components"])
        == vectors["transaction_key"]["expected_key"],
        "transaction key differs",
    )
    _require(
        settlement_key(vectors["settlement_key"]["components"])
        == vectors["settlement_key"]["expected_key"],
        "settlement key differs",
    )
    chain = vectors["policy_manifest_proof_case_chain"]
    for value_name, digest_field, expected_name in (
        ("policy", "policy_sha256", "expected_policy_sha256"),
        ("manifest", "manifest_sha256", "expected_manifest_sha256"),
        ("proof", "proof_sha256", "expected_proof_sha256"),
        ("case_revision_one", "case_revision_sha256", "expected_case_revision_one_sha256"),
        ("case_revision_two", "case_revision_sha256", "expected_case_revision_two_sha256"),
    ):
        _require(
            canonical_sha256(chain[value_name], {digest_field}) == chain[expected_name],
            f"{value_name} digest differs",
        )
    proof = chain["proof"]
    proof_components = {
        field: proof[field]
        for field in (
            "grain",
            "reconciliation_key",
            "revision",
            "source_manifest_sha256",
            "policy_sha256",
        )
    }
    _require(proof_id(proof_components) == chain["expected_proof_id"], "proof identity differs")
    case = chain["case_revision_one"]
    case_components = {
        field: case[field]
        for field in ("grain", "reconciliation_key", "initial_exception_proof_id")
    }
    _require(case_id(case_components) == chain["expected_case_id"], "case identity differs")
    return outcomes


def _boundaries(root: Path) -> dict[str, int]:
    passed = 0
    for function, arguments in (
        (checked_add, (2**63 - 1, 1)),
        (checked_subtract, (-(2**63), 1)),
        (checked_abs, (-(2**63),)),
        (checked_i64, (True,)),
        (checked_i64, (1.0,)),
    ):
        try:
            function(*arguments)
        except AdmissionRejected:
            passed += 1
        else:
            raise Stage2Error(f"boundary did not reject: {function.__name__}")
    vectors = _load(root, "spec/contract-coherence-vectors-v1.json")
    for value in vectors["invalid_timestamps"]:
        try:
            canonical_timestamp(value)
        except AdmissionRejected:
            passed += 1
        else:
            raise Stage2Error(f"invalid timestamp admitted: {value}")
    for value in vectors["invalid_json_numbers"]:
        try:
            parse_strict_json('{"value":' + value + "}")
        except AdmissionRejected:
            passed += 1
        else:
            raise Stage2Error(f"invalid JSON number admitted: {value}")
    return {"boundary_rejections": passed}


def validate_stage2(root: Path | None = None) -> dict[str, Any]:
    """Validate and reproduce the independent Stage 2 oracle candidate."""

    repository = (root or Path(__file__).resolve().parents[1]).resolve()
    authority_digests = _authority(repository)
    _contract(repository)
    _traceability(repository)
    coverage = _coverage(repository)
    imports = _imports(repository)
    controls = _controls(repository)
    outcomes = _goldens(repository)
    boundaries = _boundaries(repository)
    artifact_digests: dict[str, str] = {}
    for relative in STAGE2_ARTIFACTS:
        path = repository / relative
        _require(path.is_file(), f"Stage 2 artifact missing: {relative}")
        artifact_digests[relative] = _digest(path)
    candidate_payload = {
        "artifacts": artifact_digests,
        "authority": authority_digests,
        "golden_outcomes": outcomes,
        "coverage": coverage,
        "boundaries": boundaries,
        "imports": imports,
        "controls": controls,
    }
    return {
        "project": PROJECT,
        "part": 2,
        "stage": 2,
        "state": "PART2_IN_PROGRESS",
        "stage_state": "PART2_STAGE2_REFERENCE_ORACLE_VERIFIED_CANDIDATE",
        "stage1_baseline": {"commit": STAGE1_MAIN, "tree": STAGE1_TREE, "parent": STAGE1_PARENT},
        "stage2_candidate_digest": sha256(canonical_json_bytes(candidate_payload)).hexdigest(),
        "artifact_digests": artifact_digests,
        "authority_digests": authority_digests,
        "oracle": {
            "frozen_examples": len(outcomes),
            **coverage,
            **boundaries,
            "imports": imports,
            **controls,
            "authoritative_proofs_emitted": 0,
        },
        "master_part2_gates": {
            "independent_oracle_verified": "LOCAL_VERIFIED_CANDIDATE_PENDING_EXTERNAL_CLOSURE",
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
    print(json.dumps(validate_stage2(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
