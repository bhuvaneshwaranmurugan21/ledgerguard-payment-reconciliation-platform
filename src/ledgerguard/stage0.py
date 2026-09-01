"""Fail-closed validation for the Part 1 Stage 0 baseline audit."""

from __future__ import annotations

import json
from collections.abc import Mapping
from hashlib import sha256
from pathlib import Path
from typing import Any

PROJECT = "ledgerguard-payment-reconciliation-platform"
STAGE_STATE = "PART1_STAGE0_BASELINE_AUDIT_COMPLETE"
PART1_STATE = "PART1_FOUNDATION_CORRECTION_IN_PROGRESS"
BASE_SHA = "ae36abc157c3cfb018880314d5732e3d91d403bf"
DRAFT_SHA = "08066c92bb182ad6ec829d6feaf36dc34ad10d51"
MAIN_SHA = "7f36c7cd0e093f75e1e97cb99ba28d7fb4d69d07"
DISPOSITIONS = {"PRESERVE", "REPLACE", "DEFER", "EXCLUDE"}
REJECTED_RUNTIME = {"aws_evidence.py", "cli.py", "engine.py", "model.py", "simulator.py"}


class Stage0Error(ValueError):
    """Raised when the Stage 0 contract or evidence fails closed."""


def _load(path: Path) -> dict[str, Any]:
    try:
        value: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise Stage0Error(f"cannot load {path}: {error}") from error
    if not isinstance(value, dict):
        raise Stage0Error(f"JSON object required: {path}")
    return value


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise Stage0Error(message)


def _mapping(value: object, message: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise Stage0Error(message)
    return value


def validate_stage0(root: Path) -> dict[str, Any]:
    """Validate Stage 0 and return a deterministic evidence summary."""

    contract_path = root / "contracts/part1-stage0-completion-v1.json"
    evidence_path = root / "evidence/part1-stage0-local.json"
    gap_audit_path = root / "docs/gap-audit.md"
    contract = _load(contract_path)
    evidence = _load(evidence_path)

    _require(contract.get("project") == PROJECT, "project identity differs")
    _require(contract.get("stage") == 0, "stage must be zero")
    _require(contract.get("state") == STAGE_STATE, "Stage 0 state differs")
    _require(contract.get("overall_part1_state") == PART1_STATE, "Part 1 state differs")
    _require(
        contract.get("allowed_dispositions") == ["PRESERVE", "REPLACE", "DEFER", "EXCLUDE"],
        "disposition vocabulary differs",
    )

    history = _mapping(contract.get("history"), "history missing")
    _require(history.get("base_sha") == BASE_SHA, "base SHA differs")
    _require(history.get("rejected_draft_sha") == DRAFT_SHA, "draft SHA differs")
    _require(history.get("corrective_main_sha") == MAIN_SHA, "main SHA differs")
    rejected_pr = _mapping(history.get("rejected_pr"), "rejected PR evidence missing")
    corrective_pr = _mapping(history.get("corrective_pr"), "corrective PR evidence missing")
    _require(rejected_pr.get("number") == 1, "rejected PR number differs")
    _require(rejected_pr.get("state") == "CLOSED", "rejected PR must be closed")
    _require(rejected_pr.get("merged") is False, "rejected PR must be unmerged")
    _require(corrective_pr.get("number") == 2, "corrective PR number differs")
    _require(corrective_pr.get("state") == "CLOSED", "corrective PR must be closed")
    _require(corrective_pr.get("merged") is True, "corrective PR must be merged")

    boundary = _mapping(contract.get("execution_boundary"), "execution boundary missing")
    for field in (
        "aws_execution",
        "infrastructure_mutation",
        "schema_mutation",
        "reconciliation_engine_added",
    ):
        _require(boundary.get(field) is False, f"{field} must be false")

    inventory = _mapping(contract.get("draft_inventory"), "draft inventory missing")
    artifacts = inventory.get("artifacts")
    if not isinstance(artifacts, list):
        raise Stage0Error("draft artifacts must be a list")
    _require(inventory.get("file_count") == 32, "draft file count must be 32")
    _require(len(artifacts) == 32, "exactly 32 dispositions required")

    refs: set[str] = set()
    counts = {name: 0 for name in sorted(DISPOSITIONS)}
    for item_value in artifacts:
        item = _mapping(item_value, "every disposition must be an object")
        ref = item.get("ref")
        disposition = item.get("disposition")
        reason = item.get("reason")
        if not isinstance(ref, str) or not ref:
            raise Stage0Error("artifact reference missing")
        _require(ref not in refs, f"duplicate artifact reference: {ref}")
        refs.add(ref)
        if not isinstance(disposition, str) or disposition not in DISPOSITIONS:
            raise Stage0Error(f"unknown disposition: {disposition}")
        if not isinstance(reason, str) or not reason.strip():
            raise Stage0Error(f"reason missing for {ref}")
        if disposition in {"REPLACE", "DEFER"}:
            owner = item.get("owner")
            _require(isinstance(owner, str) and bool(owner), f"owner missing for {ref}")
        counts[disposition] += 1

    expected_contract_digest = sha256(contract_path.read_bytes()).hexdigest()
    expected_gap_audit_digest = sha256(gap_audit_path.read_bytes()).hexdigest()
    _require(evidence.get("project") == PROJECT, "evidence project differs")
    _require(evidence.get("stage") == 0, "evidence stage differs")
    _require(evidence.get("stage_state") == STAGE_STATE, "evidence Stage 0 state differs")
    _require(evidence.get("overall_part1_state") == PART1_STATE, "evidence Part 1 state differs")
    _require(evidence.get("base_sha") == BASE_SHA, "evidence base SHA differs")
    _require(evidence.get("draft_sha") == DRAFT_SHA, "evidence draft SHA differs")
    _require(evidence.get("main_sha") == MAIN_SHA, "evidence main SHA differs")
    _require(evidence.get("draft_blob_integrity") == "VERIFIED_32_OF_32", "draft blobs unverified")
    _require(evidence.get("contract_sha256") == expected_contract_digest, "contract digest differs")
    _require(
        evidence.get("gap_audit_sha256") == expected_gap_audit_digest,
        "gap audit digest differs",
    )
    _require(evidence.get("draft_file_count") == 32, "evidence draft count differs")
    _require(evidence.get("disposition_counts") == counts, "disposition counts differ")
    _require(evidence.get("aws_execution") is False, "evidence claims AWS execution")
    _require(evidence.get("infrastructure_mutation") is False, "evidence claims mutation")
    _require(evidence.get("schemas_changed") is False, "evidence claims schema change")
    _require(evidence.get("reconciliation_engine_added") is False, "evidence claims engine")
    _require(evidence.get("schema_digests") == _schema_digests(root), "schema bytes differ")

    package_files = {path.name for path in (root / "src/ledgerguard").glob("*.py")}
    _require(not package_files.intersection(REJECTED_RUNTIME), "rejected runtime present")

    payload: dict[str, Any] = {
        "project": PROJECT,
        "stage": 0,
        "stage_state": STAGE_STATE,
        "overall_part1_state": PART1_STATE,
        "base_sha": BASE_SHA,
        "draft_sha": DRAFT_SHA,
        "main_sha": MAIN_SHA,
        "draft_file_count": len(artifacts),
        "disposition_counts": counts,
        "aws_execution": False,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    payload["stage0_sha256"] = sha256(canonical).hexdigest()
    return payload


def _schema_digests(root: Path) -> dict[str, str]:
    return {
        path.name: sha256(path.read_bytes()).hexdigest()
        for path in sorted((root / "contracts").glob("*.schema.json"))
    }
