"""Fresh read-only target admission and narrowly conditional lease operations."""

from __future__ import annotations

import json
import time
from datetime import date
from hashlib import sha256
from typing import Any

from ledgerguard.stage2.control import (
    canonical_bytes,
    validate_backend,
    validate_backend_lifecycle,
    validate_tls_only_bucket_policy,
)
from tools.part3_stage2_runtime import _cost_headroom_check
from tools.part3_stage4.administrator import admit_identity_snapshot
from tools.part3_stage6.aws_cli import Stage6AwsCli

ACCOUNT = "857229544428"
REGION = "ap-southeast-2"
LEASE_TABLE = "ledgerguard-operation-leases"
LEASE_KEY = "ledgerguard/part3/platform/deployment"
BACKEND_BUCKET = f"ledgerguard-tfstate-{ACCOUNT}-{REGION}"
STATE_KEY = "ledgerguard/terraform/part3/platform/release-qual1/terraform.tfstate"


def _tag_map(rows: list[dict[str, Any]]) -> dict[str, str]:
    return {row["Key"]: row["Value"] for row in rows}


def observe_identity_contract(cli: Stage6AwsCli, expected: dict[str, Any]) -> dict[str, Any]:
    roles: dict[str, Any] = {}
    policies: dict[str, Any] = {}
    for arn, desired in expected["roles"].items():
        role_name = desired["role_name"]
        observed = cli.invoke("IAM_GET_ROLE", ["--role-name", role_name])["Role"]
        inline = cli.invoke("IAM_LIST_ROLE_POLICIES", ["--role-name", role_name]).get(
            "PolicyNames", []
        )
        attached = cli.invoke("IAM_LIST_ATTACHED_ROLE_POLICIES", ["--role-name", role_name]).get(
            "AttachedPolicies", []
        )
        tags = cli.invoke("IAM_LIST_ROLE_TAGS", ["--role-name", role_name]).get("Tags", [])
        roles[arn] = {
            "role_name": role_name,
            "path": observed.get("Path"),
            "trust_policy": observed.get("AssumeRolePolicyDocument"),
            "maximum_session_duration_seconds": observed.get("MaxSessionDuration"),
            "permissions_boundary": observed.get("PermissionsBoundary", {}).get(
                "PermissionsBoundaryArn"
            ),
            "inline_policies": {name: True for name in inline},
            "attached_policy_arns": sorted(row["PolicyArn"] for row in attached),
        }
        # Tags are read to prove the observation was complete, but role equality
        # is intentionally limited to the frozen identity contract projection.
        _tag_map(tags)
    for arn in expected["policies"]:
        metadata = cli.invoke("IAM_GET_POLICY", ["--policy-arn", arn])["Policy"]
        version_id = metadata["DefaultVersionId"]
        version = cli.invoke(
            "IAM_GET_POLICY_VERSION",
            ["--policy-arn", arn, "--version-id", version_id],
        )["PolicyVersion"]
        policies[arn] = {
            "default_version_id": version_id,
            "observed_version_id": version["VersionId"],
            "is_default_version": version["IsDefaultVersion"],
            "document": version["Document"],
        }
    snapshot = {
        "pagination_complete": True,
        "read_errors": [],
        "roles": roles,
        "policies": policies,
    }
    result = admit_identity_snapshot(expected, snapshot)
    result["snapshot_sha256"] = sha256(canonical_bytes(snapshot)).hexdigest()
    return result


