from __future__ import annotations

import copy
import json
import runpy
import sys
from pathlib import Path
from typing import Any

import pytest

import tools.validate_part3_stage6_preparation as preparation
from tools.validate_part3_stage6_preparation import load_json, validate

ROOT = Path(__file__).resolve().parents[1]
FREEZE = json.loads((ROOT / "spec/part3-stage6-preparation-v1.json").read_text())


def test_exact_stage6_preparation_freeze_is_locally_valid() -> None:
    result = validate(ROOT)
    assert result == {
        "classification": "STAGE6_PRE_EXECUTION_INPUTS_LOCALLY_VERIFIED",
        "requirements": 3,
        "gates": 4,
        "managed_addresses": 33,
        "open_dependencies": sorted(FREEZE["pre_execution_dependencies"]),
        "aws_calls": 0,
        "stage6_complete": False,
    }


def test_main_emits_the_local_classification(capsys: pytest.CaptureFixture[str]) -> None:
    preparation.main()
    output = json.loads(capsys.readouterr().out)
    assert output["classification"] == "STAGE6_PRE_EXECUTION_INPUTS_LOCALLY_VERIFIED"


def test_module_entry_point_emits_the_local_classification(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delitem(sys.modules, "tools.validate_part3_stage6_preparation")
    runpy.run_module("tools.validate_part3_stage6_preparation", run_name="__main__")
    output = json.loads(capsys.readouterr().out)
    assert output["stage6_complete"] is False


def test_json_authority_must_be_an_object(tmp_path: Path) -> None:
    path = tmp_path / "array.json"
    path.write_text("[]")
    with pytest.raises(ValueError, match="object required"):
        load_json(path)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("classification",), "AWS_VERIFIED"),
        (("schema_version",), "ledgerguard.part3.stage6-preparation.v2"),
        (("accepted_stage5", "main_commit"), "0" * 40),
        (("accepted_stage5", "tree"), "0" * 40),
        (("accepted_stage5", "definition_sha256"), "0" * 64),
        (("accepted_stage5", "definition_sha256"), 3),
        (("accepted_stage5", "exact_main_definition_validation"), "FAIL"),
        (("requirements",), ["P3-M-L282-01"]),
        (("gates",), ["S6-G01"]),
        (("target", "account"), "000000000000"),
        (("target", "region"), "us-east-1"),
        (("target", "managed_address_count"), 32),
        (("target", "resource_inventory_sha256"), "0" * 64),
        (("target", "sorted_address_inventory_sha256"), "0" * 64),
        (("toolchain", "python"), "3.12.14"),
        (("toolchain", "terraform"), "latest"),
        (("toolchain", "parser_lock_sha256"), "0" * 64),
        (("toolchain", "parser_lock_path"), "requirements/absent.lock"),
        (("hard_invariants", "gross_project_cost_strictly_below_usd"), 11),
        (("hard_invariants", "plan_only"), False),
        (("hard_invariants", "exact_create_actions"), 34),
        (("hard_invariants", "allowed_plan_actions"), ["create", "update"]),
        (("hard_invariants", "executor_iam_mutation"), True),
        (("hard_invariants", "raw_plan_publication"), True),
        (("hard_invariants", "prohibited_workloads"), []),
        (("workflow_boundary", "trigger"), "pull_request"),
        (("workflow_boundary", "eligible_ref"), "refs/pull/1/head"),
        (("workflow_boundary", "cancel_in_progress"), True),
        (("workflow_boundary", "stale_ttl_proves_runner_stopped"), True),
        (("closure", "terminal_state"), "deployed"),
        (("closure", "requires_no_apply_proof"), False),
        (("closure", "stage6_complete"), True),
    ],
)
def test_security_critical_freeze_mutations_fail(path: tuple[str, ...], value: object) -> None:
    changed = copy.deepcopy(FREEZE)
    target = changed
    for name in path[:-1]:
        target = target[name]
    target[path[-1]] = value
    with pytest.raises(ValueError):
        validate(ROOT, changed)


@pytest.mark.parametrize("name", list(FREEZE["pre_execution_dependencies"]))
def test_no_open_dependency_can_be_claimed_by_source_preparation(name: str) -> None:
    changed = copy.deepcopy(FREEZE)
    changed["pre_execution_dependencies"][name] = True
    with pytest.raises(ValueError, match="dependencies"):
        validate(ROOT, changed)


@pytest.mark.parametrize("name", FREEZE["hard_invariants"]["prohibited_terraform"])
def test_every_terraform_prohibition_is_required(name: str) -> None:
    changed = copy.deepcopy(FREEZE)
    changed["hard_invariants"]["prohibited_terraform"].remove(name)
    with pytest.raises(ValueError, match="prohibition"):
        validate(ROOT, changed)


def test_master_requirement_drift_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    original = preparation.load_json

    def changed_load(path: Path) -> dict[str, Any]:
        value = original(path)
        if path.name == "part3-requirements-v1.json":
            value = copy.deepcopy(value)
            value["requirements"] = [
                row for row in value["requirements"] if row["requirement_id"] != "P3-M-L283-02"
            ]
        return value

    monkeypatch.setattr(preparation, "load_json", changed_load)
    with pytest.raises(ValueError, match="ownership"):
        validate(ROOT, copy.deepcopy(FREEZE))


def test_duplicate_inventory_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    original = preparation.load_json

    def changed_load(path: Path) -> dict[str, Any]:
        value = original(path)
        if path.name == "part3-stage4-resource-inventory-v1.json":
            value = copy.deepcopy(value)
            value["members"][-1] = copy.deepcopy(value["members"][0])
        return value

    monkeypatch.setattr(preparation, "load_json", changed_load)
    with pytest.raises(ValueError, match="duplicate"):
        validate(ROOT, copy.deepcopy(FREEZE))


def test_missing_parser_package_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    original = Path.read_text

    def changed_read(path: Path, *args: object, **kwargs: object) -> str:
        value = original(path, *args, **kwargs)
        if path.name == "part3-stage4-parser.lock":
            return value.replace("regex==2025.9.1", "regex==0")
        return value

    monkeypatch.setattr(Path, "read_text", changed_read)
    with pytest.raises(ValueError, match="parser package"):
        validate(ROOT, copy.deepcopy(FREEZE))
