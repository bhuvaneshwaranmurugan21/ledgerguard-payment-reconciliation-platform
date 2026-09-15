#!/usr/bin/env python3
"""Run the narrowly owner-bound Stage 6 recovery transaction."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from tools.part3_stage6.aws_cli import Stage6AwsCli
from tools.part3_stage6.recovery import recover_owned_lease


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"object required: {path}")
    return value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--expected-tree", required=True)
    parser.add_argument("--failure-handoff", type=Path, required=True)
    parser.add_argument("--backend-kms-key-arn-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if os.environ.get("GITHUB_EVENT_NAME") != "workflow_dispatch":
        raise SystemExit("Stage 6 recovery requires workflow_dispatch")
    if os.environ.get("GITHUB_REF") != "refs/heads/main":
        raise SystemExit("Stage 6 recovery requires exact main")
    if (
        os.environ.get("GITHUB_SHA") != args.expected_sha
        or os.environ.get("CHECKED_OUT_SHA") != args.expected_sha
    ):
        raise SystemExit("Stage 6 recovery source differs")
    root = args.root.resolve()
    output = args.output.resolve()
    if output.exists() or output.is_symlink() or root == output or root in output.parents:
        raise SystemExit("new recovery output outside repository required")
    kms_path = args.backend_kms_key_arn_file.resolve()
    if not kms_path.is_file() or kms_path.is_symlink():
        raise SystemExit("regular private KMS ARN file required")
    result = recover_owned_lease(
        cli=Stage6AwsCli("ap-southeast-2"),
        handoff=_load(args.failure_handoff),
        source_commit=args.expected_sha,
        source_tree=args.expected_tree,
        kms_key_arn=kms_path.read_text(encoding="utf-8").strip(),
        control_plane=_load(root / "contracts/part3-stage2-control-plane-v1.json"),
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
