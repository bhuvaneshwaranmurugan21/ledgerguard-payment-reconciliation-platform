from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import tools.part3_stage6.controller as controller
from tools.part3_stage6.artifact import inspect_artifact


def test_controller_requires_all_layers_and_leaves_independent_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    def admitted(name: str, result: dict[str, Any]):
        def run(*args: Any, **kwargs: Any) -> dict[str, Any]:
            calls.append(name)
            return result

        return run

    monkeypatch.setattr(
        controller,
        "validate_administrator_receipt",
        admitted("admin", {"private_packet_sha256": "4" * 64}),
    )
    monkeypatch.setattr(controller, "validate_preflight", admitted("preflight", {}))
    monkeypatch.setattr(controller, "expected_addresses", lambda root: [])
    monkeypatch.setattr(
        controller,
        "validate_saved_plan",
        admitted(
            "structural",
            {
                "plan_json_sha256": controller._sha({}),
                "resource_changes": 33,
                "create_actions": 33,
                "other_actions": 0,
            },
        ),
    )
    monkeypatch.setattr(controller, "validate_relationships", admitted("relationships", {}))
    monkeypatch.setattr(controller, "validate_properties", admitted("properties", {}))
    monkeypatch.setattr(controller, "parse_module", lambda root: {})
    monkeypatch.setattr(controller, "runtime_policies", lambda *args, **kwargs: {})
    monkeypatch.setattr(
        controller,
        "_source_bindings",
        lambda *args: {
            "administrator_packet_sha256": "4" * 64,
            "administrator_receipt_sha256": "5" * 64,
            "stage5_runtime_package_sha256": "6" * 64,
            "stage5_manifest_sha256": "7" * 64,
            "stage5_script_sha256": "8" * 64,
            "stage5_wheels_sha256": "9" * 64,
            "lock_sha256": {
                name: "a" * 64 for name in ("terraform", "bootstrap", "python311", "parser")
            },
        },
    )
    (tmp_path / "spec").mkdir()
    (tmp_path / "spec/part3-stage4-catalog-v1.json").write_text('{"tables":{}}')
    monkeypatch.setattr(
        controller,
        "validate_closure",
        admitted(
            "closure",
            {
                "apply_calls": 0,
                "workload_calls": 0,
                "post_inventory_clean": True,
                "lease_released": True,
                "backend_lock_absent": True,
                "recovery_required": False,
            },
        ),
    )
    admin = {"receipt": True}
    journal = [{"operation": "terraform-plan", "command": ["terraform", "plan"], "exit_code": 2}]
    output = tmp_path / "artifact.zip"
    result = controller.adjudicate_plan_only(
        root=tmp_path,
        source_commit="a" * 40,
        source_tree="b" * 40,
        administrator_receipt=admin,
        administrator_packet_sha256="4" * 64,
        administrator_receipt_sha256=controller._sha(admin),
        preflight={
            "completed_epoch": 1_800_000_000,
            "budget": {
                "known_gross_usd": "1",
                "reserved_stage6_exposure_usd": "0.05",
                "cleanup_reserve_usd": "1",
                "strict_ceiling_usd": "10",
            },
        },
        plan={},
        plan_digests={
            "binary_sha256": "1" * 64,
            "json_sha256": "2" * 64,
            "variable_sha256": "3" * 64,
        },
        stage5_release={"script_key": "script", "wheels_key": "wheels"},
        operation_id="release-qual1",
        expires_at="2026-09-16T00:00:00Z",
        postflight={},
        journal=journal,
        now_epoch=1_800_000_000,
        workflow_run_id="123",
        workflow_run_attempt="1",
        output=output,
    )
    assert calls == ["admin", "preflight", "structural", "relationships", "properties", "closure"]
    assert result["producer_gates"] == 3
    assert result["S6-G04"] is False
    verdict = inspect_artifact(output)
    assert verdict["S6-G04"] is True
    assert verdict["terminal_state"] == "plan_only_verified"


def test_controller_rejects_receipt_and_plan_digest_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(controller, "validate_administrator_receipt", lambda *args, **kwargs: {})
    with pytest.raises(ValueError, match="byte binding"):
        controller.adjudicate_plan_only(
            root=tmp_path,
            source_commit="a" * 40,
            source_tree="b" * 40,
            administrator_receipt={},
            administrator_packet_sha256="4" * 64,
            administrator_receipt_sha256="0" * 64,
            preflight={},
            plan={},
            plan_digests={},
            stage5_release={},
            operation_id="release-qual1",
            expires_at="2026-09-16T00:00:00Z",
            postflight={},
            journal=[],
            now_epoch=0,
            workflow_run_id="123",
            workflow_run_attempt="1",
            output=tmp_path / "artifact.zip",
        )


