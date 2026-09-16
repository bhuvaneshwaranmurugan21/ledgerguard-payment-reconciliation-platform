"""Validate the immutable Stage 6 pre-execution input freeze.

This validator performs source-local checks only. It cannot install IAM, prove
effective AWS permissions, create a Terraform plan, or satisfy a Stage 6 gate.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

EXPECTED_REQUIREMENTS = ["P3-M-L282-01", "P3-M-L283-01", "P3-M-L283-02"]
EXPECTED_GATES = ["S6-G01", "S6-G02", "S6-G03", "S6-G04"]
EXPECTED_BLOCKERS = {
    "successor_iam_installed",
    "effective_permissions_verified",
    "organization_scp_session_resource_restrictions_resolved",
    "fresh_budget_backend_inventory_quota_lease_admission",
    "stage6_exact_main_source_exists",
    "stage6_saved_plan_exists",
}
EXPECTED_STAGE5_DIGESTS = {
    "increment_artifact_sha256": "a787a07a0a18c37b128163184268c32f79da5e368171601ac9bb6be7a5bfc585",
    "release_artifact_sha256": "6a182e1827502bb645f3d4713489d6e0638fd07845dc95ff4215113e9775d530",
    "release_bundle_sha256": "d51b16fe835f28455cc364600690caaf81e123050cbf4d984a6cbec8fb4ab606",
    "definition_sha256": "e9233f551153fe4053575609423802eeed8741612cc16be5017d097746f693d5",
    "runtime_package_sha256": "1dde69c7338d898daa660acd800264d817d15f73bae9b2071156eb909f2291b8",
    "sbom_sha256": "622e965dc699dd2bb2aac5f638eaaf6945d57ef553965d9cb681d548c58661dc",
    "provenance_sha256": "d7cf750e5e592a5a53de4b022d31f3de7fe4fed495f6d32d26a20340332d9167",
    "handler_config_sha256": "f0bd3462aab632c8bccc378d428f3c07eb492f939eb6ff4a0e2e8d2809c1a25a",
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"object required: {path}")
    return value


def validate(root: Path, freeze: dict[str, Any] | None = None) -> dict[str, Any]:
    freeze = freeze or load_json(root / "spec/part3-stage6-preparation-v1.json")
    if freeze["schema_version"] != "ledgerguard.part3.stage6-preparation.v1":
        raise ValueError("Stage 6 preparation schema differs")
    if freeze["classification"] != "PRE_EXECUTION_INPUT_FREEZE_NOT_AWS_EVIDENCE":
        raise ValueError("Stage 6 preparation classification differs")

    stage5 = freeze["accepted_stage5"]
    if stage5["main_commit"] != "38576ff8b0592b53cd65fe3cf4241e077484afd8":
        raise ValueError("accepted Stage 5 commit differs")
    if stage5["tree"] != "d789912c580bc4fd7f8059dd5e0ea766cd251750":
        raise ValueError("accepted Stage 5 tree differs")
    if stage5["exact_main_definition_validation"] != "OK":
        raise ValueError("Stage 5 definition validation is not admitted")
    for name, expected in EXPECTED_STAGE5_DIGESTS.items():
        value = stage5[name]
        if not isinstance(value, str) or len(value) != 64 or set(value) - set("0123456789abcdef"):
            raise ValueError(f"invalid accepted Stage 5 digest: {name}")
        if value != expected:
            raise ValueError(f"accepted Stage 5 digest differs: {name}")

    if freeze["requirements"] != EXPECTED_REQUIREMENTS:
        raise ValueError("Stage 6 owning requirements differ")
    master = load_json(root / "spec/part3-requirements-v1.json")["requirements"]
    actual = [r["requirement_id"] for r in master if r["owner_part"] == 3 and r["owner_stage"] == 6]
    if actual != EXPECTED_REQUIREMENTS:
        raise ValueError("master Stage 6 requirement ownership differs")
    if freeze["gates"] != EXPECTED_GATES:
        raise ValueError("Stage 6 gate inventory differs")

    target = freeze["target"]
    if target["account"] != "857229544428" or target["region"] != "ap-southeast-2":
        raise ValueError("Stage 6 target differs")
    for path_key, digest_key in (
        ("resource_inventory_path", "resource_inventory_sha256"),
        ("resource_controls_path", "resource_controls_sha256"),
        ("provider_actions_path", "provider_actions_sha256"),
    ):
        path = root / target[path_key]
        if not path.is_file() or digest(path) != target[digest_key]:
            raise ValueError(f"Stage 6 target input differs: {path_key}")
    inventory = load_json(root / target["resource_inventory_path"])
    addresses = sorted(row["address"] for row in inventory["members"])
    if len(addresses) != len(set(addresses)):
        raise ValueError("duplicate Stage 6 address")
    if len(addresses) != target["managed_address_count"] or len(addresses) != 33:
        raise ValueError("Stage 6 address count differs")
    address_digest = hashlib.sha256(("\n".join(addresses) + "\n").encode()).hexdigest()
    if address_digest != target["sorted_address_inventory_sha256"]:
        raise ValueError("Stage 6 address inventory differs")

    toolchain = freeze["toolchain"]
    if (toolchain["python"], toolchain["terraform"], toolchain["tflint"]) != (
        "3.11.13",
        "1.13.1",
        "0.59.1",
    ):
        raise ValueError("Stage 6 toolchain differs")
    for path_key, digest_key in (
        ("parser_lock_path", "parser_lock_sha256"),
        ("terraform_lock_path", "terraform_lock_sha256"),
        ("accepted_static_workflow_path", "accepted_static_workflow_sha256"),
    ):
        path = root / toolchain[path_key]
        if not path.is_file() or digest(path) != toolchain[digest_key]:
            raise ValueError(f"Stage 6 toolchain input differs: {path_key}")
    parser = (root / toolchain["parser_lock_path"]).read_text(encoding="utf-8")
    for package in ("python-hcl2==7.3.1", "lark==1.2.2", "regex==2025.9.1"):
        if package not in parser:
            raise ValueError(f"Stage 6 parser package missing: {package}")

    invariants = freeze["hard_invariants"]
    required_true = (
        "plan_only",
        "saved_binary_plan_required",
        "same_binary_json_render_required",
        "full_refresh_required",
        "terraform_locking_required",
    )
    if any(invariants[name] is not True for name in required_true):
        raise ValueError("Stage 6 plan invariant weakened")
    if invariants["gross_project_cost_strictly_below_usd"] != 10:
        raise ValueError("Stage 6 gross cost ceiling differs")
    if invariants["exact_create_actions"] != 33 or invariants["allowed_plan_actions"] != ["create"]:
        raise ValueError("Stage 6 create-only graph differs")
    if invariants["executor_iam_mutation"] is not False:
        raise ValueError("executor IAM mutation became eligible")
    if (
        invariants["raw_plan_publication"] is not False
        or invariants["raw_state_publication"] is not False
    ):
        raise ValueError("sensitive Terraform evidence became publishable")
    for name in ("apply", "force-unlock", "import", "target", "refresh-false", "lock-false"):
        if name not in invariants["prohibited_terraform"]:
            raise ValueError(f"Terraform prohibition missing: {name}")
    if len(invariants["prohibited_workloads"]) != 6:
        raise ValueError("Stage 6 workload prohibition inventory differs")

    dependencies = freeze["pre_execution_dependencies"]
    if set(dependencies) != EXPECTED_BLOCKERS or any(
        value is not False for value in dependencies.values()
    ):
        raise ValueError("open Stage 6 dependencies were hidden or changed")
    boundary = freeze["workflow_boundary"]
    if boundary != {
        "trigger": "workflow_dispatch",
        "eligible_ref": "refs/heads/main",
        "arbitrary_ref_allowed": False,
        "cancel_in_progress": False,
        "aws_credentials_before_source_admission": False,
        "shared_operation_guard_required": True,
        "stale_ttl_proves_runner_stopped": False,
        "force_unlock_allowed": False,
    }:
        raise ValueError("Stage 6 workflow boundary differs")
    closure = freeze["closure"]
    if closure["terminal_state"] != "plan_only_verified":
        raise ValueError("Stage 6 terminal state differs")
    if any(closure[name] is not True for name in (
        "requires_independent_artifact_inspection",
        "requires_no_apply_proof",
        "requires_no_workload_proof",
        "requires_owned_lease_release_or_recovery_transfer",
    )):
        raise ValueError("Stage 6 closure proof weakened")
    if closure["stage6_complete"] is not False or closure["part3_complete"] is not False:
        raise ValueError("Stage 6 preparation claimed completion")

    return {
        "classification": "STAGE6_PRE_EXECUTION_INPUTS_LOCALLY_VERIFIED",
        "requirements": len(EXPECTED_REQUIREMENTS),
        "gates": len(EXPECTED_GATES),
        "managed_addresses": 33,
        "open_dependencies": sorted(EXPECTED_BLOCKERS),
        "aws_calls": 0,
        "stage6_complete": False,
    }


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    print(json.dumps(validate(root), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