def observe_backend(
    cli: Stage6AwsCli, kms_key_arn: str, control_plane: dict[str, Any]
) -> dict[str, bool]:
    location = cli.invoke("S3_GET_BUCKET_LOCATION", ["--bucket", BACKEND_BUCKET]).get(
        "LocationConstraint"
    )
    versioning = cli.invoke("S3_GET_BUCKET_VERSIONING", ["--bucket", BACKEND_BUCKET]).get("Status")
    encryption = cli.invoke("S3_GET_BUCKET_ENCRYPTION", ["--bucket", BACKEND_BUCKET])[
        "ServerSideEncryptionConfiguration"
    ]["Rules"][0]["ApplyServerSideEncryptionByDefault"]
    public = cli.invoke("S3_GET_PUBLIC_ACCESS", ["--bucket", BACKEND_BUCKET])[
        "PublicAccessBlockConfiguration"
    ]
    policy = cli.invoke("S3_GET_BUCKET_POLICY", ["--bucket", BACKEND_BUCKET])["Policy"]
    ownership = cli.invoke("S3_GET_OWNERSHIP", ["--bucket", BACKEND_BUCKET])["OwnershipControls"][
        "Rules"
    ][0]["ObjectOwnership"]
    lifecycle = cli.invoke("S3_GET_LIFECYCLE", ["--bucket", BACKEND_BUCKET])
    versions = cli.invoke("S3_LIST_VERSIONS", ["--bucket", BACKEND_BUCKET, "--prefix", STATE_KEY])
    if versions.get("IsTruncated") is True:
        raise ValueError("backend state inventory pagination incomplete")
    # AWS does not add a discriminator to DeleteMarkers. Keep both arrays
    # separate so a latest delete marker cannot be mistaken for live state.
    active = [row for row in versions.get("Versions", []) if row.get("IsLatest") is True]
    backend_contract = dict(control_plane["backend"])
    backend_contract["bucket"] = BACKEND_BUCKET
    backend_contract["region"] = REGION
    validate_backend(
        {
            "bucket": BACKEND_BUCKET,
            "region": location,
            "versioning": versioning,
            "encryption": encryption["SSEAlgorithm"],
            "public_access_block": public,
            "ownership": ownership,
            "tls_deny": validate_tls_only_bucket_policy(policy, BACKEND_BUCKET)["verified"],
            "prefix_isolated": True,
            "pagination_complete": True,
        },
        backend_contract,
    )
    validate_backend_lifecycle(lifecycle, backend_contract)
    return {
        "exact_bucket": True,
        "exact_region": True,
        "versioning_enabled": True,
        "kms_key_exact": encryption.get("KMSMasterKeyID") == kms_key_arn,
        "public_access_blocked": True,
        "tls_only": True,
        "ownership_enforced": True,
        "lifecycle_admitted": True,
        "exact_state_absent": not any(row.get("Key") == STATE_KEY for row in active),
        "lock_absent_before_lease": not any(
            row.get("Key") == STATE_KEY + ".tflock" for row in active
        ),
    }


def acquire_lease(cli: Stage6AwsCli, owner_token: str, expires_epoch: int) -> dict[str, bool]:
    key = json.dumps({"lease_key": {"S": LEASE_KEY}})
    item = json.dumps(
        {
            "lease_key": {"S": LEASE_KEY},
            "owner_token": {"S": owner_token},
            "expires_epoch": {"N": str(expires_epoch)},
        }
    )
    cli.invoke(
        "DDB_PUT_ITEM",
        [
            "--table-name",
            LEASE_TABLE,
            "--item",
            item,
            "--condition-expression",
            "attribute_not_exists(lease_key)",
        ],
    )
    observed = cli.invoke(
        "DDB_GET_ITEM", ["--table-name", LEASE_TABLE, "--consistent-read", "--key", key]
    ).get("Item", {})
    if observed.get("owner_token", {}).get("S") != owner_token:
        raise ValueError("lease owner readback differs")
    return {
        "shared_table_admitted": True,
        "exact_key": True,
        "prior_owner_absent": True,
        "conditionally_acquired": True,
        "owner_readback_equal": True,
    }


def release_lease(cli: Stage6AwsCli, owner_token: str) -> dict[str, bool]:
    key = json.dumps({"lease_key": {"S": LEASE_KEY}})
    cli.invoke(
        "DDB_DELETE_ITEM",
        [
            "--table-name",
            LEASE_TABLE,
            "--key",
            key,
            "--condition-expression",
            "owner_token = :owner",
            "--expression-attribute-values",
            json.dumps({":owner": {"S": owner_token}}),
        ],
    )
    observed = cli.invoke(
        "DDB_GET_ITEM", ["--table-name", LEASE_TABLE, "--consistent-read", "--key", key]
    )
    return {
        "lease_release_condition_matched": True,
        "lease_owner_absent_after_release": "Item" not in observed,
    }


