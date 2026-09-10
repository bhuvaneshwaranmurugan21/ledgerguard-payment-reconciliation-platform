"""Compose administrator-reviewed policies; never install them or assume a role.

An exact backend key ARN is mandatory. Unit-test keys are not environment
observations and cannot produce an accepted administrator packet.
"""

from __future__ import annotations

import json
import re
from typing import Any

from tools.part3_stage4.iam import ACCOUNT, REGION, ROLES, WORKLOAD_STARTS, identities, resolve

BACKEND_BUCKET = f"ledgerguard-tfstate-{ACCOUNT}-{REGION}"
LEASE_TABLE = f"arn:aws:dynamodb:{REGION}:{ACCOUNT}:table/ledgerguard-operation-leases"
LEASE_KEY = "ledgerguard/part3/platform/deployment"
DEPLOY_ROLE = f"arn:aws:iam::{ACCOUNT}:role/LedgerGuardGitHubOidcRole"


def statement(
    sid: str, actions: list[str], resources: list[str], condition: dict[str, Any] | None = None
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "Sid": sid,
        "Effect": "Allow",
        "Action": actions,
        "Resource": resources,
    }
    if condition:
        result["Condition"] = condition
    return result


def partition_policies(rows: list[dict[str, Any]], prefix: str) -> dict[str, Any]:
    """Deterministic managed-policy partitions respecting each 6,144-byte limit."""
    result: dict[str, Any] = {}
    batch: list[dict[str, Any]] = []
    for row in rows:
        document = {"Version": "2012-10-17", "Statement": [*batch, row]}
        if len(json.dumps(document, separators=(",", ":"))) > 6144:
            if not batch:
                raise ValueError("single IAM statement exceeds managed policy size")
            result[f"{prefix}-{len(result) + 1:02}"] = {"Version": "2012-10-17", "Statement": batch}
            batch = []
            if (
                len(
                    json.dumps({"Version": "2012-10-17", "Statement": [row]}, separators=(",", ":"))
                )
                > 6144
            ):
                raise ValueError("single IAM statement exceeds managed policy size")
        batch.append(row)
    if batch:
        result[f"{prefix}-{len(result) + 1:02}"] = {"Version": "2012-10-17", "Statement": batch}
    # A conservative local envelope, not an assertion of this account's quota.
    if not result or len(result) > 10:
        raise ValueError("managed policy attachment envelope exceeded or empty")
    return result


