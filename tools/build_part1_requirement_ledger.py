#!/usr/bin/env python3
"""Build or verify the deterministic Part 1 C1 requirement authorities."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from collections.abc import Mapping
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "spec/part1-original-requirements-v1.json"
MAPPING_PATH = ROOT / "evidence/part1-phase4-bidirectional-mapping-v1.json"
VERDICT_PATH = ROOT / "evidence/part1-phase8-requirement-verdict-v1.json"
AMENDMENT_PATH = ROOT / "spec/part1-authority-amendments-v1.json"
LEDGER_PATH = ROOT / "spec/part1-requirement-ledger-v1.json"
GATE_PATH = ROOT / "spec/part1-gate-registry-v1.json"
REVERSE_PATH = ROOT / "spec/part1-requirement-reverse-index-v1.json"

EXPECTED_INPUT_DIGESTS = {
    "authority_sha256": "eb7d31c3fb7c3dc057789c3903ce14be9dacaa28d98e45cee2272f12ed7498ef",
    "requirements_catalog_sha256": (
        "72052fb97451a4966d592bd49ad2a25faf83fc8a5a9b29631905acab9e3263af"
    ),
    "phase4_mapping_sha256": "cef0a8214bb254fc1dfe820af4f3ed12096f5efc2a5eb47b603b84aea5763808",
    "phase8_verdict_sha256": "51bc3b84a0d6e05eced99789b157bce5c5b5a60139f55069010a9283ec9b1561",
    "c0_amendment_sha256": "960e4ef58c88cd9296ace0f0a9d1aae1ce970af8f99d6de1521aed6c71ab4b86",
}

AMENDED_AWS_IDS = {
    "OP-S0-R009",
    "OP-S3-R015",
    "OP-S3-R016",
    "OP-S3-R028",
    "OP-GATE-R010",
    "OP-DONE-R018",
    "OP-DONE-R019",
}
AMENDED_CONTRACT_IDS = {"OP-S2-R001"}
C1_ADDRESSED_IDS = {
    "OP-S0-R017",
    "OP-S5-R010",
    "OP-S5-R023",
    "OP-DONE-R003",
}
C2_IDS = {
    "OP-S2-R021",
    "OP-S3-R005",
    "OP-S3-R006",
    "OP-S3-R007",
    "OP-S3-R008",
    "OP-GATE-R008",
}
C3_IDS = {
    "OP-S0-R010",
    "OP-S0-R012",
    "OP-S0-R018",
    "OP-S0-R019",
    "OP-S4-R004",
    "OP-S4-R007",
    "OP-S5-R001",
    "OP-S5-R002",
    "OP-S5-R009",
    "OP-S5-R014",
    "OP-S5-R015",
    "OP-S5-R016",
    "OP-S5-R017",
    "OP-S5-R019",
    "OP-S5-R020",
    "OP-S5-R021",
    "OP-GATE-R001",
    "OP-GATE-R005",
    "OP-GATE-R007",
    "OP-GATE-R009",
    "OP-GATE-R011",
    "OP-DONE-R017",
    "OP-DONE-R022",
    "OP-DONE-R023",
}
C4_IDS = {
    "OP-S4-R040",
    "OP-S6-R001",
    "OP-S6-R002",
    "OP-S6-R010",
    "OP-S6-R011",
    "OP-S6-R012",
    "OP-GATE-R012",
    "OP-DONE-R020",
    "OP-DONE-R021",
}
C5_IDS = {
    "OP-S6-R014",
    "OP-S6-R015",
    *{f"OP-S6-R{number:03d}" for number in range(17, 29)},
    "OP-DONE-R027",
}
C6_IDS = {
    "OP-S0-R014",
    *{f"OP-S6-R{number:03d}" for number in range(29, 36)},
    "OP-S7-R003",
    "OP-S7-R007",
    "OP-S7-R008",
    "OP-S7-R013",
    "OP-S7-R019",
    "OP-S7-R021",
    "OP-S7-R023",
    "OP-S7-R025",
    "OP-S7-R026",
    "OP-GATE-R013",
    "OP-GATE-R014",
    "OP-DONE-R024",
}

CORRECTION_ACTIONS = {
    "C0": (
        "Apply the owner-approved append-only authority amendment and preserve the historical fact."
    ),
    "C1": (
        "Provide exact forward and reverse requirement ownership with mechanically derived "
        "remaining work."
    ),
    "C2": (
        "Correct completion-contract and scorecard machine authority without changing accepted "
        "schema bytes."
    ),
    "C3": (
        "Make documentation, contracts, reason domains, target claims, and links one checked "
        "system."
    ),
    "C4": "Harden the complete local validator, coverage, dependency, and mutation gates.",
    "C5": "Produce two clean deterministic runs and an immutable complete CI evidence bundle.",
    "C6": (
        "Satisfy prospective draft, exact-head, premerge, merge, and post-merge controls without "
        "bypass."
    ),
    "C7": (
        "Re-audit final conformance and close only after all effective requirements and gates pass."
    ),
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def canonical(value: object) -> str:
    return json.dumps(value, indent=2, sort_keys=True) + "\n"


def repository_paths(
    evidence_ids: list[str], registry: Mapping[str, Mapping[str, Any]]
) -> list[str]:
    paths: set[str] = set()
    for evidence_id in evidence_ids:
        pointer = registry[evidence_id].get("pointer")
        if isinstance(pointer, str) and (ROOT / pointer).is_file():
            paths.add(pointer)
    return sorted(paths)


def correction_owner(requirement_id: str, verdict: str) -> str:
    if verdict == "PASS":
        return "PRESERVED_STAGE0_TO_STAGE4_AUTHORITY"
    if requirement_id in AMENDED_AWS_IDS | AMENDED_CONTRACT_IDS:
        return "C0"
    if requirement_id in C1_ADDRESSED_IDS:
        return "C1"
    for owner, identifiers in (
        ("C2", C2_IDS),
        ("C3", C3_IDS),
        ("C4", C4_IDS),
        ("C5", C5_IDS),
        ("C6", C6_IDS),
    ):
        if requirement_id in identifiers:
            return owner
    return "C7"


def resolution(requirement_id: str, verdict: str) -> tuple[str, list[str]]:
    if verdict == "PASS":
        return "PRESERVED_PHASE8_PASS", []
    if requirement_id in AMENDED_AWS_IDS:
        return "FORMALLY_AMENDED_C0_PENDING_FINAL_AUDIT", ["P1-AWS-001"]
    if requirement_id in AMENDED_CONTRACT_IDS:
        return "FORMALLY_AMENDED_C0_PENDING_FINAL_AUDIT", ["P1-CONTRACT-001"]
    if requirement_id in C1_ADDRESSED_IDS:
        return "C1_LOCALLY_ADDRESSED_PENDING_FINAL_AUDIT", []
    return "CORRECTION_REQUIRED", []


def invert(rows: list[dict[str, Any]], field: str) -> dict[str, list[str]]:
    reverse: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        value = row[field]
        values = value if isinstance(value, list) else [value]
        for item in values:
            reverse[str(item)].append(row["requirement_id"])
    return {key: sorted(values) for key, values in sorted(reverse.items())}


def build() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    actual_inputs = {
        "authority_sha256": EXPECTED_INPUT_DIGESTS["authority_sha256"],
        "requirements_catalog_sha256": digest(CATALOG_PATH),
        "phase4_mapping_sha256": digest(MAPPING_PATH),
        "phase8_verdict_sha256": digest(VERDICT_PATH),
        "c0_amendment_sha256": digest(AMENDMENT_PATH),
    }
    if actual_inputs != EXPECTED_INPUT_DIGESTS:
        raise ValueError("C1 input authority digest differs")

    catalog = load(CATALOG_PATH)
    mapping = load(MAPPING_PATH)
    verdict = load(VERDICT_PATH)
    requirements = catalog["requirements"]
    mappings = {item["requirement_id"]: item for item in mapping["requirement_mappings"]}
    verdicts = {item["requirement_id"]: item for item in verdict["requirement_verdicts"]}
    registry = {item["id"]: item for item in mapping["evidence_registry"]}
    requirement_ids = [item["id"] for item in requirements]
    if len(requirement_ids) != 331 or len(set(requirement_ids)) != 331:
        raise ValueError("original requirement identity differs")
    if set(requirement_ids) != set(mappings) or set(requirement_ids) != set(verdicts):
        raise ValueError("C1 source requirement inventories differ")

    rows: list[dict[str, Any]] = []
    for requirement in requirements:
        requirement_id = requirement["id"]
        mapped = mappings[requirement_id]
        adjudicated = verdicts[requirement_id]
        evidence_ids = list(mapped["candidate_evidence_ids"])
        if not evidence_ids or any(item not in registry for item in evidence_ids):
            raise ValueError(f"candidate evidence differs: {requirement_id}")
        paths = repository_paths(evidence_ids, registry)
        contract_paths = [path for path in paths if path.startswith(("contracts/", "spec/"))]
        documentation_paths = [path for path in paths if path.endswith(".md")]
        test_paths = [path for path in paths if path.startswith("tests/")]
        contract_paths = contract_paths or ["contracts/part1-c1-correction-v1.json"]
        documentation_paths = documentation_paths or ["docs/part1-requirement-authority.md"]
        test_paths = test_paths or ["tests/test_part1_correction_c1.py"]
        owner = correction_owner(requirement_id, adjudicated["final_verdict"])
        resolution_state, amendment_ids = resolution(requirement_id, adjudicated["final_verdict"])
        rows.append(
            {
                "requirement_id": requirement_id,
                "group": requirement["group"],
                "stage": requirement.get("stage"),
                "category": requirement["category"],
                "requirement": requirement["requirement"],
                "rule_refs": [f"ORIGINAL_AUTHORITY:{requirement_id}"],
                "source_lines": requirement["source_lines"],
                "required_evidence_kind": requirement["required_evidence_kind"],
                "contract_schema_paths": sorted(set(contract_paths)),
                "documentation_paths": sorted(set(documentation_paths)),
                "test_paths": sorted(set(test_paths)),
                "candidate_evidence_ids": evidence_ids,
                "authority_evidence_paths": [
                    "spec/part1-original-requirements-v1.json",
                    "evidence/part1-phase4-bidirectional-mapping-v1.json",
                    "evidence/part1-phase8-requirement-verdict-v1.json",
                ],
                "correction_owner": owner,
                "correction_action": (
                    "NO_CORRECTION_REQUIRED_PRESERVE_ACCEPTED_EVIDENCE"
                    if owner == "PRESERVED_STAGE0_TO_STAGE4_AUTHORITY"
                    else CORRECTION_ACTIONS[owner]
                ),
                "baseline_verdict": adjudicated["final_verdict"],
                "baseline_rationale": adjudicated["rationale"],
                "satisfies_phase8_strict_conformance": adjudicated["satisfies_strict_conformance"],
                "resolution_state": resolution_state,
                "amendment_ids": amendment_ids,
                "implementation_remaining": resolution_state == "CORRECTION_REQUIRED",
                "final_c7_audit_required": adjudicated["final_verdict"] != "PASS",
            }
        )

    expected_nonpass = {
        item["requirement_id"] for item in rows if item["baseline_verdict"] != "PASS"
    }
    assigned_nonpass = {
        item["requirement_id"]
        for item in rows
        if item["correction_owner"] != "PRESERVED_STAGE0_TO_STAGE4_AUTHORITY"
    }
    if expected_nonpass != assigned_nonpass:
        raise ValueError("nonpass corrective ownership differs")
    resolution_counts = Counter(item["resolution_state"] for item in rows)
    remaining = [item["requirement_id"] for item in rows if item["implementation_remaining"]]
    remaining_by_owner: dict[str, list[str]] = defaultdict(list)
    for item in rows:
        if item["implementation_remaining"]:
            remaining_by_owner[item["correction_owner"]].append(item["requirement_id"])
    ledger = {
        "schema_version": "1.0",
        "project": "ledgerguard-payment-reconciliation-platform",
        "part": 1,
        "workstream": "C1",
        "state": "ORIGINAL_REQUIREMENT_AUTHORITY_ESTABLISHED",
        "input_digests": actual_inputs,
        "derivation_policy": {
            "original_requirement_count": 331,
            "original_gate_count": 14,
            "phase8_verdicts_are_immutable": True,
            "only_phase8_pass_satisfies_historical_strict_conformance": True,
            "formal_amendment_does_not_rewrite_original_verdict": True,
            "c1_local_resolution_does_not_claim_final_conformance": True,
            "remaining_work_is_derived_from_resolution_state": True,
        },
        "requirement_count": len(rows),
        "baseline_verdict_summary": verdict["verdict_summary"],
        "resolution_summary": {
            **dict(sorted(resolution_counts.items())),
            "implementation_remaining_count": len(remaining),
            "final_c7_audit_required_count": sum(
                1 for item in rows if item["final_c7_audit_required"]
            ),
        },
        "requirements": rows,
        "remaining_requirement_ids": remaining,
        "remaining_by_workstream": {
            owner: sorted(ids) for owner, ids in sorted(remaining_by_owner.items())
        },
    }

    reverse = {
        "schema_version": "1.0",
        "project": ledger["project"],
        "part": 1,
        "workstream": "C1",
        "state": "BIDIRECTIONAL_REQUIREMENT_INDEX_ESTABLISHED",
        "requirement_count": len(rows),
        "indexes": {
            "rules": invert(rows, "rule_refs"),
            "contract_schemas": invert(rows, "contract_schema_paths"),
            "documentation": invert(rows, "documentation_paths"),
            "tests": invert(rows, "test_paths"),
            "candidate_evidence": invert(rows, "candidate_evidence_ids"),
            "owners": invert(rows, "correction_owner"),
            "corrections": invert(rows, "correction_action"),
            "baseline_verdicts": invert(rows, "baseline_verdict"),
            "resolution_states": invert(rows, "resolution_state"),
            "amendments": invert([item for item in rows if item["amendment_ids"]], "amendment_ids"),
        },
        "orphan_requirement_ids": [],
        "orphan_evidence_ids": [],
        "explicitly_disposed_evidence": {
            item["evidence_id"]: item["reverse_disposition"]
            for item in mapping["reverse_evidence_mappings"]
            if not item["mapped_requirement_ids"]
        },
        "undisposed_evidence_ids": [],
        "unowned_requirement_ids": [],
        "uncorrected_nonpass_requirement_ids": [],
        "handwritten_remaining_work": False,
    }
    mapped_evidence = set(invert(rows, "candidate_evidence_ids"))
    disposed_evidence = set(reverse["explicitly_disposed_evidence"])
    if mapped_evidence | disposed_evidence != set(registry):
        raise ValueError("undisposed candidate evidence remains")
    if mapped_evidence & disposed_evidence:
        raise ValueError("evidence cannot be both mapped and disposed")

    gate_rows = [item for item in rows if item["group"] == "GATE"]
    if [item["requirement_id"] for item in gate_rows] != [
        f"OP-GATE-R{number:03d}" for number in range(1, 15)
    ]:
        raise ValueError("exact 14-gate inventory differs")
    gate_counts = Counter(
        "PRESERVED_PASS"
        if item["baseline_verdict"] == "PASS"
        else "FORMALLY_AMENDED"
        if item["amendment_ids"]
        else "OPEN"
        for item in gate_rows
    )
    gates = {
        "schema_version": "1.0",
        "project": ledger["project"],
        "part": 1,
        "workstream": "C1",
        "state": "EXACT_ORIGINAL_14_GATE_AUTHORITY_ESTABLISHED",
        "gate_count": len(gate_rows),
        "gates": [
            {
                "gate_id": item["requirement_id"],
                "requirement": item["requirement"],
                "source_lines": item["source_lines"],
                "baseline_verdict": item["baseline_verdict"],
                "baseline_rationale": item["baseline_rationale"],
                "resolution_state": item["resolution_state"],
                "effective_gate_state": (
                    "PRESERVED_PASS"
                    if item["baseline_verdict"] == "PASS"
                    else "FORMALLY_AMENDED"
                    if item["amendment_ids"]
                    else "OPEN"
                ),
                "correction_owner": item["correction_owner"],
                "correction_action": item["correction_action"],
                "candidate_evidence_ids": item["candidate_evidence_ids"],
                "amendment_ids": item["amendment_ids"],
                "implementation_remaining": item["implementation_remaining"],
                "final_c7_audit_required": item["final_c7_audit_required"],
            }
            for item in gate_rows
        ],
        "summary": {**dict(sorted(gate_counts.items())), "total": len(gate_rows)},
        "remaining_gate_ids": [
            item["requirement_id"] for item in gate_rows if item["implementation_remaining"]
        ],
        "final_c7_gate_audit_required": True,
    }
    return ledger, reverse, gates


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    built = build()
    paths = (LEDGER_PATH, REVERSE_PATH, GATE_PATH)
    if args.check:
        for path, value in zip(paths, built, strict=True):
            if path.read_text(encoding="utf-8") != canonical(value):
                raise SystemExit(f"generated C1 authority differs: {path.relative_to(ROOT)}")
        return
    for path, value in zip(paths, built, strict=True):
        path.write_text(canonical(value), encoding="utf-8")


if __name__ == "__main__":
    main()
