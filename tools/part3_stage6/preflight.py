"""Fail-closed validation of freshly collected Stage 6 target admission."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any

HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _obj(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _all_true(value: Any, label: str, required: set[str]) -> None:
    rows = _obj(value, label)
    if set(rows) != required or any(rows[key] is not True for key in required):
        raise ValueError(f"{label} is incomplete")


def validate_preflight(
    value: dict[str, Any],
    *,
    source_commit: str,
    source_tree: str,
    administrator_receipt_sha256: str,
    now_epoch: int,
) -> dict[str, Any]:
    if value.get("schema_version") != "ledgerguard.part3-stage6-live-preflight.v1":
        raise ValueError("live preflight schema differs")
    if value.get("classification") != "FRESH_EXACT_MAIN_PLAN_ONLY_ADMISSION":
        raise ValueError("live preflight classification differs")
    if _obj(value.get("source"), "source") != {
        "commit": source_commit,
        "tree": source_tree,
        "ref": "refs/heads/main",
        "event": "workflow_dispatch",
    }:
        raise ValueError("live source binding differs")
    if _obj(value.get("target"), "target") != {
        "account": "857229544428",
        "region": "ap-southeast-2",
        "operation_id": "release-qual1",
    }:
        raise ValueError("live target differs")
    observed = value.get("completed_epoch")
    if not isinstance(observed, int) or isinstance(observed, bool):
        raise ValueError("live preflight time invalid")
    if observed > now_epoch + 60 or now_epoch - observed > 900:
        raise ValueError("live preflight is stale or future-dated")
    if (
        value.get("administrator_receipt_sha256") != administrator_receipt_sha256
        or HEX64.fullmatch(administrator_receipt_sha256) is None
    ):
        raise ValueError("administrator receipt binding differs")
    _all_true(
        value.get("identity_iam"),
        "identity/IAM admission",
        {
            "expected_account",
            "expected_deploy_role",
            "trust_parity",
            "role_attachment_parity",
            "policy_document_parity",
            "effective_allow_probe",
            "effective_deny_probe",
            "restrictions_resolved",
        },
    )
    _all_true(
        value.get("backend"),
        "backend admission",
        {
            "exact_bucket",
            "exact_region",
            "versioning_enabled",
            "kms_key_exact",
            "public_access_blocked",
            "tls_only",
            "ownership_enforced",
            "lifecycle_admitted",
            "exact_state_absent",
            "lock_absent_before_lease",
        },
    )
    _all_true(
        value.get("lease"),
        "lease admission",
        {
            "shared_table_admitted",
            "exact_key",
            "prior_owner_absent",
            "conditionally_acquired",
            "owner_readback_equal",
        },
    )
    _all_true(
        value.get("quota"),
        "quota admission",
        {"iam", "lambda", "glue", "athena", "states", "dynamodb", "cloudwatch", "s3"},
    )
    inventory = _obj(value.get("inventory"), "inventory")
    if inventory != {
        "pagination_complete": True,
        "access_denied": [],
        "expected_operation_resources": 0,
        "other_ledgerguard_workload_resources": 0,
        "active_glue_runs": 0,
        "active_athena_queries": 0,
        "active_state_machine_executions": 0,
    }:
        raise ValueError("clean inventory admission differs")
    budget = _obj(value.get("budget"), "budget")
    if budget.get("currency") != "USD" or budget.get("cost_explorer_delayed") is not True:
        raise ValueError("budget classification differs")
    try:
        gross = Decimal(str(budget["known_gross_usd"]))
        exposure = Decimal(str(budget["reserved_stage6_exposure_usd"]))
        cleanup = Decimal(str(budget["cleanup_reserve_usd"]))
        ceiling = Decimal(str(budget["strict_ceiling_usd"]))
    except (KeyError, InvalidOperation) as exc:
        raise ValueError("budget amount invalid") from exc
    if min(gross, exposure, cleanup) < 0 or ceiling != Decimal("10"):
        raise ValueError("budget bounds differ")
    total = gross + exposure + cleanup
    if total >= ceiling:
        raise ValueError("strict cumulative gross budget is not admitted")
    return {
        "classification": "S6_G01_PREFLIGHT_ADMITTED",
        "known_plus_reserves_usd": format(total, "f"),
        "lease_acquired": True,
        "inventory_clean": True,
        "workload_calls": 0,
        "stage6_complete": False,
    }
