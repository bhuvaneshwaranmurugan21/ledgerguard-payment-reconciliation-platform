"""Fail-closed LedgerGuard Part 1 Stage 7 promotion-candidate validation."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping
from hashlib import sha256
from pathlib import Path
from typing import Any

from ledgerguard_correction_c4 import C4Error, validate_stage6

PROJECT = "ledgerguard-payment-reconciliation-platform"
STAGE7_IDS = [f"OP-S7-R{number:03d}" for number in range(1, 27)]
GATE_IDS = [f"OP-GATE-R{number:03d}" for number in range(1, 15)]
EXPECTED_OWNER_COUNTS = {
    "C0": 8,
    "C1": 4,
    "C2": 6,
    "C3": 24,
    "C4": 9,
    "C5": 15,
    "C6": 20,
    "C7": 10,
}
EXPECTED_STAGE6 = {
    "commit_sha": "6e9a6f315c1e3bfc309494f22c331621a3bc64f5",
    "tree_sha": "52ee74d4a5216141948e49abccc45d8ff6caf65e",
    "workflow_run_id": 33609507209,
    "workflow_run_attempt": 1,
    "workflow_conclusion": "success",
    "artifact_id": 9838502686,
    "artifact_zip_sha256": "12622a5fdfc62d5a8fb5ba1f75883f765a0a217696878c468c27e3cc4a3501dd",
    "evidence_json_sha256": "9df86e50311891308c4356533a03a929a3686d121559650fe2283bf0750a1afb",
    "deterministic_payload_sha256": (
        "53c12723ef35508ee607e990453c2941959f93a017e657b968ec08ee44821c5c"
    ),
    "foundation_digest": "3f315ecf51a89d95c77d1b22db4c5cd039a32c752cbd70715097987300031f59",
}
EXPECTED_EXTERNAL_CLOSURE = [
    "EXACT_HEAD_PR_CI_PASS_AFTER_FINAL_STATE_COMMIT",
    "PR_READY_ONLY_AFTER_EXACT_HEAD_CI_PASS",
    "NO_MERGE_CONFLICT_IMMEDIATELY_BEFORE_MERGE",
    "SQUASH_ONLY_VALIDATED_IMMUTABLE_HEAD",
    "INDEPENDENT_MAIN_PUSH_CI_PASS",
    "POSTMERGE_FOUNDATION_DIGEST_MATCH",
    "POSTMERGE_NO_AWS_EXECUTION_OR_MUTATION",
    "NO_OPEN_CORRECTIVE_PR",
]


class C5Error(ValueError):
    """Raised when Stage 7 promotion evidence or state is incomplete."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise C5Error(message)


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise C5Error(f"JSON object required: {path}")
    return dict(value)


def _digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _stage7_source_ids(root: Path) -> list[str]:
    authority = _load(root / "spec/part1-original-requirements-v1.json")
    return [
        str(row["id"])
        for row in authority["requirements"]
        if isinstance(row, Mapping) and str(row.get("id", "")).startswith("OP-S7-")
    ]


