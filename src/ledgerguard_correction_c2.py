"""Fail-closed validation for LedgerGuard Part 1 corrective workstream C2."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Mapping
from hashlib import sha1, sha256
from pathlib import Path
from typing import Any, cast

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from ledgerguard.foundation import FoundationError

PROJECT = "ledgerguard-payment-reconciliation-platform"
PART1_STATE = "PART1_CORRECTION_IN_PROGRESS"
PROJECT_STATE = "PROJECT_IN_PROGRESS"
PART2_STATE = "BLOCKED"
C2_STATE = "COMPLETION_AND_SCORECARD_AUTHORITY_ESTABLISHED"
C1_MANIFEST_PATH = "history/part1/c1/manifest-v1.json"
C1_MANIFEST_SHA256 = "0c5469bd6de0ec9be71f4e4c3e74fb7659261751836c0f4a7263b357768bf7c4"
C1_FILE_COUNT = 126
C1_MUTABLE_PATHS = {
    "PROJECT_STATUS.md",
    "README.md",
    "contracts/project-completion-v1.json",
    "docs/architecture.md",
    "docs/contract-model.md",
    "docs/correctness.md",
    "docs/failure-model.md",
    "docs/gap-audit.md",
    "docs/part1-correction.md",
    "docs/scorecard.md",
    "pyproject.toml",
    "tests/test_part1_correction_c1.py",
}
C2_REQUIREMENT_IDS = [
    "OP-S2-R021",
    "OP-S3-R005",
    "OP-S3-R006",
    "OP-S3-R007",
    "OP-S3-R008",
    "OP-GATE-R008",
]
EXPECTED_TARGETS = {
    "architecture_quality": 8.0,
    "automated_testing": 8.5,
    "documentation_and_adrs": 8.0,
    "evidence_integrity": 8.5,
    "failure_and_recovery": 8.5,
    "financial_correctness": 9.0,
    "lifecycle_ownership": 8.5,
    "performance_and_scale": 7.5,
    "problem_clarity": 8.5,
    "real_aws_execution": 8.0,
    "repository_structure": 8.0,
    "security_and_cost_controls": 8.0,
}
EXPECTED_LEVELS = {
    "architecture_quality": "DESIGNED/MODELED",
    "automated_testing": "LOCAL_VERIFIED",
    "documentation_and_adrs": "LOCAL_VERIFIED",
    "evidence_integrity": "LOCAL_VERIFIED",
    "failure_and_recovery": "DESIGNED/MODELED",
    "financial_correctness": "LOCAL_VERIFIED",
    "lifecycle_ownership": "DESIGNED/MODELED",
    "performance_and_scale": "UNCLAIMED",
    "problem_clarity": "LOCAL_VERIFIED",
    "real_aws_execution": "UNCLAIMED",
    "repository_structure": "LOCAL_VERIFIED",
    "security_and_cost_controls": "DESIGNED/MODELED",
}
EXPECTED_CONTRIBUTION = {
    "architecture_quality": True,
    "automated_testing": True,
    "documentation_and_adrs": True,
    "evidence_integrity": True,
    "failure_and_recovery": True,
    "financial_correctness": True,
    "lifecycle_ownership": False,
    "performance_and_scale": False,
    "problem_clarity": True,
    "real_aws_execution": False,
    "repository_structure": True,
    "security_and_cost_controls": True,
}
EXPECTED_EXECUTION_BOUNDARY = {
    "aws_api_called": False,
    "aws_workflow_dispatched": False,
    "infrastructure_mutated": False,
    "reconciliation_runtime_added": False,
    "stage0_to_stage4_history_rewritten": False,
    "c0_history_rewritten": False,
    "c1_history_rewritten": False,
    "historical_v1_mutated": False,
    "accepted_v2_mutated": False,
    "phase8_verdict_relabelled": False,
    "part1_completion_claimed": False,
    "part2_unlocked": False,
}
EXPECTED_PROMOTION_BOUNDARY = {
    "pull_request_number": 8,
    "pull_request_state": "DRAFT_REQUIRED",
    "exact_head_ci": "REQUIRED",
    "merge_in_c2": "PROHIBITED",
    "post_merge_main_ci": "DEFERRED_TO_C6_C7",
}


class C2Error(FoundationError):
    """Raised when the C2 authority or evidence fails closed."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise C2Error(message)


