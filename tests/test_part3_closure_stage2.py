from __future__ import annotations

import json
import runpy
import shutil
from pathlib import Path
from typing import Any, cast

import pytest

from ledgerguard_part3_stage2_closure import Stage2ClosureError, validate_stage2_closure
from ledgerguard_part3_stage2_closure_evidence import run_closure_mutation_checks

ROOT = Path(__file__).resolve().parents[1]
IGNORED = shutil.ignore_patterns(".git", ".venv", "__pycache__", "*.egg-info")


def copy_repository(tmp_path: Path) -> Path:
    repository = tmp_path / "repository"
    shutil.copytree(ROOT, repository, ignore=IGNORED)
    return repository


def load(repository: Path, relative: str) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads((repository / relative).read_text(encoding="utf-8")))


def write(repository: Path, relative: str, value: object) -> None:
    (repository / relative).write_text(json.dumps(value), encoding="utf-8")


def test_stage2_closure_candidate_is_complete_and_bounded() -> None:
    result = validate_stage2_closure(ROOT)
    assert result == {
        "qualified_commit": "aa136331e44dcd181f766b42d76ee2616a22f435",
        "qualified_tree": "184d8d7ff8d1172ec863060d4be7132339eaba49",
        "read_only_run": 34337121587,
        "capability_run": 34337699794,
        "requirements_verified": 22,
        "stage2_gates_verified": 19,
        "stage2_gate_pending_external": "P3-S2-G020",
        "master_gates_verified": 3,
        "next_owner": "PART3_STAGE3",
        "closure_candidate_digest": result["closure_candidate_digest"],
        "aws_api_called": False,
        "managed_reconciliation_started": False,
        "part3_complete": False,
        "project_complete": False,
    }
    assert len(result["closure_candidate_digest"]) == 64


def test_stage2_closure_module_entrypoint(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(ROOT)
    runpy.run_module("ledgerguard_part3_stage2_closure", run_name="__main__")
    assert json.loads(capsys.readouterr().out)["stage2_gate_pending_external"] == "P3-S2-G020"


def test_stage2_closure_semantic_mutants_are_all_killed() -> None:
    result = run_closure_mutation_checks(ROOT)
    assert result["checks"] == 13
    assert result["survivors"] == 0
    assert len(result["killed"]) == 13


def test_non_object_json_fails_closed(tmp_path: Path) -> None:
    repository = copy_repository(tmp_path)
    write(repository, "spec/part3-stage2-operational-freeze-v1.json", [])
    with pytest.raises(Stage2ClosureError, match="JSON object required"):
        validate_stage2_closure(repository)


def test_invalid_freeze_row_fails_closed(tmp_path: Path) -> None:
    repository = copy_repository(tmp_path)
    relative = "spec/part3-stage2-operational-freeze-v1.json"
    value = load(repository, relative)
    files = cast(dict[str, str], value["operational_sha256"])
    first = next(iter(files))
    files[first] = cast(Any, 7)
    write(repository, relative, value)
    with pytest.raises(Stage2ClosureError, match="invalid freeze row"):
        validate_stage2_closure(repository)


def test_missing_frozen_operational_file_fails_closed(tmp_path: Path) -> None:
    repository = copy_repository(tmp_path)
    (repository / ".github/workflows/part3-stage2-read-only.yml").unlink()
    with pytest.raises(Stage2ClosureError, match="frozen operational file missing"):
        validate_stage2_closure(repository)


def test_malformed_capability_cases_fail_closed(tmp_path: Path) -> None:
    repository = copy_repository(tmp_path)
    relative = "evidence/part3-stage2/capability-receipt-v1.json"
    value = load(repository, relative)
    value["cases"] = {}
    write(repository, relative, value)
    with pytest.raises(Stage2ClosureError, match="capability case count differs"):
        validate_stage2_closure(repository)


def test_missing_publication_transactions_fail_closed(tmp_path: Path) -> None:
    repository = copy_repository(tmp_path)
    relative = "evidence/part3-stage2/implementation-publication-receipt-v1.json"
    value = load(repository, relative)
    value["transactions"] = None
    write(repository, relative, value)
    with pytest.raises(Stage2ClosureError, match="publication transactions missing"):
        validate_stage2_closure(repository)


def test_missing_closure_file_fails_closed(tmp_path: Path) -> None:
    repository = copy_repository(tmp_path)
    relative = "spec/part3-stage2-closure-coverage-v1.json"
    (repository / relative).unlink()
    with pytest.raises(Stage2ClosureError, match="closure file missing"):
        validate_stage2_closure(repository)