def _validate_requirement_reaudit(root: Path, audit: Mapping[str, Any]) -> list[str]:
    ledger = _load(root / "spec/part1-requirement-ledger-v1.json")
    requirements = ledger.get("requirements")
    if not isinstance(requirements, list):
        raise C5Error("requirement ledger is missing")
    rows = [row for row in requirements if isinstance(row, Mapping)]
    ids = [str(row.get("requirement_id")) for row in rows]
    _require(len(rows) == 331 and len(set(ids)) == 331, "331 unique requirements required")

    preserved = [row for row in rows if row.get("baseline_verdict") == "PASS"]
    nonpass = [row for row in rows if row.get("baseline_verdict") != "PASS"]
    _require(len(preserved) == 235 and len(nonpass) == 96, "immutable Phase 8 counts differ")
    _require(
        all(row.get("resolution_state") == "PRESERVED_PHASE8_PASS" for row in preserved),
        "historical pass was not preserved",
    )
    owner_counts = Counter(str(row.get("correction_owner")) for row in nonpass)
    _require(dict(owner_counts) == EXPECTED_OWNER_COUNTS, "non-pass owner inventory differs")

    requirement_audit = audit.get("requirement_reaudit")
    if not isinstance(requirement_audit, Mapping):
        raise C5Error("requirement re-audit is missing")
    _require(requirement_audit.get("requirements_total") == 331, "audit total differs")
    _require(requirement_audit.get("historical_pass_preserved") == 235, "pass count differs")
    _require(requirement_audit.get("historical_nonpass_reaudited") == 96, "non-pass count differs")
    _require(requirement_audit.get("owner_counts") == EXPECTED_OWNER_COUNTS, "owner counts differ")
    evidence_by_owner = requirement_audit.get("evidence_by_owner")
    if not isinstance(evidence_by_owner, Mapping):
        raise C5Error("owner evidence map is missing")
    _require(set(evidence_by_owner) == set(EXPECTED_OWNER_COUNTS), "owner evidence scope differs")
    for owner, raw_paths in evidence_by_owner.items():
        if not isinstance(raw_paths, list) or not raw_paths:
            raise C5Error(f"evidence missing for {owner}")
        for raw_path in raw_paths:
            path = root / str(raw_path)
            _require(path.is_file(), f"owner evidence path missing: {raw_path}")
    return ids


def _validate_gate_reaudit(root: Path, audit: Mapping[str, Any]) -> list[str]:
    registry = _load(root / "spec/part1-gate-registry-v1.json")
    gates = registry.get("gates")
    if not isinstance(gates, list):
        raise C5Error("gate registry is missing")
    gate_ids = [str(row.get("gate_id")) for row in gates if isinstance(row, Mapping)]
    _require(gate_ids == GATE_IDS, "exact 14-gate inventory differs")
    gate_audit = audit.get("gate_reaudit")
    if not isinstance(gate_audit, Mapping):
        raise C5Error("gate re-audit is missing")
    _require(gate_audit.get("mandatory_gates_total") == 14, "gate total differs")
    _require(gate_audit.get("premerge_candidate_pass") == 13, "premerge gate count differs")
    _require(
        gate_audit.get("postmerge_external_pending") == ["OP-GATE-R014"],
        "post-merge gate boundary differs",
    )
    return gate_ids


def _validate_status(root: Path) -> None:
    status = (root / "PROJECT_STATUS.md").read_text(encoding="utf-8")
    for required in (
        "Part: 1 — Foundation and completion contract",
        "State: `PART1_FOUNDATION_COMPLETE`",
        "Highest claim: `LOCAL_VERIFIED` for foundation validation",
        "AWS execution: false",
        "AWS infrastructure mutated: false",
        "Part 2 entry: `UNLOCKED_AFTER_POSTMERGE_MAIN_CI_PASS`",
    ):
        _require(required in status, f"Stage 7 status line missing: {required}")
    _require("PART1_CORRECTION_IN_PROGRESS" not in status, "active status remains corrective")


