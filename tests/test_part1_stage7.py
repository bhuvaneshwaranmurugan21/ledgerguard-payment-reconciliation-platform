from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from ledgerguard_correction_c5 import EXPECTED_STAGE6, C5Error, validate_stage7

ROOT = Path(__file__).resolve().parents[1]


def _copy(tmp_path: Path) -> Path:
    destination = tmp_path / "repository"
    shutil.copytree(
        ROOT,
        destination,
        ignore=shutil.ignore_patterns(".git", ".venv", "__pycache__", ".pytest_cache"),
    )
    return destination


def _mutate_json(root: Path, relative: str, callback: object) -> None:
    path = root / relative
    value = json.loads(path.read_text(encoding="utf-8"))
    assert callable(callback)
    callback(value)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def test_s7_t001_final_candidate_is_complete_and_deterministic() -> None:
    first = validate_stage7(ROOT)
    second = validate_stage7(ROOT)
    assert first == second
    assert first["state"] == "PART1_FOUNDATION_COMPLETE"
    assert first["requirements"] == {"total": 331, "reaudited_nonpass": 96}
    assert first["gates"] == {"total": 14, "premerge_candidate_pass": 13, "postmerge_pending": 1}
    assert first["aws_execution"] is False
    assert first["infrastructure_mutation"] is False


def test_s7_t002_stage6_checkpoint_is_exact() -> None:
    result = validate_stage7(ROOT)
    assert result["stage6_entry_checkpoint"] == EXPECTED_STAGE6
    assert result["stage6_foundation_digest"] == EXPECTED_STAGE6["foundation_digest"]


def test_s7_t003_stage6_artifact_identity_mutation_fails_closed(tmp_path: Path) -> None:
    root = _copy(tmp_path)
    _mutate_json(
        root,
        "evidence/part1-stage6-ci-evidence-manifest-v1.json",
        lambda value: value.update({"artifact_id": 1}),
    )
    with pytest.raises(C5Error, match="artifact manifest differs"):
        validate_stage7(root)


def test_s7_t004_requirement_owner_count_mutation_fails_closed(tmp_path: Path) -> None:
    root = _copy(tmp_path)
    _mutate_json(
        root,
        "evidence/part1-stage7-premerge-audit-v1.json",
        lambda value: value["requirement_reaudit"]["owner_counts"].update({"C7": 9}),
    )
    with pytest.raises(C5Error, match="owner counts differ"):
        validate_stage7(root)


def test_s7_t005_missing_owner_evidence_fails_closed(tmp_path: Path) -> None:
    root = _copy(tmp_path)
    _mutate_json(
        root,
        "evidence/part1-stage7-premerge-audit-v1.json",
        lambda value: value["requirement_reaudit"]["evidence_by_owner"]["C5"].append(
            "evidence/missing.json"
        ),
    )
    with pytest.raises(C5Error, match="owner evidence path missing"):
        validate_stage7(root)


def test_s7_t006_postmerge_gate_cannot_be_counted_premerge(tmp_path: Path) -> None:
    root = _copy(tmp_path)
    _mutate_json(
        root,
        "evidence/part1-stage7-premerge-audit-v1.json",
        lambda value: value["gate_reaudit"].update({"premerge_candidate_pass": 14}),
    )
    with pytest.raises(C5Error, match="premerge gate count differs"):
        validate_stage7(root)


def test_s7_t007_aws_claim_mutation_fails_closed(tmp_path: Path) -> None:
    root = _copy(tmp_path)
    _mutate_json(
        root,
        "contracts/part1-stage7-promotion-v1.json",
        lambda value: value["claim_boundary"].update({"aws_execution": True}),
    )
    with pytest.raises(C5Error, match="AWS execution was claimed"):
        validate_stage7(root)


def test_s7_t008_failure_policy_cannot_be_weakened(tmp_path: Path) -> None:
    root = _copy(tmp_path)
    _mutate_json(
        root,
        "contracts/part1-stage7-promotion-v1.json",
        lambda value: value["failure_policy"].update(
            {"failed_requirement_relabelling_prohibited": False}
        ),
    )
    with pytest.raises(C5Error, match="failure policy is weakened"):
        validate_stage7(root)


def test_s7_t009_active_state_cannot_regress(tmp_path: Path) -> None:
    root = _copy(tmp_path)
    status = root / "PROJECT_STATUS.md"
    status.write_text(
        status.read_text(encoding="utf-8").replace(
            "PART1_FOUNDATION_COMPLETE", "PART1_CORRECTION_IN_PROGRESS"
        ),
        encoding="utf-8",
    )
    with pytest.raises(C5Error, match="status line missing"):
        validate_stage7(root)


def test_s7_t010_external_closure_cannot_be_removed(tmp_path: Path) -> None:
    root = _copy(tmp_path)
    _mutate_json(
        root,
        "evidence/part1-stage7-premerge-audit-v1.json",
        lambda value: value["external_closure_required"].pop(),
    )
    with pytest.raises(C5Error, match="closure differs"):
        validate_stage7(root)


def test_s7_t011_stage7_ci_cannot_use_ambient_python(tmp_path: Path) -> None:
    root = _copy(tmp_path)
    workflow = root / ".github/workflows/ci.yml"
    workflow.write_text(
        workflow.read_text(encoding="utf-8").replace(
            '"$RUNNER_TEMP/ledgerguard-stage6/run-1/venv/bin/python"', "python", 1
        ),
        encoding="utf-8",
    )
    with pytest.raises(C5Error, match="locked clean environment"):
        validate_stage7(root)
