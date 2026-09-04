"""Fail-closed repository validation for Part 2 Stage 7."""

from __future__ import annotations

import ast
import json
from hashlib import sha256
from pathlib import Path
from typing import Any, cast

from ledgerguard_part2_stage3_validation import FROZEN_SCHEMA_DIGESTS
from ledgerguard_part2_stage6_validation import validate_stage6

PROJECT = "ledgerguard-payment-reconciliation-platform"
STAGE6_MAIN = "376e686813e6271e2d6787467a5500ba0827dfcb"
STAGE6_TREE = "997bd12abfef144212cb6f774cdfff086d31a0ff"
STAGE7_REQUIREMENTS = [f"P2-S7-R{number:03d}" for number in range(1, 25)]
STAGE7_GATES = [f"P2-S7-G{number:03d}" for number in range(1, 9)]
STAGE7_ARTIFACTS = (
    ".github/workflows/ci.yml",
    "contracts/part2-stage7-spark-parity-v1.json",
    "docs/adr/0023-spark-logical-parity-and-parquet.md",
    "docs/part2-stage7-gap-audit.md",
    "docs/part2-stage7-spark-parity.md",
    "requirements/part2-stage7-bootstrap.lock",
    "requirements/part2-stage7-py311.lock",
    "spec/part2-stage6-closure-freeze-v1.json",
    "spec/part2-stage7-ci-evidence-v1.schema.json",
    "spec/part2-stage7-coverage-v1.json",
    "spec/part2-stage7-critical-paths-v1.json",
    "spec/part2-stage7-failure-matrix-v1.json",
    "spec/part2-stage7-gate-registry-v1.json",
    "spec/part2-stage7-requirements-v1.json",
    "spec/part2-stage7-traceability-v1.json",
    "src/ledgerguard_part2_stage7_spark.py",
    "src/ledgerguard_part2_stage7_validation.py",
    "src/ledgerguard_part2_stage7_evidence.py",
    "tests/test_part2_stage7_spark_parity.py",
    "tests/test_part2_stage7_validation.py",
    "tools/build_part2_stage7_ci_evidence.py",
    "tools/run_part2_stage7.py",
    "tools/validate_part2_stage7_run.py",
)


