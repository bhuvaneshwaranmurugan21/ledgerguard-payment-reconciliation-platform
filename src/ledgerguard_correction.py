"""Fail-closed validation for LedgerGuard Part 1 corrective workstream C0."""

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

from ledgerguard.foundation import FoundationError, parse_contract_json

PROJECT = "ledgerguard-payment-reconciliation-platform"
C0_STATE = "PART1_CORRECTION_IN_PROGRESS"
PROJECT_STATE = "PROJECT_IN_PROGRESS"
PART2_STATE = "BLOCKED"
ACCEPTED_STAGE4_MAIN_SHA = "2842550d24559a636ff5f15cbd6ea4be1c2ab1c1"
ACCEPTED_STAGE4_TREE_SHA = "c66d5fc61352ab29c34c8b34b3e949e88ed350c1"
STAGE4_MANIFEST_PATH = "history/part1/stage4/manifest-v1.json"
STAGE4_MANIFEST_SHA256 = "fa1bebf5af7b8f1d6d4f4e4e5fe07866c9ee3dbd590e6562bcf1adc15ef206af"
STAGE4_ACCEPTED_FILE_COUNT = 95
STAGE4_MUTABLE_PATHS = {
    "PROJECT_STATUS.md",
    "README.md",
    "pyproject.toml",
    "src/ledgerguard/foundation.py",
    "tests/test_part1_stage4.py",
}
PHASE8_AUTHORITIES = {
    "authority_sha256": "eb7d31c3fb7c3dc057789c3903ce14be9dacaa28d98e45cee2272f12ed7498ef",
    "requirement_catalog_sha256": (
        "72052fb97451a4966d592bd49ad2a25faf83fc8a5a9b29631905acab9e3263af"
    ),
    "requirement_verdict_sha256": (
        "51bc3b84a0d6e05eced99789b157bce5c5b5a60139f55069010a9283ec9b1561"
    ),
    "corrective_contract_sha256": (
        "d78aed4f0eae2a052ec4ca83a6da49117de25ba775fbc295c4e10c858d71cf19"
    ),
    "final_verdict_sha256": ("b8102d0674e55d9364480a94ce8808b8d60e09b40ddd626c65a85f53035673ce"),
    "acceptance_sha256": "25aae95a8f04f1ed83fbb55ce0caab64eb177f2100cf2b48d8c4716aa0ae0e6b",
}
EXPECTED_AUDIT_COUNTS = {
    "requirements_total": 331,
    "requirements_pass": 235,
    "requirements_nonpass": 96,
    "mandatory_gates_total": 14,
    "mandatory_gates_pass": 4,
}
EXPECTED_REMAINING_WORKSTREAMS = [f"C{number}" for number in range(1, 8)]
EXPECTED_EXECUTION_BOUNDARY = {
    "aws_api_called": False,
    "aws_workflow_dispatched": False,
    "infrastructure_mutated": False,
    "reconciliation_runtime_added": False,
    "stage0_to_stage4_history_rewritten": False,
    "historical_v1_mutated": False,
    "accepted_v2_mutated": False,
    "part1_completion_claimed": False,
    "part2_unlocked": False,
}
EXPECTED_PROMOTION_BOUNDARY = {
    "pull_request_state": "DRAFT_REQUIRED",
    "exact_head_ci": "REQUIRED",
    "merge_in_c0": "PROHIBITED",
    "post_merge_main_ci": "DEFERRED_TO_C6_C7",
}


