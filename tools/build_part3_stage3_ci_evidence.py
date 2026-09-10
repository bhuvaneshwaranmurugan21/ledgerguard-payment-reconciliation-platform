#!/usr/bin/env python3
"""Bind exact GitHub event identity to the completed Stage 3 evidence directory."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from hashlib import sha256
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from ledgerguard.stage3.canonical import canonical_bytes

ROOT = Path(__file__).resolve().parents[1]


def _required(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"required CI environment variable is missing: {name}")
    return value


def _identity(path: Path, root: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    return {
        "path": path.relative_to(root).as_posix(),
        "size_bytes": len(raw),
        "sha256": sha256(raw).hexdigest(),
    }


def build(artifact: Path) -> dict[str, Any]:
    artifact = artifact.resolve()
    local_path = artifact / "part3-stage3-local-evidence.json"
    local = json.loads(local_path.read_text(encoding="utf-8"))
    event_name = _required("GITHUB_EVENT_NAME")
    if event_name not in {"pull_request", "push"}:
        raise SystemExit("Stage 3 CI evidence requires pull_request or push")
    event = json.loads(Path(_required("GITHUB_EVENT_PATH")).read_text(encoding="utf-8"))
    expected_sha = (
        str(event["pull_request"]["head"]["sha"])
        if event_name == "pull_request"
        else _required("GITHUB_SHA")
    )
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    tree = subprocess.check_output(
        ["git", "show", "-s", "--format=%T", "HEAD"], cwd=ROOT, text=True
    ).strip()
    if commit != expected_sha or commit != _required("EXPECTED_SHA"):
        raise SystemExit("Stage 3 checkout differs from exact event head")
    if local.get("head_sha") != commit or local.get("head_tree") != tree:
        raise SystemExit("Stage 3 local evidence source identity differs")
    envelope = {
        "schema_version": "1.0",
        "repository": _required("GITHUB_REPOSITORY"),
        "event": event_name,
        "head_sha": commit,
        "head_tree": tree,
        "workflow_run_id": int(_required("GITHUB_RUN_ID")),
        "workflow_run_attempt": int(_required("GITHUB_RUN_ATTEMPT")),
        "git_ref": _required("GITHUB_REF"),
        "job_name": "part3-stage3-current",
        "deterministic_payload_sha256": local["deterministic_payload_sha256"],
        "verdict": local["verdict"],
        "aws_execution": local["aws_execution"],
    }
    schema = json.loads(
        (ROOT / "spec/part3-stage3-ci-evidence-v1.schema.json").read_text(encoding="utf-8")
    )
    Draft202012Validator.check_schema(schema)
    errors = sorted(
        Draft202012Validator(schema).iter_errors(envelope), key=lambda row: list(row.path)
    )
    if errors:
        raise SystemExit(f"Stage 3 CI evidence is invalid: {errors[0].message}")
    (artifact / "ci-evidence.json").write_bytes(canonical_bytes(envelope) + b"\n")
    members = [
        _identity(path, artifact)
        for path in sorted(artifact.rglob("*"))
        if path.is_file() and path.name != "artifact-manifest.json"
    ]
    manifest: dict[str, Any] = {
        "schema_version": "1.0",
        "head_sha": commit,
        "head_tree": tree,
        "members": members,
    }
    manifest["manifest_sha256"] = sha256(canonical_bytes(manifest)).hexdigest()
    (artifact / "artifact-manifest.json").write_bytes(canonical_bytes(manifest) + b"\n")
    return envelope


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-directory", type=Path, required=True)
    arguments = parser.parse_args()
    print(json.dumps(build(arguments.artifact_directory), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
