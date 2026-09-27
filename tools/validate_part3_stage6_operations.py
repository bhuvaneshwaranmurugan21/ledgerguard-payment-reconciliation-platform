#!/usr/bin/env python3
"""Validate the complete static AWS-operation authority for Part 3 Stage 6."""

from __future__ import annotations

import ast
import hashlib
import importlib
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any, cast

from tools.part3_stage4.administrator import compose
from tools.part3_stage4.resources import parse_module
from tools.part3_stage6.aws_cli import EXTRA_COMMANDS

COMMANDS = cast(
    dict[str, tuple[str, ...]],
    importlib.import_module("ledgerguard.stage2.aws_cli").COMMANDS,
)

EXPECTED_CONTROLLER_IAM = {
    "ATHENA_LIST_WORKGROUPS": "athena:ListWorkGroups",
    "CE_GET_COST": "ce:GetCostAndUsage",
    "CLOUDWATCH_DESCRIBE_ALARMS": "cloudwatch:DescribeAlarms",
    "DDB_DELETE_ITEM": "dynamodb:DeleteItem",
    "DDB_GET_ITEM": "dynamodb:GetItem",
    "DDB_LIST_TABLES": "dynamodb:ListTables",
    "DDB_PUT_ITEM": "dynamodb:PutItem",
    "GLUE_GET_DATABASES": "glue:GetDatabases",
    "GLUE_GET_JOBS": "glue:GetJobs",
    "IAM_GET_ACCOUNT_SUMMARY": "iam:GetAccountSummary",
    "IAM_GET_POLICY": "iam:GetPolicy",
    "IAM_GET_POLICY_VERSION": "iam:GetPolicyVersion",
    "IAM_GET_ROLE": "iam:GetRole",
    "IAM_LIST_ATTACHED_ROLE_POLICIES": "iam:ListAttachedRolePolicies",
    "IAM_LIST_ROLES": "iam:ListRoles",
    "IAM_LIST_ROLE_POLICIES": "iam:ListRolePolicies",
    "IAM_LIST_ROLE_TAGS": "iam:ListRoleTags",
    "KMS_DESCRIBE_KEY": "kms:DescribeKey",
    "LAMBDA_LIST_FUNCTIONS": "lambda:ListFunctions",
    "LOGS_DESCRIBE_GROUPS": "logs:DescribeLogGroups",
    "QUOTAS_LIST": "servicequotas:ListServiceQuotas",
    "S3_GET_BUCKET_ENCRYPTION": "s3:GetEncryptionConfiguration",
    "S3_GET_BUCKET_LOCATION": "s3:GetBucketLocation",
    "S3_GET_BUCKET_POLICY": "s3:GetBucketPolicy",
    "S3_GET_BUCKET_VERSIONING": "s3:GetBucketVersioning",
    "S3_GET_LIFECYCLE": "s3:GetLifecycleConfiguration",
    "S3_GET_OWNERSHIP": "s3:GetBucketOwnershipControls",
    "S3_GET_PUBLIC_ACCESS": "s3:GetBucketPublicAccessBlock",
    "S3_LIST_BUCKETS": "s3:ListAllMyBuckets",
    "S3_LIST_VERSIONS": "s3:ListBucketVersions",
    "SFN_LIST": "states:ListStateMachines",
    "STS_GET_CALLER_IDENTITY": "sts:GetCallerIdentity",
    "TAG_GET_RESOURCES": "tag:GetResources",
}
EXPECTED_ROLE_PROBE_IAM = {
    ("athena", "list-work-groups"): "athena:ListWorkGroups",
    ("athena", "stop-query-execution"): "athena:StopQueryExecution",
    ("dynamodb", "describe-table"): "dynamodb:DescribeTable",
    ("dynamodb", "update-item"): "dynamodb:UpdateItem",
    ("glue", "batch-stop-job-run"): "glue:BatchStopJobRun",
    ("iam", "get-role"): "iam:GetRole",
    ("kms", "describe-key"): "kms:DescribeKey",
    ("s3api", "get-bucket-encryption"): "s3:GetEncryptionConfiguration",
    ("s3api", "get-bucket-location"): "s3:GetBucketLocation",
    ("s3api", "upload-part"): "s3:PutObject",
    ("stepfunctions", "stop-execution"): "states:StopExecution",
    ("sts", "get-caller-identity"): "sts:GetCallerIdentity",
}
ALLOWED_CLASSES = {
    "READ",
    "BOUNDED_CONTROL_MUTATION",
    "READ_OR_EXPECTED_DENY",
    "BOUNDED_ABSENT_RESOURCE_NOOP",
    "CONDITIONALLY_IMPOSSIBLE_NOOP",
    "NONEXISTENT_MULTIPART_NOOP",
}
ROLES = {"deploy", "read", "recovery"}
KEY_VECTOR = "arn:aws:kms:ap-southeast-2:857229544428:key/00000000-0000-0000-0000-000000000001"


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"object required: {path}")
    return value


