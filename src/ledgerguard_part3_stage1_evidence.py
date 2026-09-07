"""Exact-event CI envelope and bounded artifact integrity checks."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import Any

from ledgerguard_part3_stage1_validation import BASE, check

REPOSITORY = "bhuvaneshwaranmurugan21/ledgerguard-payment-reconciliation-platform"
HEX40 = re.compile(r"^[a-f0-9]{40}$")
HEX64 = re.compile(r"^[a-f0-9]{64}$")


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def envelope(
    environment: Mapping[str, str],
    event: Mapping[str, Any],
    local: Mapping[str, Any],
    actual_commit: str,
    actual_tree: str,
) -> dict[str, Any]:
    check(environment.get("GITHUB_REPOSITORY") == REPOSITORY, "CI repository differs")
    kind = environment.get("GITHUB_EVENT_NAME")
    check(kind in ("push", "pull_request"), "unsupported CI event")
    if kind == "pull_request":
        expected = event["pull_request"]["head"]["sha"]
        number = event["number"]
        check(
            isinstance(number, int) and not isinstance(number, bool) and number > 0,
            "PR identity differs",
        )
    else:
        expected = environment.get("GITHUB_SHA")
        number = None
        check(environment.get("GITHUB_REF") == "refs/heads/main", "push is not main")
    check(isinstance(expected, str) and HEX40.fullmatch(expected) is not None, "event head differs")
    check(
        actual_commit == expected and environment.get("EXPECTED_SHA") == expected,
        "CI checkout differs",
    )
    check(HEX40.fullmatch(actual_tree) is not None, "tree identity differs")
    for key in ("GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT"):
        check(
            environment.get(key, "").isdigit() and int(environment[key]) > 0,
            "CI run identity differs",
        )
    check(
        local["part"] == 3
        and local["stage"] == 1
        and local["clean_run_count"] == 2
        and local["deterministic_equal"] is True,
        "clean run requirement differs",
    )
    payload = local["deterministic_payload"]
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    check(
        digest(raw) == local["deterministic_payload_sha256"], "deterministic payload digest differs"
    )
    check(HEX64.fullmatch(payload["wheel_sha256"]) is not None, "wheel identity differs")
    check(
        local["execution_boundary"]["aws_execution"] is False, "local artifact claims AWS execution"
    )
    return {
        "schema_version": "1.0",
        "repository": REPOSITORY,
        "event": kind,
        "pull_request_number": number,
        "commit": actual_commit,
        "tree": actual_tree,
        "entry_base": BASE,
        "workflow_run_id": environment["GITHUB_RUN_ID"],
        "workflow_run_attempt": environment["GITHUB_RUN_ATTEMPT"],
        "deterministic_payload_sha256": local["deterministic_payload_sha256"],
        "wheel_sha256": payload["wheel_sha256"],
        "producer_state": "LOCAL_VALIDATION_FINISHED",
        "run_success_independently_required": True,
        "postmerge_verification_required": True,
        "aws_execution": False,
        "project_complete": False,
    }


def build_manifest(directory: Path) -> dict[str, Any]:
    members = []
    for path in sorted(directory.rglob("*")):
        check(not path.is_symlink(), "artifact symlink forbidden")
        if not path.is_file():
            continue
        relative = path.relative_to(directory).as_posix()
        if relative == "manifest.json":
            continue
        raw = path.read_bytes()
        members.append({"path": relative, "size_bytes": len(raw), "sha256": digest(raw)})
    check(bool(members), "artifact is empty")
    return {"schema_version": "1.0", "excluded_self": "manifest.json", "members": members}


def verify_manifest(directory: Path, manifest: Mapping[str, Any]) -> dict[str, Any]:
    check(
        set(manifest) == {"schema_version", "excluded_self", "members"}
        and manifest["schema_version"] == "1.0"
        and manifest["excluded_self"] == "manifest.json",
        "artifact manifest envelope differs",
    )
    rows = manifest["members"]
    check(isinstance(rows, list) and bool(rows), "artifact member inventory missing")
    for row in rows:
        check(
            isinstance(row, dict) and set(row) == {"path", "size_bytes", "sha256"},
            "artifact member shape differs",
        )
        path = PurePosixPath(row["path"])
        check(
            not path.is_absolute()
            and ".." not in path.parts
            and "\\" not in row["path"]
            and path.as_posix() == row["path"]
            and row["path"] != "manifest.json",
            "unsafe artifact member",
        )
    check(
        dict(manifest) == build_manifest(directory),
        "artifact bytes or exact member inventory differ",
    )
    return {"members": len(rows), "integrity_verified": True}
