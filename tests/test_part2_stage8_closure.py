from __future__ import annotations

import json
import runpy
import shutil
from pathlib import Path
from typing import Any, cast

import pytest

import ledgerguard_part2_stage8_closure as closure
from ledgerguard_part2_stage8_closure import Stage8ClosureError, validate_stage8_closure
from ledgerguard_part2_stage8_closure_evidence import run_closure_mutation_checks

ROOT = Path(__file__).resolve().parents[1]
IGNORED = shutil.ignore_patterns(".git", ".rsync-tmp", ".venv", "__pycache__", "*.egg-info")


def copy_repository(tmp_path: Path) -> Path:
    repository = tmp_path / "repository"
    shutil.copytree(ROOT, repository, ignore=IGNORED)
    return repository


def load(repository: Path, relative: str) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads((repository / relative).read_text(encoding="utf-8")))


def write(repository: Path, relative: str, value: object) -> None:
    (repository / relative).write_text(json.dumps(value), encoding="utf-8")


def test_p2s8_closure_authority_is_complete() -> None:
    result = validate_stage8_closure(ROOT)
    assert result["promotion"] == {
        "commit": "71b42d6622558093a2bfaced58724f2ab71e793e",
        "tree": "406f40dfb1e94e38031505e23a6d77b50198840f",
        "state": "PART2_STAGE8_PROMOTION_EXTERNALLY_VERIFIED",
    }
    assert result["requirements"] == 203
    assert result["stage_gates"] == 69
    assert set(result["master_part2_gates"].values()) == {"EXTERNALLY_VERIFIED"}
    assert result["part2_state"] == "LOCAL_RECONCILIATION_VERIFIED"
    assert result["part2_closed"] is True
    assert result["project_complete"] is False
    assert result["aws_execution"] is False


def test_p2s8_closure_module_entrypoint(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(ROOT)
    runpy.run_module("ledgerguard_part2_stage8_closure", run_name="__main__")
    assert json.loads(capsys.readouterr().out)["part2_closed"] is True


def test_p2s8_closure_mutants_are_killed() -> None:
    result = run_closure_mutation_checks(ROOT)
    assert result["checks"] == 12
    assert result["survivors"] == 0
    assert len(result["killed"]) == 12


def test_p2s8_closure_non_object_json_fails_closed(tmp_path: Path) -> None:
    repository = copy_repository(tmp_path)
    write(repository, "spec/part2-stage8-promotion-closure-freeze-v1.json", [])
    with pytest.raises(Stage8ClosureError, match="JSON object required"):
        validate_stage8_closure(repository)


def test_p2s8_closure_invalid_authority_row_fails_closed(tmp_path: Path) -> None:
    repository = copy_repository(tmp_path)
    relative = "spec/part2-stage8-promotion-closure-freeze-v1.json"
    value = load(repository, relative)
    value["protected_authorities"] = {1: 2}
    write(repository, relative, value)
    with pytest.raises(Stage8ClosureError, match="promotion authority inventory differs"):
        validate_stage8_closure(repository)


def test_p2s8_closure_missing_authority_fails_closed(tmp_path: Path) -> None:
    repository = copy_repository(tmp_path)
    relative = "spec/part2-stage8-promotion-closure-freeze-v1.json"
    value = load(repository, relative)
    protected = cast(dict[str, str], value["protected_authorities"])
    protected["spec/missing.json"] = protected.pop("contracts/part2-stage8-promotion-v1.json")
    write(repository, relative, value)
    with pytest.raises(Stage8ClosureError, match="promotion authority differs"):
        validate_stage8_closure(repository)


def test_p2s8_closure_missing_artifact_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        closure,
        "CLOSURE_ARTIFACTS",
        (*closure.CLOSURE_ARTIFACTS, "spec/missing.json"),
    )
    with pytest.raises(Stage8ClosureError, match="closure artifact missing"):
        validate_stage8_closure(ROOT)
