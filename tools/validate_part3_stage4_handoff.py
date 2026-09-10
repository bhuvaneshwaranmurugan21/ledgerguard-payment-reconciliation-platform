#!/usr/bin/env python3
"""Admit the unchanged Stage 3 authority and append-only Stage 4 handoff."""

from __future__ import annotations

import argparse
import json
import subprocess
from hashlib import sha256
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RECEIPT_SHA256 = "0af219b16d74d17114b26f03edc41b401d655629fdd6e1b2725ec9406d15a3ea"
REGISTRY_SHA256 = "abd6004b1285ab180db6750085ce166781677dabb82e421fbd36d4e8067d11aa"
BASELINE_COMMIT = "3370898d83539fe41594c7cb7ad15e920dcb5674"
BASELINE_TREE = "32e66b9d97cc63cd588eca14ecaf6602b9ff7f0a"
FREEZE_SHA256 = "8b744e9f37d9c7f3df9566128b7e16ac6fea1b97cfabb71f619cc1bf35cdaf72"
POINTER = "/stage3_adjudication/downstream_part3_master_gates_not_executed"
GATES = ["plan_only_verified", "zero_workload_canary_verified", "teardown_verified"]


def admit_receipt(raw: bytes, correction: dict[str, Any], registry_raw: bytes) -> None:
    if sha256(raw).hexdigest() != RECEIPT_SHA256:
        raise ValueError("original receipt bytes changed")
    if sha256(registry_raw).hexdigest() != REGISTRY_SHA256:
        raise ValueError("gate registry bytes changed")
    if correction["original_receipt_sha256"] != RECEIPT_SHA256:
        raise ValueError("correction receipt binding differs")
    if correction["authoritative_gate_registry_sha256"] != REGISTRY_SHA256:
        raise ValueError("correction registry binding differs")
    if (
        correction["original_receipt_mutated"] is not False
        or correction["unaffected_fields_remain_authoritative"] is not True
    ):
        raise ValueError("append-only claim differs")
    change = correction["correction"]
    old = json.loads(raw)["stage3_adjudication"]["downstream_part3_master_gates_not_executed"]
    if change["json_pointer"] != POINTER or change["superseded_value"] != old:
        raise ValueError("correction target differs")
    registered = {row["gate_id"] for row in json.loads(registry_raw)["gates"]}
    if change["corrected_value"] != GATES or not set(GATES).issubset(registered):
        raise ValueError("unregistered or incorrect successor gates")


def validate(root: Path) -> dict[str, Any]:
    raw = (root / "spec/part3-stage3-external-closure-v1.json").read_bytes()
    correction = json.loads(
        (root / "spec/part3-stage3-external-closure-correction-v1.json").read_text()
    )
    admit_receipt(raw, correction, (root / "spec/part3-master-gates-v1.json").read_bytes())
    freeze_raw = (root / "spec/part3-stage4-inherited-freeze-v1.json").read_bytes()
    if sha256(freeze_raw).hexdigest() != FREEZE_SHA256:
        raise ValueError("inherited inventory bytes changed")
    freeze = json.loads(freeze_raw)
    if freeze["baseline_commit"] != BASELINE_COMMIT or freeze["baseline_tree"] != BASELINE_TREE:
        raise ValueError("inherited source identity differs")
    result = subprocess.run(
        ["git", "-C", str(root), "rev-parse", BASELINE_COMMIT + "^{tree}"],
        check=True,
        capture_output=True,
        text=True,
    )
    if result.stdout.strip() != BASELINE_TREE:
        raise ValueError("baseline tree differs")
    names: set[str] = set()
    for row in freeze["members"]:
        name = row["path"]
        if name in names or Path(name).is_absolute() or ".." in Path(name).parts:
            raise ValueError("unsafe inherited inventory path")
        names.add(name)
        path = root / name
        if path.is_symlink() or sha256(path.read_bytes()).hexdigest() != row["sha256"]:
            raise ValueError("inherited file differs: " + name)
        blob = subprocess.run(
            ["git", "-C", str(root), "rev-parse", BASELINE_COMMIT + ":" + name],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        if blob != row["git_blob"]:
            raise ValueError("inherited Git binding differs: " + name)
    requirements = json.loads((root / "spec/part3-requirements-v1.json").read_text())
    ids = [row["requirement_id"] for row in requirements["requirements"]]
    if len(ids) != 99 or len(set(ids)) != 99:
        raise ValueError("original requirement identity set differs")
    return {
        "baseline_commit": BASELINE_COMMIT,
        "baseline_tree": BASELINE_TREE,
        "original_receipt_sha256": RECEIPT_SHA256,
        "inherited_files_verified": len(names),
        "original_requirement_count": 99,
        "handoff_admitted": True,
        "stage4_complete": False,
        "aws_execution": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    print(json.dumps(validate(args.root), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
