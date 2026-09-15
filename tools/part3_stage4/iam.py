"""Render exact Stage 4 IAM packets without contacting AWS or changing IAM."""

from __future__ import annotations

import json
import re
from copy import deepcopy
from typing import Any

ACCOUNT = "857229544428"
REGION = "ap-southeast-2"
ROLES = ("glue", "workflow", "validator", "controller")
WORKLOAD_STARTS = [
    "glue:StartJobRun",
    "states:StartExecution",
    "states:StartSyncExecution",
    "lambda:InvokeFunction",
    "lambda:InvokeAsync",
    "athena:StartQueryExecution",
]


def identities(operation_id: str) -> dict[str, Any]:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{7,31}", operation_id):
        raise ValueError("invalid operation identity")
    name = "ledgerguard-p3-" + operation_id
    bucket = f"ledgerguard-p3-{ACCOUNT}-{operation_id}"
    database = (name + "-reconciliation").replace("-", "_")
    return {
        "name": name,
        "bucket": bucket,
        "bucket_arn": "arn:aws:s3:::" + bucket,
        "control_arn": f"arn:aws:dynamodb:{REGION}:{ACCOUNT}:table/{name}-control",
        "glue_arn": f"arn:aws:glue:{REGION}:{ACCOUNT}:job/{name}-reconciliation",
        "workgroup_arn": f"arn:aws:athena:{REGION}:{ACCOUNT}:workgroup/{name}-checks",
        "workflow_arn": f"arn:aws:states:{REGION}:{ACCOUNT}:stateMachine:{name}-reconciliation",
        "catalog_arns": [
            f"arn:aws:glue:{REGION}:{ACCOUNT}:catalog",
            f"arn:aws:glue:{REGION}:{ACCOUNT}:database/{database}",
        ]
        + [
            f"arn:aws:glue:{REGION}:{ACCOUNT}:table/{database}/{table}"
            for table in ("transactions", "settlements", "bank_allocations")
        ],
        "function_arns": {
            role: f"arn:aws:lambda:{REGION}:{ACCOUNT}:function:{name}-{role}"
            for role in ("validator", "controller")
        },
        "role_arns": {
            role: f"arn:aws:iam::{ACCOUNT}:role/ledgerguard/{name}-{role}" for role in ROLES
        },
        "boundary_arns": {
            role: f"arn:aws:iam::{ACCOUNT}:policy/LedgerGuardPart3-{role}-Boundary-v1"
            for role in ROLES
        },
    }


def resolve(value: Any, bindings: dict[str, Any]) -> Any:
    """Resolve the reviewed atomic references only; never evaluate arbitrary HCL."""
    if isinstance(value, dict):
        return {key: resolve(item, bindings) for key, item in value.items()}
    if isinstance(value, list):
        return [resolve(item, bindings) for item in value]
    if not isinstance(value, str):
        return value
    full = re.fullmatch(r"\$\{([^{}]+)\}", value)
    if full:
        if full[1] not in bindings:
            raise ValueError("unreviewed IAM reference: " + full[1])
        return deepcopy(bindings[full[1]])
    for match in list(re.finditer(r"\$\{([^{}]+)\}", value)):
        replacement = bindings.get(match[1])
        if not isinstance(replacement, str):
            raise ValueError("unreviewed IAM interpolation: " + match[1])
        value = value.replace(match[0], replacement)
    if "${" in value:
        raise ValueError("unresolved IAM interpolation")
    return value


