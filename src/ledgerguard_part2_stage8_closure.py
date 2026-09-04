"""Fail-closed validation for the LedgerGuard Part 2 closure attestation."""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
from typing import Any, cast

from jsonschema import Draft202012Validator

PROJECT = "ledgerguard-payment-reconciliation-platform"
PROMOTION_HEAD = "2b1147dac823d59a8891b5f7852e7c6977f20aa6"
PROMOTION_COMMIT = "71b42d6622558093a2bfaced58724f2ab71e793e"
PROMOTION_PARENT = "8fac3795ed0dac5284dd3b1595bd8fc9f6dc7344"
PROMOTION_TREE = "406f40dfb1e94e38031505e23a6d77b50198840f"
STAGE7_FREEZE_SHA256 = "ae0182fc306355be27417457393a8f4fe96624b4ce6e0359a233563b676eb3b1"
MASTER_GATES = [
    "independent_oracle_verified",
    "spark_parity_verified",
    "financial_invariants_verified",
    "failure_matrix_verified",
    "deterministic_replay_verified",
    "critical_paths_tested",
]
MUTATION_CLASSES = [
    "ACCEPT_PROMOTION_COMMIT_DRIFT",
    "ACCEPT_PROMOTION_TREE_DRIFT",
    "ACCEPT_NON_SQUASH_PROMOTION",
    "ACCEPT_PROMOTION_ARTIFACT_DRIFT",
    "ACCEPT_FAILED_POSTMERGE_MAIN",
    "ACCEPT_PROMOTION_AUTHORITY_DRIFT",
    "ALLOW_NONTERMINAL_PART2_STATE",
    "ALLOW_UNVERIFIED_MASTER_GATE",
    "CLAIM_AWS_EXECUTION",
    "ALLOW_INCORRECT_COMPLETION_TOTAL",
    "ALLOW_STALE_FINAL_DOCUMENTATION",
    "ALLOW_RECURSIVE_SELF_ATTESTATION",
]
PROMOTION_FACTS: dict[str, Any] = {
    "state": "PART2_STAGE8_PROMOTION_EXTERNALLY_VERIFIED",
    "pull_request": 17,
    "pull_request_head": PROMOTION_HEAD,
    "squash_merge_commit": PROMOTION_COMMIT,
    "squash_merge_parent": PROMOTION_PARENT,
    "squash_merge_tree": PROMOTION_TREE,
    "parent_count": 1,
    "exact_head_ci_run": 33871740027,
    "exact_head_ci_job": 101019086101,
    "postmerge_main_ci_run": 33874130476,
    "postmerge_main_ci_job": 101026900537,
    "ci_artifact_id": 9936995094,
    "ci_artifact_name": f"ledgerguard-part2-stage8-{PROMOTION_HEAD}",
    "ci_artifact_zip_sha256": ("082f66b53ec08cc877f04b815911da4c35dd79ff3ac9fd45c8e7df9e7bf307e6"),
    "ci_manifest_sha256": ("8a35c734a32282ca287b0b458e2014d68ba626c055959194951414c652a7e0c7"),
    "ci_evidence_sha256": ("c4a0fe47dcbd2deaf0c39c2d6d54060eded7198476fda3e5c46a1556ecc7b961"),
    "requirement_ledger_sha256": (
        "5f906064eed35a135a3d23fcdfbd789554c7fad6a92bfb606d360f7cb9b169b5"
    ),
    "gate_ledger_sha256": ("2eb2f21ec1cb19555333094489e0475ed899f5f08a6aca4ad80b2ca1b298f6c1"),
    "stage8_candidate_digest": ("67fc895a4ce41ff853873bfd461a963e21fb5141443e63ae2fe6eb2a6e42d797"),
    "deterministic_payload_sha256": (
        "91ef0aba167bae19f2e8d493aa7840375ef721879e7f8260571cd6da0ac767c7"
    ),
    "wheel_sha256": "fedf664616e99b66e4a42aa4efc5427fa92442ea5781b04209e57128005e28c9",
    "ci_test_count": 514,
    "coverage_statements": 169,
    "coverage_branches": 24,
    "coverage_percent": 100.0,
    "mutation_checks": 14,
    "mutation_survivors": 0,
    "requirement_count": 203,
    "stage_gate_count": 69,
    "master_gate_count": 6,
    "spark_reexecuted": True,
    "spark_authoritative": False,
    "aws_execution": False,
    "managed_persistence": False,
    "infrastructure_mutation": False,
}
CLOSURE_ARTIFACTS = (
    ".github/workflows/ci.yml",
    "Makefile",
    "PROJECT_STATUS.md",
    "README.md",
    "docs/part2-completion.md",
    "docs/part2-execution-contract.md",
    "pyproject.toml",
    "spec/part2-completion-authority-v1.json",
    "spec/part2-stage8-closure-ci-evidence-v1.schema.json",
    "spec/part2-stage8-closure-coverage-v1.json",
    "spec/part2-stage8-promotion-closure-freeze-v1.json",
    "src/ledgerguard_part2_stage8_closure.py",
    "src/ledgerguard_part2_stage8_closure_evidence.py",
    "tests/test_part2_stage8_closure.py",
    "tools/build_part2_stage8_closure_ci_evidence.py",
    "tools/run_part2_stage8_closure.py",
    "tools/validate_part2_stage8_closure_run.py",
)