def _mapping(value: object, message: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise C2Error(message)
    return value


def _list(value: object, message: str) -> list[Any]:
    if not isinstance(value, list):
        raise C2Error(message)
    return value


def _load(path: Path) -> dict[str, Any]:
    def reject_constant(value: str) -> None:
        raise ValueError(f"non-finite JSON number is forbidden: {value}")

    def reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key is forbidden: {key}")
            result[key] = value
        return result

    try:
        value: object = json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=reject_constant,
            object_pairs_hook=reject_duplicate_pairs,
        )
    except (OSError, json.JSONDecodeError, ValueError) as error:
        raise C2Error(f"cannot load {path}: {error}") from error
    if not isinstance(value, dict):
        raise C2Error(f"JSON object required: {path}")
    return value


def _safe_file(root: Path, relative: str, label: str) -> Path:
    path_value = Path(relative)
    _require(
        bool(relative) and not path_value.is_absolute() and ".." not in path_value.parts,
        f"{label} path escapes repository",
    )
    path = root / path_value
    _require(path.is_file() and not path.is_symlink(), f"{label} missing: {relative}")
    _require(path.resolve().is_relative_to(root.resolve()), f"{label} escapes repository")
    return path


def _digest(root: Path, relative: str) -> str:
    return sha256(_safe_file(root, relative, "digest-bound artifact").read_bytes()).hexdigest()


def _git_blob_sha(data: bytes) -> str:
    return sha1(f"blob {len(data)}\0".encode() + data).hexdigest()


def _validate_c1_manifest(root: Path) -> list[Mapping[str, Any]]:
    path = _safe_file(root, C1_MANIFEST_PATH, "C1 history manifest")
    _require(
        sha256(path.read_bytes()).hexdigest() == C1_MANIFEST_SHA256,
        "C1 manifest digest differs",
    )
    manifest = _load(path)
    _require(manifest.get("project") == PROJECT, "C1 manifest project differs")
    _require(manifest.get("workstream") == "C1", "C1 manifest workstream differs")
    _require(manifest.get("state") == "C1_EXACT_HEAD_TREE_PRESERVED", "C1 state differs")
    source = _mapping(manifest.get("source"), "C1 source missing")
    expected_source = {
        "base_main_sha": "2842550d24559a636ff5f15cbd6ea4be1c2ab1c1",
        "branch": "part1-c0-truthful-correction",
        "pr_number": 8,
        "pr_state": "DRAFT",
        "exact_head_sha": "9eb497b86b30496e82cc016d29682d29c05a4e73",
        "tree_sha": "c62b5283786e5cd721cc6cb8c627dec496eeb5f5",
        "exact_head_ci_run_id": 33594729489,
        "exact_head_ci_conclusion": "success",
        "c1_sha256": "d22707d2583873a1ebbda3d1562fe10a345084ab9c7a8511888ce9449d3ac222",
        "c1_contract_sha256": ("25e8947c0d87ebb2aa3f39eaaeaba1b704b89e1e58a405b8d788440e1f722d8f"),
    }
    _require(dict(source) == expected_source, "C1 manifest source differs")
    files = [
        _mapping(item, "C1 file entry invalid")
        for item in _list(manifest.get("files"), "C1 files missing")
    ]
    _require(
        len(files) == manifest.get("accepted_file_count") == C1_FILE_COUNT,
        "C1 file count differs",
    )
    logical = [item.get("logical_path") for item in files]
    _require(len(logical) == len(set(logical)), "duplicate C1 logical path")
    snapshots = {
        str(item["logical_path"]) for item in files if isinstance(item.get("snapshot_path"), str)
    }
    _require(snapshots == C1_MUTABLE_PATHS, "C1 snapshot inventory differs")
    _require(manifest.get("mutable_snapshot_count") == 12, "C1 snapshot count differs")
    return files


def materialize_c1_view(root: Path, destination: Path) -> Path:
    """Materialize the exact 126-file green C1 tree."""

    files = _validate_c1_manifest(root)
    _require(not destination.exists(), "C1 destination already exists")
    destination.mkdir(parents=True)
    for item in files:
        logical = item.get("logical_path")
        if not isinstance(logical, str):
            raise C2Error("C1 logical path invalid")
        snapshot = item.get("snapshot_path")
        source_relative = snapshot if isinstance(snapshot, str) else logical
        data = _safe_file(root, source_relative, "C1 artifact").read_bytes()
        _require(sha256(data).hexdigest() == item.get("sha256"), f"C1 digest drift: {logical}")
        _require(_git_blob_sha(data) == item.get("git_blob_sha"), f"C1 blob drift: {logical}")
        target = destination / logical
        _require(target.resolve().is_relative_to(destination.resolve()), "C1 target escapes")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    actual = sorted(
        path.relative_to(destination).as_posix()
        for path in destination.rglob("*")
        if path.is_file()
    )
    expected = sorted(str(item["logical_path"]) for item in files)
    _require(actual == expected, "materialized C1 inventory differs")
    return destination


