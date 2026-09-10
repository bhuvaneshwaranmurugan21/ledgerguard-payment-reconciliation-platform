#!/usr/bin/env python3
"""Independently inspect one extracted immutable Stage 3 CI artifact."""

from __future__ import annotations

import argparse
import json
from hashlib import sha256
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from ledgerguard.stage3.canonical import canonical_bytes

ROOT = Path(__file__).resolve().parents[1]


def inspect(
    artifact: Path, expected_sha: str, expected_run_id: int, expected_run_attempt: int
) -> dict[str, Any]:
    artifact = artifact.resolve()
    if not artifact.is_dir() or artifact == ROOT or ROOT in artifact.parents:
        raise ValueError("artifact must be an external directory")
    for path in artifact.rglob("*"):
        if path.is_symlink():
            raise ValueError("artifact contains a symlink")
    manifest_path = artifact / "artifact-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected_manifest_digest = manifest.pop("manifest_sha256", None)
    if sha256(canonical_bytes(manifest)).hexdigest() != expected_manifest_digest:
        raise ValueError("artifact manifest digest differs")
    rows = manifest.get("members")
    if not isinstance(rows, list):
        raise ValueError("artifact member inventory is unavailable")
    actual = {
        path.relative_to(artifact).as_posix(): path
        for path in artifact.rglob("*")
        if path.is_file() and path != manifest_path
    }
    declared: set[str] = set()
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("path"), str):
            raise ValueError("artifact inventory row is invalid")
        name = row["path"]
        if name in declared or name not in actual or ".." in Path(name).parts:
            raise ValueError("artifact inventory path is unsafe or duplicated")
        declared.add(name)
        raw = actual[name].read_bytes()
        if len(raw) != row.get("size_bytes") or sha256(raw).hexdigest() != row.get("sha256"):
            raise ValueError(f"artifact member identity differs: {name}")
    if declared != set(actual):
        raise ValueError("artifact member set differs")
    ci = json.loads((artifact / "ci-evidence.json").read_text(encoding="utf-8"))
    schema = json.loads(
        (ROOT / "spec/part3-stage3-ci-evidence-v1.schema.json").read_text(encoding="utf-8")
    )
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(ci)
    local = json.loads((artifact / "part3-stage3-local-evidence.json").read_text(encoding="utf-8"))
    if (
        ci["head_sha"] != expected_sha
        or manifest["head_sha"] != expected_sha
        or local["head_sha"] != expected_sha
        or ci["head_tree"] != manifest["head_tree"]
        or ci["head_tree"] != local["head_tree"]
    ):
        raise ValueError("artifact head identity differs")
    if (
        ci["workflow_run_id"] != expected_run_id
        or ci["workflow_run_attempt"] != expected_run_attempt
    ):
        raise ValueError("artifact workflow run identity differs")
    if ci["deterministic_payload_sha256"] != local["deterministic_payload_sha256"]:
        raise ValueError("artifact deterministic payload binding differs")
    if ci["verdict"] != "PASS" or local["verdict"] != "PASS":
        raise ValueError("artifact qualification verdict differs")
    if ci["aws_execution"] is not False or local["aws_execution"] is not False:
        raise ValueError("artifact AWS execution boundary differs")
    return {
        "schema_version": "1.0",
        "head_sha": expected_sha,
        "head_tree": ci["head_tree"],
        "workflow_run_id": expected_run_id,
        "workflow_run_attempt": expected_run_attempt,
        "member_count": len(actual),
        "artifact_manifest_file_sha256": sha256(manifest_path.read_bytes()).hexdigest(),
        "deterministic_payload_sha256": ci["deterministic_payload_sha256"],
        "independently_accepted": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--expected-run-id", type=int, required=True)
    parser.add_argument("--expected-run-attempt", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    result = inspect(
        arguments.artifact,
        arguments.expected_sha,
        arguments.expected_run_id,
        arguments.expected_run_attempt,
    )
    arguments.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
