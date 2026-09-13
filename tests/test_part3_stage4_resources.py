from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from tools.part3_stage4.resources import evaluate, parse_module

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = json.loads((ROOT / "spec/part3-stage4-resource-controls-v1.json").read_text())


@pytest.fixture
def module() -> dict[str, Any]:
    return parse_module(ROOT / "infra/part3")


def test_actual_hcl_meets_reviewed_resource_controls(module: dict[str, Any]) -> None:
    report = evaluate(module, CONTRACT)
    assert report["controls_passed"] == 143
    assert report["managed_addresses"] == 33
    assert report["native_terraform_validation_required"] is True
    assert report["stage5_artifacts_required"] is True
    assert report["aws_execution"] is False


@pytest.mark.parametrize("rule", CONTRACT["rules"], ids=lambda r: r["id"])
def test_each_resource_control_rejects_changed_value(
    module: dict[str, Any], rule: dict[str, Any]
) -> None:
    value: Any = module
    for segment in rule["path"][:-1]:
        value = value[segment]
    value[rule["path"][-1]] = "UNAPPROVED_CONFIGURATION"
    with pytest.raises(ValueError, match=r"differs|input contract"):
        evaluate(module, CONTRACT)


@pytest.mark.parametrize("kind", ["resource", "variable"])
def test_unknown_or_missing_identity_rejected(module: dict[str, Any], kind: str) -> None:
    module[kind]["unapproved"] = {}
    with pytest.raises(ValueError, match="differs"):
        evaluate(module, CONTRACT)
    del module[kind]["unapproved"]
    module[kind].pop(next(iter(module[kind])))
    with pytest.raises(ValueError, match="differs"):
        evaluate(module, CONTRACT)


def test_required_release_cannot_gain_default(module: dict[str, Any]) -> None:
    module["variable"]["stage5_release"]["default"] = {}
    with pytest.raises(ValueError, match="default"):
        evaluate(module, CONTRACT)


@pytest.mark.parametrize("attribute", ["provisioner", "connection", "lifecycle", "replication"])
def test_hidden_effect_or_unreviewed_attribute_rejected(
    module: dict[str, Any], attribute: str
) -> None:
    module["resource"]["aws_s3_bucket.workload"][attribute] = {}
    with pytest.raises(ValueError, match=r"side effect|attribute set"):
        evaluate(module, CONTRACT)


def test_duplicate_and_missing_control_rejected(module: dict[str, Any]) -> None:
    changed = deepcopy(CONTRACT)
    changed["rules"].append(changed["rules"][0])
    with pytest.raises(ValueError, match="duplicate resource control"):
        evaluate(module, changed)
    for missing_path in [["locals", "absent"], ["terraform", 100], ["locals", "name", "nested"]]:
        changed = deepcopy(CONTRACT)
        changed["rules"][0]["path"] = missing_path
        with pytest.raises(ValueError, match="missing resource control"):
            evaluate(module, changed)


def test_numeric_one_is_not_boolean_true(module: dict[str, Any]) -> None:
    module["resource"]["aws_s3_bucket_public_access_block.workload"]["block_public_acls"] = 1
    with pytest.raises(ValueError, match="block_public_acls"):
        evaluate(module, CONTRACT)


def test_empty_module_or_json_override_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="missing HCL"):
        parse_module(tmp_path)
    (tmp_path / "main.tf").write_text('locals { name = "approved" }')
    (tmp_path / "override.tf.json").write_text("{}")
    with pytest.raises(ValueError, match="unadmitted JSON"):
        parse_module(tmp_path)


def test_real_hcl_side_channels_and_duplicate_names_rejected(tmp_path: Path) -> None:
    first, second = tmp_path / "first.tf", tmp_path / "second.tf"
    first.write_text('locals { x = "one" }')
    second.write_text('locals { x = "two" }')
    with pytest.raises(ValueError, match="duplicate configuration"):
        parse_module(tmp_path)
    second.write_text('module "hidden" { source = "./elsewhere" }')
    with pytest.raises(ValueError, match="unadmitted configuration block"):
        parse_module(tmp_path)
    second.unlink()
    second.symlink_to(first)
    with pytest.raises(ValueError, match="symlink"):
        parse_module(tmp_path)


@pytest.mark.parametrize("replacement", ["number_of_workers = 20", "number_of_workers = 1"])
def test_worker_limit_mutation_in_actual_hcl_fails(tmp_path: Path, replacement: str) -> None:
    for source in (ROOT / "infra/part3").glob("*.tf"):
        raw = source.read_text()
        if source.name == "compute.tf":
            import re

            raw, count = re.subn(r"number_of_workers\s*=\s*2", replacement, raw)
            assert count == 1
        (tmp_path / source.name).write_text(raw)
    with pytest.raises(ValueError, match="number_of_workers"):
        evaluate(parse_module(tmp_path), CONTRACT)


def test_traceability_preserves_all_master_obligations_and_resolves_local_references() -> None:
    master = json.loads((ROOT / "spec/part3-requirements-v1.json").read_text())["requirements"]
    trace = json.loads((ROOT / "spec/part3-stage4-traceability-v1.json").read_text())
    assert len(trace["master_rows"]) == trace["master_count"] == len(master) == 99
    actual = {r["requirement_id"]: r for r in trace["master_rows"]}
    assert len(actual) == 99
    rule_ids = {r["id"] for r in CONTRACT["rules"]}
    owned = 0
    for original in master:
        row = actual[original["requirement_id"]]
        for field in ("normative_statement", "owner_stage", "allowed_claim"):
            assert row[field] == original[field]
        assert set(row["resource_controls"]) <= rule_ids
        for name in row["evidence"]:
            assert (ROOT / name).is_file(), name
        if row["owner_stage"] == 4:
            owned += 1
            assert row["current_stage4_claim"] == "SOURCE_AND_LOCAL_CONTROLS_ONLY_AWS_PROOF_PENDING"
            assert row["remaining"]
    assert owned == trace["stage4_master_count"] == 35
    assert len({r["id"] for r in trace["additive"]}) == len(trace["additive"]) == 13
    for row in trace["additive"]:
        for name in row["evidence"]:
            assert (ROOT / name).is_file(), name
    assert trace["stage4_complete"] is False and trace["part3_complete"] is False
