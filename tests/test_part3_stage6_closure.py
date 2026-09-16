from __future__ import annotations

import pytest

from tools.part3_stage6.closure import EXPECTED_TERRAFORM_OPERATIONS, validate_closure


def postflight() -> dict[str, object]:
    return {
        "schema_version": "ledgerguard.part3-stage6-postflight.v1",
        "plan_applied": False,
        "apply_calls": 0,
        "workload_calls": 0,
        "resource_create_update_delete_calls": 0,
        "exact_state_absent": True,
        "backend_lock_absent": True,
        "lease_release_condition_matched": True,
        "lease_owner_absent_after_release": True,
        "inventory_pagination_complete": True,
        "expected_operation_resources": 0,
        "other_ledgerguard_workload_resources": 0,
        "active_glue_runs": 0,
        "active_athena_queries": 0,
        "active_state_machine_executions": 0,
        "recovery_required": False,
    }


def journal() -> list[dict[str, object]]:
    return [
        {
            "operation": operation,
            "command": ["terraform", operation.removeprefix("terraform-")],
            "exit_code": 2 if operation == "terraform-plan" else 0,
        }
        for operation in EXPECTED_TERRAFORM_OPERATIONS
    ]


def test_exact_zero_mutation_closure_passes() -> None:
    result = validate_closure(postflight(), journal())
    assert result["classification"] == "S6_G03_ZERO_MUTATION_CLOSURE_ADMITTED"
    assert result["lease_released"] is True
    assert result["stage6_complete"] is False


@pytest.mark.parametrize(
    "field",
    [
        "plan_applied",
        "apply_calls",
        "workload_calls",
        "resource_create_update_delete_calls",
        "exact_state_absent",
        "backend_lock_absent",
        "lease_release_condition_matched",
        "lease_owner_absent_after_release",
        "inventory_pagination_complete",
        "expected_operation_resources",
        "other_ledgerguard_workload_resources",
        "active_glue_runs",
        "active_athena_queries",
        "active_state_machine_executions",
        "recovery_required",
    ],
)
def test_each_closure_mutation_fails(field: str) -> None:
    changed = postflight()
    changed[field] = not changed[field] if isinstance(changed[field], bool) else 1
    with pytest.raises(ValueError, match="closure differs"):
        validate_closure(changed, journal())


def test_command_sequence_and_workload_operation_fail() -> None:
    changed = journal()
    changed[2], changed[3] = changed[3], changed[2]
    with pytest.raises(ValueError, match="sequence differs"):
        validate_closure(postflight(), changed)
    changed = journal()
    changed.append({"operation": "StartJobRun", "command": ["aws", "glue"], "exit_code": 0})
    with pytest.raises(ValueError, match="prohibited operation"):
        validate_closure(postflight(), changed)
    changed_postflight = postflight()
    changed_postflight["schema_version"] = "wrong"
    with pytest.raises(ValueError, match="schema"):
        validate_closure(changed_postflight, journal())
