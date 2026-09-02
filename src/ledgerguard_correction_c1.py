"""Fail-closed validation for LedgerGuard Part 1 corrective workstream C1."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from collections import defaultdict
from collections.abc import Mapping
from hashlib import sha1, sha256
from pathlib import Path
from typing import Any, cast

from ledgerguard.foundation import FoundationError, parse_contract_json

PROJECT = "ledgerguard-payment-reconciliation-platform"
PART1_STATE = "PART1_CORRECTION_IN_PROGRESS"
PROJECT_STATE = "PROJECT_IN_PROGRESS"
PART2_STATE = "BLOCKED"
C1_STATE = "ORIGINAL_REQUIREMENT_AUTHORITY_ESTABLISHED"
C0_MANIFEST_PATH = "history/part1/c0/manifest-v1.json"
C0_MANIFEST_SHA256 = "6933360fe19fe292d4faa9245ece10b0dab71d85ff268608345f00be2ce956f7"
C0_FILE_COUNT = 108
C0_MUTABLE_PATHS = {
    "PROJECT_STATUS.md",
    "README.md",
    "pyproject.toml",
    "tests/test_part1_correction.py",
}
EXPECTED_SOURCE_DIGESTS = {
    "catalog": "72052fb97451a4966d592bd49ad2a25faf83fc8a5a9b29631905acab9e3263af",
    "mapping": "cef0a8214bb254fc1dfe820af4f3ed12096f5efc2a5eb47b603b84aea5763808",
    "verdict": "51bc3b84a0d6e05eced99789b157bce5c5b5a60139f55069010a9283ec9b1561",
    "amendments": "960e4ef58c88cd9296ace0f0a9d1aae1ce970af8f99d6de1521aed6c71ab4b86",
}
EXPECTED_GENERATED_DIGESTS = {
    "ledger": "1a866e7f1dfdb8a9e4e172fd9c308589f6d000268acd8f1336be868d2461b296",
    "reverse": "ebe5d5d6f4904893fb07718d9eb1709068e29a04fdeaab6d3986270db1ff2802",
    "gates": "015b48e75e77b3b2194d2cf6dafa03cb76bc928a0b2ebd28f83de1effe3237a9",
}
EXPECTED_BASELINE_SUMMARY = {
    "FAIL": 69,
    "NOT_PROVEN": 14,
    "PARTIAL": 13,
    "PASS": 235,
    "strict_nonpass_count": 96,
    "strict_pass_count": 235,
    "total": 331,
}
EXPECTED_RESOLUTION_SUMMARY = {
    "C1_LOCALLY_ADDRESSED_PENDING_FINAL_AUDIT": 4,
    "CORRECTION_REQUIRED": 84,
    "FORMALLY_AMENDED_C0_PENDING_FINAL_AUDIT": 8,
    "PRESERVED_PHASE8_PASS": 235,
    "final_c7_audit_required_count": 96,
    "implementation_remaining_count": 84,
}
EXPECTED_REMAINING_BY_WORKSTREAM = {"C2": 6, "C3": 24, "C4": 9, "C5": 15, "C6": 20, "C7": 10}
EXPECTED_GATE_SUMMARY = {"FORMALLY_AMENDED": 1, "OPEN": 9, "PRESERVED_PASS": 4, "total": 14}
EXPECTED_EXECUTION_BOUNDARY = {
    "aws_api_called": False,
    "aws_workflow_dispatched": False,
    "infrastructure_mutated": False,
    "reconciliation_runtime_added": False,
    "stage0_to_stage4_history_rewritten": False,
    "c0_history_rewritten": False,
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
    "merge_in_c1": "PROHIBITED",
    "post_merge_main_ci": "DEFERRED_TO_C6_C7",
}


class C1Error(FoundationError):
    """Raised when the C1 authority or evidence fails closed."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise C1Error(message)


