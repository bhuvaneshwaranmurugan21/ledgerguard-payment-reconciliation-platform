"""Compose Stage 6 gates from independently produced, exact inputs."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from tools.part3_stage4.resources import parse_module
from tools.part3_stage6.admin_packet import stage5_runtime_policies as runtime_policies
from tools.part3_stage6.admission import validate_administrator_receipt
from tools.part3_stage6.artifact import build_artifact, canonical
from tools.part3_stage6.closure import validate_closure
from tools.part3_stage6.plan_policy import expected_addresses, validate_saved_plan
from tools.part3_stage6.preflight import validate_preflight
from tools.part3_stage6.property_policy import validate_properties
from tools.part3_stage6.relationships import validate_relationships


def _sha(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def _file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source_bindings(
    root: Path,
    stage5_release: dict[str, Any],
    administrator_packet_sha256: str,
    administrator_receipt_sha256: str,
) -> dict[str, Any]:
    locks = {
        "terraform": "infra/part3/.terraform.lock.hcl",
        "bootstrap": "requirements/part3-stage3-bootstrap.lock",
        "python311": "requirements/part3-stage3-py311.lock",
        "parser": "requirements/part3-stage4-parser.lock",
    }
    return {
        "administrator_packet_sha256": administrator_packet_sha256,
        "administrator_receipt_sha256": administrator_receipt_sha256,
        "stage5_runtime_package_sha256": stage5_release["runtime_package_sha256"],
        "stage5_manifest_sha256": stage5_release["manifest_sha256"],
        "stage5_script_sha256": stage5_release["script_sha256"],
        "stage5_wheels_sha256": stage5_release["wheels_sha256"],
        "lock_sha256": {name: _file_sha(root / path) for name, path in locks.items()},
    }


def adjudicate_plan_only(
    *,
    root: Path,
    source_commit: str,
    source_tree: str,
    administrator_receipt: dict[str, Any],
    administrator_packet_sha256: str,
    administrator_receipt_sha256: str,
    preflight: dict[str, Any],
    plan: dict[str, Any],
    plan_digests: dict[str, str],
    stage5_release: dict[str, Any],
    operation_id: str,
    expires_at: str,
    postflight: dict[str, Any],
    journal: list[dict[str, Any]],
    now_epoch: int,
    workflow_run_id: str,
    workflow_run_attempt: str,
    output: Path,
) -> dict[str, Any]:
    """Adjudicate S6-G01..G03 and create the sanitized producer artifact.

    S6-G04 is intentionally absent.  Only ``inspect_artifact`` may add it.
    """
    admitted_admin = validate_administrator_receipt(
        administrator_receipt,
        source_commit=source_commit,
        source_tree=source_tree,
        now_epoch=now_epoch,
    )
    if _sha(administrator_receipt) != administrator_receipt_sha256:
        raise ValueError("administrator receipt byte binding differs")
    if admitted_admin["private_packet_sha256"] != administrator_packet_sha256:
        raise ValueError("administrator private packet binding differs")
    admitted_preflight = validate_preflight(
        preflight,
        source_commit=source_commit,
        source_tree=source_tree,
        administrator_receipt_sha256=administrator_receipt_sha256,
        now_epoch=now_epoch,
    )
    structural = validate_saved_plan(plan, expected_addresses(root))
    relationships = validate_relationships(plan)
    properties = validate_properties(
        plan,
        operation_id=operation_id,
        expires_at=expires_at,
        permissions_boundary_arns={
            role: f"arn:aws:iam::857229544428:policy/LedgerGuardPart3-{role}-Boundary-v1"
            for role in ("glue", "workflow", "validator", "controller")
        },
        stage5_release=stage5_release,
        runtime_policy_documents=runtime_policies(
            parse_module(root / "infra/part3"),
            operation_id,
            {
                "script_key": stage5_release["script_key"],
                "wheels_key": stage5_release["wheels_key"],
            },
        ),
        catalog_tables=json.loads(
            (root / "spec/part3-stage4-catalog-v1.json").read_text(encoding="utf-8")
        )["tables"],
    )
    closure = validate_closure(postflight, journal)
    if structural["plan_json_sha256"] != _sha(plan):
        raise AssertionError("internal canonical plan binding differs")
    required_digests = {"binary_sha256", "json_sha256", "variable_sha256"}
    if set(plan_digests) != required_digests or any(
        not isinstance(value, str) or len(value) != 64 for value in plan_digests.values()
    ):
        raise ValueError("plan digest inventory differs")
    policy_projection = {
        "administrator": admitted_admin,
        "preflight": admitted_preflight,
        "structural": structural,
        "relationships": relationships,
        "properties": properties,
        "closure": closure,
    }
    policy_sha256 = _sha(policy_projection)
    evidence = {
        "schema_version": "ledgerguard.part3-stage6-plan-only-evidence.v1",
        "source": {
            "commit": source_commit,
            "tree": source_tree,
            "ref": "refs/heads/main",
            "event": "workflow_dispatch",
            "workflow_run_id": workflow_run_id,
            "workflow_run_attempt": workflow_run_attempt,
        },
        "target": {"account": "857229544428", "region": "ap-southeast-2"},
        "bindings": _source_bindings(
            root,
            stage5_release,
            administrator_packet_sha256,
            administrator_receipt_sha256,
        ),
        "toolchain": {
            "terraform": "1.13.1",
            "aws_provider": "6.11.0",
        },
        "backend": {
            "state_key_sha256": hashlib.sha256(
                b"ledgerguard/terraform/part3/platform/release-qual1/terraform.tfstate"
            ).hexdigest(),
            "state_absent_before_and_after": True,
        },
        "budget": {
            "billing_observed_epoch": preflight["completed_epoch"],
            "billing_classification": "COST_EXPLORER_DELAYED_WITH_CONSERVATIVE_RESERVE",
            "known_gross_usd": preflight["budget"]["known_gross_usd"],
            "reserved_stage6_exposure_usd": preflight["budget"]["reserved_stage6_exposure_usd"],
            "cleanup_reserve_usd": preflight["budget"]["cleanup_reserve_usd"],
            "strict_ceiling_usd": preflight["budget"]["strict_ceiling_usd"],
            "estimated_monthly_standing_usd": "0.00",
            "assumptions": [
                "plan-only; no managed resources created",
                "provider control-plane reads only",
                "no reconciliation, Glue, Athena, Step Functions or Lambda workload",
            ],
        },
        "gates": {"S6-G01": True, "S6-G02": True, "S6-G03": True, "S6-G04": False},
        "plan": {
            **plan_digests,
            "policy_sha256": policy_sha256,
            "resource_changes": structural["resource_changes"],
            "create_actions": structural["create_actions"],
            "other_actions": structural["other_actions"],
            "applied": False,
        },
        "preflight": {
            "exact_identity": True,
            "installed_iam": True,
            "effective_permissions": True,
            "restrictions_resolved": True,
            "backend_admitted": True,
            "lease_acquired": True,
            "budget_admitted": True,
            "quota_admitted": True,
            "inventory_clean": True,
        },
        "closure": {
            "apply_calls": closure["apply_calls"],
            "workload_calls": closure["workload_calls"],
            "post_inventory_clean": closure["post_inventory_clean"],
            "lease_released": closure["lease_released"],
            "backend_lock_absent": closure["backend_lock_absent"],
            "recovery_required": closure["recovery_required"],
            "stage6_complete": False,
            "terminal_state": "awaiting_independent_inspection",
        },
    }
    artifact_sha = build_artifact(output, evidence, journal)
    return {
        "classification": "STAGE6_PRODUCER_ARTIFACT_AWAITING_INDEPENDENT_INSPECTION",
        "artifact_sha256": artifact_sha,
        "policy_sha256": policy_sha256,
        "producer_gates": 3,
        "S6-G04": False,
        "stage6_complete": False,
    }
