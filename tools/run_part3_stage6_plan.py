#!/usr/bin/env python3
"""Execute the exact-main Stage 6 plan-only transaction."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import time
from pathlib import Path
from typing import Any

from tools.part3_stage6.admin_packet import validate_release
from tools.part3_stage6.admission import validate_administrator_receipt
from tools.part3_stage6.aws_cli import Stage6AwsCli
from tools.part3_stage6.controller import adjudicate_plan_only
from tools.part3_stage6.live import (
    collect_preflight,
    observe_backend,
    observe_clean_inventory,
    release_lease,
)
from tools.part3_stage6.terraform import PlanSession, backend_arguments, terraform_variables


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"object required: {path}")
    return value


def _journal(cli: Stage6AwsCli, terraform: PlanSession) -> list[dict[str, Any]]:
    aws = [
        {
            "sequence": index + 1,
            "operation": row["operation"],
            "command": ["aws", row["operation"]],
            "exit_code": row["returncode"],
            "response_sha256": row["response_sha256"],
        }
        for index, row in enumerate(cli.journal)
    ]
    offset = len(aws)
    tf = [dict(row, sequence=offset + index + 1) for index, row in enumerate(terraform.journal)]
    return [*aws, *tf]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--expected-tree", required=True)
    parser.add_argument("--administrator-packet", type=Path, required=True)
    parser.add_argument("--administrator-receipt", type=Path, required=True)
    parser.add_argument("--release-dir", type=Path, required=True)
    parser.add_argument("--expires-at", required=True)
    parser.add_argument("--private-work-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--failure-output", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    if os.environ.get("GITHUB_EVENT_NAME") != "workflow_dispatch":
        raise SystemExit("Stage 6 requires workflow_dispatch")
    if os.environ.get("GITHUB_REF") != "refs/heads/main":
        raise SystemExit("Stage 6 requires the exact main ref")
    if (
        os.environ.get("GITHUB_SHA") != args.expected_sha
        or os.environ.get("CHECKED_OUT_SHA") != args.expected_sha
    ):
        raise SystemExit("Stage 6 source checkout differs")
    packet = _load(args.administrator_packet)
    receipt = _load(args.administrator_receipt)
    packet_sha = hashlib.sha256(args.administrator_packet.read_bytes()).hexdigest()
    release = _load(args.release_dir / "terraform-stage5-release.json")
    validate_release(release, args.release_dir)
    receipt_sha = hashlib.sha256(
        (json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n").encode()
    ).hexdigest()
    now = int(time.time())
    validate_administrator_receipt(
        receipt,
        source_commit=args.expected_sha,
        source_tree=args.expected_tree,
        now_epoch=now,
    )
    if packet.get("classification") != "PRIVATE_DESIRED_NOT_INSTALLED_NOT_EFFECTIVELY_VERIFIED":
        raise SystemExit("private administrator packet classification differs")
    expected_identity = packet["documents"]["identity_contract"]
    kms_key_arn = packet["documents"]["administrator"]["backend"]["kms_key_id"]
    control_plane = _load(root / "contracts/part3-stage2-control-plane-v1.json")
    cost_contract = _load(root / "contracts/part3-stage2-cost-v1.json")
    inventory_contract = _load(root / "contracts/part3-stage2-inventory-v1.json")
    private = args.private_work_dir.resolve()
    if private.exists() or private.is_symlink() or root in private.parents:
        raise SystemExit("new private work directory outside the repository required")
    private.mkdir(parents=True, mode=0o700)
    os.environ["TF_DATA_DIR"] = str(private / "terraform-data")
    owner_token = hashlib.sha256(
        f"{os.environ.get('GITHUB_RUN_ID')}:{os.environ.get('GITHUB_RUN_ATTEMPT')}:{args.expected_sha}".encode()
    ).hexdigest()
    cli = Stage6AwsCli("ap-southeast-2")
    session = PlanSession(root / "infra/part3", private / "plan")
    lease_acquired = False
    lease_was_ever_acquired = False
    failure: BaseException | None = None
    try:
        preflight = collect_preflight(
            cli=cli,
            expected_identity=expected_identity,
            administrator_receipt_sha256=receipt_sha,
            source_commit=args.expected_sha,
            source_tree=args.expected_tree,
            kms_key_arn=kms_key_arn,
            control_plane=control_plane,
            cost_contract=cost_contract,
            inventory_contract=inventory_contract,
            owner_token=owner_token,
            lease_expires_epoch=now + 1800,
            now_epoch=now,
        )
        lease_acquired = True
        lease_was_ever_acquired = True
        variables = terraform_variables(
            release,
            args.release_dir,
            operation_id="release-qual1",
            expires_at=args.expires_at,
        )
        plan, digests = session.execute(
            variables=variables,
            backend=backend_arguments(kms_key_arn=kms_key_arn, operation_id="release-qual1"),
        )
        released = release_lease(cli, owner_token)
        lease_acquired = False
        backend = observe_backend(cli, kms_key_arn, control_plane)
        inventory = observe_clean_inventory(cli)
        postflight = {
            "schema_version": "ledgerguard.part3-stage6-postflight.v1",
            "plan_applied": False,
            "apply_calls": 0,
            "workload_calls": 0,
            "resource_create_update_delete_calls": 0,
            "exact_state_absent": backend["exact_state_absent"],
            "backend_lock_absent": backend["lock_absent_before_lease"],
            **released,
            "inventory_pagination_complete": inventory["pagination_complete"],
            "expected_operation_resources": inventory["expected_operation_resources"],
            "other_ledgerguard_workload_resources": inventory[
                "other_ledgerguard_workload_resources"
            ],
            "active_glue_runs": inventory["active_glue_runs"],
            "active_athena_queries": inventory["active_athena_queries"],
            "active_state_machine_executions": inventory["active_state_machine_executions"],
            "recovery_required": False,
        }
        result = adjudicate_plan_only(
            root=root,
            source_commit=args.expected_sha,
            source_tree=args.expected_tree,
            administrator_receipt=receipt,
            administrator_packet_sha256=packet_sha,
            administrator_receipt_sha256=receipt_sha,
            preflight=preflight,
            plan=plan,
            plan_digests=digests,
            stage5_release=release,
            operation_id="release-qual1",
            expires_at=args.expires_at,
            postflight=postflight,
            journal=_journal(cli, session),
            now_epoch=int(time.time()),
            workflow_run_id=os.environ.get("GITHUB_RUN_ID", ""),
            workflow_run_attempt=os.environ.get("GITHUB_RUN_ATTEMPT", ""),
            output=args.output,
        )
        print(json.dumps(result, sort_keys=True))
    except BaseException as exc:
        failure = exc
        raise
    finally:
        recovery_required = lease_acquired
        if lease_acquired:
            # Conditional owner release is safe; ambiguity is retained as a
            # failure and never escalated to force-unlock or unbounded deletion.
            try:
                release_lease(cli, owner_token)
                recovery_required = False
            except Exception:
                recovery_required = True
        if failure is not None:
            failure_receipt = {
                "schema_version": "ledgerguard.part3-stage6-failure-handoff.v1",
                "source": {"commit": args.expected_sha, "tree": args.expected_tree},
                "target": {"account": "857229544428", "region": "ap-southeast-2"},
                "run": {
                    "id": os.environ.get("GITHUB_RUN_ID", ""),
                    "attempt": os.environ.get("GITHUB_RUN_ATTEMPT", ""),
                },
                "failure_type": type(failure).__name__,
                "lease_was_acquired": lease_was_ever_acquired,
                "conditional_release_completed": (
                    lease_was_ever_acquired and not recovery_required
                ),
                "recovery_required": recovery_required,
                "force_unlock_attempted": False,
                "apply_calls": 0,
                "workload_calls": 0,
                "journal": _journal(cli, session),
            }
            args.failure_output.parent.mkdir(parents=True, exist_ok=True)
            args.failure_output.write_text(
                json.dumps(failure_receipt, sort_keys=True, indent=2) + "\n",
                encoding="utf-8",
            )
        shutil.rmtree(private, ignore_errors=False)


if __name__ == "__main__":
    main()