def reproduce_c1(root: Path) -> dict[str, Any]:
    """Run the preserved C1 validator from the exact green PR tree."""

    with tempfile.TemporaryDirectory(prefix="ledgerguard-c1-view-") as temporary:
        view = materialize_c1_view(root, Path(temporary) / "repository")
        environment = os.environ.copy()
        entries = [str(view / "src")]
        if environment.get("PYTHONPATH"):
            entries.append(environment["PYTHONPATH"])
        environment["PYTHONPATH"] = os.pathsep.join(entries)
        completed = subprocess.run(
            [sys.executable, "-m", "ledgerguard_correction_c1"],
            cwd=view,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
        )
        _require(
            completed.returncode == 0,
            f"preserved C1 validation failed: {completed.stderr.strip()}",
        )
        try:
            parsed: object = json.loads(completed.stdout)
        except json.JSONDecodeError as error:
            raise C2Error("preserved C1 output is not JSON") from error
    _require(isinstance(parsed, dict), "preserved C1 result must be an object")
    result = cast(dict[str, Any], parsed)
    _require(
        result.get("c1_sha256")
        == "d22707d2583873a1ebbda3d1562fe10a345084ab9c7a8511888ce9449d3ac222",
        "C1 digest differs",
    )
    _require(result.get("state") == PART1_STATE, "preserved C1 state differs")
    _require(result.get("part2_entry") == PART2_STATE, "preserved C1 Part 2 state differs")
    return result


def _validate_completion_authority(root: Path) -> tuple[dict[str, Any], str, str]:
    schema_path = _safe_file(
        root, "spec/part1-completion-authority-v2.schema.json", "completion schema"
    )
    contract_path = _safe_file(
        root, "contracts/part1-completion-authority-v2.json", "completion authority"
    )
    schema = _load(schema_path)
    contract = _load(contract_path)
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as error:
        raise C2Error(f"completion authority schema invalid: {error.message}") from error
    errors = sorted(
        Draft202012Validator(schema).iter_errors(contract), key=lambda item: list(item.path)
    )
    _require(
        not errors, f"completion authority violates schema: {errors[0].message if errors else ''}"
    )
    _require(
        schema.get("$id") == "urn:ledgerguard:part1-completion-authority:v2",
        "completion schema ID differs",
    )
    _require(contract.get("correction_scope") == C2_REQUIREMENT_IDS, "C2 scope differs")
    supersession = _mapping(contract.get("authority_supersession"), "supersession missing")
    _require(
        _digest(root, "contracts/project-completion-v1.json")
        == supersession.get("historical_contract_sha256")
        == "9a323c8b7800c90fc3ad1697ec407f6756ceebba8df266ab88deba97fe6017b6",
        "historical completion authority differs",
    )
    amendments = _load(root / "spec/part1-authority-amendments-v1.json")
    amendment_ids = [
        _mapping(item, "amendment invalid").get("id")
        for item in _list(amendments.get("amendments"), "amendments missing")
    ]
    _require(
        supersession.get("domain_schema_change_control_amendment") in amendment_ids,
        "completion authority amendment link differs",
    )
    ledger = _load(root / "spec/part1-requirement-ledger-v1.json")
    rows = [
        _mapping(item, "ledger row invalid")
        for item in _list(ledger.get("requirements"), "ledger missing")
    ]
    c2_ids = [item.get("requirement_id") for item in rows if item.get("correction_owner") == "C2"]
    _require(c2_ids == C2_REQUIREMENT_IDS, "C2 ledger ownership differs")
    scorecard = _mapping(contract.get("scorecard"), "scorecard missing")
    _require(set(scorecard) == set(EXPECTED_TARGETS), "scorecard dimensions differ")
    for dimension in sorted(EXPECTED_TARGETS):
        item = _mapping(scorecard.get(dimension), f"scorecard dimension missing: {dimension}")
        _require(item.get("target") == EXPECTED_TARGETS[dimension], f"target differs: {dimension}")
        _require(
            item.get("current_evidence_level") == EXPECTED_LEVELS[dimension],
            f"evidence level differs: {dimension}",
        )
        _require(
            item.get("part1_contributes") is EXPECTED_CONTRIBUTION[dimension],
            f"Part 1 contribution differs: {dimension}",
        )
        _require(item.get("score_type") == "TARGET", f"score type differs: {dimension}")
        _require(bool(item.get("evidence_scope")), f"evidence scope empty: {dimension}")
        _require(
            bool(
                _list(item.get("evidence_required_to_achieve_target"), "required evidence invalid")
            ),
            f"required evidence empty: {dimension}",
        )
        _require(
            bool(_list(item.get("remaining_evidence"), "remaining evidence invalid")),
            f"remaining evidence empty: {dimension}",
        )
    target = _load(root / ".github/ledgerguard-target.json")
    aws = _mapping(contract.get("aws_boundary"), "AWS boundary missing")
    _require(aws.get("repository") == target.get("repository"), "repository target differs")
    _require(aws.get("default_branch") == target.get("default_branch"), "branch target differs")
    _require(aws.get("account_id") == target.get("account_id"), "account target differs")
    _require(aws.get("region") == target.get("region"), "region target differs")
    _require(aws.get("oidc_role_name") == target.get("oidc_role_name"), "role target differs")
    runtime = _mapping(target.get("managed_runtime"), "target runtime missing")
    for field in ("glue_version", "spark_version", "python_version"):
        _require(aws.get(field) == runtime.get(field), f"runtime target differs: {field}")
    invariants = _mapping(contract.get("completion_invariants"), "completion invariants missing")
    current = _mapping(invariants.get("current"), "current invariants missing")
    _require(current.get("requirement_count") == 331, "requirement invariant differs")
    _require(current.get("implementation_remaining_count") == 84, "remaining invariant differs")
    _require(current.get("open_gate_count") == 9, "gate invariant differs")
    _require(current.get("final_c7_audit_required") is True, "C7 invariant bypassed")
    return (
        contract,
        sha256(schema_path.read_bytes()).hexdigest(),
        sha256(contract_path.read_bytes()).hexdigest(),
    )