class Stage8ClosureError(ValueError):
    """Raised when Part 2 closure evidence is incomplete or inflated."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise Stage8ClosureError(message)


def _load(root: Path, relative: str) -> dict[str, Any]:
    value = json.loads((root / relative).read_text(encoding="utf-8"))
    _require(isinstance(value, dict), f"JSON object required: {relative}")
    return cast(dict[str, Any], value)


def _digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _promotion(root: Path) -> dict[str, Any]:
    freeze = _load(root, "spec/part2-stage8-promotion-closure-freeze-v1.json")
    _require(
        freeze.get("schema_version") == "1.0" and freeze.get("project") == PROJECT,
        "promotion closure identity differs",
    )
    for key, expected in PROMOTION_FACTS.items():
        _require(freeze.get(key) == expected, f"promotion closure differs: {key}")
    protected = freeze.get("protected_authorities")
    _require(
        isinstance(protected, dict) and len(protected) == 23,
        "promotion authority inventory differs",
    )
    for relative, expected in cast(dict[object, object], protected).items():
        _require(
            isinstance(relative, str) and isinstance(expected, str),
            "invalid promotion authority row",
        )
        relative_text = cast(str, relative)
        expected_text = cast(str, expected)
        _require(
            (root / relative_text).is_file() and _digest(root / relative_text) == expected_text,
            f"promotion authority differs: {relative_text}",
        )
    return freeze


def _completion(root: Path, freeze: dict[str, Any]) -> dict[str, Any]:
    schema = _load(root, "spec/part2-completion-authority-v1.schema.json")
    authority = _load(root, "spec/part2-completion-authority-v1.json")
    Draft202012Validator.check_schema(schema)
    errors = sorted(
        Draft202012Validator(schema).iter_errors(authority), key=lambda row: list(row.path)
    )
    _require(
        not errors, f"completion authority schema failure: {errors[0].message if errors else ''}"
    )
    _require(
        authority.get("stage7_closure_sha256") == STAGE7_FREEZE_SHA256, "Stage 7 binding differs"
    )
    promotion = authority.get("promotion")
    expected_promotion = {
        "pull_request": freeze["pull_request"],
        "validated_head": freeze["pull_request_head"],
        "validated_tree": freeze["squash_merge_tree"],
        "squash_merge_commit": freeze["squash_merge_commit"],
        "squash_merge_parent": freeze["squash_merge_parent"],
        "parent_count": freeze["parent_count"],
        "exact_head_ci_run": freeze["exact_head_ci_run"],
        "exact_head_ci_job": freeze["exact_head_ci_job"],
        "postmerge_main_ci_run": freeze["postmerge_main_ci_run"],
        "postmerge_main_ci_job": freeze["postmerge_main_ci_job"],
        "artifact_id": freeze["ci_artifact_id"],
        "artifact_name": freeze["ci_artifact_name"],
        "artifact_zip_sha256": freeze["ci_artifact_zip_sha256"],
        "manifest_sha256": freeze["ci_manifest_sha256"],
        "evidence_sha256": freeze["ci_evidence_sha256"],
        "deterministic_payload_sha256": freeze["deterministic_payload_sha256"],
        "wheel_sha256": freeze["wheel_sha256"],
        "conclusion": "SUCCESS",
    }
    _require(promotion == expected_promotion, "completion promotion transaction differs")
    gates = authority.get("master_part2_completion_gates")
    _require(
        isinstance(gates, dict)
        and list(gates) == MASTER_GATES
        and all(gates[gate] == "EXTERNALLY_VERIFIED" for gate in MASTER_GATES),
        "completion master gates differ",
    )
    _require(
        authority.get("outcome")
        == {
            "requirements_pass": 203,
            "stage_gates_pass": 69,
            "master_gates_pass": 6,
            "critical_findings": 0,
            "major_findings": 0,
            "remaining_part2_work": 0,
        },
        "completion outcome differs",
    )
    boundary = authority.get("claim_boundary")
    _require(
        isinstance(boundary, dict) and bool(boundary) and not any(boundary.values()),
        "completion claim boundary is inflated",
    )
    publication = authority.get("closure_attestation")
    _require(
        publication
        == {
            "method": "SEPARATE_CLOSURE_ATTESTATION_PULL_REQUEST",
            "promotion_base_required": True,
            "repository_record": "spec/part2-completion-authority-v1.json",
            "exact_head_ci_required": True,
            "squash_merge_required": True,
            "independent_main_ci_required": True,
        },
        "closure publication protocol differs",
    )
    return authority


def _controls(root: Path) -> None:
    coverage = _load(root, "spec/part2-stage8-closure-coverage-v1.json")
    _require(
        coverage
        == {
            "schema_version": "1.0",
            "production_surface": "ledgerguard_part2_stage8_closure",
            "minimum_statement_percent": 100.0,
            "minimum_branch_percent": 100.0,
            "mutation_classes": MUTATION_CLASSES,
        },
        "closure quality authority differs",
    )
    workflow = (root / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    for marker in (
        "PART2_STAGE8_PROMOTION_SHA",
        "ledgerguard-part2-stage8-promotion-closure",
        "tools/run_part2_stage8_closure.py",
        "tools/build_part2_stage8_closure_ci_evidence.py",
        "ledgerguard-part2-stage8-closure-${{ github.event.pull_request.head.sha }}",
    ):
        _require(marker in workflow, f"closure CI control missing: {marker}")
    _require("id-token: write" not in workflow, "automatic CI can request an OIDC token")
    closure_block = workflow.split("Run Part 2 Stage 8 closure validation twice", 1)[-1]
    _require(
        "aws-actions/" not in closure_block and "aws " not in closure_block,
        "closure CI can call AWS",
    )
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    _require(
        'ledgerguard-part2-stage8-closure = "ledgerguard_part2_stage8_closure:main"' in pyproject,
        "closure command missing",
    )


def _documentation(root: Path) -> None:
    status = (root / "PROJECT_STATUS.md").read_text(encoding="utf-8")
    readme = (root / "README.md").read_text(encoding="utf-8")
    completion = (root / "docs/part2-completion.md").read_text(encoding="utf-8")
    _require("State: `LOCAL_RECONCILIATION_VERIFIED`" in status, "terminal Part 2 state missing")
    _require(
        "Stage state: `PART2_STAGE8_CLOSURE_ATTESTATION_CANDIDATE`" in status,
        "closure candidate state missing",
    )
    _require("PR #17 completed the Stage 8 promotion audit" in readme, "README promotion missing")
    _require("overall project remains in progress" in readme, "README project boundary missing")
    _require(
        "PR #17 completed the Stage 8 promotion transaction" in completion, "closure record missing"
    )
    _require("not yet active on `main`" in completion, "publication boundary missing")


def validate_stage8_closure(root: Path) -> dict[str, Any]:
    """Validate the complete repository-resident Part 2 closure attestation."""
    root = root.resolve()
    freeze = _promotion(root)
    authority = _completion(root, freeze)
    _controls(root)
    _documentation(root)
    for relative in CLOSURE_ARTIFACTS:
        _require((root / relative).is_file(), f"closure artifact missing: {relative}")
    closure_digest = sha256(
        "".join(
            f"{relative}:{_digest(root / relative)}\n" for relative in CLOSURE_ARTIFACTS
        ).encode()
    ).hexdigest()
    return {
        "promotion": {
            "commit": freeze["squash_merge_commit"],
            "tree": freeze["squash_merge_tree"],
            "state": freeze["state"],
        },
        "closure_attestation_digest": closure_digest,
        "requirements": 203,
        "stage_gates": 69,
        "master_part2_gates": authority["master_part2_completion_gates"],
        "part2_state": authority["state"],
        "part2_closed": True,
        "project_complete": False,
        "aws_execution": False,
    }


def main() -> None:
    print(json.dumps(validate_stage8_closure(Path.cwd()), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
