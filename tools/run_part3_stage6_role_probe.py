#!/usr/bin/env python3
"""Run bounded real-session probes for one Stage 6 successor role."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from tools.part3_stage6.role_probe import (
    ACCOUNT,
    BACKEND_BUCKET,
    BACKEND_KMS_KEY_ARN,
    LEASE_KEY,
    LEASE_TABLE,
    REGION,
    ROLE_NAMES,
    STATE_LOCK_KEY,
    build_receipt,
    validate_backend_kms_key_arn,
)


def _error_code(stderr: str) -> str | None:
    match = re.search(r"An error occurred \(([^)]+)\)", stderr)
    return match.group(1) if match else None


def _invoke(service: str, operation: str, arguments: list[str]) -> tuple[dict[str, Any], Any]:
    command = [
        "aws",
        service,
        operation,
        *arguments,
        "--region",
        REGION,
        "--output",
        "json",
        "--no-cli-pager",
    ]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    parsed: Any = None
    if completed.stdout:
        try:
            parsed = json.loads(completed.stdout)
        except json.JSONDecodeError:
            parsed = None
    row = {
        "returncode": completed.returncode,
        "error_code": _error_code(completed.stderr),
        "response_sha256": hashlib.sha256(completed.stdout.encode()).hexdigest(),
    }
    return row, parsed


def run(role: str) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    if role not in ROLE_NAMES:
        raise ValueError("unknown Stage 6 role")
    caller_row, caller = _invoke("sts", "get-caller-identity", [])
    if caller_row["returncode"] or not isinstance(caller, dict):
        raise ValueError("caller identity probe failed")
    outcomes: dict[str, dict[str, Any]] = {}
    encryption_row, encryption = _invoke(
        "s3api", "get-bucket-encryption", ["--bucket", BACKEND_BUCKET]
    )
    if encryption_row["returncode"] or not isinstance(encryption, dict):
        raise ValueError("backend encryption probe failed")
    # Terraform supplies this reviewed key explicitly per backend request; the
    # bucket default may independently use SSE-S3 and is not its source of truth.
    kms_key_arn = validate_backend_kms_key_arn(BACKEND_KMS_KEY_ARN)
    commands: dict[str, tuple[str, str, list[str]]] = {
        "get_role": ("iam", "get-role", ["--role-name", ROLE_NAMES[role]]),
        "get_bucket_location": ("s3api", "get-bucket-location", ["--bucket", BACKEND_BUCKET]),
        "describe_lease_table": ("dynamodb", "describe-table", ["--table-name", LEASE_TABLE]),
        "describe_key": ("kms", "describe-key", ["--key-id", kms_key_arn]),
        "conditional_lease_noop": (
            "dynamodb",
            "update-item",
            [
                "--table-name",
                LEASE_TABLE,
                "--key",
                json.dumps({"lease_key": {"S": LEASE_KEY}}),
                "--update-expression",
                "SET #probe = :value",
                "--expression-attribute-names",
                json.dumps({"#probe": "stage6_permission_probe"}),
                "--expression-attribute-values",
                json.dumps({":value": {"S": "never-written"}}),
                "--condition-expression",
                "attribute_exists(lease_key) AND attribute_not_exists(lease_key)",
            ],
        ),
    }
    with tempfile.NamedTemporaryFile() as body:
        commands["conditional_lock_noop"] = (
            "s3api",
            "upload-part",
            [
                "--bucket",
                BACKEND_BUCKET,
                "--key",
                STATE_LOCK_KEY,
                "--body",
                body.name,
                "--part-number",
                "1",
                "--upload-id",
                "ledgerguard-stage6-permission-probe-never-created",
            ],
        )
        if role == "recovery":
            commands.update(
                {
                    "stop_missing_glue": (
                        "glue",
                        "batch-stop-job-run",
                        [
                            "--job-name",
                            "ledgerguard-p3-release-qual1-reconciliation",
                            "--job-run-ids",
                            "jr_stage6_permission_probe_never_created",
                        ],
                    ),
                    "stop_missing_execution": (
                        "stepfunctions",
                        "stop-execution",
                        [
                            "--execution-arn",
                            f"arn:aws:states:{REGION}:{ACCOUNT}:execution:ledgerguard-p3-release-qual1-reconciliation:stage6-permission-probe-never-created",
                        ],
                    ),
                    "stop_missing_query": (
                        "athena",
                        "stop-query-execution",
                        ["--query-execution-id", "00000000-0000-0000-0000-000000000000"],
                    ),
                }
            )
        outcomes["get_bucket_encryption"] = encryption_row
        for name, (service, operation, arguments) in commands.items():
            outcomes[name], _ = _invoke(service, operation, arguments)
    return caller, outcomes


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-role", choices=sorted(ROLE_NAMES), required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--source-tree", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or args.output.is_symlink():
        raise SystemExit("new regular output path required")
    caller, outcomes = run(args.expected_role)
    receipt = build_receipt(
        source_commit=args.source_commit,
        source_tree=args.source_tree,
        role=args.expected_role,
        caller=caller,
        outcomes=outcomes,
        run_id=os.environ.get("GITHUB_RUN_ID", ""),
        run_attempt=os.environ.get("GITHUB_RUN_ATTEMPT", ""),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("xb") as target:
        target.write(json.dumps(receipt, sort_keys=True, indent=2).encode() + b"\n")


if __name__ == "__main__":
    main()
