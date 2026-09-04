from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from ledgerguard_part2_stage7_evidence import run_mutation_checks
from ledgerguard_part2_stage7_validation import Stage7Error, validate_stage7

ROOT = Path(__file__).resolve().parents[1]


def test_p2s7_repository_contract_is_complete() -> None:
    result = validate_stage7(ROOT)
    assert result["failure_matrix"] == {"scenarios": 21, "reason_codes": 21}
    assert result["critical_paths"] == 8
    assert result["aws_execution"] is False
    assert run_mutation_checks(ROOT)["survivors"] == 0


def test_p2s7_missing_failure_scenario_fails_closed(tmp_path: Path) -> None:
    shutil.copytree(
        ROOT, tmp_path / "repo", ignore=shutil.ignore_patterns(".git", ".venv", "__pycache__")
    )
    path = tmp_path / "repo/spec/part2-stage7-failure-matrix-v1.json"
    value = json.loads(path.read_text())
    value["scenario_tests"].pop("Worker fails before finalization")
    path.write_text(json.dumps(value))
    with pytest.raises(Stage7Error, match="failure scenario matrix differs"):
        validate_stage7(tmp_path / "repo")