def runtime_policies(
    module: dict[str, Any], operation_id: str, objects: dict[str, str]
) -> dict[str, Any]:
    names = identities(operation_id)
    if set(objects) != {"script_key", "wheels_key"}:
        raise ValueError("deployment object inventory differs")
    for field, suffix in [
        ("script_key", "ledgerguard_stage3_job.py"),
        ("wheels_key", "ledgerguard.gluewheels.zip"),
    ]:
        if not re.fullmatch(
            r"deployment/[0-9a-f]{64}/" + re.escape(suffix), objects.get(field, "")
        ):
            raise ValueError("unqualified deployment object: " + field)
    bindings = {"local." + key: value for key, value in names.items()}
    bindings.update({"var.stage5_release." + key: value for key, value in objects.items()})
    bindings.update(
        {f'local.function_arns["{role}"]': arn for role, arn in names["function_arns"].items()}
    )
    logs = resolve(module["locals"]["log_names"], bindings)
    result = {}
    for role in ROLES:
        statements = resolve(module["locals"]["runtime_statements"][role], bindings)
        keys = module["locals"]["role_log_keys"][role]
        if keys:
            statements.append(
                {
                    "Sid": "WriteOwnStructuredLogs",
                    "Effect": "Allow",
                    "Action": ["logs:CreateLogStream", "logs:PutLogEvents"],
                    "Resource": [
                        f"arn:aws:logs:{REGION}:{ACCOUNT}:log-group:{logs[key]}:*" for key in keys
                    ],
                }
            )
        if role in ("validator", "controller"):
            statements.append(
                {
                    "Sid": "LambdaTraceTelemetry",
                    "Effect": "Allow",
                    "Action": ["xray:PutTraceSegments", "xray:PutTelemetryRecords"],
                    "Resource": ["*"],
                    "Condition": {"StringEquals": {"aws:RequestedRegion": REGION}},
                }
            )
        result[role] = {"Version": "2012-10-17", "Statement": statements}
    return result


def runtime_boundaries(policies: dict[str, Any], operation_id: str) -> dict[str, Any]:
    """Role-specific ceilings also prevent any Part 3 runtime workload mutation.

    The inline policies describe future task interfaces. These explicit denials are
    the Part 3 safety boundary; no managed reconciliation effectiveness is claimed.
    """
    names = identities(operation_id)
    if set(policies) != set(ROLES):
        raise ValueError("runtime boundary role inventory differs")
    result = deepcopy(policies)
    for role in ROLES:
        result[role]["Statement"].extend(
            [
                {
                    "Sid": "NoPart3WorkloadStart",
                    "Effect": "Deny",
                    "Action": WORKLOAD_STARTS,
                    "Resource": "*",
                },
                {
                    "Sid": "NoIdentityChaining",
                    "Effect": "Deny",
                    "Action": ["sts:AssumeRole"],
                    "Resource": "*",
                },
                {
                    "Sid": "NoPart3BusinessObjects",
                    "Effect": "Deny",
                    "Action": ["s3:PutObject", "s3:DeleteObject", "s3:DeleteObjectVersion"],
                    "Resource": [
                        names["bucket_arn"] + "/" + prefix + "/*"
                        for prefix in ("runs", "publications", "query-results")
                    ],
                },
                {
                    "Sid": "NoPart3BusinessRecords",
                    "Effect": "Deny",
                    "Action": [
                        "dynamodb:PutItem",
                        "dynamodb:UpdateItem",
                        "dynamodb:DeleteItem",
                        "dynamodb:BatchWriteItem",
                        "dynamodb:PartiQLInsert",
                        "dynamodb:PartiQLUpdate",
                        "dynamodb:PartiQLDelete",
                    ],
                    "Resource": names["control_arn"],
                },
            ]
        )
        if len(json.dumps(result[role], separators=(",", ":"))) > 6144:
            raise ValueError("managed runtime boundary exceeds IAM policy size: " + role)
    return result


def exact_policy_set(expected: dict[str, Any], observed: dict[str, Any]) -> dict[str, Any]:
    """Compare named administrator policy documents; excess is drift, not harmless."""
    missing, excess = (
        sorted(expected.keys() - observed.keys()),
        sorted(observed.keys() - expected.keys()),
    )
    changed = sorted(
        name
        for name in expected.keys() & observed.keys()
        if json.dumps(expected[name], sort_keys=True) != json.dumps(observed[name], sort_keys=True)
    )
    if missing or excess or changed:
        raise ValueError(
            json.dumps({"missing": missing, "excess": excess, "changed": changed}, sort_keys=True)
        )
    return {"equal": True, "missing": [], "excess": [], "changed": []}
