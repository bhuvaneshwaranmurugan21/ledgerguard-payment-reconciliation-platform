from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from ledgerguard_correction_c4 import EXPECTED_BASELINE, STAGE6_IDS, C4Error, validate_stage6

ROOT = Path(__file__).resolve().parents[1]


def _copy(tmp_path: Path) -> Path:
    destination = tmp_path / "repository"
    shutil.copytree(
        ROOT,
        destination,
        ignore=shutil.ignore_patterns(
            ".git",
            ".venv",
            ".mypy_cache",
            ".pytest_cache",
            ".ruff_cache",
            "__pycache__",
            "*.egg-info",
            "build",
            "dist",
            ".coverage",
        ),
    )
    return destination


def _mutate_json(root: Path, relative: str, mutation: Callable[[dict[str, Any]], None]) -> None:
    path = root / relative
    value = json.loads(path.read_text(encoding="utf-8"))
    mutation(value)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def test_c4_t001_stage6_candidate_is_deterministic_and_truthful() -> None:
    first = validate_stage6(ROOT)
    second = validate_stage6(ROOT)
    assert first == second
    assert first["requirement_inventory"] == STAGE6_IDS
    assert first["part1_state"] == "PART1_CORRECTION_IN_PROGRESS"
    assert first["part2_entry"] == "BLOCKED"
    assert first["execution_boundary"]["aws_api_called"] is False
    assert len(first["part1_gate_results"]) == 14
    assert len(first["foundation_digest"]) == 64


def test_c4_t002_phase8_baseline_is_preserved() -> None:
    assert EXPECTED_BASELINE == {"PASS": 9, "PARTIAL": 1, "FAIL": 18, "NOT_PROVEN": 7}


def test_c4_t003_stage6_inventory_mutation_fails_closed(tmp_path: Path) -> None:
    repository = _copy(tmp_path)
    _mutate_json(
        repository,
        "spec/part1-stage6-validation-profile-v1.json",
        lambda value: value["requirement_ids"].pop(),
    )
    with pytest.raises(C4Error, match="profile inventory"):
        validate_stage6(repository)


def test_c4_t004_boundary_inflation_fails_closed(tmp_path: Path) -> None:
    repository = _copy(tmp_path)
    _mutate_json(
        repository,
        "spec/part1-stage6-validation-profile-v1.json",
        lambda value: value["boundaries"].update({"aws_api_called": True}),
    )
    with pytest.raises(C4Error, match="boundary differs"):
        validate_stage6(repository)


def test_c4_t005_unhashed_dependency_fails_closed(tmp_path: Path) -> None:
    repository = _copy(tmp_path)
    path = repository / "requirements/part1-stage6-py311.lock"
    path.write_text(path.read_text(encoding="utf-8") + "unbounded>=1\n", encoding="utf-8")
    with pytest.raises(C4Error, match="OP-S6-R002"):
        validate_stage6(repository)


def test_c4_t006_duplicate_dependency_fails_closed(tmp_path: Path) -> None:
    repository = _copy(tmp_path)
    path = repository / "requirements/part1-stage6-bootstrap.lock"
    path.write_text(
        path.read_text(encoding="utf-8") + "pip==25.2 "
        "--hash=sha256:6d67a2b4e7f14d8b31b8b52648866fa717f45a1eb70e83002f4331d07e953717\n",
        encoding="utf-8",
    )
    with pytest.raises(C4Error, match="duplicate dependency"):
        validate_stage6(repository)


def test_c4_t007_accepted_schema_mutation_fails_closed(tmp_path: Path) -> None:
    repository = _copy(tmp_path)
    path = repository / "contracts/v2/journal-v2.schema.json"
    path.write_text(path.read_text(encoding="utf-8") + " ", encoding="utf-8")
    with pytest.raises(C4Error, match="Stage 5 checkpoint replay failed"):
        validate_stage6(repository)


def test_c4_t008_raw_head_control_removal_fails_closed(tmp_path: Path) -> None:
    repository = _copy(tmp_path)
    path = repository / ".github/workflows/ci.yml"
    path.write_text(
        path.read_text(encoding="utf-8").replace("git rev-parse HEAD", "git status --short"),
        encoding="utf-8",
    )
    with pytest.raises(C4Error, match="git rev-parse HEAD"):
        validate_stage6(repository)


def test_c4_t009_oidc_permission_fails_closed(tmp_path: Path) -> None:
    repository = _copy(tmp_path)
    path = repository / ".github/workflows/ci.yml"
    path.write_text(path.read_text(encoding="utf-8") + "\n# id-token: write\n", encoding="utf-8")
    with pytest.raises(C4Error, match="OIDC token"):
        validate_stage6(repository)


def test_c4_t010_ci_evidence_must_use_the_exact_validation_environment(tmp_path: Path) -> None:
    repository = _copy(tmp_path)
    path = repository / ".github/workflows/ci.yml"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            '"$RUNNER_TEMP/ledgerguard-stage6/run-1/venv/bin/python"', "python"
        ),
        encoding="utf-8",
    )
    with pytest.raises(C4Error, match="run-1/venv/bin/python"):
        validate_stage6(repository)