class Stage7Error(ValueError):
    """Raised when Stage 7 authority or evidence is incomplete."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise Stage7Error(message)


def _load(root: Path, relative: str) -> dict[str, Any]:
    value = json.loads((root / relative).read_text(encoding="utf-8"))
    _require(isinstance(value, dict), f"JSON object required: {relative}")
    return cast(dict[str, Any], value)


def _digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _closure(root: Path) -> dict[str, Any]:
    freeze = _load(root, "spec/part2-stage6-closure-freeze-v1.json")
    expected: dict[str, Any] = {
        "state": "PART2_STAGE6_PROOF_FINALIZATION_VERIFIED",
        "pull_request": 15,
        "pull_request_head": "012752daf09a1249997f626276bcb9b5bd74d468",
        "squash_merge_commit": STAGE6_MAIN,
        "squash_merge_tree": STAGE6_TREE,
        "squash_merge_parent": "89373adf968ff7071693f8cce5d12901fd9b1e69",
        "exact_head_ci_run": 33848115905,
        "postmerge_main_ci_run": 33850525300,
        "ci_artifact_id": 9927915612,
        "ci_artifact_zip_sha256": (
            "30924b4583641bb5bcdebeecd57746e8a03f5ac1abc60cb03b833d1670e9c7d3"
        ),
        "ci_evidence_sha256": "f9b23350b4459237deb3aa472e53e950539bb7a755bee1e3e110ccc6d48709f2",
        "ci_test_count": 498,
        "coverage_statements": 1847,
        "coverage_branches": 754,
        "coverage_percent": 100.0,
        "mutation_checks": 24,
        "mutation_survivors": 0,
    }
    for key, value in expected.items():
        _require(freeze.get(key) == value, f"Stage 6 closure differs: {key}")
    protected = cast(dict[str, str], freeze.get("protected_authorities"))
    _require(isinstance(protected, dict) and len(protected) == 10, "Stage 6 authority set differs")
    for relative, expected_digest in protected.items():
        _require(
            _digest(root / relative) == expected_digest, f"Stage 6 authority differs: {relative}"
        )
    return freeze


def _traceability(root: Path) -> None:
    requirements = cast(
        list[dict[str, Any]], _load(root, "spec/part2-stage7-requirements-v1.json")["requirements"]
    )
    gates = cast(
        list[dict[str, Any]], _load(root, "spec/part2-stage7-gate-registry-v1.json")["gates"]
    )
    traces = cast(
        list[dict[str, Any]], _load(root, "spec/part2-stage7-traceability-v1.json")["traceability"]
    )
    _require(
        [row["id"] for row in requirements] == STAGE7_REQUIREMENTS, "Stage 7 requirements differ"
    )
    _require([row["gate_id"] for row in gates] == STAGE7_GATES, "Stage 7 gates differ")
    _require([row["gate_id"] for row in traces] == STAGE7_GATES, "Stage 7 trace gates differ")
    traced = [item for row in traces for item in row["requirement_ids"]]
    _require(traced == STAGE7_REQUIREMENTS, "Stage 7 requirement trace differs")
    for row in traces:
        for relative in row["authorities"] + row["validation"]:
            _require((root / relative).is_file(), f"Stage 7 trace file missing: {relative}")


def _matrix(root: Path) -> tuple[int, int, int]:
    matrix = _load(root, "spec/part2-stage7-failure-matrix-v1.json")
    source = _load(root, "spec/part1-stage5-documentation-authority-v1.json")
    reasons = _load(root, "spec/part2-stage2-coverage-v1.json")
    expected_scenarios = [str(row["scenario"]) for row in source["failure_scenarios"]]
    expected_reasons = [
        str(reason)
        for owner in ("ADMISSION", "FINANCIAL", "EXECUTION")
        for reason in reasons["reason_codes"][owner]
    ]
    scenario_tests = cast(dict[str, str], matrix.get("scenario_tests"))
    reason_tests = cast(dict[str, str], matrix.get("reason_tests"))
    _require(list(scenario_tests) == expected_scenarios, "failure scenario matrix differs")
    _require(list(reason_tests) == expected_reasons, "reason-code matrix differs")
    test_source = "\n".join(
        path.read_text(encoding="utf-8") for path in (root / "tests").glob("test_*.py")
    )
    for test_name in list(scenario_tests.values()) + list(reason_tests.values()):
        _require(f"def {test_name}" in test_source, f"failure-matrix test missing: {test_name}")
    critical = cast(
        list[dict[str, str]],
        _load(root, "spec/part2-stage7-critical-paths-v1.json")["critical_paths"],
    )
    coverage = _load(root, "spec/part2-stage7-coverage-v1.json")
    _require([row["id"] for row in critical] == coverage["critical_paths"], "critical paths differ")
    for row in critical:
        _require(f"def {row['test']}" in test_source, f"critical-path test missing: {row['test']}")
    return len(scenario_tests), len(reason_tests), len(critical)


def _controls(root: Path) -> None:
    runtime = (root / "requirements/part2-stage7-py311.lock").read_text(encoding="utf-8")
    for marker in ("pyspark==3.5.6", "py4j==0.10.9.7"):
        _require(marker in runtime, f"locked runtime missing: {marker}")
    _require("--hash=sha256:" in runtime, "Stage 7 runtime is not hash locked")
    workflow = (root / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    for marker in (
        "PART2_STAGE6_CLOSURE_SHA",
        "tools/run_part2_stage7.py",
        "tools/build_part2_stage7_ci_evidence.py",
    ):
        _require(marker in workflow, f"Stage 7 CI marker missing: {marker}")
    stage7_block = workflow.split("Run Part 2 Stage 7 validation twice", 1)[-1]
    _require("aws-actions/" not in stage7_block, "Stage 7 CI contains AWS action")
    tree = ast.parse((root / "src/ledgerguard_part2_stage7_spark.py").read_text())
    imports = {
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    _require(
        not ({"boto3", "botocore", "requests"} & imports),
        "Spark path contains network or AWS import",
    )


def validate_stage7(root: Path) -> dict[str, Any]:
    root = root.resolve()
    closure = _closure(root)
    for relative, expected in FROZEN_SCHEMA_DIGESTS.items():
        _require(_digest(root / relative) == expected, f"frozen schema differs: {relative}")
    validate_stage6(root)
    contract = _load(root, "contracts/part2-stage7-spark-parity-v1.json")
    _require(
        contract.get("stage_state") == "PART2_STAGE7_SPARK_PARITY_VERIFIED_CANDIDATE",
        "Stage 7 state differs",
    )
    _require(contract.get("stage_gates") == STAGE7_GATES, "Stage 7 contract gates differ")
    master = cast(dict[str, str], contract.get("master_part2_completion_gates"))
    _require(master.get("spark_parity_verified") == "VERIFIED_CANDIDATE", "Spark claim differs")
    _require(master.get("failure_matrix_verified") == "VERIFIED_CANDIDATE", "failure claim differs")
    _require(master.get("critical_paths_tested") == "VERIFIED_CANDIDATE", "critical claim differs")
    boundary = cast(dict[str, Any], contract.get("implementation_boundary"))
    _require(
        not any(
            boundary.get(key)
            for key in (
                "aws_execution",
                "managed_persistence",
                "infrastructure_mutation",
                "part2_closed",
            )
        ),
        "Stage 7 claim boundary inflated",
    )
    _traceability(root)
    scenario_count, reason_count, critical_count = _matrix(root)
    _controls(root)
    for relative in STAGE7_ARTIFACTS:
        _require((root / relative).is_file(), f"Stage 7 artifact missing: {relative}")
    artifact_digest = sha256(
        "".join(
            f"{relative}:{_digest(root / relative)}\n" for relative in STAGE7_ARTIFACTS
        ).encode()
    ).hexdigest()
    return {
        "stage6_closure": {
            "commit": closure["squash_merge_commit"],
            "state": "EXTERNALLY_VERIFIED",
        },
        "stage7_candidate_digest": artifact_digest,
        "master_part2_gates": master,
        "failure_matrix": {"scenarios": scenario_count, "reason_codes": reason_count},
        "critical_paths": critical_count,
        "aws_execution": False,
    }


def main() -> None:
    print(json.dumps(validate_stage7(Path.cwd()), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