def compose(
    provider: dict[str, Any], module: dict[str, Any], operation_id: str, backend_kms_key_arn: str
) -> dict[str, Any]:
    """Return the exact desired successor, separate inventory set and rescue delta.

    This is a source-qualified design, not AWS effective-permission proof. The
    administrator must observe and validate the live key, trust, policy versions,
    boundary, SCP/session restrictions, quotas and Access Analyzer findings.
    """
    if not re.fullmatch(
        rf"arn:aws:kms:{REGION}:{ACCOUNT}:key/"
        r"(?:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|mrk-[0-9a-f]{32})",
        backend_kms_key_arn,
    ):
        raise ValueError("exact observed backend KMS key ARN is required")
    names = identities(operation_id)
    logs = resolve(
        module["locals"]["log_names"], {"local." + key: value for key, value in names.items()}
    )
    bindings = dict(names, function_arns=list(names["function_arns"].values()))
    bindings["log_arns"] = [
        f"arn:aws:logs:{REGION}:{ACCOUNT}:log-group:{name}{suffix}"
        for name in logs.values()
        for suffix in ("", ":*")
    ]
    bindings["alarm_arns"] = [
        f"arn:aws:cloudwatch:{REGION}:{ACCOUNT}:alarm:{names['name']}-{suffix}"
        for suffix in ("validator-errors", "controller-errors", "workflow-failure")
    ]
    read: list[dict[str, Any]] = []
    mutate: list[dict[str, Any]] = []
    cleanup: list[dict[str, Any]] = []
    categories = {"READ": read, "MUTATE": mutate, "CLEANUP": cleanup}
    seen: set[str] = set()
    for row in provider["statements"]:
        if row["sid"] in seen or row["classification"] not in categories:
            raise ValueError("duplicate or unclassified provider statement")
        seen.add(row["sid"])
        if any("*" in action or "?" in action for action in row["actions"]):
            raise ValueError("wildcard IAM action is not admitted")
        expanded = resolve(row["resources"], bindings)
        resources = [
            arn for group in expanded for arn in (group if isinstance(group, list) else [group])
        ]
        if not resources or not all(isinstance(arn, str) for arn in resources):
            raise ValueError("invalid provider resource binding")
        categories[row["classification"]].append(statement(row["sid"], row["actions"], resources))
    mutate.append(
        statement(
            "CreateExactRegionalBucket",
            ["s3:CreateBucket"],
            [names["bucket_arn"]],
            {"StringEquals": {"s3:LocationConstraint": REGION}},
        )
    )
    services = {
        "glue": "glue.amazonaws.com",
        "workflow": "states.amazonaws.com",
        "validator": "lambda.amazonaws.com",
        "controller": "lambda.amazonaws.com",
    }
    for role in ROLES:
        arn = names["role_arns"][role]
        mutate.extend(
            [
                statement(
                    "CreateBounded" + role.title(),
                    ["iam:CreateRole"],
                    [arn],
                    {"StringEquals": {"iam:PermissionsBoundary": names["boundary_arns"][role]}},
                ),
                statement(
                    "ManageOwned" + role.title(),
                    [
                        "iam:PutRolePolicy",
                        "iam:DeleteRolePolicy",
                        "iam:DeleteRole",
                        "iam:TagRole",
                        "iam:UntagRole",
                    ],
                    [arn],
                ),
                statement(
                    "PassExact" + role.title(),
                    ["iam:PassRole"],
                    [arn],
                    {"StringEquals": {"iam:PassedToService": services[role]}},
                ),
            ]
        )
    read.append(
        statement(
            "ReadRuntimeAndDeployIdentity",
            [
                "iam:GetRole",
                "iam:GetRolePolicy",
                "iam:ListRolePolicies",
                "iam:ListAttachedRolePolicies",
                "iam:ListRoleTags",
                "iam:ListInstanceProfilesForRole",
            ],
            [DEPLOY_ROLE, *names["role_arns"].values()],
        )
    )
    read.append(
        statement("ReadIdentityInventory", ["iam:ListRoles", "iam:GetAccountSummary"], ["*"])
    )
    read.append(
        statement(
            "ReadBackendControls",
            [
                "s3:GetBucketLocation",
                "s3:GetBucketVersioning",
                "s3:GetEncryptionConfiguration",
                "s3:GetBucketPolicy",
                "s3:GetBucketPublicAccessBlock",
                "s3:GetBucketOwnershipControls",
                "s3:GetLifecycleConfiguration",
                "s3:GetBucketTagging",
            ],
            ["arn:aws:s3:::" + BACKEND_BUCKET],
        )
    )
    state_key = f"ledgerguard/terraform/part3/platform/{operation_id}/terraform.tfstate"
    state_arn = f"arn:aws:s3:::{BACKEND_BUCKET}/{state_key}"
    read.append(
        statement(
            "ListExactStateAndLock",
            ["s3:ListBucket"],
            ["arn:aws:s3:::" + BACKEND_BUCKET],
            {"StringEquals": {"s3:prefix": [state_key, state_key + ".tflock"]}},
        )
    )
    read.append(
        statement("ReadExactStateAndLock", ["s3:GetObject"], [state_arn, state_arn + ".tflock"])
    )
    mutate.extend(
        [
            statement(
                "WriteExactStateAndLock", ["s3:PutObject"], [state_arn, state_arn + ".tflock"]
            ),
            statement("RemoveExactLockOnly", ["s3:DeleteObject"], [state_arn + ".tflock"]),
        ]
    )
    via_s3 = {
        "StringEquals": {
            "kms:ViaService": f"s3.{REGION}.amazonaws.com",
            "kms:CallerAccount": ACCOUNT,
        }
    }
    # Bucket keys change the KMS encryption context to the bucket ARN; the exact
    # key + ViaService + exact S3 object grants remain authoritative in either mode.
    read.append(statement("ReadBackendKey", ["kms:DescribeKey"], [backend_kms_key_arn]))
    read.append(
        statement("DecryptExactBackendKeyThroughS3", ["kms:Decrypt"], [backend_kms_key_arn], via_s3)
    )
    mutate.append(
        statement(
            "EncryptExactBackendKeyThroughS3",
            ["kms:Encrypt", "kms:GenerateDataKey"],
            [backend_kms_key_arn],
            via_s3,
        )
    )
    read.extend(
        [
            statement(
                "ReadLeaseControls",
                [
                    "dynamodb:DescribeTable",
                    "dynamodb:DescribeTimeToLive",
                    "dynamodb:DescribeContinuousBackups",
                    "dynamodb:ListTagsOfResource",
                ],
                [LEASE_TABLE],
            ),
            statement(
                "ReadDeploymentLease",
                ["dynamodb:GetItem"],
                [LEASE_TABLE],
                {"ForAllValues:StringEquals": {"dynamodb:LeadingKeys": [LEASE_KEY]}},
            ),
        ]
    )
    mutate.append(
        statement(
            "ConditionalDeploymentLease",
            ["dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:DeleteItem"],
            [LEASE_TABLE],
            {"ForAllValues:StringEquals": {"dynamodb:LeadingKeys": [LEASE_KEY]}},
        )
    )
    deny = {
        "Sid": "NoDeploymentIdentityWorkloadStart",
        "Effect": "Deny",
        "Action": WORKLOAD_STARTS,
        "Resource": ["*"],
    }
    # Managed-policy self-observation uses the exact bounded partition namespace;
    # administrator-only CreatePolicy/CreatePolicyVersion/AttachRolePolicy stay absent.
    read.append(
        statement(
            "ReadApprovedPolicyVersions",
            ["iam:GetPolicy", "iam:GetPolicyVersion", "iam:ListPolicyVersions"],
            list(names["boundary_arns"].values())
            + [
                f"arn:aws:iam::{ACCOUNT}:policy/LedgerGuardPart3Deploy-v1-{i:02}"
                for i in range(1, 11)
            ],
        )
    )
    read_policies = partition_policies([*read, deny], "LedgerGuardPart3Read-v1")
    deploy_policies = partition_policies(
        read + mutate + cleanup + [deny], "LedgerGuardPart3Deploy-v1"
    )
    rescue = partition_policies(
        [
            statement("StopOwnedGlue", ["glue:BatchStopJobRun"], [names["glue_arn"]]),
            statement(
                "StopOwnedExecution",
                ["states:StopExecution"],
                [f"arn:aws:states:{REGION}:{ACCOUNT}:execution:{names['name']}-reconciliation:*"],
            ),
            statement("StopOwnedAthena", ["athena:StopQueryExecution"], [names["workgroup_arn"]]),
        ],
        "LedgerGuardPart3RescueDelta-v1",
    )
    return {
        "schema_version": "1.0",
        "classification": "DESIRED_NOT_INSTALLED_OR_AWS_VALIDATED",
        "operation_id": operation_id,
        "backend": {
            "bucket": BACKEND_BUCKET,
            "key": state_key,
            "region": REGION,
            "encrypt": True,
            "kms_key_id": backend_kms_key_arn,
            "use_lockfile": True,
        },
        "lease": {"table_arn": LEASE_TABLE, "key": LEASE_KEY},
        "read_policies": read_policies,
        "deploy_policies": deploy_policies,
        "rescue_delta_policies": rescue,
        "rescue_identity": "ADMINISTRATOR_SELECTED_SEPARATE_ROLE",
        "trust_change": False,
        "executor_self_remediation": False,
        "aws_execution": False,
    }
