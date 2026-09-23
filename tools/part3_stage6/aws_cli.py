"""Stage 6-owned extension of the frozen Stage 2 AWS CLI adapter."""

from __future__ import annotations

import json
import subprocess
import time
from hashlib import sha256
from typing import Any, cast

from ledgerguard.stage2.aws_cli import FORBIDDEN, AwsCli, _sanitize
from ledgerguard.stage2.control import Stage2Rejected, require

EXTRA_COMMANDS = {
    "IAM_GET_ACCOUNT_SUMMARY": ("iam", "get-account-summary"),
    "IAM_LIST_ROLES": ("iam", "list-roles"),
    "IAM_GET_POLICY": ("iam", "get-policy"),
    "IAM_GET_POLICY_VERSION": ("iam", "get-policy-version"),
    "IAM_LIST_POLICY_VERSIONS": ("iam", "list-policy-versions"),
    "KMS_DESCRIBE_KEY": ("kms", "describe-key"),
    "GLUE_GET_DATABASES": ("glue", "get-databases"),
    "ATHENA_LIST_WORKGROUPS": ("athena", "list-work-groups"),
    "LAMBDA_LIST_FUNCTIONS": ("lambda", "list-functions"),
    "CLOUDWATCH_DESCRIBE_ALARMS": ("cloudwatch", "describe-alarms"),
}


class Stage6AwsCli(AwsCli):
    """Retain the accepted adapter and admit only Stage 6 inventory reads."""

    def invoke(self, operation: str, arguments: list[str] | None = None) -> dict[str, Any]:
        if operation not in EXTRA_COMMANDS:
            return super().invoke(operation, arguments)
        prefix = EXTRA_COMMANDS[operation]
        require(not FORBIDDEN.intersection(prefix), "forbidden AWS operation")
        args = list(arguments or [])
        require(not any(token.lower() in FORBIDDEN for token in args), "forbidden AWS argument")
        command = [
            "aws",
            *prefix,
            *args,
            "--region",
            self.region,
            "--output",
            "json",
            "--no-cli-pager",
        ]
        started = time.time_ns()
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        row: dict[str, Any] = {
            "sequence": len(self.journal) + 1,
            "operation": operation,
            "region": self.region,
            "started_epoch_ns": started,
            "finished_epoch_ns": time.time_ns(),
            "returncode": result.returncode,
            "response_sha256": sha256(result.stdout.encode()).hexdigest(),
        }
        if result.returncode:
            row["error"] = _sanitize(result.stderr)
        self.journal.append(row)
        if result.returncode:
            raise Stage2Rejected(f"AWS operation failed: {operation}: {row['error']}")
        try:
            value = json.loads(result.stdout or "{}")
        except json.JSONDecodeError as exc:
            raise Stage2Rejected(f"AWS operation returned non-JSON: {operation}") from exc
        require(isinstance(value, dict), f"AWS object response required: {operation}")
        return cast(dict[str, Any], value)
