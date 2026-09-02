from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from ledgerguard_correction_c3 import (
    ALL_STAGE5_IDS,
    C2_FILE_COUNT,
    C2_MANIFEST_SHA256,
    DIRECT_STAGE5_IDS,
    C3Error,
    _validate_authority,
    _validate_c2_manifest,
    reproduce_c2,
    validate_stage5,
)

ROOT = Path(__file__).resolve().parents[1]


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


def test_c3_t001_c2_exact_head_checkpoint_reproduces() -> None:
    files = _validate_c2_manifest(ROOT)
    result = reproduce_c2(ROOT)
    assert len(files) == C2_FILE_COUNT == 148
    assert C2_MANIFEST_SHA256 == (
        "6f5d1f0a15a035e6e527de778d7fad12b1f3229dae2765bdc487955f67d5f34c"
    )
    assert result["c2_sha256"] == (
        "977f3af4ebaa4759b4ece41160299fd17a751333392e73c8df355b7ff24b33f0"
    )


def test_c3_t002_all_23_stage5_requirements_are_revalidated() -> None:
    verdict = _load(ROOT, "evidence/part1-stage5-candidate-verdict-v1.json")
    results = verdict["requirement_results"]
    assert [row["requirement_id"] for row in results] == ALL_STAGE5_IDS
    assert all(row["candidate_result"] == "PASS" for row in results)
    assert verdict["summary"] == {
        "requirement_count": 23,
        "phase8_pass_preserved": 11,
        "c1_locally_addressed_revalidated": 2,
        "stage5_locally_addressed": 10,
        "candidate_pass": 23,
        "candidate_nonpass": 0,
    }
    assert verdict["phase8_baseline_immutable"] is True
    assert verdict["final_c7_audit_required"] is True


def test_c3_t003_direct_stage5_scope_is_exact() -> None:
    assert DIRECT_STAGE5_IDS == [
        "OP-S5-R001",
        "OP-S5-R002",
        "OP-S5-R009",
        "OP-S5-R014",
        "OP-S5-R015",
        "OP-S5-R016",
        "OP-S5-R017",
        "OP-S5-R019",
        "OP-S5-R020",
        "OP-S5-R021",
    ]


def test_c3_t004_document_contract_reason_target_scorecard_and_links_pass() -> None:
    contract_count, scenario_count, digest = _validate_authority(ROOT)
    assert contract_count == 9
    assert scenario_count == 21
    assert len(digest) == 64


def test_c3_t005_unknown_architecture_contract_fails_closed(tmp_path: Path) -> None:
    repository = _copy_repository(tmp_path)
    path = repository / "docs/architecture-v2.md"
    text = path.read_text(encoding="utf-8").replace(
        "journal-v2.schema.json", "journal-v3.schema.json", 1
    )
    path.write_text(text, encoding="utf-8")
    with pytest.raises(C3Error, match="OP-S5-R002"):
        _validate_authority(repository)


def test_c3_t006_unknown_reason_code_fails_closed(tmp_path: Path) -> None:
    repository = _copy_repository(tmp_path)
    _mutate_json(
        repository,
        "spec/part1-stage5-documentation-authority-v1.json",
        lambda value: value["failure_scenarios"][1]["reason_codes"].append("INVENTED_REASON"),
    )
    with pytest.raises(C3Error, match="OP-S5-R015"):
        _validate_authority(repository)


def test_c3_t007_wrong_documented_aws_region_fails_closed(tmp_path: Path) -> None:
    repository = _copy_repository(tmp_path)
    path = repository / "docs/architecture-v2.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace("ap-southeast-2", "us-east-1"),
        encoding="utf-8",
    )
    with pytest.raises(C3Error, match="OP-S5-R016"):
        _validate_authority(repository)


def test_c3_t008_scorecard_target_drift_fails_closed(tmp_path: Path) -> None:
    repository = _copy_repository(tmp_path)
    path = repository / "docs/scorecard-v2.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "| Financial correctness | 9.0 |", "| Financial correctness | 7.0 |"
        ),
        encoding="utf-8",
    )
    with pytest.raises(C3Error, match="OP-S5-R017"):
        _validate_authority(repository)


def test_c3_t009_broken_internal_link_fails_closed(tmp_path: Path) -> None:
    repository = _copy_repository(tmp_path)
    path = repository / "docs/stage5-gap-audit.md"
    path.write_text(
        path.read_text(encoding="utf-8") + "\n[missing](does-not-exist.md)\n",
        encoding="utf-8",
    )
    with pytest.raises(C3Error, match="Markdown link target missing"):
        _validate_authority(repository)


def test_c3_t010_managed_execution_claim_fails_closed(tmp_path: Path) -> None:
    repository = _copy_repository(tmp_path)
    path = repository / "README.md"
    path.write_text(
        path.read_text(encoding="utf-8") + "\nManaged reconciliation was executed.\n",
        encoding="utf-8",
    )
    with pytest.raises(C3Error, match="OP-S5-R020"):
        _validate_authority(repository)


def test_c3_t011_implementation_claim_fails_closed(tmp_path: Path) -> None:
    repository = _copy_repository(tmp_path)
    path = repository / "README.md"
    path.write_text(
        path.read_text(encoding="utf-8") + "\nReconciliation engine is implemented.\n",
        encoding="utf-8",
    )
    with pytest.raises(C3Error, match="OP-S5-R021"):
        _validate_authority(repository)


def test_c3_t012_missing_original_test_trace_fails_closed(tmp_path: Path) -> None:
    repository = _copy_repository(tmp_path)
    _mutate_json(
        repository,
        "spec/part1-requirement-ledger-v1.json",
        lambda value: value["requirements"][0].update({"test_paths": []}),
    )
    with pytest.raises(C3Error, match="OP-S5-R010"):
        _validate_authority(repository)


def test_c3_t013_candidate_verdict_baseline_rewrite_fails_closed(tmp_path: Path) -> None:
    repository = _copy_repository(tmp_path)
    _mutate_json(
        repository,
        "evidence/part1-stage5-candidate-verdict-v1.json",
        lambda value: value["requirement_results"][0].update({"baseline_verdict": "PASS"}),
    )
    with pytest.raises(C3Error, match="Stage 5 baseline differs"):
        _validate_authority(repository)


def test_c3_t014_validator_is_deterministic_and_blocks_part2() -> None:
    first = validate_stage5(ROOT, verify_evidence=False)
    second = validate_stage5(ROOT, verify_evidence=False)
    assert first == second
    assert first["state"] == "PART1_CORRECTION_IN_PROGRESS"
    assert first["part2_entry"] == "BLOCKED"
    assert first["implementation_remaining_count"] == 68
    assert first["stage5_candidate_pass_count"] == 23
    assert first["final_c7_audit_required"] is True