def _validate_active_status(root: Path) -> None:
    for relative in ("README.md", "PROJECT_STATUS.md"):
        text = _safe_file(root, relative, "active status").read_text(encoding="utf-8")
        _require(PART1_STATE in text and PROJECT_STATE in text, f"active state differs: {relative}")
        _require(PART2_STATE in text, f"Part 2 block missing: {relative}")
        _require("C2" in text and "scorecard" in text.lower(), f"C2 status missing: {relative}")


def _validate_contract(root: Path) -> tuple[dict[str, str], str]:
    path = _safe_file(root, "contracts/part1-c2-correction-v1.json", "C2 contract")
    contract = _load(path)
    _require(
        contract.get("project") == PROJECT and contract.get("part") == 1, "C2 identity differs"
    )
    _require(
        contract.get("workstream") == "C2" and contract.get("state") == C2_STATE,
        "C2 state differs",
    )
    _require(
        contract.get("part1_state") == PART1_STATE and contract.get("part2_entry") == PART2_STATE,
        "C2 active boundary differs",
    )
    dependency = _mapping(contract.get("c1_dependency"), "C1 dependency missing")
    _require(dependency.get("manifest_sha256") == C1_MANIFEST_SHA256, "C1 dependency differs")
    _require(
        dependency.get("c1_sha256")
        == "d22707d2583873a1ebbda3d1562fe10a345084ab9c7a8511888ce9449d3ac222",
        "C1 result dependency differs",
    )
    _require(dependency.get("exact_head_ci_run_id") == 33594729489, "C1 CI dependency differs")
    _require(contract.get("correction_requirement_ids") == C2_REQUIREMENT_IDS, "C2 IDs differ")
    _require(contract.get("locally_addressed_count") == 6, "C2 addressed count differs")
    _require(contract.get("implementation_remaining_count") == 78, "C2 remainder differs")
    _require(
        contract.get("remaining_workstreams") == [f"C{number}" for number in range(3, 8)],
        "C2 remaining workstreams differ",
    )
    _require(contract.get("scorecard_dimension_count") == 12, "C2 scorecard count differs")
    _require(
        contract.get("execution_boundary") == EXPECTED_EXECUTION_BOUNDARY,
        "C2 execution boundary differs",
    )
    _require(
        contract.get("promotion_boundary") == EXPECTED_PROMOTION_BOUNDARY,
        "C2 promotion boundary differs",
    )
    artifacts = _mapping(contract.get("artifacts"), "C2 artifacts missing")
    actual: dict[str, str] = {}
    for name, value in artifacts.items():
        artifact = _mapping(value, f"C2 artifact invalid: {name}")
        relative = artifact.get("path")
        if not isinstance(relative, str):
            raise C2Error(f"C2 artifact path missing: {name}")
        digest = _digest(root, relative)
        _require(digest == artifact.get("sha256"), f"C2 artifact digest differs: {relative}")
        actual[str(name)] = digest
    _require(len(actual) == 17, "C2 artifact inventory differs")
    return actual, sha256(path.read_bytes()).hexdigest()