class CorrectionError(FoundationError):
    """Raised when C0 authority, preservation, or evidence fails closed."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise CorrectionError(message)


def _mapping(value: object, message: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise CorrectionError(message)
    return value


def _list(value: object, message: str) -> list[Any]:
    if not isinstance(value, list):
        raise CorrectionError(message)
    return value


def _load(path: Path) -> dict[str, Any]:
    try:
        value = parse_contract_json(path.read_text(encoding="utf-8"))
    except (OSError, FoundationError) as error:
        raise CorrectionError(f"cannot load {path}: {error}") from error
    if not isinstance(value, dict):
        raise CorrectionError(f"JSON object required: {path}")
    return value


def _safe_file(root: Path, relative: str, label: str) -> Path:
    relative_path = Path(relative)
    _require(
        bool(relative) and not relative_path.is_absolute() and ".." not in relative_path.parts,
        f"{label} path escapes repository",
    )
    path = root / relative_path
    _require(path.is_file() and not path.is_symlink(), f"{label} missing: {relative}")
    _require(path.resolve().is_relative_to(root.resolve()), f"{label} escapes repository")
    return path


def _git_blob_sha(data: bytes) -> str:
    return sha1(f"blob {len(data)}\0".encode() + data).hexdigest()


def _validate_stage4_manifest(root: Path) -> tuple[dict[str, Any], list[Mapping[str, Any]]]:
    manifest_path = _safe_file(root, STAGE4_MANIFEST_PATH, "Stage 4 history manifest")
    _require(
        sha256(manifest_path.read_bytes()).hexdigest() == STAGE4_MANIFEST_SHA256,
        "Stage 4 history manifest digest differs",
    )
    manifest = _load(manifest_path)
    _require(manifest.get("project") == PROJECT, "Stage 4 history project differs")
    _require(manifest.get("part") == 1 and manifest.get("stage") == 4, "history stage differs")
    _require(
        manifest.get("state") == "ACCEPTED_STAGE4_TREE_PRESERVED",
        "Stage 4 history state differs",
    )
    source = _mapping(manifest.get("source"), "Stage 4 history source missing")
    _require(source.get("main_sha") == ACCEPTED_STAGE4_MAIN_SHA, "accepted main SHA differs")
    _require(source.get("tree_sha") == ACCEPTED_STAGE4_TREE_SHA, "accepted tree SHA differs")
    _require(source.get("pr_number") == 7, "accepted Stage 4 PR differs")
    _require(source.get("exact_head_ci_run_id") == 33528424730, "Stage 4 PR CI differs")
    _require(source.get("post_merge_main_ci_run_id") == 33528779642, "Stage 4 main CI differs")
    files = [
        _mapping(item, "Stage 4 history file entry invalid")
        for item in _list(manifest.get("files"), "Stage 4 history files missing")
    ]
    _require(
        manifest.get("accepted_file_count") == STAGE4_ACCEPTED_FILE_COUNT == len(files),
        "Stage 4 accepted-file count differs",
    )
    logical_paths = [item.get("logical_path") for item in files]
    _require(
        all(isinstance(path, str) and path for path in logical_paths),
        "Stage 4 logical path missing",
    )
    _require(len(logical_paths) == len(set(logical_paths)), "duplicate Stage 4 logical path")
    snapshots = {
        str(item["logical_path"]) for item in files if isinstance(item.get("snapshot_path"), str)
    }
    _require(snapshots == STAGE4_MUTABLE_PATHS, "Stage 4 mutable snapshot inventory differs")
    _require(
        manifest.get("mutable_snapshot_count") == len(STAGE4_MUTABLE_PATHS),
        "Stage 4 mutable snapshot count differs",
    )
    return manifest, files


def materialize_stage4_view(root: Path, destination: Path) -> Path:
    """Materialize exactly the accepted 95-file Stage 4 logical tree."""

    _manifest, files = _validate_stage4_manifest(root)
    _require(not destination.exists(), "Stage 4 destination already exists")
    destination.mkdir(parents=True)
    for item in files:
        logical = item.get("logical_path")
        expected_digest = item.get("sha256")
        expected_blob = item.get("git_blob_sha")
        if not isinstance(logical, str):
            raise CorrectionError("Stage 4 logical path invalid")
        snapshot = item.get("snapshot_path")
        source_relative = snapshot if isinstance(snapshot, str) else logical
        source = _safe_file(root, source_relative, "accepted Stage 4 artifact")
        data = source.read_bytes()
        _require(sha256(data).hexdigest() == expected_digest, f"Stage 4 digest drift: {logical}")
        _require(_git_blob_sha(data) == expected_blob, f"Stage 4 blob drift: {logical}")
        target = destination / logical
        _require(target.resolve().is_relative_to(destination.resolve()), "Stage 4 target escapes")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    materialized = sorted(
        path.relative_to(destination).as_posix()
        for path in destination.rglob("*")
        if path.is_file()
    )
    expected = sorted(str(item["logical_path"]) for item in files)
    _require(materialized == expected, "materialized Stage 4 inventory differs")
    return destination


def reproduce_stage4(root: Path) -> dict[str, Any]:
    """Execute the preserved Stage 4 module in an isolated historical tree."""

    with tempfile.TemporaryDirectory(prefix="ledgerguard-stage4-view-") as temporary:
        view = materialize_stage4_view(root, Path(temporary) / "repository")
        environment = os.environ.copy()
        existing_pythonpath = environment.get("PYTHONPATH")
        pythonpath_entries = [str(view / "src")]
        if existing_pythonpath:
            pythonpath_entries.append(existing_pythonpath)
        environment["PYTHONPATH"] = os.pathsep.join(pythonpath_entries)
        completed = subprocess.run(
            [sys.executable, "-m", "ledgerguard.part1"],
            cwd=view,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
        )
        _require(
            completed.returncode == 0,
            f"preserved Stage 4 validation failed: {completed.stderr.strip()}",
        )
        try:
            parsed: object = json.loads(completed.stdout)
        except json.JSONDecodeError as error:
            raise CorrectionError("preserved Stage 4 output is not JSON") from error
    _require(isinstance(parsed, dict), "preserved Stage 4 result must be an object")
    result = cast(dict[str, Any], parsed)
    _require(result.get("state") == "PART1_FOUNDATION_COMPLETE", "Stage 4 state differs")
    _require(result.get("project_state") == PROJECT_STATE, "Stage 4 project state differs")
    _require(result.get("remaining_part1_work") == [], "accepted Stage 4 result differs")
    _require(isinstance(result.get("part1_sha256"), str), "Stage 4 digest missing")
    return result


def _validate_amendments(root: Path) -> tuple[dict[str, Any], str]:
    path = _safe_file(root, "spec/part1-authority-amendments-v1.json", "authority amendments")
    amendments = _load(path)
    _require(amendments.get("project") == PROJECT, "amendment project differs")
    _require(amendments.get("approval") == "OWNER_APPROVED", "owner approval missing")
    _require(amendments.get("approved_at_utc") == "2026-09-02T00:00:00Z", "approval time differs")
    entries = _list(amendments.get("amendments"), "authority amendments missing")
    _require(
        [_mapping(item, "amendment invalid").get("id") for item in entries]
        == [
            "P1-AWS-001",
            "P1-CONTRACT-001",
        ],
        "authority amendment inventory differs",
    )

    aws = _mapping(entries[0], "AWS amendment missing")
    historical = _mapping(aws.get("historical_observation"), "historical AWS observation missing")
    _require(historical.get("workflow_run_id") == 31722045599, "historical AWS run differs")
    _require(historical.get("account_id") == "887720497919", "historical AWS account differs")
    _require(
        historical.get("region_components") == ["ap", "south", "1"],
        "historical AWS region differs",
    )
    _require(
        historical.get("identity_plane_execution") == "AWS_VERIFIED_WRONG_TARGET",
        "historical AWS execution claim differs",
    )
    replacement = _mapping(
        aws.get("replacement_claim_boundary"), "AWS replacement boundary missing"
    )
    _require(
        replacement.get("managed_reconciliation_execution") == "UNCLAIMED", "AWS claim inflated"
    )
    _require(replacement.get("frozen_target_live_identity") == "UNCLAIMED", "target claim inflated")
    _require(
        replacement.get("aws_account_wide_nonmutation") == "NOT_PROVEN",
        "nonmutation claim inflated",
    )
    _require(replacement.get("c0_aws_execution") is False, "C0 claims AWS execution")
    _require(replacement.get("c0_infrastructure_mutation") is False, "C0 claims mutation")

    versioning = _mapping(entries[1], "contract amendment missing")
    _require(
        versioning.get("supersedes_requirement_id") == "OP-S2-R001", "v1 authority link differs"
    )
    authority = _mapping(versioning.get("replacement_authority"), "version authority missing")
    _require(
        dict(authority)
        == {
            "historical_v1_status": "SUPERSEDED_BEFORE_RUNTIME_USE",
            "historical_v1_bytes": "IMMUTABLE_AND_DIGEST_BOUND",
            "active_contract_registry": "contracts/active-contract-set-v1.json",
            "active_schema_version": "2.0",
            "accepted_v2_bytes": "IMMUTABLE_AND_DIGEST_BOUND",
            "future_incompatible_changes": "REQUIRE_NEW_VERSION",
        },
        "approved v1/v2 replacement authority differs",
    )
    policy = _mapping(amendments.get("history_policy"), "history policy missing")
    _require(
        all(value is False for value in policy.values()), "authority amendment rewrites history"
    )
    return amendments, sha256(path.read_bytes()).hexdigest()


def _validate_active_status(root: Path) -> None:
    for relative in ("README.md", "PROJECT_STATUS.md"):
        text = _safe_file(root, relative, "active status").read_text(encoding="utf-8")
        _require(C0_STATE in text, f"active correction state missing from {relative}")
        _require(PROJECT_STATE in text, f"project state missing from {relative}")
        _require(PART2_STATE in text, f"Part 2 block missing from {relative}")
        _require(
            "PART1_CORRECTION_REQUIRED" in text or "CORRECTION_REQUIRED" in text,
            f"audit result missing from {relative}",
        )
    status = _safe_file(root, "PROJECT_STATUS.md", "project status").read_text(encoding="utf-8")
    _require("235 of 331" in status and "4 of 14" in status, "audit counts missing from status")


def _validate_contract(
    root: Path, amendment_digest: str
) -> tuple[dict[str, Any], dict[str, str], str]:
    path = _safe_file(root, "contracts/part1-c0-correction-v1.json", "C0 contract")
    contract = _load(path)
    _require(contract.get("project") == PROJECT, "C0 contract project differs")
    _require(
        contract.get("part") == 1 and contract.get("workstream") == "C0", "C0 identity differs"
    )
    _require(contract.get("state") == C0_STATE, "C0 contract state differs")
    _require(contract.get("project_state") == PROJECT_STATE, "C0 project state differs")
    _require(contract.get("part2_entry") == PART2_STATE, "C0 contract unlocks Part 2")
    accepted = _mapping(contract.get("accepted_stage4_baseline"), "accepted baseline missing")
    _require(
        dict(accepted)
        == {
            "main_sha": ACCEPTED_STAGE4_MAIN_SHA,
            "tree_sha": ACCEPTED_STAGE4_TREE_SHA,
            "manifest_path": STAGE4_MANIFEST_PATH,
            "manifest_sha256": STAGE4_MANIFEST_SHA256,
            "accepted_file_count": STAGE4_ACCEPTED_FILE_COUNT,
        },
        "accepted Stage 4 baseline differs",
    )
    _require(
        contract.get("phase8_authorities") == PHASE8_AUTHORITIES, "Phase 8 authority digests differ"
    )
    _require(contract.get("audit_counts") == EXPECTED_AUDIT_COUNTS, "audit counts differ")
    approved = _mapping(contract.get("approved_amendments"), "approved amendments missing")
    _require(approved.get("approval") == "OWNER_APPROVED", "contract owner approval missing")
    _require(approved.get("sha256") == amendment_digest, "amendment digest differs")
    _require(approved.get("ids") == ["P1-AWS-001", "P1-CONTRACT-001"], "approved IDs differ")
    _require(
        contract.get("remaining_workstreams") == EXPECTED_REMAINING_WORKSTREAMS,
        "remaining corrective workstreams differ",
    )
    _require(
        contract.get("execution_boundary") == EXPECTED_EXECUTION_BOUNDARY,
        "C0 execution boundary differs",
    )
    _require(
        contract.get("promotion_boundary") == EXPECTED_PROMOTION_BOUNDARY,
        "C0 promotion boundary differs",
    )
    artifacts = _mapping(contract.get("artifacts"), "C0 artifacts missing")
    artifact_digests: dict[str, str] = {}
    for name, value in artifacts.items():
        artifact = _mapping(value, f"C0 artifact {name} invalid")
        relative = artifact.get("path")
        expected = artifact.get("sha256")
        if not isinstance(relative, str):
            raise CorrectionError(f"C0 artifact path missing: {name}")
        digest = sha256(_safe_file(root, relative, "C0 artifact").read_bytes()).hexdigest()
        _require(digest == expected, f"C0 artifact digest differs: {relative}")
        artifact_digests[str(name)] = digest
    _require(len(artifact_digests) == 11, "C0 artifact inventory differs")
    return contract, artifact_digests, sha256(path.read_bytes()).hexdigest()


def validate_c0(root: Path | None = None, *, verify_evidence: bool = True) -> dict[str, Any]:
    """Validate the truthful C0 reset and return deterministic candidate evidence."""

    repository = (root or Path.cwd()).resolve()
    stage4 = reproduce_stage4(repository)
    _amendments, amendment_digest = _validate_amendments(repository)
    _validate_active_status(repository)
    _contract, artifact_digests, contract_digest = _validate_contract(repository, amendment_digest)
    payload: dict[str, Any] = {
        "project": PROJECT,
        "part": 1,
        "workstream": "C0",
        "state": C0_STATE,
        "project_state": PROJECT_STATE,
        "part2_entry": PART2_STATE,
        "accepted_stage4_main_sha": ACCEPTED_STAGE4_MAIN_SHA,
        "accepted_stage4_tree_sha": ACCEPTED_STAGE4_TREE_SHA,
        "stage4_manifest_sha256": STAGE4_MANIFEST_SHA256,
        "historical_stage4_part1_sha256": stage4["part1_sha256"],
        "phase8_authorities": PHASE8_AUTHORITIES,
        "audit_counts": EXPECTED_AUDIT_COUNTS,
        "amendment_sha256": amendment_digest,
        "contract_sha256": contract_digest,
        "artifact_digests": artifact_digests,
        "remaining_workstreams": EXPECTED_REMAINING_WORKSTREAMS,
        "execution_boundary": EXPECTED_EXECUTION_BOUNDARY,
        "promotion_boundary": EXPECTED_PROMOTION_BOUNDARY,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    payload["c0_sha256"] = sha256(canonical).hexdigest()

    if verify_evidence:
        evidence = _load(
            _safe_file(repository, "evidence/part1-c0-local.json", "C0 local evidence")
        )
        _require(evidence.get("project") == PROJECT, "C0 evidence project differs")
        _require(
            evidence.get("part") == 1 and evidence.get("workstream") == "C0",
            "C0 evidence identity differs",
        )
        _require(evidence.get("state") == C0_STATE, "C0 evidence state differs")
        _require(evidence.get("contract_sha256") == contract_digest, "C0 contract evidence differs")
        _require(evidence.get("c0_sha256") == payload["c0_sha256"], "C0 evidence digest differs")
        local = _mapping(evidence.get("local_validation"), "C0 local validation missing")
        for field in (
            "ruff_format",
            "ruff_lint",
            "strict_mypy",
            "pytest",
            "c0_focused_pytest",
            "historical_stage4_reproduction",
            "accepted_tree_preservation",
            "authority_amendments",
            "determinism",
        ):
            _require(local.get(field) == "PASS", f"C0 local validation {field} differs")
        _require(isinstance(local.get("test_count"), int), "C0 test count missing")
        external = _mapping(evidence.get("external_ci"), "C0 external CI evidence missing")
        _require(
            external.get("exact_head_ci") == "REQUIRED_EXTERNAL", "exact-head CI boundary differs"
        )
        _require(external.get("merge") == "PROHIBITED_IN_C0", "C0 evidence permits merge")
        _require(
            evidence.get("execution_boundary") == EXPECTED_EXECUTION_BOUNDARY,
            "C0 evidence boundary differs",
        )
    return payload


def main() -> None:
    print(json.dumps(validate_c0(Path.cwd()), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