def _validate_workflow(root: Path) -> None:
    workflow = (root / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    _require("-m ledgerguard_correction_c5" in workflow, "Stage 7 CI gate missing")
    stage7_block = workflow.split("- name: Validate Stage 7 promotion candidate", 1)[-1].split(
        "- name: Build trusted CI evidence envelope", 1
    )[0]
    _require(
        '"$RUNNER_TEMP/ledgerguard-stage6/run-1/venv/bin/python"' in stage7_block,
        "Stage 7 CI must use the locked clean environment",
    )
    _require("github.event.pull_request.head.sha" in workflow, "raw PR head control missing")
    _require("aws-actions/" not in workflow, "Stage 7 CI includes an AWS action")
    _require("id-token: write" not in workflow, "Stage 7 CI requests an OIDC token")


def validate_stage7(root: Path | None = None) -> dict[str, Any]:
    """Validate the repository-resident Stage 7 promotion candidate."""

    repository = (root or Path.cwd()).resolve()
    try:
        stage6 = validate_stage6(repository)
    except C4Error as error:
        raise C5Error(f"Stage 6 regression failed: {error}") from error
    contract = _load(repository / "contracts/part1-stage7-promotion-v1.json")
    audit = _load(repository / "evidence/part1-stage7-premerge-audit-v1.json")
    manifest = _load(repository / "evidence/part1-stage6-ci-evidence-manifest-v1.json")

    _require(contract.get("project") == PROJECT and contract.get("stage") == 7, "identity differs")
    _require(contract.get("state") == "PART1_FOUNDATION_COMPLETE", "completion state differs")
    _require(
        contract.get("part2_entry") == "UNLOCKED_AFTER_POSTMERGE_MAIN_CI_PASS",
        "Part 2 entry condition differs",
    )
    _require(
        contract.get("stage6_entry_checkpoint") == EXPECTED_STAGE6, "Stage 6 checkpoint differs"
    )
    _require(
        manifest.get("artifact_id") == EXPECTED_STAGE6["artifact_id"]
        and manifest.get("artifact_zip_sha256") == EXPECTED_STAGE6["artifact_zip_sha256"]
        and manifest.get("evidence_sha256") == EXPECTED_STAGE6["evidence_json_sha256"],
        "Stage 6 artifact manifest differs",
    )
    _require(
        manifest.get("commit_sha") == EXPECTED_STAGE6["commit_sha"]
        and manifest.get("workflow_run_id") == str(EXPECTED_STAGE6["workflow_run_id"])
        and manifest.get("workflow_run_attempt") == "1",
        "Stage 6 workflow identity differs",
    )
    _require(audit.get("historical_phase8_verdict_mutated") is False, "Phase 8 was relabelled")
    _require(audit.get("external_closure_required") == EXPECTED_EXTERNAL_CLOSURE, "closure differs")
    findings = audit.get("findings")
    _require(findings == {"critical": 0, "major": 0}, "blocking finding remains")
    boundary = audit.get("execution_boundary")
    _require(
        boundary
        == {
            "aws_api_called": False,
            "aws_workflow_dispatched": False,
            "infrastructure_mutated": False,
        },
        "Stage 7 execution boundary differs",
    )
    failure = contract.get("failure_policy")
    if not isinstance(failure, Mapping):
        raise C5Error("failure policy is weakened")
    _require(all(bool(value) for value in failure.values()), "failure policy is weakened")
    claims = contract.get("claim_boundary")
    if not isinstance(claims, Mapping):
        raise C5Error("claim boundary is missing")
    _require(claims.get("highest_part1_claim") == "LOCAL_VERIFIED", "claim is inflated")
    _require(claims.get("aws_execution") is False, "AWS execution was claimed")
    _require(claims.get("aws_infrastructure_mutated") is False, "AWS mutation was claimed")

    _require(_stage7_source_ids(repository) == STAGE7_IDS, "Stage 7 source inventory differs")
    requirement_ids = _validate_requirement_reaudit(repository, audit)
    gate_ids = _validate_gate_reaudit(repository, audit)
    _validate_status(repository)
    _validate_workflow(repository)
    payload: dict[str, Any] = {
        "project": PROJECT,
        "part": 1,
        "stage": 7,
        "state": "PART1_FOUNDATION_COMPLETE",
        "part2_entry": "UNLOCKED_AFTER_POSTMERGE_MAIN_CI_PASS",
        "requirements": {"total": len(requirement_ids), "reaudited_nonpass": 96},
        "gates": {"total": len(gate_ids), "premerge_candidate_pass": 13, "postmerge_pending": 1},
        "stage6_foundation_digest": stage6["foundation_digest"],
        "stage6_entry_checkpoint": EXPECTED_STAGE6,
        "blocking_findings": {"critical": 0, "major": 0},
        "external_closure_required": EXPECTED_EXTERNAL_CLOSURE,
        "aws_execution": False,
        "infrastructure_mutation": False,
        "authority_digests": {
            relative: _digest(repository / relative)
            for relative in (
                "contracts/part1-stage7-promotion-v1.json",
                "evidence/part1-stage6-ci-evidence-manifest-v1.json",
                "evidence/part1-stage7-premerge-audit-v1.json",
                "docs/stage7-gap-audit.md",
                "docs/adr/0015-fail-closed-stage7-promotion.md",
            )
        },
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    payload["stage7_candidate_digest"] = sha256(encoded).hexdigest()
    return payload


def main() -> None:
    print(json.dumps(validate_stage7(Path.cwd()), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