def _functions(tree: ast.Module, names: set[str] | None) -> Iterable[ast.AST]:
    if names is None:
        return tree.body
    return [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names
    ]


def _controller_calls(root: Path) -> set[str]:
    calls: set[str] = set()
    sources = (
        ("tools/part3_stage6/live.py", None),
        ("tools/part3_stage6/recovery.py", None),
        ("tools/part3_stage2_runtime.py", {"_cost_headroom_check"}),
    )
    for relative, names in sources:
        tree = ast.parse((root / relative).read_text(encoding="utf-8"), filename=relative)
        for top in _functions(tree, names):
            for node in ast.walk(top):
                if not (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "invoke"
                    and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str)
                ):
                    continue
                calls.add(node.args[0].value)
    return calls


def _role_probe_calls(root: Path) -> set[tuple[str, str]]:
    relative = "tools/run_part3_stage6_role_probe.py"
    tree = ast.parse((root / relative).read_text(encoding="utf-8"), filename=relative)
    calls: set[tuple[str, str]] = set()
    services = {"athena", "dynamodb", "glue", "iam", "kms", "s3api", "stepfunctions", "sts"}
    for node in ast.walk(tree):
        values: tuple[str, str] | None = None
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_invoke"
            and len(node.args) >= 2
            and all(
                isinstance(arg, ast.Constant) and isinstance(arg.value, str)
                for arg in node.args[:2]
            )
        ):
            values = (
                cast(str, cast(ast.Constant, node.args[0]).value),
                cast(str, cast(ast.Constant, node.args[1]).value),
            )
        elif (
            isinstance(node, ast.Tuple)
            and len(node.elts) == 3
            and all(
                isinstance(item, ast.Constant) and isinstance(item.value, str)
                for item in node.elts[:2]
            )
        ):
            values = (
                cast(str, cast(ast.Constant, node.elts[0]).value),
                cast(str, cast(ast.Constant, node.elts[1]).value),
            )
        if values is not None and values[0] in services:
            calls.add(values)
    return calls


def _actions(policies: dict[str, dict[str, Any]], effect: str) -> set[str]:
    result: set[str] = set()
    for policy in policies.values():
        for row in policy.get("Statement", []):
            if row.get("Effect") != effect:
                continue
            actions = row.get("Action", [])
            result.update([actions] if isinstance(actions, str) else actions)
    return result


def _statement(policies: dict[str, dict[str, Any]], sid: str) -> dict[str, Any]:
    rows = [
        row
        for policy in policies.values()
        for row in policy.get("Statement", [])
        if row.get("Sid") == sid
    ]
    if len(rows) != 1:
        raise ValueError(f"exact policy statement missing or duplicated: {sid}")
    return cast(dict[str, Any], rows[0])