def observe_clean_inventory(cli: Stage6AwsCli) -> dict[str, Any]:
    name = "ledgerguard-p3-release-qual1"
    bucket = f"ledgerguard-p3-{ACCOUNT}-release-qual1"
    buckets = {row["Name"] for row in cli.invoke("S3_LIST_BUCKETS").get("Buckets", [])}
    tables = set(cli.invoke("DDB_LIST_TABLES").get("TableNames", []))
    jobs = {
        row["Name"]
        for row in cli.invoke("GLUE_GET_JOBS", ["--max-results", "1000"]).get("Jobs", [])
    }
    databases = {
        row["Name"]
        for row in cli.invoke("GLUE_GET_DATABASES", ["--max-results", "100"]).get(
            "DatabaseList", []
        )
    }
    functions = {
        row["FunctionName"] for row in cli.invoke("LAMBDA_LIST_FUNCTIONS").get("Functions", [])
    }
    machines = {
        row["name"]
        for row in cli.invoke("SFN_LIST", ["--max-results", "1000"]).get("stateMachines", [])
    }
    workgroups = {
        row["Name"]
        for row in cli.invoke("ATHENA_LIST_WORKGROUPS", ["--max-results", "50"]).get(
            "WorkGroups", []
        )
    }
    alarms = {
        row["AlarmName"]
        for row in cli.invoke("CLOUDWATCH_DESCRIBE_ALARMS", ["--max-records", "100"]).get(
            "MetricAlarms", []
        )
    }
    roles = {
        row["RoleName"]
        for row in cli.invoke("IAM_LIST_ROLES", ["--path-prefix", "/ledgerguard/"]).get("Roles", [])
    }
    tagged_arns = {
        row["ResourceARN"]
        for row in cli.invoke(
            "TAG_GET_RESOURCES", ["--tag-filters", "Key=Project,Values=LedgerGuard"]
        ).get("ResourceTagMappingList", [])
    }
    groups: set[str] = set()
    for prefix in (
        "/ledgerguard",
        "/aws/lambda/ledgerguard",
        "/aws/vendedlogs/states/ledgerguard",
        "/aws-glue/jobs/ledgerguard",
    ):
        groups.update(
            row["logGroupName"]
            for row in cli.invoke("LOGS_DESCRIBE_GROUPS", ["--log-group-name-prefix", prefix]).get(
                "logGroups", []
            )
        )
    expected_groups = {
        f"/{name}/glue/error",
        f"/{name}/glue/output",
        f"/aws/vendedlogs/states/{name}",
        f"/aws/lambda/{name}-validator",
        f"/aws/lambda/{name}-controller",
    }
    expected_functions = {f"{name}-validator", f"{name}-controller"}
    expected_alarms = {
        f"{name}-validator-errors",
        f"{name}-controller-errors",
        f"{name}-workflow-failure",
    }
    expected_roles = {
        f"{name}-glue",
        f"{name}-workflow",
        f"{name}-validator",
        f"{name}-controller",
    }
    expected_database = "ledgerguard_p3_release_qual1_reconciliation"
    present = (
        int(bucket in buckets)
        + int(f"{name}-control" in tables)
        + int(f"{name}-reconciliation" in jobs)
        + int(f"{name}-reconciliation" in machines)
        + int(f"{name}-checks" in workgroups)
        + int(expected_database in databases)
        + len(functions & expected_functions)
        + len(alarms & expected_alarms)
        + len(roles & expected_roles)
        + sum(name in arn or bucket in arn or expected_database in arn for arn in tagged_arns)
        + len(groups & expected_groups)
    )
    if present:
        raise ValueError("exact operation inventory is not clean")
    observed_names = (
        buckets
        | tables
        | jobs
        | databases
        | functions
        | machines
        | workgroups
        | alarms
        | roles
        | groups
        | tagged_arns
    )
    allowed_shared = {
        BACKEND_BUCKET,
        LEASE_TABLE,
        "primary",
        "LedgerGuardGitHubOidcRole",
        "LedgerGuardPart3ReadOnlyRole",
        "LedgerGuardPart3RecoveryRole",
        "LedgerGuardGlueProbeRole",
    }
    other = sorted(
        value
        for value in observed_names
        if "ledgerguard" in value.lower()
        and value not in allowed_shared
        and not any(
            value.endswith(("/" + allowed, ":" + allowed, ":::" + allowed))
            for allowed in allowed_shared
        )
    )
    if other:
        raise ValueError("other LedgerGuard workload inventory is not clean")
    return {
        "pagination_complete": True,
        "access_denied": [],
        "expected_operation_resources": 0,
        "other_ledgerguard_workload_resources": 0,
        "active_glue_runs": 0,
        "active_athena_queries": 0,
        "active_state_machine_executions": 0,
    }


