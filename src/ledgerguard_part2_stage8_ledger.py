#!/usr/bin/env python3
"""Build deterministic Part 2 requirement and gate closure ledgers."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, cast

PROJECT = "ledgerguard-payment-reconciliation-platform"
STAGE_COUNTS = {1: 26, 2: 15, 3: 22, 4: 23, 5: 35, 6: 30, 7: 24, 8: 28}
GATE_COUNTS = {1: 6, 2: 7, 3: 9, 4: 9, 5: 10, 6: 10, 7: 8, 8: 10}
CLOSURE_AUTHORITIES = {
    1: "contracts/part2-stage2-reference-oracle-v1.json",
    2: "spec/part2-stage2-closure-freeze-v1.json",
    3: "spec/part2-stage3-closure-freeze-v1.json",
    4: "spec/part2-stage4-closure-freeze-v1.json",
    5: "spec/part2-stage5-closure-freeze-v1.json",
    6: "spec/part2-stage6-closure-freeze-v1.json",
    7: "spec/part2-stage7-closure-freeze-v1.json",
    8: "part2-stage8-ci-evidence.json",
}


def load(root: Path, relative: str) -> dict[str, Any]:
    value = json.loads((root / relative).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {relative}")
    return value


def as_strings(value: object, label: str) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return cast(list[str], value)
    raise ValueError(f"string or string list required: {label}")


def build_requirement_ledger(root: Path) -> dict[str, Any]:
    result: list[dict[str, Any]] = []
    stage_counts: dict[str, int] = {}
    for stage, expected_count in STAGE_COUNTS.items():
        requirements = cast(
            list[dict[str, Any]],
            load(root, f"spec/part2-stage{stage}-requirements-v1.json")["requirements"],
        )
        traces = cast(
            list[dict[str, Any]],
            load(root, f"spec/part2-stage{stage}-traceability-v1.json")["traceability"],
        )
        if len(requirements) != expected_count:
            raise ValueError(f"Stage {stage} requirement count differs")
        trace_by_requirement: dict[str, dict[str, Any]] = {}
        for trace in traces:
            members = (
                [str(trace["requirement_id"])]
                if "requirement_id" in trace
                else as_strings(trace.get("requirement_ids"), "requirement_ids")
            )
            for member in members:
                if member in trace_by_requirement:
                    raise ValueError(f"duplicate trace ownership: {member}")
                trace_by_requirement[member] = trace
        for requirement in requirements:
            requirement_id = str(requirement["id"])
            selected_trace = trace_by_requirement.get(requirement_id)
            if selected_trace is None:
                raise ValueError(f"missing trace ownership: {requirement_id}")
            gate_id = str(requirement["gate_id"])
            if "gate_id" in selected_trace and selected_trace["gate_id"] != gate_id:
                raise ValueError(f"trace gate differs: {requirement_id}")
            result.append(
                {
                    "id": requirement_id,
                    "stage": stage,
                    "gate_id": gate_id,
                    "statement": str(requirement["statement"]),
                    "authorities": as_strings(selected_trace.get("authorities"), "authorities"),
                    "validation": as_strings(selected_trace.get("validation"), "validation"),
                    "evidence": as_strings(selected_trace.get("evidence"), "evidence"),
                    "adjudication": ("EXTERNALLY_VERIFIED" if stage < 8 else "VERIFIED_CANDIDATE"),
                }
            )
        if set(trace_by_requirement) != {str(row["id"]) for row in requirements}:
            raise ValueError(f"Stage {stage} trace inventory differs")
        stage_counts[str(stage)] = len(requirements)
    return {
        "schema_version": "1.0",
        "project": PROJECT,
        "part": 2,
        "stage_counts": stage_counts,
        "historical_requirement_count": sum(STAGE_COUNTS[stage] for stage in range(1, 8)),
        "total_requirement_count": len(result),
        "requirements": result,
    }


def build_gate_adjudication(root: Path) -> dict[str, Any]:
    result: list[dict[str, Any]] = []
    stage_counts: dict[str, int] = {}
    for stage, expected_count in GATE_COUNTS.items():
        gates = cast(
            list[dict[str, Any]],
            load(root, f"spec/part2-stage{stage}-gate-registry-v1.json")["gates"],
        )
        if len(gates) != expected_count:
            raise ValueError(f"Stage {stage} gate count differs")
        for gate in gates:
            result.append(
                {
                    "gate_id": str(gate["gate_id"]),
                    "stage": stage,
                    "name": str(gate["name"]),
                    "state": "EXTERNALLY_VERIFIED" if stage < 8 else "VERIFIED_CANDIDATE",
                    "closure_authority": CLOSURE_AUTHORITIES[stage],
                }
            )
        stage_counts[str(stage)] = len(gates)
    return {
        "schema_version": "1.0",
        "project": PROJECT,
        "part": 2,
        "stage_counts": stage_counts,
        "historical_gate_count": sum(GATE_COUNTS[stage] for stage in range(1, 8)),
        "total_gate_count": len(result),
        "critical_findings": 0,
        "major_findings": 0,
        "open_findings": 0,
        "gates": result,
    }


def encode(value: dict[str, Any]) -> str:
    return json.dumps(value, indent=2, sort_keys=True) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    outputs = {
        "spec/part2-requirement-ledger-v1.json": build_requirement_ledger(root),
        "spec/part2-gate-adjudication-v1.json": build_gate_adjudication(root),
    }
    for relative, value in outputs.items():
        path = root / relative
        encoded = encode(value)
        if args.check:
            if not path.is_file() or path.read_text(encoding="utf-8") != encoded:
                raise SystemExit(f"generated ledger differs: {relative}")
        else:
            path.write_text(encoded, encoding="utf-8")
    print(json.dumps({path: value["stage_counts"] for path, value in outputs.items()}))


if __name__ == "__main__":
    main()