def validate(root: Path, manifest: dict[str, Any] | None = None) -> dict[str, Any]:
    manifest = manifest or _load(root / "spec/part3-stage6-operation-manifest-v1.json")
    if manifest.get("schema_version") != "ledgerguard.part3-stage6-operation-manifest.v1":
        raise ValueError("operation manifest schema differs")
    if manifest.get("classification") != "STATIC_COMPLETE_STAGE6_OPERATION_AUTHORITY":
        raise ValueError("operation manifest classification differs")
    if manifest.get("stage6_complete") is not False:
        raise ValueError("operation manifest cannot complete Stage 6")

    controller_rows = manifest.get("controller_operations")
    if not isinstance(controller_rows, list) or any(
        not isinstance(row, list) or len(row) != 5 for row in controller_rows
    ):
        raise ValueError("controller operation rows invalid")
    controller = {row[0]: row for row in controller_rows}
    if len(controller) != len(controller_rows):
        raise ValueError("controller operation identity duplicated")
    actual_controller = _controller_calls(root)
    if actual_controller != set(EXPECTED_CONTROLLER_IAM) or set(controller) != actual_controller:
        raise ValueError("controller operation manifest differs from reachable calls")
    if any(controller[name][1] != action for name, action in EXPECTED_CONTROLLER_IAM.items()):
        raise ValueError("controller IAM action mapping differs")
    if any(controller[name][2] not in ALLOWED_CLASSES for name in controller):
        raise ValueError("controller mutation class differs")
    if any(not set(controller[name][3]).issubset(ROLES) for name in controller):
        raise ValueError("controller role scope differs")
    adapters = set(COMMANDS) | set(EXTRA_COMMANDS)
    if not actual_controller.issubset(adapters):
        raise ValueError("reachable controller call bypasses the AWS adapter")

    probe_rows = manifest.get("role_probe_operations")
    if not isinstance(probe_rows, list) or any(
        not isinstance(row, list) or len(row) != 5 for row in probe_rows
    ):
        raise ValueError("role probe operation rows invalid")
    probes = {(row[0], row[1]): row for row in probe_rows}
    if len(probes) != len(probe_rows):
        raise ValueError("role probe operation identity duplicated")
    actual_probes = _role_probe_calls(root)
    if actual_probes != set(EXPECTED_ROLE_PROBE_IAM) or set(probes) != actual_probes:
        raise ValueError("role probe manifest differs from reachable calls")
    if any(probes[key][2] != action for key, action in EXPECTED_ROLE_PROBE_IAM.items()):
        raise ValueError("role probe IAM action mapping differs")
    if any(probes[key][3] not in ALLOWED_CLASSES for key in probes):
        raise ValueError("role probe mutation class differs")
    if any(not set(probes[key][4]).issubset(ROLES) for key in probes):
        raise ValueError("role probe role scope differs")

    provider = _load(root / manifest["terraform_provider_authority"]["path"])
    provider_actions = {
        action for row in provider.get("statements", []) for action in row.get("actions", [])
    }
    if provider.get("provider_version") != "6.11.0" or len(provider_actions) != 127:
        raise ValueError("Terraform provider operation authority differs")
    if "athena:ListWorkGroups" in provider_actions:
        raise ValueError("controller inventory permission leaked into provider authority")
    if manifest["terraform_provider_authority"].get("mutating_capabilities_invoked") is not False:
        raise ValueError("Stage 6 cannot invoke provider mutations")

    module = parse_module(root / "infra/part3")
    packet = compose(provider, module, "release-qual1", KEY_VECTOR)
    deploy = packet["deploy_policies"]
    read = packet["read_policies"]
    deploy_actions = _actions(deploy, "Allow")
    read_actions = _actions(read, "Allow")
    requirement = manifest["policy_requirements"]
    list_action = requirement["deploy_only_inventory_action"]
    if list_action not in deploy_actions or list_action in read_actions:
        raise ValueError("Athena workgroup inventory role boundary differs")
    list_statement = _statement(deploy, "ListAthenaWorkgroupsForCleanInventory")
    if list_statement != {
        "Sid": "ListAthenaWorkgroupsForCleanInventory",
        "Effect": "Allow",
        "Action": [list_action],
        "Resource": [requirement["deploy_only_inventory_resource"]],
        "Condition": requirement["deploy_only_inventory_condition"],
    }:
        raise ValueError("Athena workgroup inventory policy scope differs")
    required_denies = set(requirement["all_roles_must_deny_workload_start"])
    if not required_denies.issubset(_actions(deploy, "Deny")) or not required_denies.issubset(
        _actions(read, "Deny")
    ):
        raise ValueError("workload start denial differs")

    manifest_bytes = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    return {
        "classification": "STAGE6_OPERATION_MANIFEST_LOCALLY_VERIFIED",
        "controller_operations": len(controller),
        "role_probe_operations": len(probes),
        "terraform_provider_actions": len(provider_actions),
        "athena_list_workgroups_deploy_allowed": True,
        "athena_list_workgroups_read_denied": True,
        "workload_start_denies": len(required_denies),
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "aws_calls": 0,
        "stage6_complete": False,
    }


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    print(json.dumps(validate(root), sort_keys=True))


if __name__ == "__main__":
    main()