def _mapping(value: object, message: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise C1Error(message)
    return value


def _list(value: object, message: str) -> list[Any]:
    if not isinstance(value, list):
        raise C1Error(message)
    return value


def _load(path: Path) -> dict[str, Any]:
    try:
        value = parse_contract_json(path.read_text(encoding="utf-8"))
    except (OSError, FoundationError) as error:
        raise C1Error(f"cannot load {path}: {error}") from error
    if not isinstance(value, dict):
        raise C1Error(f"JSON object required: {path}")
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


def _git_blob_sha(data: bytes) -> str:
    return sha1(f"blob {len(data)}\0".encode() + data).hexdigest()


def _digest(root: Path, relative: str) -> str:
    return sha256(_safe_file(root, relative, "digest-bound artifact").read_bytes()).hexdigest()


def _validate_c0_manifest(root: Path) -> list[Mapping[str, Any]]:
    path = _safe_file(root, C0_MANIFEST_PATH, "C0 history manifest")
    _require(
        sha256(path.read_bytes()).hexdigest() == C0_MANIFEST_SHA256, "C0 manifest digest differs"
    )
    manifest = _load(path)
    _require(manifest.get("project") == PROJECT, "C0 manifest project differs")
    _require(manifest.get("workstream") == "C0", "C0 manifest workstream differs")
    _require(manifest.get("state") == "C0_EXACT_HEAD_TREE_PRESERVED", "C0 manifest state differs")
    source = _mapping(manifest.get("source"), "C0 manifest source missing")
    expected_source = {
        "base_main_sha": "2842550d24559a636ff5f15cbd6ea4be1c2ab1c1",
        "branch": "part1-c0-truthful-correction",
        "pr_number": 8,
        "pr_state": "DRAFT",
        "exact_head_sha": "6efe71b9ec54482527793b31ad990f980e2442ca",
        "tree_sha": "27b8e3fe5759243411b546641b4219dbc63457fb",
        "exact_head_ci_run_id": 33589011816,
        "exact_head_ci_conclusion": "success",
        "c0_sha256": "c6d6476cfb1e1b3a62d9e3fca4d488db3f98fa96f22282d44a154fda727a6877",
        "c0_contract_sha256": "5902cf1b41aaa075cf7650cf25246cba9fc5fa040f964e4f537d32b304e8236e",
    }
    _require(dict(source) == expected_source, "C0 manifest source differs")
    files = [
        _mapping(item, "C0 file entry invalid")
        for item in _list(manifest.get("files"), "C0 files missing")
    ]
    _require(
        len(files) == manifest.get("accepted_file_count") == C0_FILE_COUNT, "C0 file count differs"
    )
    logical_paths = [item.get("logical_path") for item in files]
    _require(
        all(isinstance(item, str) and item for item in logical_paths), "C0 logical path missing"
    )
    _require(len(logical_paths) == len(set(logical_paths)), "duplicate C0 logical path")
    snapshots = {
        str(item["logical_path"]) for item in files if isinstance(item.get("snapshot_path"), str)
    }
    _require(snapshots == C0_MUTABLE_PATHS, "C0 mutable snapshot inventory differs")
    _require(
        manifest.get("mutable_snapshot_count") == len(C0_MUTABLE_PATHS), "C0 snapshot count differs"
    )
    return files


def materialize_c0_view(root: Path, destination: Path) -> Path:
    """Materialize the exact 108-file C0 PR tree from immutable history."""

    files = _validate_c0_manifest(root)
    _require(not destination.exists(), "C0 destination already exists")
    destination.mkdir(parents=True)
    for item in files:
        logical = item.get("logical_path")
        if not isinstance(logical, str):
            raise C1Error("C0 logical path invalid")
        snapshot = item.get("snapshot_path")
        source_relative = snapshot if isinstance(snapshot, str) else logical
        data = _safe_file(root, source_relative, "C0 artifact").read_bytes()
        _require(sha256(data).hexdigest() == item.get("sha256"), f"C0 digest drift: {logical}")
        _require(_git_blob_sha(data) == item.get("git_blob_sha"), f"C0 blob drift: {logical}")
        target = destination / logical
        _require(target.resolve().is_relative_to(destination.resolve()), "C0 target escapes")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    actual = sorted(
        path.relative_to(destination).as_posix()
        for path in destination.rglob("*")
        if path.is_file()
    )
    expected = sorted(str(item["logical_path"]) for item in files)
    _require(actual == expected, "materialized C0 inventory differs")
    return destination


def reproduce_c0(root: Path) -> dict[str, Any]:
    """Run the preserved C0 validator from the exact green PR tree."""

    with tempfile.TemporaryDirectory(prefix="ledgerguard-c0-view-") as temporary:
        view = materialize_c0_view(root, Path(temporary) / "repository")
        environment = os.environ.copy()
        entries = [str(view / "src")]
        if environment.get("PYTHONPATH"):
            entries.append(environment["PYTHONPATH"])
        environment["PYTHONPATH"] = os.pathsep.join(entries)
        completed = subprocess.run(
            [sys.executable, "-m", "ledgerguard_correction"],
            cwd=view,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
        )
        _require(
            completed.returncode == 0, f"preserved C0 validation failed: {completed.stderr.strip()}"
        )
        try:
            parsed: object = json.loads(completed.stdout)
        except json.JSONDecodeError as error:
            raise C1Error("preserved C0 output is not JSON") from error
    _require(isinstance(parsed, dict), "preserved C0 result must be an object")
    result = cast(dict[str, Any], parsed)
    _require(
        result.get("c0_sha256")
        == "c6d6476cfb1e1b3a62d9e3fca4d488db3f98fa96f22282d44a154fda727a6877",
        "C0 digest differs",
    )
    _require(result.get("state") == PART1_STATE, "preserved C0 state differs")
    _require(result.get("part2_entry") == PART2_STATE, "preserved C0 Part 2 state differs")
    return result


def _invert(rows: list[Mapping[str, Any]], field: str) -> dict[str, list[str]]:
    reverse: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        requirement_id = row.get("requirement_id")
        if not isinstance(requirement_id, str):
            raise C1Error("ledger requirement ID missing")
        value = row.get(field)
        values = value if isinstance(value, list) else [value]
        for item in values:
            reverse[str(item)].append(requirement_id)
    return {key: sorted(values) for key, values in sorted(reverse.items())}


def _validate_requirement_authorities(
    root: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    source_paths = {
        "catalog": "spec/part1-original-requirements-v1.json",
        "mapping": "evidence/part1-phase4-bidirectional-mapping-v1.json",
        "verdict": "evidence/part1-phase8-requirement-verdict-v1.json",
        "amendments": "spec/part1-authority-amendments-v1.json",
    }
    for name, relative in source_paths.items():
        _require(
            _digest(root, relative) == EXPECTED_SOURCE_DIGESTS[name],
            f"C1 source digest differs: {name}",
        )
    generated_paths = {
        "ledger": "spec/part1-requirement-ledger-v1.json",
        "reverse": "spec/part1-requirement-reverse-index-v1.json",
        "gates": "spec/part1-gate-registry-v1.json",
    }
    for name, relative in generated_paths.items():
        _require(
            _digest(root, relative) == EXPECTED_GENERATED_DIGESTS[name],
            f"C1 generated digest differs: {name}",
        )

    catalog = _load(root / source_paths["catalog"])
    mapping = _load(root / source_paths["mapping"])
    verdict = _load(root / source_paths["verdict"])
    ledger = _load(root / generated_paths["ledger"])
    reverse = _load(root / generated_paths["reverse"])
    gates = _load(root / generated_paths["gates"])
    rows = [
        _mapping(item, "ledger row invalid")
        for item in _list(ledger.get("requirements"), "ledger rows missing")
    ]
    source_rows = [
        _mapping(item, "source requirement invalid")
        for item in _list(catalog.get("requirements"), "source requirements missing")
    ]
    verdict_rows = {
        _mapping(item, "verdict row invalid").get("requirement_id"): _mapping(
            item, "verdict row invalid"
        )
        for item in _list(verdict.get("requirement_verdicts"), "verdicts missing")
    }
    mapping_rows = {
        _mapping(item, "mapping row invalid").get("requirement_id"): _mapping(
            item, "mapping row invalid"
        )
        for item in _list(mapping.get("requirement_mappings"), "mappings missing")
    }
    source_ids = [item.get("id") for item in source_rows]
    row_ids = [item.get("requirement_id") for item in rows]
    _require(
        len(rows) == len(set(row_ids)) == ledger.get("requirement_count") == 331,
        "331 requirement inventory differs",
    )
    _require(row_ids == source_ids, "ledger requirement order differs")
    for source, row in zip(source_rows, rows, strict=True):
        requirement_id = row.get("requirement_id")
        _require(
            row.get("requirement") == source.get("requirement"),
            f"requirement text differs: {requirement_id}",
        )
        _require(
            row.get("source_lines") == source.get("source_lines"),
            f"source lines differ: {requirement_id}",
        )
        adjudicated = verdict_rows.get(requirement_id)
        mapped = mapping_rows.get(requirement_id)
        if adjudicated is None or mapped is None:
            raise C1Error(f"source mapping missing: {requirement_id}")
        _require(
            row.get("baseline_verdict") == adjudicated.get("final_verdict"),
            f"baseline verdict differs: {requirement_id}",
        )
        _require(
            row.get("baseline_rationale") == adjudicated.get("rationale"),
            f"baseline rationale differs: {requirement_id}",
        )
        _require(
            row.get("candidate_evidence_ids") == mapped.get("candidate_evidence_ids"),
            f"candidate evidence differs: {requirement_id}",
        )
        for field in (
            "rule_refs",
            "contract_schema_paths",
            "documentation_paths",
            "test_paths",
            "candidate_evidence_ids",
            "authority_evidence_paths",
        ):
            _require(
                bool(_list(row.get(field), f"{field} missing: {requirement_id}")),
                f"{field} empty: {requirement_id}",
            )
        _require(isinstance(row.get("correction_owner"), str), f"owner missing: {requirement_id}")
        _require(
            isinstance(row.get("correction_action"), str), f"correction missing: {requirement_id}"
        )
        _require(
            row.get("implementation_remaining")
            == (row.get("resolution_state") == "CORRECTION_REQUIRED"),
            f"remaining derivation differs: {requirement_id}",
        )

    _require(
        ledger.get("baseline_verdict_summary") == EXPECTED_BASELINE_SUMMARY,
        "baseline summary differs",
    )
    _require(
        ledger.get("resolution_summary") == EXPECTED_RESOLUTION_SUMMARY,
        "resolution summary differs",
    )
    derived_remaining = [row["requirement_id"] for row in rows if row["implementation_remaining"]]
    _require(
        ledger.get("remaining_requirement_ids") == derived_remaining,
        "remaining requirement derivation differs",
    )
    remaining_by_owner: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        if row["implementation_remaining"]:
            remaining_by_owner[str(row["correction_owner"])].append(str(row["requirement_id"]))
    actual_by_owner = _mapping(ledger.get("remaining_by_workstream"), "remaining ownership missing")
    _require(
        {
            key: len(_list(value, f"remaining owner {key} invalid"))
            for key, value in actual_by_owner.items()
        }
        == EXPECTED_REMAINING_BY_WORKSTREAM,
        "remaining workstream counts differ",
    )
    _require(
        dict(actual_by_owner)
        == {key: sorted(values) for key, values in sorted(remaining_by_owner.items())},
        "remaining workstream derivation differs",
    )

    indexes = _mapping(reverse.get("indexes"), "reverse indexes missing")
    fields = {
        "rules": "rule_refs",
        "contract_schemas": "contract_schema_paths",
        "documentation": "documentation_paths",
        "tests": "test_paths",
        "candidate_evidence": "candidate_evidence_ids",
        "owners": "correction_owner",
        "corrections": "correction_action",
        "baseline_verdicts": "baseline_verdict",
        "resolution_states": "resolution_state",
    }
    for index, field in fields.items():
        _require(indexes.get(index) == _invert(rows, field), f"reverse index differs: {index}")
    amendment_rows = [row for row in rows if row.get("amendment_ids")]
    _require(
        indexes.get("amendments") == _invert(amendment_rows, "amendment_ids"),
        "amendment reverse index differs",
    )
    for field in (
        "orphan_requirement_ids",
        "orphan_evidence_ids",
        "undisposed_evidence_ids",
        "unowned_requirement_ids",
        "uncorrected_nonpass_requirement_ids",
    ):
        _require(reverse.get(field) == [], f"C1 reverse orphan remains: {field}")
    registry_ids = {
        item.get("id")
        for item in _list(mapping.get("evidence_registry"), "evidence registry missing")
    }
    mapped_ids = set(
        _mapping(indexes.get("candidate_evidence"), "candidate evidence reverse missing")
    )
    disposed_ids = set(
        _mapping(reverse.get("explicitly_disposed_evidence"), "disposed evidence missing")
    )
    _require(mapped_ids.isdisjoint(disposed_ids), "evidence is both mapped and disposed")
    _require(mapped_ids | disposed_ids == registry_ids, "evidence disposition inventory differs")

    gate_rows = [
        _mapping(item, "gate row invalid") for item in _list(gates.get("gates"), "gates missing")
    ]
    expected_gate_ids = [f"OP-GATE-R{number:03d}" for number in range(1, 15)]
    _require(
        [item.get("gate_id") for item in gate_rows] == expected_gate_ids,
        "exact 14-gate inventory differs",
    )
    _require(
        gates.get("gate_count") == 14 and gates.get("summary") == EXPECTED_GATE_SUMMARY,
        "gate summary differs",
    )
    expected_remaining_gates = [
        row["requirement_id"]
        for row in rows
        if row["group"] == "GATE" and row["implementation_remaining"]
    ]
    _require(gates.get("remaining_gate_ids") == expected_remaining_gates, "remaining gates differ")
    _require(gates.get("final_c7_gate_audit_required") is True, "final gate audit was bypassed")
    return ledger, reverse, gates


def _validate_active_status(root: Path) -> None:
    for relative in ("README.md", "PROJECT_STATUS.md"):
        text = _safe_file(root, relative, "active status").read_text(encoding="utf-8")
        _require(PART1_STATE in text and PROJECT_STATE in text, f"active state differs: {relative}")
        _require(PART2_STATE in text, f"Part 2 block missing: {relative}")
        _require("C1" in text and "331" in text and "14" in text, f"C1 status missing: {relative}")


def _validate_contract(root: Path) -> tuple[dict[str, str], str]:
    path = _safe_file(root, "contracts/part1-c1-correction-v1.json", "C1 contract")
    contract = _load(path)
    _require(
        contract.get("project") == PROJECT and contract.get("part") == 1,
        "C1 contract identity differs",
    )
    _require(
        contract.get("workstream") == "C1" and contract.get("state") == C1_STATE,
        "C1 contract state differs",
    )
    _require(
        contract.get("part1_state") == PART1_STATE and contract.get("part2_entry") == PART2_STATE,
        "C1 active boundary differs",
    )
    dependency = _mapping(contract.get("c0_dependency"), "C0 dependency missing")
    _require(
        dependency.get("manifest_sha256") == C0_MANIFEST_SHA256, "C0 dependency digest differs"
    )
    _require(
        dependency.get("c0_sha256")
        == "c6d6476cfb1e1b3a62d9e3fca4d488db3f98fa96f22282d44a154fda727a6877",
        "C0 dependency result differs",
    )
    _require(
        contract.get("requirement_count") == 331 and contract.get("gate_count") == 14,
        "C1 inventory counts differ",
    )
    _require(
        contract.get("remaining_requirement_count") == 84
        and contract.get("remaining_gate_count") == 9,
        "C1 remaining counts differ",
    )
    _require(
        contract.get("remaining_workstreams") == [f"C{number}" for number in range(2, 8)],
        "C1 remaining workstreams differ",
    )
    _require(
        contract.get("execution_boundary") == EXPECTED_EXECUTION_BOUNDARY,
        "C1 execution boundary differs",
    )
    _require(
        contract.get("promotion_boundary") == EXPECTED_PROMOTION_BOUNDARY,
        "C1 promotion boundary differs",
    )
    artifacts = _mapping(contract.get("artifacts"), "C1 artifacts missing")
    actual: dict[str, str] = {}
    for name, value in artifacts.items():
        artifact = _mapping(value, f"C1 artifact invalid: {name}")
        relative = artifact.get("path")
        if not isinstance(relative, str):
            raise C1Error(f"C1 artifact path missing: {name}")
        digest = _digest(root, relative)
        _require(digest == artifact.get("sha256"), f"C1 artifact digest differs: {relative}")
        actual[str(name)] = digest
    _require(len(actual) == 16, "C1 artifact inventory differs")
    return actual, sha256(path.read_bytes()).hexdigest()


def validate_c1(root: Path | None = None, *, verify_evidence: bool = True) -> dict[str, Any]:
    """Validate C1 and return its deterministic correction evidence."""

    repository = (root or Path.cwd()).resolve()
    c0 = reproduce_c0(repository)
    ledger, _reverse, gates = _validate_requirement_authorities(repository)
    _validate_active_status(repository)
    artifact_digests, contract_digest = _validate_contract(repository)
    payload: dict[str, Any] = {
        "project": PROJECT,
        "part": 1,
        "workstream": "C1",
        "workstream_state": C1_STATE,
        "state": PART1_STATE,
        "project_state": PROJECT_STATE,
        "part2_entry": PART2_STATE,
        "c0_sha256": c0["c0_sha256"],
        "c0_manifest_sha256": C0_MANIFEST_SHA256,
        "source_digests": EXPECTED_SOURCE_DIGESTS,
        "generated_digests": EXPECTED_GENERATED_DIGESTS,
        "requirement_count": ledger["requirement_count"],
        "gate_count": gates["gate_count"],
        "baseline_verdict_summary": ledger["baseline_verdict_summary"],
        "resolution_summary": ledger["resolution_summary"],
        "gate_summary": gates["summary"],
        "remaining_requirement_count": len(ledger["remaining_requirement_ids"]),
        "remaining_gate_count": len(gates["remaining_gate_ids"]),
        "remaining_workstreams": [f"C{number}" for number in range(2, 8)],
        "contract_sha256": contract_digest,
        "artifact_digests": artifact_digests,
        "execution_boundary": EXPECTED_EXECUTION_BOUNDARY,
        "promotion_boundary": EXPECTED_PROMOTION_BOUNDARY,
        "final_c7_audit_required": True,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    payload["c1_sha256"] = sha256(canonical).hexdigest()
    if verify_evidence:
        evidence = _load(_safe_file(repository, "evidence/part1-c1-local.json", "C1 evidence"))
        _require(
            evidence.get("project") == PROJECT and evidence.get("workstream") == "C1",
            "C1 evidence identity differs",
        )
        _require(evidence.get("contract_sha256") == contract_digest, "C1 evidence contract differs")
        _require(evidence.get("c1_sha256") == payload["c1_sha256"], "C1 evidence digest differs")
        local = _mapping(evidence.get("local_validation"), "C1 local validation missing")
        for field in (
            "ruff_format",
            "ruff_lint",
            "strict_mypy",
            "pytest",
            "c1_focused_pytest",
            "c0_reproduction",
            "ledger_builder_check",
            "source_digest_check",
            "331_forward_mapping",
            "reverse_mapping",
            "14_gate_inventory",
            "mechanical_remaining_work",
            "adversarial_mutations",
            "determinism",
        ):
            _require(local.get(field) == "PASS", f"C1 local validation differs: {field}")
        _require(isinstance(local.get("test_count"), int), "C1 test count missing")
        _require(
            evidence.get("execution_boundary") == EXPECTED_EXECUTION_BOUNDARY,
            "C1 evidence boundary differs",
        )
        external = _mapping(evidence.get("external_ci"), "C1 external CI missing")
        _require(
            external.get("exact_head_ci") == "REQUIRED_EXTERNAL", "C1 exact-head boundary differs"
        )
        _require(external.get("merge") == "PROHIBITED_IN_C1", "C1 evidence permits merge")
    return payload


def main() -> None:
    print(json.dumps(validate_c1(Path.cwd()), indent=2, sort_keys=True))


def main_c0() -> None:
    """Validate the preserved C0 checkpoint from its immutable historical view."""

    print(json.dumps(reproduce_c0(Path.cwd()), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
