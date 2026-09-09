"""Fail-closed validation of the LedgerGuard Part 3 Stage 2 closure candidate."""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
from typing import Any, cast

PROJECT = "bhuvaneshwaranmurugan21/ledgerguard-payment-reconciliation-platform"
QUALIFIED_COMMIT = "aa136331e44dcd181f766b42d76ee2616a22f435"
QUALIFIED_TREE = "184d8d7ff8d1172ec863060d4be7132339eaba49"
REQUIREMENT_IDS = [
    "P3-M-L226-01",
    "P3-M-L227-01",
    "P3-M-L227-02",
    "P3-M-L228-01",
    "P3-M-L228-02",
    "P3-M-L229-01",
    "P3-M-L230-01",
    "P3-M-L231-01",
    "P3-M-L232-01",
    "P3-M-L233-01",
    "P3-M-L234-01",
    "P3-M-L234-02",
    "P3-M-L234-03",
    "P3-M-L235-01",
    "P3-M-L236-01",
    "P3-M-L237-01",
    "P3-M-L238-01",
    "P3-M-L239-01",
    "P3-M-L266-01",
    "P3-M-L266-02",
    "P3-M-L267-01",
    "P3-M-L276-01",
]
MASTER_GATES = [
    "environment_qualified",
    "live_iam_parity_verified",
    "glue_definition_probe_verified",
    "plan_only_verified",
    "zero_workload_canary_verified",
    "teardown_verified",
]
MUTATION_CLASSES = [
    "ACCEPT_QUALIFIED_COMMIT_DRIFT",
    "ACCEPT_OPERATIONAL_BYTE_DRIFT",
    "ACCEPT_LIVE_RECEIPT_COMMIT_DRIFT",
    "ACCEPT_IAM_PARITY_FAILURE",
    "ACCEPT_COST_HEADROOM_FAILURE",
    "ACCEPT_INCOMPLETE_CLEANUP",
    "ACCEPT_WORKLOAD_EXECUTION",
    "ALLOW_UNVERIFIED_REQUIREMENT",
    "PREMATURELY_CLOSE_EXTERNAL_GATE",
    "ALLOW_EXCESS_MASTER_GATE",
    "LEAVE_OWNED_CARRYOVER_OPEN",
    "ALLOW_INFLATED_HANDOFF_CLAIM",
    "ALLOW_WEAKENED_QUALITY_AUTHORITY",
]
CLOSURE_FILES = (
    "contracts/part3-stage2-stage3-handoff-v1.json",
    "evidence/part3-stage2/capability-receipt-v1.json",
    "evidence/part3-stage2/implementation-publication-receipt-v1.json",
    "evidence/part3-stage2/read-only-receipt-v1.json",
    "evidence/part3-stage2/recovery-receipt-v1.json",
    "spec/part3-gap-adjudication-v1.json",
    "spec/part3-stage2-closure-coverage-v1.json",
    "spec/part3-stage2-gate-adjudication-v1.json",
    "spec/part3-stage2-master-gate-adjudication-v1.json",
    "spec/part3-stage2-operational-freeze-v1.json",
    "spec/part3-stage2-requirement-adjudication-executed-v1.json",
)


