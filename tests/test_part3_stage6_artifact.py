from __future__ import annotations

import copy
import zipfile
from pathlib import Path
from typing import Any

import pytest

from tools.part3_stage6.artifact import _array, build_artifact, inspect_artifact, validate_evidence


def evidence() -> dict[str, Any]:
    return {
        "schema_version": "ledgerguard.part3-stage6-plan-only-evidence.v1",
        "source": {
            "commit": "a" * 40,
            "tree": "b" * 40,
            "ref": "refs/heads/main",
            "event": "workflow_dispatch",
            "workflow_run_id": "123",
            "workflow_run_attempt": "1",
        },
        "target": {"account": "857229544428", "region": "ap-southeast-2"},
        "bindings": {
            "administrator_packet_sha256": "5" * 64,
            "administrator_receipt_sha256": "6" * 64,
            "stage5_runtime_package_sha256": "7" * 64,
            "stage5_manifest_sha256": "8" * 64,
            "stage5_script_sha256": "9" * 64,
            "stage5_wheels_sha256": "a" * 64,
            "lock_sha256": {
                "terraform": "b" * 64,
                "bootstrap": "c" * 64,
                "python311": "d" * 64,
                "parser": "e" * 64,
            },
        },
        "toolchain": {"terraform": "1.13.1", "aws_provider": "6.11.0"},
        "backend": {"state_key_sha256": "f" * 64, "state_absent_before_and_after": True},
        "budget": {
            "billing_observed_epoch": 1_800_000_000,
            "billing_classification": "COST_EXPLORER_DELAYED_WITH_CONSERVATIVE_RESERVE",
            "known_gross_usd": "1.00",
            "reserved_stage6_exposure_usd": "0.05",
            "cleanup_reserve_usd": "1.00",
            "strict_ceiling_usd": "10",
            "estimated_monthly_standing_usd": "0.00",
            "assumptions": [
                "plan-only; no managed resources created",
                "provider control-plane reads only",
                "no reconciliation, Glue, Athena, Step Functions or Lambda workload",
            ],
        },
        "gates": {"S6-G01": True, "S6-G02": True, "S6-G03": True, "S6-G04": False},
        "plan": {
            "binary_sha256": "1" * 64,
            "json_sha256": "2" * 64,
            "variable_sha256": "3" * 64,
            "policy_sha256": "4" * 64,
            "resource_changes": 33,
            "create_actions": 33,
            "other_actions": 0,
            "applied": False,
        },
        "preflight": {
            name: True
            for name in (
                "exact_identity",
                "installed_iam",
                "effective_permissions",
                "restrictions_resolved",
                "backend_admitted",
                "lease_acquired",
                "budget_admitted",
                "quota_admitted",
                "inventory_clean",
            )
        },
        "closure": {
            "apply_calls": 0,
            "workload_calls": 0,
            "post_inventory_clean": True,
            "lease_released": True,
            "backend_lock_absent": True,
            "recovery_required": False,
            "stage6_complete": False,
            "terminal_state": "awaiting_independent_inspection",
        },
    }


def journal() -> list[dict[str, Any]]:
    return [
        {
            "operation": "terraform_show",
            "command": ["terraform", "show", "-json", "private-plan"],
            "exit_code": 0,
        }
    ]


def test_detailed_exit_code_two_is_only_valid_for_saved_plan() -> None:
    value = evidence()
    rows = journal()
    rows.append({"operation": "terraform-plan", "command": ["terraform", "plan"], "exit_code": 2})
    validate_evidence(value, rows)
    rows[-1]["operation"] = "terraform-show"
    with pytest.raises(ValueError, match="unsuccessful"):
        validate_evidence(value, rows)


def test_build_and_independently_inspect(tmp_path: Path) -> None:
    artifact = tmp_path / "stage6.zip"
    digest = build_artifact(artifact, evidence(), journal())
    first = inspect_artifact(artifact)
    second = inspect_artifact(artifact)
    assert first == second
    assert first["artifact_sha256"] == digest
    assert first["terminal_state"] == "plan_only_verified"
    assert first["stage6_complete"] is True
    with zipfile.ZipFile(artifact) as archive:
        assert set(archive.namelist()) == {"evidence.json", "command-journal.json", "manifest.json"}


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        (("schema_version",), "v2", "schema"),
        (("source", "commit"), "x", "commit"),
        (("source", "tree"), "x", "tree"),
        (("source", "ref"), "refs/pull/1/head", "event boundary"),
        (("source", "workflow_run_id"), "", "run identity"),
        (("source", "workflow_run_attempt"), "0", "run attempt"),
        (("target", "region"), "us-east-1", "target"),
        (("bindings", "administrator_packet_sha256"), "x", "binding invalid"),
        (("toolchain", "terraform"), "1.12.0", "toolchain"),
        (("backend", "state_absent_before_and_after"), False, "backend evidence"),
        (("budget", "strict_ceiling_usd"), "1", "ceiling"),
        (("budget", "estimated_monthly_standing_usd"), "0.01", "classification"),
        (("gates", "S6-G04"), None, "self-admit"),
        (("gates", "S6-G04"), True, "self-admit"),
        (("gates", "S6-G02"), False, "incomplete"),
        (("plan", "binary_sha256"), "x", "digest"),
        (("plan", "resource_changes"), 32, "graph"),
        (("plan", "other_actions"), 1, "non-create"),
        (("preflight", "budget_admitted"), False, "preflight"),
        (("closure", "lease_released"), False, "closure"),
    ],
)
def test_evidence_mutation_fails(path: tuple[str, ...], value: Any, message: str) -> None:
    changed = copy.deepcopy(evidence())
    target = changed
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(ValueError, match=message):
        validate_evidence(changed, journal())


