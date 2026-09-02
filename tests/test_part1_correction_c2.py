from __future__ import annotations

import json
import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from ledgerguard_correction_c2 import (
    C1_FILE_COUNT,
    C1_MANIFEST_SHA256,
    C2_REQUIREMENT_IDS,
    EXPECTED_CONTRIBUTION,
    EXPECTED_LEVELS,
    EXPECTED_TARGETS,
    C2Error,
    _validate_c1_manifest,
    _validate_completion_authority,
    reproduce_c1,
    validate_c2,
)
from ledgerguard_correction_c3 import materialize_c2_view
from ledgerguard_correction_c4 import materialize_stage5_view

ACTIVE_ROOT = Path(__file__).resolve().parents[1]
_C2_TEMPORARY = tempfile.TemporaryDirectory(prefix="ledgerguard-c2-tests-")
_STAGE5_ROOT = materialize_stage5_view(ACTIVE_ROOT, Path(_C2_TEMPORARY.name) / "stage5")
ROOT = materialize_c2_view(_STAGE5_ROOT, Path(_C2_TEMPORARY.name) / "repository")


def _load(root: Path, relative: str) -> dict[str, Any]:
    return json.loads((root / relative).read_text(encoding="utf-8"))


def _copy_repository(tmp_path: Path) -> Path:
    destination = tmp_path / "repository"
    shutil.copytree(
        ROOT,
        destination,
        ignore=shutil.ignore_patterns(
            ".git",
            ".mypy_cache",
            ".pytest_cache",
            ".ruff_cache",
            ".venv",
            "__pycache__",
            "build",
            "*.egg-info",
        ),
    )
    return destination


def _mutate_json(
    root: Path,
    relative: str,
    mutation: Callable[[dict[str, Any]], None],
) -> None:
    path = root / relative
    value = _load(root, relative)
    mutation(value)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def test_c2_t001_c1_exact_head_checkpoint_reproduces() -> None:
    files = _validate_c1_manifest(ROOT)
    result = reproduce_c1(ROOT)
    assert len(files) == C1_FILE_COUNT == 126
    assert C1_MANIFEST_SHA256 == (
        "0c5469bd6de0ec9be71f4e4c3e74fb7659261751836c0f4a7263b357768bf7c4"
    )
    assert result["state"] == "PART1_CORRECTION_IN_PROGRESS"
    assert result["part2_entry"] == "BLOCKED"


def test_c2_t002_completion_schema_is_valid_and_enforced() -> None:
    schema = _load(ROOT, "spec/part1-completion-authority-v2.schema.json")
    authority = _load(ROOT, "contracts/part1-completion-authority-v2.json")
    Draft202012Validator.check_schema(schema)
    assert list(Draft202012Validator(schema).iter_errors(authority)) == []
    assert schema["$id"] == "urn:ledgerguard:part1-completion-authority:v2"


def test_c2_t003_scope_matches_all_and_only_c2_owned_requirements() -> None:
    authority = _load(ROOT, "contracts/part1-completion-authority-v2.json")
    ledger = _load(ROOT, "spec/part1-requirement-ledger-v1.json")
    owned = [
        row["requirement_id"] for row in ledger["requirements"] if row["correction_owner"] == "C2"
    ]
    assert authority["correction_scope"] == owned == C2_REQUIREMENT_IDS


def test_c2_t004_scorecard_has_complete_exact_fields() -> None:
    scorecard = _load(ROOT, "contracts/part1-completion-authority-v2.json")["scorecard"]
    assert set(scorecard) == set(EXPECTED_TARGETS)
    required = {
        "target",
        "score_type",
        "current_evidence_level",
        "evidence_scope",
        "evidence_required_to_achieve_target",
        "part1_contributes",
        "remaining_evidence",
    }
    for dimension, row in scorecard.items():
        assert set(row) == required, dimension
        assert row["evidence_scope"], dimension
        assert row["evidence_required_to_achieve_target"], dimension
        assert row["remaining_evidence"], dimension


def test_c2_t005_scorecard_targets_are_targets_above_seven() -> None:
    scorecard = _load(ROOT, "contracts/part1-completion-authority-v2.json")["scorecard"]
    for dimension, target in EXPECTED_TARGETS.items():
        assert target > 7
        assert scorecard[dimension]["target"] == target
        assert scorecard[dimension]["score_type"] == "TARGET"
    interpretation = _load(ROOT, "contracts/part1-completion-authority-v2.json")[
        "scorecard_interpretation"
    ]
    assert interpretation["achieved_scores_recorded"] is False


