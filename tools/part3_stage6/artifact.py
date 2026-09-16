"""Build and independently inspect sanitized Stage 6 plan-only evidence."""

from __future__ import annotations

import hashlib
import json
import re
import zipfile
from decimal import Decimal, InvalidOperation
from pathlib import Path, PurePosixPath
from typing import Any

HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
REQUIRED_MEMBERS = {"evidence.json", "command-journal.json", "manifest.json"}
PROHIBITED_NAMES = {"terraform.tfstate", "terraform.tfplan", "plan.json", ".tflock"}
PROHIBITED_COMMAND_TERMS = {
    "apply",
    "force-unlock",
    "import",
    "-target",
    "-refresh=false",
    "-lock=false",
}
PROHIBITED_API_TERMS = {
    "startjobrun",
    "startqueryexecution",
    "startexecution",
    "invokefunction",
    "createfunction",
    "createjob",
    "createtable",
    "createstatemachine",
}


def canonical(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        + b"\n"
    )


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _array(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be an array")
    return value


def validate_evidence(evidence: dict[str, Any], journal: list[Any]) -> dict[str, Any]:
    if evidence.get("schema_version") != "ledgerguard.part3-stage6-plan-only-evidence.v1":
        raise ValueError("Stage 6 evidence schema differs")
    source = _object(evidence.get("source"), "source")
    if HEX40.fullmatch(str(source.get("commit", ""))) is None:
        raise ValueError("source commit invalid")
    if HEX40.fullmatch(str(source.get("tree", ""))) is None:
        raise ValueError("source tree invalid")
    if source.get("ref") != "refs/heads/main" or source.get("event") != "workflow_dispatch":
        raise ValueError("source event boundary differs")
    if re.fullmatch(r"[1-9][0-9]*", str(source.get("workflow_run_id", ""))) is None:
        raise ValueError("workflow run identity invalid")
    if re.fullmatch(r"[1-9][0-9]*", str(source.get("workflow_run_attempt", ""))) is None:
        raise ValueError("workflow run attempt invalid")
    target = _object(evidence.get("target"), "target")
    if target != {"account": "857229544428", "region": "ap-southeast-2"}:
        raise ValueError("target differs")
    bindings = _object(evidence.get("bindings"), "bindings")
    if set(bindings) != {
        "administrator_packet_sha256",
        "administrator_receipt_sha256",
        "stage5_runtime_package_sha256",
        "stage5_manifest_sha256",
        "stage5_script_sha256",
        "stage5_wheels_sha256",
        "lock_sha256",
    }:
        raise ValueError("source binding inventory differs")
    for name, value in bindings.items():
        if name == "lock_sha256":
            continue
        if HEX64.fullmatch(str(value)) is None:
            raise ValueError(f"source binding invalid: {name}")
    locks = _object(bindings["lock_sha256"], "lock bindings")
    if set(locks) != {"terraform", "bootstrap", "python311", "parser"} or any(
        HEX64.fullmatch(str(value)) is None for value in locks.values()
    ):
        raise ValueError("lock binding inventory differs")
    if _object(evidence.get("toolchain"), "toolchain") != {
        "terraform": "1.13.1",
        "aws_provider": "6.11.0",
    }:
        raise ValueError("toolchain differs")
    backend = _object(evidence.get("backend"), "backend")
    if (
        HEX64.fullmatch(str(backend.get("state_key_sha256", ""))) is None
        or backend.get("state_absent_before_and_after") is not True
    ):
        raise ValueError("backend evidence differs")
    budget = _object(evidence.get("budget"), "budget")
    if (
        not isinstance(budget.get("billing_observed_epoch"), int)
        or isinstance(budget.get("billing_observed_epoch"), bool)
        or budget.get("billing_classification") != "COST_EXPLORER_DELAYED_WITH_CONSERVATIVE_RESERVE"
        or budget.get("estimated_monthly_standing_usd") != "0.00"
        or budget.get("assumptions")
        != [
            "plan-only; no managed resources created",
            "provider control-plane reads only",
            "no reconciliation, Glue, Athena, Step Functions or Lambda workload",
        ]
    ):
        raise ValueError("budget evidence classification differs")
    try:
        amounts = [
            Decimal(str(budget[name]))
            for name in (
                "known_gross_usd",
                "reserved_stage6_exposure_usd",
                "cleanup_reserve_usd",
            )
        ]
        ceiling = Decimal(str(budget["strict_ceiling_usd"]))
    except (KeyError, InvalidOperation) as exc:
        raise ValueError("budget evidence amount invalid") from exc
    if min(amounts) < 0 or ceiling != Decimal("10") or sum(amounts) >= ceiling:
        raise ValueError("budget evidence ceiling not admitted")
    gates = _object(evidence.get("gates"), "gates")
    if set(gates) != {"S6-G01", "S6-G02", "S6-G03", "S6-G04"}:
        raise ValueError("gate inventory differs")
    if gates["S6-G04"] is not False:
        raise ValueError("producer cannot self-admit independent inspection")
    for name in ("S6-G01", "S6-G02", "S6-G03"):
        if gates[name] is not True:
            raise ValueError(f"producer gate incomplete: {name}")
    plan = _object(evidence.get("plan"), "plan")
    for key in ("binary_sha256", "json_sha256", "variable_sha256", "policy_sha256"):
        if HEX64.fullmatch(str(plan.get(key, ""))) is None:
            raise ValueError(f"plan digest invalid: {key}")
    if plan.get("resource_changes") != 33 or plan.get("create_actions") != 33:
        raise ValueError("plan graph differs")
    if plan.get("other_actions") != 0 or plan.get("applied") is not False:
        raise ValueError("plan contains non-create action or apply")
    preflight = _object(evidence.get("preflight"), "preflight")
    required = (
        "exact_identity",
        "installed_iam",
        "effective_permissions",
        "restrictions_resolved",
        "backend_admitted",
        "lease_acquired",
        "budget_admitted",
        "quota_admitted",
        "inventory_clean",
    )
    if any(preflight.get(name) is not True for name in required):
        raise ValueError("preflight is incomplete")
    closure = _object(evidence.get("closure"), "closure")
    if closure != {
        "apply_calls": 0,
        "workload_calls": 0,
        "post_inventory_clean": True,
        "lease_released": True,
        "backend_lock_absent": True,
        "recovery_required": False,
        "stage6_complete": False,
        "terminal_state": "awaiting_independent_inspection",
    }:
        raise ValueError("producer closure differs")
    for raw in journal:
        row = _object(raw, "journal row")
        command = row.get("command")
        if (
            not isinstance(command, list)
            or not command
            or not all(isinstance(x, str) for x in command)
        ):
            raise ValueError("journal command invalid")
        lowered = " ".join(command).lower()
        if any(term in lowered for term in PROHIBITED_COMMAND_TERMS):
            raise ValueError("prohibited Terraform command recorded")
        operation = str(row.get("operation", "")).lower().replace("_", "")
        if any(term in operation for term in PROHIBITED_API_TERMS):
            raise ValueError("prohibited workload or resource API recorded")
        expected_exit = 2 if row.get("operation") == "terraform-plan" else 0
        if row.get("exit_code") != expected_exit:
            raise ValueError("journal contains unsuccessful operation")
    return {
        "source_commit": source["commit"],
        "source_tree": source["tree"],
        "resources": 33,
        "apply_calls": 0,
        "workload_calls": 0,
        "producer_gates": 3,
    }


def build_artifact(output: Path, evidence: dict[str, Any], journal: list[Any]) -> str:
    validate_evidence(evidence, journal)
    if output.exists() or output.is_symlink():
        raise ValueError("artifact output already exists")
    members = {"evidence.json": canonical(evidence), "command-journal.json": canonical(journal)}
    manifest = {
        "schema_version": "ledgerguard.part3-stage6-artifact-manifest.v1",
        "members": {
            name: {"sha256": sha256(data), "size": len(data)}
            for name, data in sorted(members.items())
        },
    }
    members["manifest.json"] = canonical(manifest)
    with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in sorted(members.items()):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100600 << 16
            archive.writestr(info, data)
    return sha256(output.read_bytes())


def inspect_artifact(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise ValueError("regular artifact file required")
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        for info in infos:
            pure = PurePosixPath(info.filename)
            if pure.is_absolute() or ".." in pure.parts or info.is_dir():
                raise ValueError("unsafe artifact member")
            if pure.name in PROHIBITED_NAMES or info.file_size > 5_000_000:
                raise ValueError("sensitive or oversized artifact member")
        if len(names) != len(set(names)) or set(names) != REQUIRED_MEMBERS:
            raise ValueError("artifact member inventory differs")
        raw = {name: archive.read(name) for name in names}
    manifest = _object(json.loads(raw["manifest.json"]), "manifest")
    if manifest.get("schema_version") != "ledgerguard.part3-stage6-artifact-manifest.v1":
        raise ValueError("manifest schema differs")
    listed = _object(manifest.get("members"), "manifest members")
    if set(listed) != REQUIRED_MEMBERS - {"manifest.json"}:
        raise ValueError("manifest member inventory differs")
    for name, metadata in listed.items():
        item = _object(metadata, f"manifest {name}")
        if item != {"sha256": sha256(raw[name]), "size": len(raw[name])}:
            raise ValueError(f"manifest binding differs: {name}")
    evidence = _object(json.loads(raw["evidence.json"]), "evidence")
    journal = _array(json.loads(raw["command-journal.json"]), "journal")
    verdict = validate_evidence(evidence, journal)
    return {
        "classification": "STAGE6_ARTIFACT_INDEPENDENTLY_INSPECTED",
        "artifact_sha256": sha256(path.read_bytes()),
        **verdict,
        "S6-G04": True,
        "terminal_state": "plan_only_verified",
        "stage6_complete": True,
        "part3_complete": False,
    }
