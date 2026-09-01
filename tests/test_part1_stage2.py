from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from ledgerguard.foundation import FoundationError, validate_foundation

ROOT = Path(__file__).resolve().parents[1]
Mutation = Callable[[dict[str, Any]], None]


def _copy_repository(tmp_path: Path) -> Path:
    destination = tmp_path / "repository"
    shutil.copytree(
        ROOT,
        destination,
        ignore=shutil.ignore_patterns(
            ".git", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".venv", "__pycache__"
        ),
    )
    return destination


def _mutate_json(root: Path, relative: str, mutation: Mutation) -> None:
    path = root / relative
    value: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    mutation(value)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def test_stage2_foundation_is_deterministic_and_preserves_prior_stages() -> None:
    first = validate_foundation(ROOT)
    second = validate_foundation(ROOT)
    assert first == second
    assert first["stage"] == 2
    assert first["stage_state"] == "PART1_FINANCIAL_CONTRACTS_ENCODED"
    assert first["state"] == "PART1_FOUNDATION_CORRECTION_IN_PROGRESS"
    assert (
        first["stage0_sha256"] == "3da80eb91b0948f50c5080c7198e78a0a1716a36c7ca7267ec205099b981282b"
    )
    assert (
        first["stage1_sha256"] == "4234ac61999de769b87b2329512a8741761023b6c258dfd2207beb66f7dbc191"
    )
    assert len(first["stage2_sha256"]) == 64
    assert first["aws_execution"] is False


@pytest.mark.parametrize(
    "mutation,match",
    [
        (
            lambda value: value["baseline"].update({"main_sha": "0" * 40}),
            "Stage 2 baseline differs",
        ),
        (
            lambda value: value["required_gates"].remove("EXACT_HEAD_CI_SUCCESS"),
            "exact-head CI gate missing",
        ),
        (
            lambda value: value["required_gates"].remove("POST_MERGE_MAIN_CI_SUCCESS"),
            "post-merge CI gate missing",
        ),
        (
            lambda value: value["contract_artifacts"]["active_registry"].update(
                {"path": "../outside.json"}
            ),
            "escapes repository",
        ),
    ],
)
def test_stage2_completion_contract_fails_closed(
    tmp_path: Path, mutation: Mutation, match: str
) -> None:
    repository = _copy_repository(tmp_path)
    _mutate_json(repository, "contracts/part1-stage2-completion-v1.json", mutation)
    with pytest.raises(FoundationError, match=match):
        validate_foundation(repository)


def test_stage2_rejects_historical_v1_schema_mutation(tmp_path: Path) -> None:
    repository = _copy_repository(tmp_path)
    path = repository / "contracts/processor-event-v1.schema.json"
    path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(FoundationError, match="preserved stage validation failed"):
        validate_foundation(repository)


def test_stage2_rejects_active_schema_drift(tmp_path: Path) -> None:
    repository = _copy_repository(tmp_path)
    _mutate_json(
        repository,
        "contracts/v2/processor-event-v2.schema.json",
        lambda value: value.update({"title": "unregistered drift"}),
    )
    with pytest.raises(FoundationError, match="active contract digest differs"):
        validate_foundation(repository)


def test_stage2_rejects_traceability_artifact_drift(tmp_path: Path) -> None:
    repository = _copy_repository(tmp_path)
    path = repository / "spec/contract-traceability-v1.json"
    path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(FoundationError, match="artifact digest differs"):
        validate_foundation(repository)


def test_stage2_rejects_inflated_aws_claim(tmp_path: Path) -> None:
    repository = _copy_repository(tmp_path)
    _mutate_json(
        repository,
        "evidence/part1-stage2-local.json",
        lambda value: value["claim_boundary"].update({"aws_execution": True}),
    )
    with pytest.raises(FoundationError, match="claims AWS execution"):
        validate_foundation(repository)


def test_stage2_rejects_reconciliation_runtime(tmp_path: Path) -> None:
    repository = _copy_repository(tmp_path)
    (repository / "src/ledgerguard/engine.py").write_text(
        "# forbidden during Part 1 Stage 2\n", encoding="utf-8"
    )
    with pytest.raises(FoundationError, match="preserved stage validation failed"):
        validate_foundation(repository)