@pytest.mark.parametrize(
    "row",
    [
        None,
        {"operation": "terraform", "command": "terraform show", "exit_code": 0},
        {"operation": "terraform", "command": ["terraform", "apply"], "exit_code": 0},
        {"operation": "StartJobRun", "command": ["aws", "glue"], "exit_code": 0},
        {"operation": "read", "command": ["aws", "sts"], "exit_code": 1},
    ],
)
def test_journal_mutation_fails(row: Any) -> None:
    with pytest.raises(ValueError):
        validate_evidence(evidence(), [row])


def rewrite_member(source: Path, target: Path, name: str, data: bytes) -> None:
    with zipfile.ZipFile(source) as old, zipfile.ZipFile(target, "w") as new:
        for info in old.infolist():
            new.writestr(info.filename, data if info.filename == name else old.read(info.filename))


def test_manifest_tampering_and_existing_output_fail(tmp_path: Path) -> None:
    artifact = tmp_path / "stage6.zip"
    build_artifact(artifact, evidence(), journal())
    with pytest.raises(ValueError, match="already exists"):
        build_artifact(artifact, evidence(), journal())
    changed = tmp_path / "changed.zip"
    rewrite_member(artifact, changed, "evidence.json", b"{}\n")
    with pytest.raises(ValueError, match="manifest binding"):
        inspect_artifact(changed)


def test_artifact_inventory_and_file_type_fail(tmp_path: Path) -> None:
    missing = tmp_path / "missing.zip"
    with zipfile.ZipFile(missing, "w") as archive:
        archive.writestr("evidence.json", "{}")
    with pytest.raises(ValueError, match="inventory"):
        inspect_artifact(missing)
    directory = tmp_path / "directory"
    directory.mkdir()
    with pytest.raises(ValueError, match="regular"):
        inspect_artifact(directory)


def test_non_array_journal_fails() -> None:
    with pytest.raises(ValueError, match="array"):
        _array({}, "journal")


def test_gate_inventory_must_be_exact() -> None:
    changed = evidence()
    changed["gates"].pop("S6-G04")
    with pytest.raises(ValueError, match="gate inventory"):
        validate_evidence(changed, journal())


def test_binding_and_budget_inventories_are_exact() -> None:
    changed = evidence()
    changed["bindings"]["extra"] = "0" * 64
    with pytest.raises(ValueError, match="binding inventory"):
        validate_evidence(changed, journal())
    changed = evidence()
    changed["bindings"]["lock_sha256"].pop("parser")
    with pytest.raises(ValueError, match="lock binding"):
        validate_evidence(changed, journal())
    changed = evidence()
    changed["budget"]["known_gross_usd"] = "not-a-number"
    with pytest.raises(ValueError, match="amount"):
        validate_evidence(changed, journal())
    changed = evidence()
    changed["budget"]["known_gross_usd"] = "8.95"
    with pytest.raises(ValueError, match="ceiling"):
        validate_evidence(changed, journal())


@pytest.mark.parametrize(
    ("member", "message"),
    [("../evidence.json", "unsafe"), ("terraform.tfplan", "sensitive")],
)
def test_unsafe_member_fails(tmp_path: Path, member: str, message: str) -> None:
    artifact = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(artifact, "w") as archive:
        archive.writestr(member, "x")
    with pytest.raises(ValueError, match=message):
        inspect_artifact(artifact)


def test_manifest_schema_and_inventory_fail(tmp_path: Path) -> None:
    artifact = tmp_path / "stage6.zip"
    build_artifact(artifact, evidence(), journal())
    wrong_schema = tmp_path / "wrong-schema.zip"
    rewrite_member(artifact, wrong_schema, "manifest.json", b'{"schema_version":"v2"}\n')
    with pytest.raises(ValueError, match="manifest schema"):
        inspect_artifact(wrong_schema)
    wrong_inventory = tmp_path / "wrong-inventory.zip"
    rewrite_member(
        artifact,
        wrong_inventory,
        "manifest.json",
        b'{"schema_version":"ledgerguard.part3-stage6-artifact-manifest.v1","members":{}}\n',
    )
    with pytest.raises(ValueError, match="manifest member inventory"):
        inspect_artifact(wrong_inventory)