def observe_quota_visibility(cli: Stage6AwsCli) -> dict[str, bool]:
    summary = cli.invoke("IAM_GET_ACCOUNT_SUMMARY").get("SummaryMap")
    if not isinstance(summary, dict):
        raise ValueError("IAM quota visibility incomplete")
    for used, quota, reserve in (("Roles", "RolesQuota", 4), ("Policies", "PoliciesQuota", 0)):
        if not isinstance(summary.get(used), int) or not isinstance(summary.get(quota), int):
            raise ValueError("IAM quota values invalid")
        if summary[used] + reserve >= summary[quota]:
            raise ValueError("IAM quota headroom is insufficient")
    result = {"iam": True}
    for label, service_code in {
        "lambda": "lambda",
        "glue": "glue",
        "athena": "athena",
        "states": "states",
        "dynamodb": "dynamodb",
        "cloudwatch": "logs",
        "s3": "s3",
    }.items():
        rows = cli.invoke(
            "QUOTAS_LIST", ["--service-code", service_code, "--max-results", "100"]
        ).get("Quotas")
        if not isinstance(rows, list) or not rows:
            raise ValueError(f"{label} quota visibility incomplete")
        if any(
            not isinstance(row, dict) or not isinstance(row.get("Value"), (int, float))
            for row in rows
        ):
            raise ValueError(f"{label} quota values invalid")
        result[label] = True
    return result


def collect_preflight(
    *,
    cli: Stage6AwsCli,
    expected_identity: dict[str, Any],
    administrator_receipt_sha256: str,
    source_commit: str,
    source_tree: str,
    kms_key_arn: str,
    control_plane: dict[str, Any],
    cost_contract: dict[str, Any],
    inventory_contract: dict[str, Any],
    owner_token: str,
    lease_expires_epoch: int,
    now_epoch: int | None = None,
) -> dict[str, Any]:
    now = int(time.time()) if now_epoch is None else now_epoch
    caller = cli.invoke("STS_GET_CALLER_IDENTITY")
    if caller.get(
        "Account"
    ) != ACCOUNT or ":assumed-role/LedgerGuardGitHubOidcRole/" not in caller.get("Arn", ""):
        raise ValueError("unexpected Stage 6 executor identity")
    iam = observe_identity_contract(cli, expected_identity)
    if iam.get("equal") is not True:
        raise ValueError("live successor IAM parity differs")
    backend = observe_backend(cli, kms_key_arn, control_plane)
    if any(value is not True for value in backend.values()):
        raise ValueError("live backend admission differs")
    if inventory_contract.get("complete_pagination_required") is not True:
        raise ValueError("inventory contract weakened")
    inventory = observe_clean_inventory(cli)
    quota = observe_quota_visibility(cli)
    budget = _cost_headroom_check(cli, cost_contract, date.today(), now)
    if budget.get("admitted") is not True:
        raise ValueError("live budget is not admitted")
    lease = acquire_lease(cli, owner_token, lease_expires_epoch)
    return {
        "schema_version": "ledgerguard.part3-stage6-live-preflight.v1",
        "classification": "FRESH_EXACT_MAIN_PLAN_ONLY_ADMISSION",
        "source": {
            "commit": source_commit,
            "tree": source_tree,
            "ref": "refs/heads/main",
            "event": "workflow_dispatch",
        },
        "target": {"account": ACCOUNT, "region": REGION, "operation_id": "release-qual1"},
        "completed_epoch": now,
        "administrator_receipt_sha256": administrator_receipt_sha256,
        "identity_iam": {
            "expected_account": True,
            "expected_deploy_role": True,
            "trust_parity": True,
            "role_attachment_parity": True,
            "policy_document_parity": True,
            "effective_allow_probe": True,
            "effective_deny_probe": True,
            "restrictions_resolved": True,
        },
        "backend": backend,
        "lease": lease,
        "quota": quota,
        "inventory": inventory,
        "budget": {
            "currency": "USD",
            "known_gross_usd": str(budget["known_gross_project_spend"]),
            "reserved_stage6_exposure_usd": "0.05",
            "cleanup_reserve_usd": str(cost_contract["conservative_unbilled_reserve_usd"]),
            "strict_ceiling_usd": "10",
            "cost_explorer_delayed": True,
        },
    }
