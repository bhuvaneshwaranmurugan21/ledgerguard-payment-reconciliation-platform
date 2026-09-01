from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from ledgerguard.stage0 import Stage0Error
from ledgerguard.stage1 import Stage1Error, validate_stage1

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


def test_stage1_passes_deterministically_and_preserves_stage0() -> None:
    first = validate_stage1(ROOT)
    second = validate_stage1(ROOT)
    assert first == second
    assert first["stage_state"] == "PART1_FINANCIAL_SEMANTICS_FROZEN"
    assert first["overall_part1_state"] == "PART1_FOUNDATION_CORRECTION_IN_PROGRESS"
    assert first["baseline_main_sha"] == "9a920a300b50fe46bb534e7fc9f32ad5eda1224c"
    assert (
        first["stage0_sha256"] == "3da80eb91b0948f50c5080c7198e78a0a1716a36c7ca7267ec205099b981282b"
    )
    assert first["decision_count"] == 18
    assert first["unresolved_decision_count"] == 0
    assert first["aws_execution"] is False


@pytest.mark.parametrize(
    "mutation,match",
    [
        (lambda value: value["baseline"].update({"main_sha": "0" * 40}), "baseline main_sha"),
        (
            lambda value: value["baseline"].update({"main_tree_sha": "0" * 40}),
            "baseline main_tree_sha",
        ),
        (
            lambda value: value["execution_boundary"].update({"aws_execution": True}),
            "aws_execution",
        ),
        (
            lambda value: value["required_gates"].remove("POST_MERGE_MAIN_CI_SUCCESS"),
            "post-merge CI",
        ),
    ],
)
def test_stage1_contract_fails_closed(tmp_path: Path, mutation: Mutation, match: str) -> None:
    repository = _copy_repository(tmp_path)
    _mutate_json(repository, "contracts/part1-stage1-completion-v1.json", mutation)
    with pytest.raises(Stage1Error, match=match):
        validate_stage1(repository)


def test_stage1_rejects_unresolved_semantic_decision(tmp_path: Path) -> None:
    repository = _copy_repository(tmp_path)
    _mutate_json(
        repository,
        "spec/financial-semantics-v1.json",
        lambda value: value["unresolved_decisions"].append("bank-date-fallback"),
    )
    with pytest.raises(Stage1Error, match="unresolved semantic decisions"):
        validate_stage1(repository)


def test_stage1_rejects_failure_ownership_overlap(tmp_path: Path) -> None:
    repository = _copy_repository(tmp_path)
    _mutate_json(
        repository,
        "spec/financial-semantics-v1.json",
        lambda value: value["failure_ownership"]["FINANCIAL_EXCEPTION"].append(
            "CURRENCY_DOMAIN_VIOLATION"
        ),
    )
    with pytest.raises(Stage1Error, match="admission and financial reasons overlap"):
        validate_stage1(repository)


def test_stage1_rejects_admission_failure_published_as_proof(tmp_path: Path) -> None:
    repository = _copy_repository(tmp_path)

    def authorize(value: dict[str, Any]) -> None:
        case = next(
            item
            for item in value["transaction_cases"]
            if item["name"] == "cross-currency-contamination"
        )
        case["expected"] = {
            "status": "EXCEPTION",
            "authoritative_proof": True,
            "reason_codes": ["CURRENCY_DOMAIN_VIOLATION"],
        }

    _mutate_json(repository, "spec/financial-examples-v1.json", authorize)
    with pytest.raises(Stage1Error, match="currency outcome differs"):
        validate_stage1(repository)


def test_stage1_rejects_evidence_contract_digest_change(tmp_path: Path) -> None:
    repository = _copy_repository(tmp_path)
    _mutate_json(
        repository,
        "evidence/part1-stage1-local.json",
        lambda value: value.update({"completion_contract_sha256": "0" * 64}),
    )
    with pytest.raises(Stage1Error, match="contract digest"):
        validate_stage1(repository)


def test_stage1_rejects_artifact_drift(tmp_path: Path) -> None:
    repository = _copy_repository(tmp_path)
    path = repository / "docs/part1-requirements.md"
    path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(Stage1Error, match="artifact digest differs"):
        validate_stage1(repository)


def test_stage1_rejects_repository_escape_in_artifact_path(tmp_path: Path) -> None:
    repository = _copy_repository(tmp_path)
    _mutate_json(
        repository,
        "contracts/part1-stage1-completion-v1.json",
        lambda value: value["semantic_artifacts"]["requirements"].update({"path": "../outside.md"}),
    )
    with pytest.raises(Stage1Error, match="escapes repository"):
        validate_stage1(repository)


def test_stage1_rejects_reconciliation_runtime(tmp_path: Path) -> None:
    repository = _copy_repository(tmp_path)
    (repository / "src/ledgerguard/engine.py").write_text(
        "# forbidden in Stage 1\n", encoding="utf-8"
    )
    with pytest.raises(Stage0Error, match="rejected runtime"):
        validate_stage1(repository)
