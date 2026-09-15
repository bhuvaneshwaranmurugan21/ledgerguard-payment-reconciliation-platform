"""Owner-bound recovery for an ambiguous Stage 6 lease release.

Recovery can only remove the exact shared lease after proving the Stage 6 state
and lock objects are absent. It never force-unlocks Terraform or touches a
workload resource.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

from tools.part3_stage6.aws_cli import Stage6AwsCli
from tools.part3_stage6.live import (
    ACCOUNT,
    LEASE_KEY,
    LEASE_TABLE,
    REGION,
    observe_backend,
    observe_clean_inventory,
    release_lease,
)

HEX40 = re.compile(r"^[0-9a-f]{40}$")


def owner_token(run_id: str, run_attempt: str, source_commit: str) -> str:
    if not run_id.isdigit() or not run_attempt.isdigit() or HEX40.fullmatch(source_commit) is None:
        raise ValueError("recovery owner inputs invalid")
    return hashlib.sha256(f"{run_id}:{run_attempt}:{source_commit}".encode()).hexdigest()


def validate_failure_handoff(
    value: dict[str, Any], *, source_commit: str, source_tree: str
) -> dict[str, str]:
    if value.get("schema_version") != "ledgerguard.part3-stage6-failure-handoff.v1":
        raise ValueError("failure handoff schema differs")
    if value.get("source") != {"commit": source_commit, "tree": source_tree}:
        raise ValueError("failure handoff source differs")
    if HEX40.fullmatch(source_commit) is None or HEX40.fullmatch(source_tree) is None:
        raise ValueError("failure handoff source identity invalid")
    if value.get("target") != {"account": ACCOUNT, "region": REGION}:
        raise ValueError("failure handoff target differs")
    run = value.get("run")
    if not isinstance(run, dict):
        raise ValueError("failure handoff run missing")
    token = owner_token(str(run.get("id", "")), str(run.get("attempt", "")), source_commit)
    exact = {
        "lease_was_acquired": True,
        "conditional_release_completed": False,
        "recovery_required": True,
        "force_unlock_attempted": False,
        "apply_calls": 0,
        "workload_calls": 0,
    }
    if {key: value.get(key) for key in exact} != exact:
        raise ValueError("failure handoff safety state differs")
    return {"owner_token": token, "run_id": str(run["id"]), "run_attempt": str(run["attempt"])}


def recover_owned_lease(
    *,
    cli: Stage6AwsCli,
    handoff: dict[str, Any],
    source_commit: str,
    source_tree: str,
    kms_key_arn: str,
    control_plane: dict[str, Any],
) -> dict[str, Any]:
    admitted = validate_failure_handoff(
        handoff, source_commit=source_commit, source_tree=source_tree
    )
    backend = observe_backend(cli, kms_key_arn, control_plane)
    if backend["exact_state_absent"] is not True or backend["lock_absent_before_lease"] is not True:
        raise ValueError("recovery blocked by Stage 6 state or lock object")
    key = '{"lease_key":{"S":"' + LEASE_KEY + '"}}'
    observed = cli.invoke(
        "DDB_GET_ITEM", ["--table-name", LEASE_TABLE, "--consistent-read", "--key", key]
    ).get("Item")
    lease_already_absent = observed is None
    if observed is not None:
        if (
            not isinstance(observed, dict)
            or observed.get("owner_token", {}).get("S") != admitted["owner_token"]
        ):
            raise ValueError("recovery lease is owned by a different transaction")
        release_lease(cli, admitted["owner_token"])
    inventory = observe_clean_inventory(cli)
    return {
        "schema_version": "ledgerguard.part3-stage6-recovery-receipt.v1",
        "source": {"commit": source_commit, "tree": source_tree},
        "target": {"account": ACCOUNT, "region": REGION},
        "failed_run": {"id": admitted["run_id"], "attempt": admitted["run_attempt"]},
        "state_absent": True,
        "terraform_lock_absent": True,
        "lease_already_absent": lease_already_absent,
        "owned_conditional_release": not lease_already_absent,
        "lease_absent_after_recovery": True,
        "inventory_clean": inventory["expected_operation_resources"] == 0
        and inventory["other_ledgerguard_workload_resources"] == 0,
        "force_unlock_attempted": False,
        "apply_calls": 0,
        "workload_calls": 0,
        "stage6_complete": False,
    }
