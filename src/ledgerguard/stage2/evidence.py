"""Stage 2 producer evidence helpers and independent-safe manifest construction."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ledgerguard.stage2.control import scan_safe_evidence, sha256_bytes, validate_manifest


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n")


def build_manifest(directory: Path) -> dict[str, Any]:
    members = []
    for path in sorted(directory.rglob("*")):
        if path.is_file() and path.name != "manifest.json":
            members.append(
                {
                    "path": path.relative_to(directory).as_posix(),
                    "size_bytes": path.stat().st_size,
                    "sha256": sha256_bytes(path.read_bytes()),
                }
            )
    return {"schema_version": "1.0", "excluded_self": "manifest.json", "members": members}


def finalize_artifact(directory: Path) -> dict[str, Any]:
    scan_safe_evidence(directory)
    manifest = build_manifest(directory)
    validate_manifest(directory, manifest)
    write_json(directory / "manifest.json", manifest)
    return manifest