def validate_c2(root: Path | None = None, *, verify_evidence: bool = True) -> dict[str, Any]:
    """Validate C2 and return deterministic correction evidence."""

    repository = (root or Path.cwd()).resolve()
    c1 = reproduce_c1(repository)
    _authority, schema_digest, authority_digest = _validate_completion_authority(repository)
    _validate_active_status(repository)
    artifacts, contract_digest = _validate_contract(repository)
    payload: dict[str, Any] = {
        "project": PROJECT,
        "part": 1,
        "workstream": "C2",
        "workstream_state": C2_STATE,
        "state": PART1_STATE,
        "project_state": PROJECT_STATE,
        "part2_entry": PART2_STATE,
        "c1_sha256": c1["c1_sha256"],
        "c1_manifest_sha256": C1_MANIFEST_SHA256,
        "completion_schema_sha256": schema_digest,
        "completion_authority_sha256": authority_digest,
        "correction_requirement_ids": C2_REQUIREMENT_IDS,
        "locally_addressed_count": 6,
        "implementation_remaining_count": 78,
        "remaining_workstreams": [f"C{number}" for number in range(3, 8)],
        "scorecard_dimension_count": 12,
        "scorecard_targets": EXPECTED_TARGETS,
        "scorecard_evidence_levels": EXPECTED_LEVELS,
        "contract_sha256": contract_digest,
        "artifact_digests": artifacts,
        "execution_boundary": EXPECTED_EXECUTION_BOUNDARY,
        "promotion_boundary": EXPECTED_PROMOTION_BOUNDARY,
        "final_c7_audit_required": True,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    payload["c2_sha256"] = sha256(canonical).hexdigest()
    if verify_evidence:
        evidence = _load(_safe_file(repository, "evidence/part1-c2-local.json", "C2 evidence"))
        _require(
            evidence.get("project") == PROJECT and evidence.get("workstream") == "C2",
            "C2 evidence identity differs",
        )
        _require(evidence.get("contract_sha256") == contract_digest, "C2 evidence contract differs")
        _require(evidence.get("c2_sha256") == payload["c2_sha256"], "C2 evidence digest differs")
        local = _mapping(evidence.get("local_validation"), "C2 local validation missing")
        for field in (
            "ruff_format",
            "ruff_lint",
            "strict_mypy",
            "pytest",
            "c2_focused_pytest",
            "c1_reproduction",
            "schema_meta_validation",
            "completion_schema_validation",
            "exact_completion_invariants",
            "scorecard_field_completeness",
            "scorecard_target_integrity",
            "aws_target_consistency",
            "adversarial_mutations",
            "determinism",
        ):
            _require(local.get(field) == "PASS", f"C2 local validation differs: {field}")
        _require(isinstance(local.get("test_count"), int), "C2 test count missing")
        _require(
            evidence.get("execution_boundary") == EXPECTED_EXECUTION_BOUNDARY,
            "C2 evidence boundary differs",
        )
        external = _mapping(evidence.get("external_ci"), "C2 external CI missing")
        _require(external.get("exact_head_ci") == "REQUIRED_EXTERNAL", "C2 CI boundary differs")
        _require(external.get("merge") == "PROHIBITED_IN_C2", "C2 evidence permits merge")
    return payload


def main() -> None:
    print(json.dumps(validate_c2(Path.cwd()), indent=2, sort_keys=True))


def main_c1() -> None:
    print(json.dumps(reproduce_c1(Path.cwd()), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
