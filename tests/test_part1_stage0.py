from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from ledgerguard.stage0 import Stage0Error, validate_stage0

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


def _mutate_contract(root: Path, mutation: Mutation) -> None:
    path = root / "contracts/part1-stage0-completion-v1.json"
    contract: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    mutation(contract)
    path.write_text(json.dumps(contract, indent=2) + "\n", encoding="utf-8")


def test_stage0_passes_deterministically() -> None:
    first = validate_stage0(ROOT)
    second = validate_stage0(ROOT)
    assert first == second
    assert first["stage_state"] == "PART1_STAGE0_BASELINE_AUDIT_COMPLETE"
    assert first["overall_part1_state"] == "PART1_FOUNDATION_CORRECTION_IN_PROGRESS"
    assert first["draft_file_count"] == 32
    assert first["aws_execution"] is False


@pytest.mark.parametrize(
    "mutation,match",
    [
        (lambda value: value["history"].update({"base_sha": "0" * 40}), "base SHA"),
        (lambda value: value["history"]["rejected_pr"].update({"merged": True}), "unmerged"),
        (
            lambda value: value["execution_boundary"].update({"aws_execution": True}),
            "aws_execution",
        ),
        (
            lambda value: value.update({"overall_part1_state": "PART1_FOUNDATION_COMPLETE"}),
            "Part 1 state",
        ),
        (lambda value: value["draft_inventory"]["artifacts"].pop(), "32 dispositions"),
        (
            lambda value: value["draft_inventory"]["artifacts"][0].update(
                {"disposition": "ACCEPT"}
            ),
            "unknown disposition",
        ),
        (
            lambda value: value["draft_inventory"]["artifacts"][0].pop("owner"),
            "owner missing",
        ),
    ],
)
def test_stage0_contract_fails_closed(tmp_path: Path, mutation: Mutation, match: str) -> None:
    repository = _copy_repository(tmp_path)
    _mutate_contract(repository, mutation)
    with pytest.raises(Stage0Error, match=match):
        validate_stage0(repository)


def test_stage0_rejects_duplicate_disposition(tmp_path: Path) -> None:
    repository = _copy_repository(tmp_path)

    def duplicate(value: dict[str, Any]) -> None:
        artifacts = value["draft_inventory"]["artifacts"]
        artifacts[1]["ref"] = artifacts[0]["ref"]

    _mutate_contract(repository, duplicate)
    with pytest.raises(Stage0Error, match="duplicate artifact"):
        validate_stage0(repository)


def test_stage0_rejects_schema_byte_change(tmp_path: Path) -> None:
    repository = _copy_repository(tmp_path)
    path = repository / "contracts/bank-entry-v1.schema.json"
    path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(Stage0Error, match="schema bytes differ"):
        validate_stage0(repository)


def test_stage0_rejects_evidence_digest_change(tmp_path: Path) -> None:
    repository = _copy_repository(tmp_path)
    path = repository / "evidence/part1-stage0-local.json"
    evidence = json.loads(path.read_text(encoding="utf-8"))
    evidence["contract_sha256"] = "0" * 64
    path.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(Stage0Error, match="contract digest"):
        validate_stage0(repository)