def test_controller_rejects_private_packet_binding_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    admin = {"receipt": True}
    monkeypatch.setattr(
        controller,
        "validate_administrator_receipt",
        lambda *args, **kwargs: {"private_packet_sha256": "9" * 64},
    )
    with pytest.raises(ValueError, match="private packet binding"):
        controller.adjudicate_plan_only(
            root=tmp_path,
            source_commit="a" * 40,
            source_tree="b" * 40,
            administrator_receipt=admin,
            administrator_packet_sha256="4" * 64,
            administrator_receipt_sha256=controller._sha(admin),
            preflight={},
            plan={},
            plan_digests={},
            stage5_release={},
            operation_id="release-qual1",
            expires_at="2026-09-16T00:00:00Z",
            postflight={},
            journal=[],
            now_epoch=0,
            workflow_run_id="123",
            workflow_run_attempt="1",
            output=tmp_path / "artifact.zip",
        )


def test_controller_rejects_internal_plan_and_digest_inventory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        controller,
        "validate_administrator_receipt",
        lambda *args, **kwargs: {"private_packet_sha256": "4" * 64},
    )
    monkeypatch.setattr(controller, "validate_preflight", lambda *args, **kwargs: {})
    monkeypatch.setattr(controller, "expected_addresses", lambda root: [])
    monkeypatch.setattr(controller, "validate_relationships", lambda value: {})
    monkeypatch.setattr(controller, "validate_properties", lambda *args, **kwargs: {})
    monkeypatch.setattr(controller, "validate_closure", lambda *args, **kwargs: {})
    monkeypatch.setattr(controller, "parse_module", lambda root: {})
    monkeypatch.setattr(controller, "runtime_policies", lambda *args, **kwargs: {})
    (tmp_path / "spec").mkdir()
    (tmp_path / "spec/part3-stage4-catalog-v1.json").write_text('{"tables":{}}')
    admin: dict[str, object] = {}
    common = dict(
        root=tmp_path,
        source_commit="a" * 40,
        source_tree="b" * 40,
        administrator_receipt=admin,
        administrator_packet_sha256="4" * 64,
        administrator_receipt_sha256=controller._sha(admin),
        preflight={},
        plan={},
        stage5_release={"script_key": "script", "wheels_key": "wheels"},
        operation_id="release-qual1",
        expires_at="2026-09-16T00:00:00Z",
        postflight={},
        journal=[],
        now_epoch=0,
        workflow_run_id="123",
        workflow_run_attempt="1",
    )
    monkeypatch.setattr(
        controller, "validate_saved_plan", lambda *args: {"plan_json_sha256": "0" * 64}
    )
    with pytest.raises(AssertionError, match="canonical plan"):
        controller.adjudicate_plan_only(**common, plan_digests={}, output=tmp_path / "one.zip")
    monkeypatch.setattr(
        controller,
        "validate_saved_plan",
        lambda *args: {
            "plan_json_sha256": controller._sha({}),
            "resource_changes": 33,
            "create_actions": 33,
            "other_actions": 0,
        },
    )
    with pytest.raises(ValueError, match="digest inventory"):
        controller.adjudicate_plan_only(
            **common, plan_digests={"binary_sha256": 1}, output=tmp_path / "two.zip"
        )


def test_source_bindings_hash_every_required_lock(tmp_path: Path) -> None:
    paths = (
        "infra/part3/.terraform.lock.hcl",
        "requirements/part3-stage3-bootstrap.lock",
        "requirements/part3-stage3-py311.lock",
        "requirements/part3-stage4-parser.lock",
    )
    for index, relative in enumerate(paths):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"lock-{index}".encode())
    release = {
        "runtime_package_sha256": "1" * 64,
        "manifest_sha256": "2" * 64,
        "script_sha256": "3" * 64,
        "wheels_sha256": "4" * 64,
    }
    result = controller._source_bindings(tmp_path, release, "5" * 64, "6" * 64)
    assert set(result["lock_sha256"]) == {"terraform", "bootstrap", "python311", "parser"}
    assert result["lock_sha256"]["terraform"] == controller._file_sha(tmp_path / paths[0])
