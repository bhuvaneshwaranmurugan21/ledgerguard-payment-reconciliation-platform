#!/usr/bin/env python3
"""Build the private Stage 6 administrator review packet offline."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from tools.part3_stage4.resources import parse_module
from tools.part3_stage6.admin_packet import compose_successor_packet


def _load(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"object required: {path}")
    return value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--release-dir", type=Path, required=True)
    parser.add_argument("--backend-kms-key-arn-file", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--source-tree", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if sys.version_info[:3] != (3, 11, 13):
        raise SystemExit("exact CPython 3.11.13 is required")
    root = args.root.resolve()
    output = args.output.resolve()
    if output.exists() or output.is_symlink() or root == output or root in output.parents:
        raise SystemExit("private packet output must be new and outside the repository")
    kms_path = args.backend_kms_key_arn_file.resolve()
    if kms_path.is_symlink() or not kms_path.is_file():
        raise SystemExit("regular backend KMS key ARN file required")
    backend_kms_key_arn = kms_path.read_text(encoding="utf-8").strip()
    packet = compose_successor_packet(
        provider=_load(root / "spec/part3-stage4-provider-actions-v1.json"),
        module=parse_module(root / "infra/part3"),
        trust=_load(root / "contracts/part3-stage2-oidc-trust-v1.json"),
        release=_load(args.release_dir / "terraform-stage5-release.json"),
        release_dir=args.release_dir,
        backend_kms_key_arn=backend_kms_key_arn,
        source_commit=args.source_commit,
        source_tree=args.source_tree,
    )
    old_umask = os.umask(0o077)
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(packet, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    finally:
        os.umask(old_umask)


if __name__ == "__main__":
    main()