def test_c2_t006_evidence_levels_and_part1_contribution_are_exact() -> None:
    scorecard = _load(ROOT, "contracts/part1-completion-authority-v2.json")["scorecard"]
    assert {
        dimension: row["current_evidence_level"] for dimension, row in scorecard.items()
    } == EXPECTED_LEVELS
    assert {
        dimension: row["part1_contributes"] for dimension, row in scorecard.items()
    } == EXPECTED_CONTRIBUTION


def test_c2_t007_historical_completion_contract_is_byte_preserved() -> None:
    import hashlib

    data = (ROOT / "contracts/project-completion-v1.json").read_bytes()
    assert hashlib.sha256(data).hexdigest() == (
        "9a323c8b7800c90fc3ad1697ec407f6756ceebba8df266ab88deba97fe6017b6"
    )


def test_c2_t008_aws_boundary_matches_single_target_authority() -> None:
    authority = _load(ROOT, "contracts/part1-completion-authority-v2.json")["aws_boundary"]
    target = _load(ROOT, ".github/ledgerguard-target.json")
    runtime = target["managed_runtime"]
    assert authority == {
        "repository": target["repository"],
        "default_branch": target["default_branch"],
        "account_id": target["account_id"],
        "region": target["region"],
        "oidc_role_name": target["oidc_role_name"],
        "glue_version": runtime["glue_version"],
        "spark_version": runtime["spark_version"],
        "python_version": runtime["python_version"],
        "gross_project_cost_ceiling_usd": 10,
        "c2_aws_execution": False,
        "c2_infrastructure_mutation": False,
    }


def test_c2_t009_validator_is_deterministic_and_blocks_part2() -> None:
    first = validate_c2(ROOT, verify_evidence=False)
    second = validate_c2(ROOT, verify_evidence=False)
    assert first == second
    assert first["state"] == "PART1_CORRECTION_IN_PROGRESS"
    assert first["part2_entry"] == "BLOCKED"
    assert first["implementation_remaining_count"] == 78
    assert first["final_c7_audit_required"] is True


def test_c2_t010_missing_scorecard_field_fails_schema(tmp_path: Path) -> None:
    repository = _copy_repository(tmp_path)
    _mutate_json(
        repository,
        "contracts/part1-completion-authority-v2.json",
        lambda value: value["scorecard"]["financial_correctness"].pop("remaining_evidence"),
    )
    with pytest.raises(C2Error, match="violates schema"):
        _validate_completion_authority(repository)


def test_c2_t011_target_or_evidence_inflation_fails_closed(tmp_path: Path) -> None:
    repository = _copy_repository(tmp_path)
    _mutate_json(
        repository,
        "contracts/part1-completion-authority-v2.json",
        lambda value: value["scorecard"]["real_aws_execution"].update(
            {"current_evidence_level": "LOCAL_VERIFIED"}
        ),
    )
    with pytest.raises(C2Error, match="evidence level differs"):
        _validate_completion_authority(repository)


def test_c2_t012_completion_count_bypass_fails_closed(tmp_path: Path) -> None:
    repository = _copy_repository(tmp_path)
    _mutate_json(
        repository,
        "contracts/part1-completion-authority-v2.json",
        lambda value: value["completion_invariants"]["current"].update(
            {"implementation_remaining_count": 0}
        ),
    )
    with pytest.raises(C2Error, match=r"violates schema|remaining invariant differs"):
        _validate_completion_authority(repository)


def test_c2_t013_c1_snapshot_mutation_fails_closed(tmp_path: Path) -> None:
    repository = _copy_repository(tmp_path)
    snapshot = repository / "history/part1/c1/snapshots/README.md"
    snapshot.write_text(snapshot.read_text(encoding="utf-8") + "drift\n", encoding="utf-8")
    with pytest.raises(C2Error, match="C1 digest drift"):
        reproduce_c1(repository)


def test_c2_t014_completion_formula_requires_all_final_gates() -> None:
    invariants = _load(ROOT, "contracts/part1-completion-authority-v2.json")[
        "completion_invariants"
    ]
    assert invariants["completion_formula"] == (
        "FORMAL_AMENDMENTS_APPROVED_AND_331_REQUIREMENTS_RESOLVED_AND_14_GATES_PASS_"
        "AND_EXACT_HEAD_CI_PASS_AND_POSTMERGE_MAIN_CI_PASS_AND_NO_CRITICAL_OR_MAJOR_"
        "FINDINGS_AND_REMAINING_WORK_ZERO"
    )
    assert invariants["required_final"] == {
        "part1_state": "PART1_FOUNDATION_COMPLETE",
        "part2_entry": "UNLOCKED",
        "effective_requirements_pass": 331,
        "mandatory_gates_pass": 14,
        "remaining_part1_work": 0,
        "critical_findings": 0,
        "major_findings": 0,
        "exact_head_ci": "PASS",
        "postmerge_main_ci": "PASS",
    }
