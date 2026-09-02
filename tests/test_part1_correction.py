from __future__ import annotations

import json
import shutil
import tempfile
from collections.abc import Callable
from hashlib import sha1, sha256
from pathlib import Path
from typing import Any

import pytest

from ledgerguard_correction import (
    ACCEPTED_STAGE4_MAIN_SHA,
    ACCEPTED_STAGE4_TREE_SHA,
    CorrectionError,
    materialize_stage4_view,
    reproduce_stage4,
    validate_c0,
)
from ledgerguard_correction_c1 import materialize_c0_view
from ledgerguard_correction_c4 import materialize_stage5_view

ACTIVE_ROOT = Path(__file__).resolve().parents[1]
_C0_TEMPORARY = tempfile.TemporaryDirectory(prefix="ledgerguard-c0-tests-")
_STAGE5_ROOT = materialize_stage5_view(ACTIVE_ROOT, Path(_C0_TEMPORARY.name) / "stage5")
ROOT = materialize_c0_view(_STAGE5_ROOT, Path(_C0_TEMPORARY.name) / "repository")


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


def _mutate_json(root: Path, relative: str, mutation: Callable[[dict[str, Any]], None]) -> None:
    path = root / relative
    value = json.loads(path.read_text(encoding="utf-8"))
    mutation(value)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def test_c0_t001_accepted_stage4_source_is_exactly_bound() -> None:
    manifest = json.loads((ROOT / "history/part1/stage4/manifest-v1.json").read_text())
    assert manifest["source"]["main_sha"] == ACCEPTED_STAGE4_MAIN_SHA
    assert manifest["source"]["tree_sha"] == ACCEPTED_STAGE4_TREE_SHA
    assert manifest["accepted_file_count"] == len(manifest["files"]) == 95


def test_c0_t002_every_accepted_stage4_file_reproduces_exact_bytes(tmp_path: Path) -> None:
    view = materialize_stage4_view(ROOT, tmp_path / "stage4")
    manifest = json.loads((ROOT / "history/part1/stage4/manifest-v1.json").read_text())
    actual_paths = sorted(
        path.relative_to(view).as_posix() for path in view.rglob("*") if path.is_file()
    )
    assert actual_paths == sorted(item["logical_path"] for item in manifest["files"])
    for item in manifest["files"]:
        data = (view / item["logical_path"]).read_bytes()
        assert sha256(data).hexdigest() == item["sha256"]
        assert sha1(f"blob {len(data)}\0".encode() + data).hexdigest() == item["git_blob_sha"]


def test_c0_t003_preserved_stage4_validator_executes_in_isolation() -> None:
    result = reproduce_stage4(ROOT)
    assert result["state"] == "PART1_FOUNDATION_COMPLETE"
    assert result["project_state"] == "PROJECT_IN_PROGRESS"
    assert len(result["part1_sha256"]) == 64


def test_c0_t004_owner_approved_amendments_are_truthful_and_scoped() -> None:
    authority = json.loads((ROOT / "spec/part1-authority-amendments-v1.json").read_text())
    assert authority["approval"] == "OWNER_APPROVED"
    assert [item["id"] for item in authority["amendments"]] == [
        "P1-AWS-001",
        "P1-CONTRACT-001",
    ]
    aws = authority["amendments"][0]
    assert aws["historical_observation"]["workflow_run_id"] == 31722045599
    assert aws["historical_observation"]["identity_plane_execution"] == (
        "AWS_VERIFIED_WRONG_TARGET"
    )
    assert aws["replacement_claim_boundary"]["managed_reconciliation_execution"] == ("UNCLAIMED")
    assert aws["replacement_claim_boundary"]["aws_account_wide_nonmutation"] == "NOT_PROVEN"
    versioning = authority["amendments"][1]
    assert versioning["supersedes_requirement_id"] == "OP-S2-R001"
    assert versioning["replacement_authority"]["future_incompatible_changes"] == (
        "REQUIRE_NEW_VERSION"
    )


def test_c0_t005_active_state_is_correction_and_part2_is_blocked() -> None:
    for relative in ("README.md", "PROJECT_STATUS.md"):
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert "PART1_CORRECTION_IN_PROGRESS" in text
        assert "PROJECT_IN_PROGRESS" in text
        assert "BLOCKED" in text


def test_c0_t006_validator_is_deterministic_and_keeps_remaining_work() -> None:
    first = validate_c0(ROOT)
    second = validate_c0(ROOT)
    assert first == second
    assert first["remaining_workstreams"] == [f"C{number}" for number in range(1, 8)]
    assert first["part2_entry"] == "BLOCKED"
    assert len(first["c0_sha256"]) == 64


def test_c0_t007_stage4_manifest_mutation_fails_closed(tmp_path: Path) -> None:
    repository = _copy_repository(tmp_path)
    _mutate_json(
        repository,
        "history/part1/stage4/manifest-v1.json",
        lambda value: value.update({"accepted_file_count": 94}),
    )
    with pytest.raises(CorrectionError, match="manifest digest differs"):
        validate_c0(repository)


def test_c0_t008_stage4_snapshot_mutation_fails_closed(tmp_path: Path) -> None:
    repository = _copy_repository(tmp_path)
    path = repository / "history/part1/stage4/snapshots/README.md"
    path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(CorrectionError, match="Stage 4 digest drift"):
        validate_c0(repository)


def test_c0_t009_authority_or_boundary_inflation_fails_closed(tmp_path: Path) -> None:
    authority_repository = _copy_repository(tmp_path / "authority")
    _mutate_json(
        authority_repository,
        "spec/part1-authority-amendments-v1.json",
        lambda value: value["amendments"][0]["replacement_claim_boundary"].update(
            {"managed_reconciliation_execution": "AWS_VERIFIED"}
        ),
    )
    with pytest.raises(CorrectionError, match="AWS claim inflated"):
        validate_c0(authority_repository)

    boundary_repository = _copy_repository(tmp_path / "boundary")
    _mutate_json(
        boundary_repository,
        "contracts/part1-c0-correction-v1.json",
        lambda value: value["execution_boundary"].update({"aws_api_called": True}),
    )
    with pytest.raises(CorrectionError, match="execution boundary differs"):
        validate_c0(boundary_repository)
