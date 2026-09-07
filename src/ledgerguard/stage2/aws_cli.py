"""Narrow AWS CLI adapter with an append-only, sanitized operation journal."""

from __future__ import annotations

import json
import re
import subprocess
import time
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Any, cast

from ledgerguard.stage2.control import Stage2Rejected, require

COMMANDS = {
    "STS_GET_CALLER_IDENTITY": ("sts", "get-caller-identity"),
    "IAM_GET_ROLE": ("iam", "get-role"),
    "IAM_LIST_ROLE_POLICIES": ("iam", "list-role-policies"),
    "IAM_GET_ROLE_POLICY": ("iam", "get-role-policy"),
    "IAM_LIST_ATTACHED_ROLE_POLICIES": ("iam", "list-attached-role-policies"),
    "IAM_LIST_ROLE_TAGS": ("iam", "list-role-tags"),
    "S3_GET_BUCKET_LOCATION": ("s3api", "get-bucket-location"),
    "S3_GET_BUCKET_VERSIONING": ("s3api", "get-bucket-versioning"),
    "S3_GET_BUCKET_ENCRYPTION": ("s3api", "get-bucket-encryption"),
    "S3_GET_PUBLIC_ACCESS": ("s3api", "get-public-access-block"),
    "S3_GET_BUCKET_POLICY": ("s3api", "get-bucket-policy"),
    "S3_GET_OWNERSHIP": ("s3api", "get-bucket-ownership-controls"),
    "S3_GET_LIFECYCLE": ("s3api", "get-bucket-lifecycle-configuration"),
    "S3_GET_TAGS": ("s3api", "get-bucket-tagging"),
    "S3_LIST_BUCKETS": ("s3api", "list-buckets"),
    "S3_LIST_VERSIONS": ("s3api", "list-object-versions"),
    "S3_PUT_OBJECT": ("s3api", "put-object"),
    "S3_HEAD_OBJECT": ("s3api", "head-object"),
    "S3_GET_OBJECT": ("s3api", "get-object"),
    "S3_DELETE_OBJECT": ("s3api", "delete-object"),
    "DDB_DESCRIBE_TABLE": ("dynamodb", "describe-table"),
    "DDB_DESCRIBE_BACKUPS": ("dynamodb", "describe-continuous-backups"),
    "DDB_DESCRIBE_TTL": ("dynamodb", "describe-time-to-live"),
    "DDB_LIST_TAGS": ("dynamodb", "list-tags-of-resource"),
    "DDB_LIST_TABLES": ("dynamodb", "list-tables"),
    "DDB_GET_ITEM": ("dynamodb", "get-item"),
    "DDB_PUT_ITEM": ("dynamodb", "put-item"),
    "DDB_DELETE_ITEM": ("dynamodb", "delete-item"),
    "DDB_SCAN": ("dynamodb", "scan"),
    "GLUE_GET_JOBS": ("glue", "get-jobs"),
    "GLUE_CREATE_JOB": ("glue", "create-job"),
    "GLUE_GET_JOB": ("glue", "get-job"),
    "GLUE_GET_JOB_RUNS": ("glue", "get-job-runs"),
    "GLUE_GET_TAGS": ("glue", "get-tags"),
    "GLUE_DELETE_JOB": ("glue", "delete-job"),
    "SFN_VALIDATE": ("stepfunctions", "validate-state-machine-definition"),
    "SFN_LIST": ("stepfunctions", "list-state-machines"),
    "ATHENA_GET_WORKGROUP": ("athena", "get-work-group"),
    "ATHENA_LIST_QUERIES": ("athena", "list-query-executions"),
    "LOGS_DESCRIBE_GROUPS": ("logs", "describe-log-groups"),
    "CLOUDWATCH_LIST_METRICS": ("cloudwatch", "list-metrics"),
    "BUDGETS_DESCRIBE": ("budgets", "describe-budgets"),
    "CE_GET_COST": ("ce", "get-cost-and-usage"),
    "TAG_GET_RESOURCES": ("resourcegroupstaggingapi", "get-resources"),
    "QUOTAS_LIST": ("service-quotas", "list-service-quotas"),
}
FORBIDDEN = {
    "start-job-run",
    "batch-stop-job-run",
    "start-execution",
    "start-sync-execution",
    "redrive-execution",
    "start-query-execution",
    "create-state-machine",
    "update-state-machine",
}
MUTATING_OPERATIONS = {
    "S3_PUT_OBJECT",
    "S3_DELETE_OBJECT",
    "DDB_PUT_ITEM",
    "DDB_DELETE_ITEM",
    "GLUE_CREATE_JOB",
    "GLUE_DELETE_JOB",
}
OPERATION_REGIONS = {
    "CE_GET_COST": "us-east-1",
    "BUDGETS_DESCRIBE": "us-east-1",
}


def _sanitize(value: str) -> str:
    value = re.sub(r"(?<![0-9])[0-9]{12}(?![0-9])", "<ACCOUNT>", value)
    value = re.sub(r"(?:AKIA|ASIA)[A-Z0-9]{16}", "<ACCESS_KEY>", value)
    return value[:2000]


@dataclass
class AwsCli:
    region: str
    journal: list[dict[str, Any]] = field(default_factory=list)

    def version(self) -> dict[str, str]:
        result = subprocess.run(["aws", "--version"], capture_output=True, text=True, check=False)
        output = _sanitize(result.stdout or result.stderr)
        require(result.returncode == 0, f"AWS CLI version probe failed: {output}")
        match = re.search(r"aws-cli/([0-9]+\.[0-9]+\.[0-9]+)", output)
        require(match is not None and match.group(1).startswith("2."), "AWS CLI v2 required")
        assert match is not None
        return {"aws_cli": match.group(1)}

    def invoke(self, operation: str, arguments: list[str] | None = None) -> dict[str, Any]:
        require(operation in COMMANDS, f"AWS operation is not allowlisted: {operation}")
        prefix = COMMANDS[operation]
        require(not FORBIDDEN.intersection(prefix), "forbidden AWS operation")
        args = list(arguments or [])
        require(not any(token.lower() in FORBIDDEN for token in args), "forbidden AWS argument")
        command_region = OPERATION_REGIONS.get(operation, self.region)
        command = [
            "aws",
            *prefix,
            *args,
            "--region",
            command_region,
            "--output",
            "json",
            "--no-cli-pager",
        ]
        started = time.time_ns()
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        row: dict[str, Any] = {
            "sequence": len(self.journal) + 1,
            "operation": operation,
            "region": command_region,
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

    def write_journal(self, path: Path) -> None:
        path.write_text(json.dumps(self.journal, sort_keys=True, indent=2) + "\n")
