from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

import tools.validate_part3_stage6_operations as operations

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = json.loads((ROOT / "spec/part3-stage6-operation-manifest-v1.json").read_text())


def test_complete_stage6_operation_manifest_is_locally_verified() -> None:
    result = operations.validate(ROOT)
    assert result == {
        "classification": "STAGE6_OPERATION_MANIFEST_LOCALLY_VERIFIED",
        "controller_operations": 33,
        "role_probe_operations": 12,
        "terraform_provider_actions": 127,
        "athena_list_workgroups_deploy_allowed": True,
        "athena_list_workgroups_read_denied": True,
        "workload_start_denies": 5,
        "manifest_sha256": result["manifest_sha256"],
        "aws_calls": 0,
        "stage6_complete": False,
    }
    assert len(result["manifest_sha256"]) == 64


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda value: value.update(schema_version="wrong"), "schema"),
        (lambda value: value.update(classification="wrong"), "classification"),
        (lambda value: value.update(stage6_complete=True), "cannot complete"),
        (lambda value: value["controller_operations"].pop(), "reachable calls"),
        (
            lambda value: value["controller_operations"].append(
                copy.deepcopy(value["controller_operations"][0])
            ),
            "duplicated",
        ),
        (
            lambda value: value["controller_operations"][0].__setitem__(
                1, "athena:StartQueryExecution"
            ),
            "action mapping",
        ),
        (
            lambda value: value["controller_operations"][0].__setitem__(2, "WORKLOAD"),
            "mutation class",
        ),
        (
            lambda value: value["controller_operations"][0].__setitem__(3, ["unknown"]),
            "role scope",
        ),
        (lambda value: value["role_probe_operations"].pop(), "reachable calls"),
        (
            lambda value: value["role_probe_operations"][0].__setitem__(
                2, "athena:StartQueryExecution"
            ),
            "action mapping",
        ),
        (
            lambda value: value["role_probe_operations"][0].__setitem__(3, "WORKLOAD"),
            "mutation class",
        ),
        (
            lambda value: value["role_probe_operations"][0].__setitem__(4, ["unknown"]),
            "role scope",
        ),
        (
            lambda value: value["terraform_provider_authority"].update(
                mutating_capabilities_invoked=True
            ),
            "cannot invoke",
        ),
        (
            lambda value: value["policy_requirements"].update(
                deploy_only_inventory_resource="arn:aws:athena:ap-southeast-2:857229544428:workgroup/*"
            ),
            "policy scope",
        ),
        (
            lambda value: value["policy_requirements"].update(
                all_roles_must_deny_workload_start=["athena:UnreviewedAction"]
            ),
            "denial",
        ),
    ],
)
def test_manifest_security_mutations_fail_closed(mutation: object, message: str) -> None:
    changed = copy.deepcopy(MANIFEST)
    mutation(changed)  # type: ignore[operator]
    with pytest.raises(ValueError, match=message):
        operations.validate(ROOT, changed)


def test_reachable_call_and_adapter_drift_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        operations,
        "_controller_calls",
        lambda root: set(operations.EXPECTED_CONTROLLER_IAM) | {"UNREVIEWED"},
    )
    with pytest.raises(ValueError, match="reachable calls"):
        operations.validate(ROOT, copy.deepcopy(MANIFEST))

    monkeypatch.setattr(operations, "_controller_calls", lambda root: {"UNREVIEWED"})
    with pytest.raises(ValueError, match="reachable calls"):
        operations.validate(ROOT, copy.deepcopy(MANIFEST))


def test_role_probe_call_drift_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        operations,
        "_role_probe_calls",
        lambda root: (
            set(operations.EXPECTED_ROLE_PROBE_IAM) | {("athena", "start-query-execution")}
        ),
    )
    with pytest.raises(ValueError, match="reachable calls"):
        operations.validate(ROOT, copy.deepcopy(MANIFEST))


def test_manifest_rows_must_have_exact_shape() -> None:
    changed = copy.deepcopy(MANIFEST)
    changed["controller_operations"][0].pop()
    with pytest.raises(ValueError, match="rows invalid"):
        operations.validate(ROOT, changed)
    changed = copy.deepcopy(MANIFEST)
    changed["role_probe_operations"][0].pop()
    with pytest.raises(ValueError, match="rows invalid"):
        operations.validate(ROOT, changed)
