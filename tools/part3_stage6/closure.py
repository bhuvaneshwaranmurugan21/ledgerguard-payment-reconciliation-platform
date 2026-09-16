"""Validate post-plan absence, lock, lease, and command closure."""

from __future__ import annotations

from typing import Any

EXPECTED_TERRAFORM_OPERATIONS = [
    "terraform-version",
    "terraform-init",
    "terraform-validate",
    "terraform-plan",
    "terraform-show",
]


def validate_closure(value: dict[str, Any], journal: list[dict[str, Any]]) -> dict[str, Any]:
    if value.get("schema_version") != "ledgerguard.part3-stage6-postflight.v1":
        raise ValueError("postflight schema differs")
    exact = {
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
    observed = {key: value.get(key) for key in exact}
    if observed != exact:
        raise ValueError("Stage 6 postflight closure differs")
    operations = [
        row.get("operation")
        for row in journal
        if str(row.get("operation", "")).startswith("terraform-")
    ]
    if operations != EXPECTED_TERRAFORM_OPERATIONS:
        raise ValueError("Terraform command journal sequence differs")
    for row in journal:
        operation = str(row.get("operation", "")).lower()
        if any(
            term in operation
            for term in ("apply", "startjobrun", "startqueryexecution", "startexecution", "invoke")
        ):
            raise ValueError("prohibited operation found in closure journal")
    return {
        "classification": "S6_G03_ZERO_MUTATION_CLOSURE_ADMITTED",
        "apply_calls": 0,
        "workload_calls": 0,
        "post_inventory_clean": True,
        "lease_released": True,
        "backend_lock_absent": True,
        "recovery_required": False,
        "stage6_complete": False,
    }