class Stage2ClosureError(ValueError):
    """Raised when the Stage 2 closure candidate is incomplete or inflated."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise Stage2ClosureError(message)


def _load(root: Path, relative: str) -> dict[str, Any]:
    value = json.loads((root / relative).read_text(encoding="utf-8"))
    _require(isinstance(value, dict), f"JSON object required: {relative}")
    return cast(dict[str, Any], value)


def _digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _validate_freeze(root: Path) -> dict[str, Any]:
    freeze = _load(root, "spec/part3-stage2-operational-freeze-v1.json")
    _require(freeze.get("schema_version") == "1.0", "freeze schema differs")
    _require(freeze.get("qualified_commit") == QUALIFIED_COMMIT, "qualified commit differs")
    _require(freeze.get("qualified_tree") == QUALIFIED_TREE, "qualified tree differs")
    files = freeze.get("operational_sha256")
    _require(isinstance(files, dict) and len(files) == 30, "operational inventory differs")
    for relative, expected in cast(dict[object, object], files).items():
        _require(isinstance(relative, str) and isinstance(expected, str), "invalid freeze row")
        path = root / cast(str, relative)
        _require(path.is_file(), f"frozen operational file missing: {relative}")
        _require(_digest(path) == expected, f"qualified operational byte changed: {relative}")
    _require(freeze.get("managed_reconciliation_started") is False, "workload claim inflated")
    _require(freeze.get("project_complete") is False, "project claim inflated")
    return freeze


def _validate_receipts(root: Path) -> dict[str, Any]:
    read_only = _load(root, "evidence/part3-stage2/read-only-receipt-v1.json")
    capability = _load(root, "evidence/part3-stage2/capability-receipt-v1.json")
    recovery = _load(root, "evidence/part3-stage2/recovery-receipt-v1.json")
    publication = _load(root, "evidence/part3-stage2/implementation-publication-receipt-v1.json")
    for receipt in (read_only, capability):
        _require(receipt.get("commit") == QUALIFIED_COMMIT, "live receipt commit differs")
        _require(receipt.get("ref") == "refs/heads/main", "live receipt ref differs")
        _require(receipt.get("independently_accepted") is True, "live artifact not accepted")
        _require(
            receipt.get("managed_reconciliation_started") is False,
            "live receipt claims managed workload",
        )
        _require(receipt.get("project_complete") is False, "live receipt claims project complete")
    target = cast(dict[str, Any], read_only.get("target"))
    _require(
        target.get("account") == "857229544428"
        and target.get("region") == "ap-southeast-2"
        and all(
            target.get(key) is True
            for key in ("identity_match", "repository_match", "main_ref_match", "exact_sha_match")
        ),
        "read-only target binding differs",
    )
    iam = cast(dict[str, Any], read_only.get("iam"))
    _require(
        iam.get("trust_equal") is True and iam.get("permissions_equal") is True, "IAM parity failed"
    )
    cost = cast(dict[str, Any], read_only.get("cost"))
    _require(
        cost.get("verdict") == "HEADROOM_VERIFIED" and cost.get("remaining_usd") == "8.2082",
        "cost headroom differs",
    )
    inventory = cast(dict[str, Any], read_only.get("inventory"))
    _require(
        inventory.get("clean") is True and inventory.get("probe_residue") == 0,
        "read-only inventory not clean",
    )
    cases = capability.get("cases")
    _require(isinstance(cases, list) and len(cases) == 4, "capability case count differs")
    case_rows = cast(list[object], cases)
    _require(
        all(isinstance(row, dict) and row.get("cleanup_complete") is True for row in case_rows),
        "capability cleanup case failed",
    )
    cleanup = cast(dict[str, Any], capability.get("cleanup"))
    final = cast(dict[str, Any], capability.get("final_inventory"))
    _require(cleanup == {"required": True, "complete": True}, "capability cleanup incomplete")
    _require(
        final.get("clean") is True and final.get("probe_residue") == 0, "final inventory not clean"
    )
    _require(capability.get("glue_job_runs") == 0, "Glue workload ran")
    _require(capability.get("step_functions_executions") == 0, "Step Functions workload ran")
    _require(capability.get("athena_queries_started") == 0, "Athena workload ran")
    _require(recovery.get("failure_hidden") is False, "failed attempt was hidden")
    _require(
        cast(dict[str, Any], recovery.get("recovery")).get("cleanup_complete") is True,
        "recovery incomplete",
    )
    transactions = publication.get("transactions")
    _require(
        isinstance(transactions, list),
        "publication transactions missing",
    )
    transaction_rows = cast(list[object], transactions)
    _require(
        [row.get("pull_request") for row in transaction_rows if isinstance(row, dict)]
        == [20, 21, 22, 23, 24],
        "publication chain differs",
    )
    _require(
        publication.get("qualified_operational_commit") == QUALIFIED_COMMIT,
        "publication head differs",
    )
    return {"read_only": read_only, "capability": capability}


def _validate_adjudications(root: Path) -> dict[str, Any]:
    requirements = _load(root, "spec/part3-stage2-requirement-adjudication-executed-v1.json")
    rows = requirements.get("requirements")
    _require(isinstance(rows, list), "executed requirement rows missing")
    requirement_rows = cast(list[object], rows)
    _require(
        [row.get("requirement_id") for row in requirement_rows if isinstance(row, dict)]
        == REQUIREMENT_IDS,
        "requirement identity/order differs",
    )
    _require(
        all(
            isinstance(row, dict)
            and row.get("verdict") == "EXTERNALLY_VERIFIED"
            and bool(row.get("evidence"))
            for row in requirement_rows
        ),
        "requirement is unverified",
    )
    _require(
        requirements.get("verified_count") == 22 and requirements.get("unadjudicated_count") == 0,
        "requirement totals differ",
    )
    gates = _load(root, "spec/part3-stage2-gate-adjudication-v1.json")
    gate_rows = gates.get("gates")
    _require(isinstance(gate_rows, list) and len(gate_rows) == 20, "Stage 2 gate count differs")
    stage_gate_rows = cast(list[object], gate_rows)
    _require(
        [row.get("gate_id") for row in stage_gate_rows if isinstance(row, dict)]
        == [f"P3-S2-G{i:03d}" for i in range(1, 21)],
        "Stage 2 gate identity/order differs",
    )
    states = [row.get("state") for row in stage_gate_rows if isinstance(row, dict)]
    _require(
        states == ["EXTERNALLY_VERIFIED"] * 19 + ["PENDING_EXTERNAL_CLOSURE"],
        "Stage 2 gate states differ",
    )
    master = _load(root, "spec/part3-stage2-master-gate-adjudication-v1.json")
    master_rows = master.get("gates")
    _require(isinstance(master_rows, list), "master gate rows missing")
    master_gate_rows = cast(list[object], master_rows)
    _require(
        [row.get("gate_id") for row in master_gate_rows if isinstance(row, dict)] == MASTER_GATES,
        "master gate identity/order differs",
    )
    master_states = [row.get("state") for row in master_gate_rows if isinstance(row, dict)]
    _require(
        master_states == ["AWS_VERIFIED"] * 3 + ["NOT_EXECUTED"] * 3, "master gate states differ"
    )
    gaps = _load(root, "spec/part3-gap-adjudication-v1.json")
    gap_rows = gaps.get("gaps")
    _require(isinstance(gap_rows, list) and len(gap_rows) == 11, "carryover count differs")
    carryover_rows = cast(list[object], gap_rows)
    gap_states = [row.get("state") for row in carryover_rows if isinstance(row, dict)]
    _require(gap_states == ["EXECUTED_VERIFIED"] + ["OWNED_OPEN"] * 10, "carryover states differ")
    return {"requirements": requirements, "gates": gates, "master": master}


def _validate_handoff_and_docs(root: Path) -> dict[str, Any]:
    handoff = _load(root, "contracts/part3-stage2-stage3-handoff-v1.json")
    _require(
        handoff.get("classification") == "PART3_STAGE2_TO_STAGE3_HANDOFF_CANDIDATE",
        "handoff state differs",
    )
    _require(
        handoff.get("qualified_operational_commit") == QUALIFIED_COMMIT, "handoff commit differs"
    )
    _require(handoff.get("to_stage") == "PART3_STAGE3", "next owner differs")
    _require(
        cast(dict[str, Any], handoff.get("verified")).get("requirements") == 22,
        "handoff requirement total differs",
    )
    boundary = cast(dict[str, Any], handoff.get("claim_boundary"))
    _require(
        boundary.get("managed_platform_deployed") is False
        and boundary.get("part3_complete") is False
        and boundary.get("project_complete") is False,
        "handoff claim inflated",
    )
    status = (root / "PROJECT_STATUS.md").read_text(encoding="utf-8")
    readme = (root / "README.md").read_text(encoding="utf-8")
    record = (root / "docs/part3-stage2-execution.md").read_text(encoding="utf-8")
    for text, marker in (
        (status, "PART3_STAGE2_CLOSURE_CANDIDATE"),
        (readme, "Part 3 Stage 2 closure candidate"),
        (record, "P3-S2-G020 remains pending"),
    ):
        _require(marker in text, f"documentation marker missing: {marker}")
    workflow = (root / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    _require("part3-stage2-closure:" in workflow, "closure CI job missing")
    _require("tools/run_part3_stage2_closure.py" in workflow, "closure runner missing")
    closure_block = workflow.split("part3-stage2-closure:", 1)[1]
    _require(
        "id-token: write" not in closure_block and "aws-actions/" not in closure_block,
        "closure CI can reach AWS",
    )
    return handoff


def _validate_quality(root: Path) -> None:
    quality = _load(root, "spec/part3-stage2-closure-coverage-v1.json")
    _require(
        quality
        == {
            "schema_version": "1.0",
            "production_surface": "ledgerguard_part3_stage2_closure",
            "minimum_statement_percent": 100.0,
            "minimum_branch_percent": 100.0,
            "mutation_classes": MUTATION_CLASSES,
        },
        "closure quality authority differs",
    )


def validate_stage2_closure(root: Path) -> dict[str, Any]:
    """Validate the full repository-resident Stage 2 closure candidate."""
    root = root.resolve()
    freeze = _validate_freeze(root)
    receipts = _validate_receipts(root)
    adjudications = _validate_adjudications(root)
    handoff = _validate_handoff_and_docs(root)
    for relative in CLOSURE_FILES:
        _require((root / relative).is_file(), f"closure file missing: {relative}")
    _validate_quality(root)
    closure_digest = sha256(
        "".join(f"{path}:{_digest(root / path)}\n" for path in CLOSURE_FILES).encode()
    ).hexdigest()
    return {
        "qualified_commit": freeze["qualified_commit"],
        "qualified_tree": freeze["qualified_tree"],
        "read_only_run": receipts["read_only"]["run"]["id"],
        "capability_run": receipts["capability"]["run"]["id"],
        "requirements_verified": adjudications["requirements"]["verified_count"],
        "stage2_gates_verified": adjudications["gates"]["premerge_verified_count"],
        "stage2_gate_pending_external": "P3-S2-G020",
        "master_gates_verified": adjudications["master"]["stage2_verified_gate_count"],
        "next_owner": handoff["to_stage"],
        "closure_candidate_digest": closure_digest,
        "aws_api_called": False,
        "managed_reconciliation_started": False,
        "part3_complete": False,
        "project_complete": False,
    }


def main() -> None:
    print(json.dumps(validate_stage2_closure(Path.cwd()), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
