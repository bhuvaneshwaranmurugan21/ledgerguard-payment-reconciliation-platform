"""Admission of the separate administrator transaction into Stage 6.

The receipt is sanitized but cryptographically binds the private before/after
packet.  It is never a substitute for the live exact-main preflight; it proves
that the executor may begin that preflight without repairing its own IAM.
"""

from __future__ import annotations

import re
import time
from typing import Any

ACCOUNT = "857229544428"
REGION = "ap-southeast-2"
HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
RESTRICTIONS = {"organization_scp", "permissions_boundary", "session_policy", "resource_policy"}


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def validate_administrator_receipt(
    receipt: dict[str, Any],
    *,
    source_commit: str,
    source_tree: str,
    now_epoch: int | None = None,
    maximum_age_seconds: int = 3600,
) -> dict[str, Any]:
    if receipt.get("schema_version") != "ledgerguard.part3-stage6-administrator-receipt.v1":
        raise ValueError("administrator receipt schema differs")
    if receipt.get("classification") != "SUCCESSOR_IAM_INSTALLED_AND_EFFECTIVELY_ADMITTED":
        raise ValueError("administrator transaction is not admitted")
    source = _object(receipt.get("source"), "source")
    if source != {"commit": source_commit, "tree": source_tree}:
        raise ValueError("administrator receipt source binding differs")
    if HEX40.fullmatch(source_commit) is None or HEX40.fullmatch(source_tree) is None:
        raise ValueError("source identity invalid")
    target = _object(receipt.get("target"), "target")
    if target != {"account": ACCOUNT, "region": REGION, "operation_id": "release-qual1"}:
        raise ValueError("administrator receipt target differs")
    timing = _object(receipt.get("timing"), "timing")
    observed_epoch = timing.get("completed_epoch")
    if not isinstance(observed_epoch, int) or isinstance(observed_epoch, bool):
        raise ValueError("administrator completion time invalid")
    now = int(time.time()) if now_epoch is None else now_epoch
    if observed_epoch > now + 60 or now - observed_epoch > maximum_age_seconds:
        raise ValueError("administrator receipt is stale or future-dated")
    bindings = _object(receipt.get("bindings"), "bindings")
    for key in (
        "private_packet_sha256",
        "pre_change_snapshot_sha256",
        "mutation_journal_sha256",
        "post_change_snapshot_sha256",
        "rollback_packet_sha256",
    ):
        if HEX64.fullmatch(str(bindings.get(key, ""))) is None:
            raise ValueError(f"administrator binding invalid: {key}")
    checks = _object(receipt.get("checks"), "checks")
    required_true = {
        "separate_administrator_identity",
        "pre_change_snapshot_complete",
        "exact_policy_documents_installed",
        "exact_role_attachments_installed",
        "trust_path_session_boundary_parity",
        "effective_permissions_verified",
        "policy_simulation_allowed",
        "policy_simulation_denials_verified",
        "access_analyzer_zero_findings",
        "managed_policy_quota_headroom",
        "service_quota_headroom",
        "rollback_ready",
        "executor_did_not_self_remediate",
    }
    if set(checks) != required_true or any(checks[key] is not True for key in required_true):
        raise ValueError("administrator check inventory is incomplete")
    restrictions = _object(receipt.get("restrictions"), "restrictions")
    if set(restrictions) != RESTRICTIONS:
        raise ValueError("restriction inventory differs")
    for name, result in restrictions.items():
        row = _object(result, f"restriction {name}")
        if row.get("visibility") not in {"OBSERVED", "NOT_APPLICABLE"}:
            raise ValueError(f"restriction visibility unresolved: {name}")
        if row.get("admitted") is not True:
            raise ValueError(f"restriction not admitted: {name}")
    calls = _object(receipt.get("calls"), "calls")
    if calls.get("workload_calls") != 0 or calls.get("executor_iam_mutations") != 0:
        raise ValueError("administrator transaction crossed a prohibited boundary")
    if (
        not isinstance(calls.get("administrator_iam_mutations"), int)
        or calls["administrator_iam_mutations"] <= 0
    ):
        raise ValueError("administrator installation was not evidenced")
    return {
        "classification": "ADMINISTRATOR_RECEIPT_ADMITTED_LIVE_PREFLIGHT_STILL_REQUIRED",
        "private_packet_sha256": bindings["private_packet_sha256"],
        "receipt_age_seconds": now - observed_epoch,
        "restrictions_resolved": True,
        "effective_permissions_verified": True,
        "workload_calls": 0,
        "stage6_complete": False,
    }
