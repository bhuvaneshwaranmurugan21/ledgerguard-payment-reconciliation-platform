"""Exact-main AWS read-only qualification and bounded capability probes."""

from __future__ import annotations

import json
import os
import secrets
import tempfile
import time
from datetime import UTC, date, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from ledgerguard.stage2.aws_cli import MUTATING_OPERATIONS, AwsCli
from ledgerguard.stage2.control import (
    MAIN_REF,
    REPOSITORY,
    Stage2Rejected,
    aggregate_gross_spend,
    budget_headroom,
    canonical_bytes,
    normalize_policy,
    policy_diff,
    read_object,
    require,
    validate_backend,
    validate_backend_lifecycle,
    validate_dispatch,
    validate_glue_job,
    validate_identity,
    validate_inventory,
    validate_lease_table,
    validate_required_tags,
    validate_s3_cleanup,
    validate_tls_only_bucket_policy,
)
from ledgerguard.stage2.evidence import finalize_artifact, write_json


def _root() -> Path:
    return Path(__file__).resolve().parents[1]


def _contracts(root: Path) -> tuple[dict[str, Any], ...]:
    return tuple(
        read_object(root / path)
        for path in (
            ".github/ledgerguard-target.json",
            "contracts/part3-stage2-oidc-trust-v1.json",
            "contracts/part3-stage2-iam-permissions-v1.json",
            "contracts/part3-stage2-control-plane-v1.json",
            "contracts/part3-stage2-cost-v1.json",
            "contracts/part3-stage2-inventory-v1.json",
            "contracts/part3-stage2-glue-probe-v1.json",
        )
    )


def _authority_digests(root: Path, workflow: str) -> dict[str, str]:
    paths = (
        ".github/ledgerguard-target.json",
        workflow,
        "contracts/part3-stage2-control-plane-v1.json",
        "contracts/part3-stage2-cost-v1.json",
        "contracts/part3-stage2-glue-probe-v1.json",
        "contracts/part3-stage2-iam-permissions-v1.json",
        "contracts/part3-stage2-inventory-v1.json",
        "contracts/part3-stage2-oidc-trust-v1.json",
        "contracts/part3-stage2-operation-allowlist-v1.json",
        "contracts/part3/stage2-live-evidence-v1.schema.json",
        "fixtures/part3-stage2/inert_glue_probe_script.py",
        "fixtures/part3-stage2/qualification.asl.json",
    )
    return {path: sha256((root / path).read_bytes()).hexdigest() for path in paths}


def _context(expected_sha: str) -> dict[str, str]:
    context = {
        "repository": os.environ.get("GITHUB_REPOSITORY", ""),
        "event_name": os.environ.get("GITHUB_EVENT_NAME", ""),
        "ref": os.environ.get("GITHUB_REF", ""),
        "sha": os.environ.get("GITHUB_SHA", ""),
        "checkout_sha": os.environ.get("CHECKED_OUT_SHA", ""),
    }
    validate_dispatch(context, expected_sha)
    return context


def _prepare_output(output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    require(output.is_dir() and not output.is_symlink(), "unsafe evidence output")
    for reserved in (
        "evidence.json",
        "api-journal.json",
        "mutation-journal.json",
        "manifest.json",
    ):
        require(not (output / reserved).exists(), f"evidence output already contains {reserved}")


def _tag_map(rows: list[dict[str, Any]]) -> dict[str, str]:
    return {row["Key"]: row["Value"] for row in rows}


def _inventory_checks(
    cli: AwsCli, inventory: dict[str, Any], control_plane: dict[str, Any]
) -> dict[str, Any]:
    buckets_response = cli.invoke("S3_LIST_BUCKETS")
    tables_response = cli.invoke("DDB_LIST_TABLES")
    jobs_response = cli.invoke("GLUE_GET_JOBS", ["--max-results", "1000"])
    machines_response = cli.invoke("SFN_LIST", ["--max-results", "1000"])
    logs_response = cli.invoke(
        "LOGS_DESCRIBE_GROUPS", ["--log-group-name-prefix", "/aws/ledgerguard"]
    )
    tags_response = cli.invoke("TAG_GET_RESOURCES", ["--resources-per-page", "100"])
    versions_response = cli.invoke(
        "S3_LIST_VERSIONS",
        [
            "--bucket",
            control_plane["backend"]["bucket"],
            "--prefix",
            control_plane["backend"]["qualification_prefix"] + "/",
        ],
    )
    require(versions_response.get("IsTruncated") is not True, "S3 inventory incomplete")
    lease_response = cli.invoke(
        "DDB_SCAN",
        [
            "--table-name",
            control_plane["lease"]["table"],
            "--filter-expression",
            "begins_with(#k, :prefix)",
            "--expression-attribute-names",
            json.dumps({"#k": control_plane["lease"]["partition_key"]}),
            "--expression-attribute-values",
            json.dumps({":prefix": {"S": control_plane["lease"]["key_namespace"] + "/"}}),
            "--projection-expression",
            "#k",
        ],
    )
    buckets = buckets_response.get("Buckets", [])
    tables = tables_response.get("TableNames", [])
    jobs = jobs_response.get("Jobs", [])
    machines = machines_response.get("stateMachines", [])
    log_groups = logs_response.get("logGroups", [])
    tagged = tags_response.get("ResourceTagMappingList", [])
    observed_names = [
        *[row["Name"] for row in buckets],
        *tables,
        *[row["Name"] for row in jobs],
        *[row["name"] for row in machines],
        *[row["logGroupName"] for row in log_groups],
        *[row["ResourceARN"].rsplit("/", 1)[-1].rsplit(":", 1)[-1] for row in tagged],
    ]
    allowed = set(inventory["allowed_shared_control_plane"])
    workload = sorted(
        {
            name
            for name in observed_names
            if name.lower().startswith("ledgerguard-") and name not in allowed
        }
    )
    versions = [
        *versions_response.get("Versions", []),
        *versions_response.get("DeleteMarkers", []),
    ]
    lease_items = lease_response.get("Items", [])
    probe_jobs = [row["Name"] for row in jobs if row["Name"].startswith("ledgerguard-stage2-")]
    residue = [
        *[f"s3:{sha256(row['Key'].encode()).hexdigest()}" for row in versions],
        *[
            "lease:"
            + sha256(row[control_plane["lease"]["partition_key"]]["S"].encode()).hexdigest()
            for row in lease_items
        ],
        *[f"glue:{sha256(name.encode()).hexdigest()}" for name in probe_jobs],
    ]
    result = validate_inventory(
        {
            "pagination_complete": True,
            "access_denied": [],
            "workload_resources": workload,
            "probe_residue": residue,
        }
    )
    result["observed_fingerprint"] = sha256(
        canonical_bytes({"names": sorted(set(observed_names)), "residue": sorted(residue)})
    ).hexdigest()
    result["counts"] = {
        "buckets": len(buckets),
        "tables": len(tables),
        "jobs": len(jobs),
        "state_machines": len(machines),
        "ledgerguard_log_groups": len(log_groups),
        "tagged_resources": len(tagged),
        "probe_residue": len(residue),
    }
    return result


def _cost_headroom_check(
    cli: AwsCli,
    cost: dict[str, Any],
    today: date,
    retrieved_epoch: int,
) -> dict[str, Any]:
    start = cost["known_activity_start"]
    end = today.isoformat()
    ce = cli.invoke(
        "CE_GET_COST",
        [
            "--time-period",
            f"Start={start},End={end}",
            "--granularity",
            "MONTHLY",
            "--metrics",
            cost["metric"],
            "--group-by",
            (
                f"Type={cost['aggregation']['group_by_type']},"
                f"Key={cost['aggregation']['group_by_key']}"
            ),
        ],
    )
    require("NextPageToken" not in ce, "Cost Explorer pagination incomplete")
    periods = ce.get("ResultsByTime", [])
    gross = aggregate_gross_spend(periods, cost["metric"], cost["currency"])
    observed_boundary = datetime.combine(today, datetime.min.time(), tzinfo=UTC)
    data_through_epoch = int(observed_boundary.timestamp())
    result = budget_headroom(
        {
            "currency": gross["currency"],
            "updated_epoch": data_through_epoch,
            "known_gross_project_spend": gross["known_gross_project_spend"],
        },
        cost,
        retrieved_epoch,
    )
    result.update(
        {
            "query_start": start,
            "query_end_exclusive": end,
            "metric": cost["metric"],
            "retrieved_epoch": retrieved_epoch,
            "data_through_epoch": data_through_epoch,
            "freshness_basis": "QUERY_WINDOW_END_EXCLUSIVE_WITH_UNBILLED_RESERVE",
            "contains_estimated_period": any(row.get("Estimated") is True for row in periods),
            "pagination_complete": True,
            "aggregation_dimension": gross["aggregation_dimension"],
            "gross_aggregation": gross["gross_aggregation"],
            "negative_amount_treatment": gross["negative_amount_treatment"],
            "metric_row_count": gross["metric_row_count"],
            "record_types": gross["record_types"],
            "excluded_negative_offsets_usd": gross["excluded_negative_offsets_usd"],
        }
    )
    return result


def _read_only_checks(cli: AwsCli, root: Path, expected_sha: str) -> dict[str, Any]:
    target, trust, permission, control_plane, cost, inventory, _ = _contracts(root)
    toolchain: dict[str, Any] = cli.version()
    toolchain.update(
        {
            "terraform_contract_version": control_plane["backend"]["terraform_version"],
            "terraform_executed": False,
            "evidence_schema_version": "1.0",
        }
    )
    caller = cli.invoke("STS_GET_CALLER_IDENTITY")
    identity = validate_identity(caller["Account"], target["region"], caller["Arn"], target)
    role_name = target["oidc_role_name"]
    role = cli.invoke("IAM_GET_ROLE", ["--role-name", role_name])["Role"]
    require(
        role.get("MaxSessionDuration") == trust["maximum_session_duration_seconds"],
        "OIDC role session duration differs",
    )
    require("PermissionsBoundary" not in role, "OIDC role permissions boundary is unexpected")
    role_tags = cli.invoke("IAM_LIST_ROLE_TAGS", ["--role-name", role_name]).get("Tags", [])
    role_tag_result = validate_required_tags(_tag_map(role_tags), permission["required_role_tags"])
    trust_result = policy_diff(trust["policy"], role["AssumeRolePolicyDocument"])
    require(trust_result["equal"], f"live OIDC trust differs: {trust_result}")
    inline = cli.invoke("IAM_LIST_ROLE_POLICIES", ["--role-name", role_name])["PolicyNames"]
    attached = cli.invoke("IAM_LIST_ATTACHED_ROLE_POLICIES", ["--role-name", role_name])[
        "AttachedPolicies"
    ]
    require(
        inline == [permission["policy_name"]] and attached == [],
        "unexpected role policy composition",
    )
    live_policy = cli.invoke(
        "IAM_GET_ROLE_POLICY",
        ["--role-name", role_name, "--policy-name", permission["policy_name"]],
    )["PolicyDocument"]
    permission_result = policy_diff(permission["policy"], live_policy)
    require(permission_result["equal"], f"live permission policy differs: {permission_result}")
    permission_result["desired_normalized_sha256"] = sha256(
        canonical_bytes(normalize_policy(permission["policy"]))
    ).hexdigest()
    permission_result["live_normalized_sha256"] = sha256(
        canonical_bytes(normalize_policy(live_policy))
    ).hexdigest()
    trust_result["desired_normalized_sha256"] = sha256(
        canonical_bytes(normalize_policy(trust["policy"]))
    ).hexdigest()
    trust_result["live_normalized_sha256"] = sha256(
        canonical_bytes(normalize_policy(role["AssumeRolePolicyDocument"]))
    ).hexdigest()
    backend_contract = control_plane["backend"]
    bucket = backend_contract["bucket"]
    location = (
        cli.invoke("S3_GET_BUCKET_LOCATION", ["--bucket", bucket]).get("LocationConstraint")
        or "us-east-1"
    )
    versioning = cli.invoke("S3_GET_BUCKET_VERSIONING", ["--bucket", bucket]).get("Status")
    encryption = cli.invoke("S3_GET_BUCKET_ENCRYPTION", ["--bucket", bucket])
    algorithm = encryption["ServerSideEncryptionConfiguration"]["Rules"][0][
        "ApplyServerSideEncryptionByDefault"
    ]["SSEAlgorithm"]
    public = cli.invoke("S3_GET_PUBLIC_ACCESS", ["--bucket", bucket])[
        "PublicAccessBlockConfiguration"
    ]
    policy_text = cli.invoke("S3_GET_BUCKET_POLICY", ["--bucket", bucket])["Policy"]
    tls_policy = validate_tls_only_bucket_policy(policy_text, bucket)
    ownership = cli.invoke("S3_GET_OWNERSHIP", ["--bucket", bucket])["OwnershipControls"]["Rules"][
        0
    ]["ObjectOwnership"]
    lifecycle = validate_backend_lifecycle(
        cli.invoke("S3_GET_LIFECYCLE", ["--bucket", bucket]), backend_contract
    )
    backend_tags = validate_required_tags(
        _tag_map(cli.invoke("S3_GET_TAGS", ["--bucket", bucket]).get("TagSet", [])),
        backend_contract["required_tags"],
    )
    backend = validate_backend(
        {
            "bucket": bucket,
            "region": location,
            "versioning": versioning,
            "encryption": algorithm,
            "public_access_block": public,
            "ownership": ownership,
            "tls_deny": tls_policy["verified"],
            "prefix_isolated": True,
            "pagination_complete": True,
        },
        backend_contract,
    )
    lease_contract = control_plane["lease"]
    table_name = lease_contract["table"]
    table = cli.invoke("DDB_DESCRIBE_TABLE", ["--table-name", table_name])["Table"]
    backups = cli.invoke("DDB_DESCRIBE_BACKUPS", ["--table-name", table_name])[
        "ContinuousBackupsDescription"
    ]
    ttl = cli.invoke("DDB_DESCRIBE_TTL", ["--table-name", table_name])["TimeToLiveDescription"]
    lease_tags = validate_required_tags(
        _tag_map(
            cli.invoke("DDB_LIST_TAGS", ["--resource-arn", table["TableArn"]]).get("Tags", [])
        ),
        lease_contract["required_tags"],
    )
    empty_key = f"{lease_contract['key_namespace']}/qualification"
    current = cli.invoke(
        "DDB_GET_ITEM",
        [
            "--table-name",
            table_name,
            "--consistent-read",
            "--key",
            json.dumps({lease_contract["partition_key"]: {"S": empty_key}}),
        ],
    )
    lease = validate_lease_table(
        {
            "table": table_name,
            "status": table["TableStatus"],
            "partition_key": table["KeySchema"][0]["AttributeName"],
            "partition_key_type": table["AttributeDefinitions"][0]["AttributeType"],
            # DynamoDB uses an AWS-owned key when SSEDescription is absent; both
            # that default and an explicitly enabled KMS key are encryption at rest.
            "encryption": "SSEDescription" not in table
            or table.get("SSEDescription", {}).get("Status") == "ENABLED",
            "billing_mode": table.get("BillingModeSummary", {}).get("BillingMode", "PROVISIONED"),
            "qualification_key_empty": "Item" not in current,
            "pitr": backups.get("PointInTimeRecoveryDescription", {}).get(
                "PointInTimeRecoveryStatus"
            ),
            "ttl_status": ttl.get("TimeToLiveStatus"),
            "ttl_attribute": ttl.get("AttributeName"),
        },
        lease_contract,
    )
    probe_role_name = control_plane["glue_probe"]["role_arn"].rsplit("/", 1)[1]
    probe_role = cli.invoke("IAM_GET_ROLE", ["--role-name", probe_role_name])["Role"]
    require("PermissionsBoundary" not in probe_role, "Glue probe role boundary is unexpected")
    probe_role_tags = validate_required_tags(
        _tag_map(
            cli.invoke("IAM_LIST_ROLE_TAGS", ["--role-name", probe_role_name]).get("Tags", [])
        ),
        control_plane["glue_probe"]["role_required_tags"],
    )
    probe_inline = cli.invoke("IAM_LIST_ROLE_POLICIES", ["--role-name", probe_role_name])[
        "PolicyNames"
    ]
    probe_attached = cli.invoke(
        "IAM_LIST_ATTACHED_ROLE_POLICIES", ["--role-name", probe_role_name]
    )["AttachedPolicies"]
    service = (
        probe_role["AssumeRolePolicyDocument"]["Statement"][0].get("Principal", {}).get("Service")
    )
    require(
        service == "glue.amazonaws.com" and not probe_inline and not probe_attached,
        "Glue probe role trust or authority differs",
    )
    asl = root / "fixtures/part3-stage2/qualification.asl.json"
    validation = cli.invoke(
        "SFN_VALIDATE", ["--definition", asl.read_text(), "--severity", "ERROR"]
    )
    require(validation.get("result") == "OK", "Step Functions definition validation failed")
    workgroup = control_plane["athena"]["workgroup"]
    cli.invoke("ATHENA_GET_WORKGROUP", ["--work-group", workgroup])
    query_history = cli.invoke(
        "ATHENA_LIST_QUERIES", ["--work-group", workgroup, "--max-results", "50"]
    )
    require(
        isinstance(query_history.get("QueryExecutionIds", []), list), "Athena visibility incomplete"
    )
    log_visibility = cli.invoke(
        "LOGS_DESCRIBE_GROUPS", ["--log-group-name-prefix", "/aws-glue/jobs/"]
    )
    require(isinstance(log_visibility.get("logGroups", []), list), "Logs visibility incomplete")
    metrics = cli.invoke(
        "CLOUDWATCH_LIST_METRICS", ["--namespace", "AWS/Glue", "--recently-active", "PT3H"]
    )
    require(isinstance(metrics.get("Metrics", []), list), "metric visibility incomplete")
    for service_code in ("s3", "dynamodb", "glue", "states", "athena"):
        quotas = cli.invoke("QUOTAS_LIST", ["--service-code", service_code, "--max-results", "100"])
        require(isinstance(quotas.get("Quotas", []), list), "quota visibility incomplete")
    cost_result = _cost_headroom_check(cli, cost, date.today(), int(time.time()))
    budgets = cli.invoke(
        "BUDGETS_DESCRIBE", ["--account-id", target["account_id"], "--max-results", "100"]
    )
    require(isinstance(budgets.get("Budgets", []), list), "budget visibility incomplete")
    clean = _inventory_checks(cli, inventory, control_plane)
    return {
        "toolchain": toolchain,
        "identity": identity,
        "iam": {
            "trust": trust_result,
            "permissions": permission_result,
            "role_tags": role_tag_result,
            "permissions_boundary_absent": True,
            "effective_capability_probe_required": True,
        },
        "backend": {**backend, "lifecycle": lifecycle, "tags": backend_tags},
        "lease": {**lease, "tags": lease_tags},
        "glue_probe_role": {
            "trust": True,
            "data_plane_authority": False,
            "permissions_boundary_absent": True,
            "tags": probe_role_tags,
        },
        "step_functions": {"result": "OK"},
        "athena": {"workgroup_visible": True, "query_started": False},
        "cloudwatch": {"visible": True},
        "quotas": {"visible": True},
        "cost": cost_result,
        "budgets": {"visible": True, "count": len(budgets.get("Budgets", []))},
        "inventory": clean,
    }


def run_read_only(expected_sha: str, output: Path) -> dict[str, Any]:
    root = _root()
    _prepare_output(output)
    _context(expected_sha)
    target = read_object(root / ".github/ledgerguard-target.json")
    cli = AwsCli(target["region"])
    state = "FAILED"
    verdict = "QUALIFICATION_FAILED"
    checks: dict[str, Any] = {}
    error = None
    try:
        checks = _read_only_checks(cli, root, expected_sha)
        state = "PASSED"
        verdict = "QUALIFIED"
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        if isinstance(exc, Stage2Rejected):
            verdict = "BLOCKED_BOOTSTRAP_REQUIRED"
    identity = checks.pop(
        "identity",
        {
            "account_match": False,
            "region_match": False,
            "role_match": False,
            "identity_fingerprint": "0" * 64,
        },
    )
    evidence = {
        "schema_version": "1.0",
        "classification": "READ_ONLY_QUALIFICATION",
        "repository": REPOSITORY,
        "event": "workflow_dispatch",
        "ref": MAIN_REF,
        "commit": expected_sha,
        "checkout_commit": expected_sha,
        "workflow_path": ".github/workflows/part3-stage2-read-only.yml",
        "credential_mode": "GITHUB_OIDC",
        "authority_digests": _authority_digests(
            root, ".github/workflows/part3-stage2-read-only.yml"
        ),
        "run_id": os.environ.get("GITHUB_RUN_ID", "0"),
        "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT", "0"),
        "identity": identity,
        "checks": dict(checks, state=state, verdict=verdict, error=error),
        "api_journal": cli.journal,
        "mutation_journal": [],
        "cleanup": {"required": False, "complete": True},
        "managed_reconciliation_started": False,
        "project_complete": False,
    }
    write_json(output / "evidence.json", evidence)
    cli.write_journal(output / "api-journal.json")
    write_json(output / "mutation-journal.json", [])
    finalize_artifact(output)
    if state != "PASSED":
        raise Stage2Rejected(error or "read-only qualification failed")
    return evidence


def _ddb_item(
    key_name: str,
    key: str,
    owner: str,
    sha_value: str,
    run_id: str,
    run_attempt: str,
    correlation: str,
    now: int,
    expires: int,
) -> dict[str, Any]:
    return {
        key_name: {"S": key},
        "owner": {"S": owner},
        "commit": {"S": sha_value},
        "repository": {"S": REPOSITORY},
        "run_id": {"S": run_id},
        "run_attempt": {"S": run_attempt},
        "correlation": {"S": correlation},
        "acquired_epoch": {"N": str(now)},
        "expires_epoch": {"N": str(expires)},
        "purpose": {"S": "PART3_STAGE2_QUALIFICATION"},
    }


def _capability_case(
    cli: AwsCli, root: Path, expected_sha: str, case: str, correlation: str
) -> dict[str, Any]:
    target, _, _, control, _, _, glue_contract = _contracts(root)
    bucket = control["backend"]["bucket"]
    lease = control["lease"]
    table = lease["table"]
    key_name = lease["partition_key"]
    run_id = os.environ["GITHUB_RUN_ID"]
    run_attempt = os.environ["GITHUB_RUN_ATTEMPT"]
    owner = secrets.token_hex(16)
    prefix = f"qualification/{expected_sha}/{run_id}/{run_attempt}/{case}"
    object_key = f"{prefix}/payload.txt"
    script_key = f"{prefix}/inert_glue_probe_script.py"
    test_key = f"{lease['key_namespace']}/{expected_sha}/{run_id}/{run_attempt}/{case}/test"
    guard_key = f"{lease['key_namespace']}/qualification"
    job_name = f"ledgerguard-stage2-{run_id}-{run_attempt}-{case.replace('_', '-')}"
    created_versions: list[tuple[str, str]] = []
    created_items: list[str] = []
    created_job = False
    expected_failure = case != "normal"
    injected = False
    now = int(time.time())
    expires = now + 900
    with tempfile.TemporaryDirectory(prefix="ledgerguard-stage2-") as td:
        temp = Path(td)
        payload = temp / "payload.txt"
        payload.write_bytes(b"ledgerguard-stage2-nonfinancial-probe-v1\n")
        script = root / "fixtures/part3-stage2/inert_glue_probe_script.py"
        try:
            guard = _ddb_item(
                key_name,
                guard_key,
                owner,
                expected_sha,
                run_id,
                run_attempt,
                correlation,
                now,
                expires,
            )
            cli.invoke(
                "DDB_PUT_ITEM",
                [
                    "--table-name",
                    table,
                    "--item",
                    json.dumps(guard),
                    "--condition-expression",
                    f"attribute_not_exists({key_name}) OR expires_epoch < :now OR #o = :owner",
                    "--expression-attribute-names",
                    json.dumps({"#o": "owner"}),
                    "--expression-attribute-values",
                    json.dumps({":now": {"N": str(now)}, ":owner": {"S": owner}}),
                ],
            )
            created_items.append(guard_key)
            payload_digest = sha256(payload.read_bytes()).hexdigest()
            put = cli.invoke(
                "S3_PUT_OBJECT",
                [
                    "--bucket",
                    bucket,
                    "--key",
                    object_key,
                    "--body",
                    str(payload),
                    "--server-side-encryption",
                    "aws:kms",
                    "--metadata",
                    f"sha256={payload_digest}",
                ],
            )
            require("VersionId" in put, "versioned S3 probe required")
            created_versions.append((object_key, put["VersionId"]))
            head = cli.invoke(
                "S3_HEAD_OBJECT",
                ["--bucket", bucket, "--key", object_key, "--version-id", put["VersionId"]],
            )
            require(head.get("Metadata", {}).get("sha256") == payload_digest, "S3 metadata differs")
            require(head.get("ServerSideEncryption") == "aws:kms", "S3 probe encryption differs")
            downloaded = temp / "downloaded.txt"
            cli.invoke(
                "S3_GET_OBJECT",
                [
                    "--bucket",
                    bucket,
                    "--key",
                    object_key,
                    "--version-id",
                    put["VersionId"],
                    str(downloaded),
                ],
            )
            require(
                sha256(downloaded.read_bytes()).hexdigest() == payload_digest, "S3 payload differs"
            )
            if case == "after_s3":
                injected = True
                raise Stage2Rejected("EXPECTED_FAULT_AFTER_S3")
            first = _ddb_item(
                key_name,
                test_key,
                owner,
                expected_sha,
                run_id,
                run_attempt,
                correlation,
                now,
                expires,
            )
            cli.invoke(
                "DDB_PUT_ITEM",
                [
                    "--table-name",
                    table,
                    "--item",
                    json.dumps(first),
                    "--condition-expression",
                    f"attribute_not_exists({key_name}) OR expires_epoch < :now OR #o = :owner",
                    "--expression-attribute-names",
                    json.dumps({"#o": "owner"}),
                    "--expression-attribute-values",
                    json.dumps({":now": {"N": str(now)}, ":owner": {"S": owner}}),
                ],
            )
            created_items.append(test_key)
            cli.invoke(
                "DDB_PUT_ITEM",
                [
                    "--table-name",
                    table,
                    "--item",
                    json.dumps(first),
                    "--condition-expression",
                    f"attribute_not_exists({key_name}) OR expires_epoch < :now OR #o = :owner",
                    "--expression-attribute-names",
                    json.dumps({"#o": "owner"}),
                    "--expression-attribute-values",
                    json.dumps({":now": {"N": str(now)}, ":owner": {"S": owner}}),
                ],
            )
            try:
                competitor = _ddb_item(
                    key_name,
                    test_key,
                    "competitor",
                    expected_sha,
                    run_id,
                    run_attempt,
                    correlation,
                    now,
                    expires,
                )
                cli.invoke(
                    "DDB_PUT_ITEM",
                    [
                        "--table-name",
                        table,
                        "--item",
                        json.dumps(competitor),
                        "--condition-expression",
                        f"attribute_not_exists({key_name}) OR expires_epoch < :now OR #o = :owner",
                        "--expression-attribute-names",
                        json.dumps({"#o": "owner"}),
                        "--expression-attribute-values",
                        json.dumps({":now": {"N": str(now)}, ":owner": {"S": "competitor"}}),
                    ],
                )
                raise Stage2Rejected("competitor unexpectedly acquired lease")
            except Stage2Rejected as exc:
                require(
                    "ConditionalCheckFailedException" in str(exc),
                    "lease competitor failed for wrong reason",
                )
            if case == "after_lease":
                injected = True
                raise Stage2Rejected("EXPECTED_FAULT_AFTER_LEASE")
            expired = _ddb_item(
                key_name,
                test_key,
                owner,
                expected_sha,
                run_id,
                run_attempt,
                correlation,
                now - 20,
                now - 10,
            )
            cli.invoke(
                "DDB_PUT_ITEM",
                [
                    "--table-name",
                    table,
                    "--item",
                    json.dumps(expired),
                    "--condition-expression",
                    "#o = :owner",
                    "--expression-attribute-names",
                    json.dumps({"#o": "owner"}),
                    "--expression-attribute-values",
                    json.dumps({":owner": {"S": owner}}),
                ],
            )
            competitor_owner = "competitor-" + owner[:16]
            competitor = _ddb_item(
                key_name,
                test_key,
                competitor_owner,
                expected_sha,
                run_id,
                run_attempt,
                correlation,
                now,
                expires,
            )
            cli.invoke(
                "DDB_PUT_ITEM",
                [
                    "--table-name",
                    table,
                    "--item",
                    json.dumps(competitor),
                    "--condition-expression",
                    f"attribute_not_exists({key_name}) OR expires_epoch < :now OR #o = :owner",
                    "--expression-attribute-names",
                    json.dumps({"#o": "owner"}),
                    "--expression-attribute-values",
                    json.dumps({":now": {"N": str(now)}, ":owner": {"S": competitor_owner}}),
                ],
            )
            try:
                cli.invoke(
                    "DDB_DELETE_ITEM",
                    [
                        "--table-name",
                        table,
                        "--key",
                        json.dumps({key_name: {"S": test_key}}),
                        "--condition-expression",
                        "#o = :owner",
                        "--expression-attribute-names",
                        json.dumps({"#o": "owner"}),
                        "--expression-attribute-values",
                        json.dumps({":owner": {"S": owner}}),
                    ],
                )
                raise Stage2Rejected("wrong owner unexpectedly released lease")
            except Stage2Rejected as exc:
                require(
                    "ConditionalCheckFailedException" in str(exc),
                    "wrong-owner release failed for wrong reason",
                )
            cli.invoke(
                "DDB_DELETE_ITEM",
                [
                    "--table-name",
                    table,
                    "--key",
                    json.dumps({key_name: {"S": test_key}}),
                    "--condition-expression",
                    "#o = :owner AND #c = :commit AND #r = :run AND #a = :attempt",
                    "--expression-attribute-names",
                    json.dumps(
                        {
                            "#o": "owner",
                            "#c": "commit",
                            "#r": "run_id",
                            "#a": "run_attempt",
                        }
                    ),
                    "--expression-attribute-values",
                    json.dumps(
                        {
                            ":owner": {"S": competitor_owner},
                            ":commit": {"S": expected_sha},
                            ":run": {"S": run_id},
                            ":attempt": {"S": run_attempt},
                        }
                    ),
                ],
            )
            created_items.remove(test_key)
            put_script = cli.invoke(
                "S3_PUT_OBJECT",
                [
                    "--bucket",
                    bucket,
                    "--key",
                    script_key,
                    "--body",
                    str(script),
                    "--server-side-encryption",
                    "aws:kms",
                    "--metadata",
                    f"sha256={sha256(script.read_bytes()).hexdigest()}",
                ],
            )
            require("VersionId" in put_script, "versioned Glue script required")
            created_versions.append((script_key, put_script["VersionId"]))
            script_head = cli.invoke(
                "S3_HEAD_OBJECT",
                [
                    "--bucket",
                    bucket,
                    "--key",
                    script_key,
                    "--version-id",
                    put_script["VersionId"],
                ],
            )
            require(
                script_head.get("Metadata", {}).get("sha256")
                == sha256(script.read_bytes()).hexdigest(),
                "Glue script metadata differs",
            )
            definition = dict(glue_contract["definition"])
            definition["Name"] = job_name
            definition["Command"] = dict(
                definition["Command"], ScriptLocation=f"s3://{bucket}/{script_key}"
            )
            cli.invoke("GLUE_CREATE_JOB", ["--cli-input-json", json.dumps(definition)])
            created_job = True
            observed = cli.invoke("GLUE_GET_JOB", ["--job-name", job_name])["Job"]
            runs = cli.invoke(
                "GLUE_GET_JOB_RUNS", ["--job-name", job_name, "--max-results", "1"]
            ).get("JobRuns", [])
            observed["Tags"] = cli.invoke(
                "GLUE_GET_TAGS",
                [
                    "--resource-arn",
                    f"arn:aws:glue:{cli.region}:{target['account_id']}:job/{job_name}",
                ],
            ).get("Tags", {})
            observed["run_count"] = len(runs)
            expected_definition = dict(definition)
            expected_contract = dict(glue_contract)
            expected_contract["definition"] = expected_definition
            validate_glue_job(observed, expected_contract)
            if case == "after_glue":
                injected = True
                raise Stage2Rejected("EXPECTED_FAULT_AFTER_GLUE")
        except Stage2Rejected:
            if not expected_failure or not injected:
                raise
        finally:
            if created_job:
                cli.invoke("GLUE_DELETE_JOB", ["--job-name", job_name])
                created_job = False
                try:
                    cli.invoke("GLUE_GET_JOB", ["--job-name", job_name])
                    raise Stage2Rejected("Glue job residue")
                except Stage2Rejected as exc:
                    require(
                        "EntityNotFoundException" in str(exc),
                        "Glue absence failed for wrong reason",
                    )
            for item_key in reversed(created_items):
                cli.invoke(
                    "DDB_DELETE_ITEM",
                    [
                        "--table-name",
                        table,
                        "--key",
                        json.dumps({key_name: {"S": item_key}}),
                        "--condition-expression",
                        "#o = :owner AND #c = :commit AND #r = :run AND #a = :attempt",
                        "--expression-attribute-names",
                        json.dumps(
                            {
                                "#o": "owner",
                                "#c": "commit",
                                "#r": "run_id",
                                "#a": "run_attempt",
                            }
                        ),
                        "--expression-attribute-values",
                        json.dumps(
                            {
                                ":owner": {"S": owner},
                                ":commit": {"S": expected_sha},
                                ":run": {"S": run_id},
                                ":attempt": {"S": run_attempt},
                            }
                        ),
                    ],
                )
            for obj, version in reversed(created_versions):
                cli.invoke(
                    "S3_DELETE_OBJECT", ["--bucket", bucket, "--key", obj, "--version-id", version]
                )
            response = cli.invoke("S3_LIST_VERSIONS", ["--bucket", bucket, "--prefix", prefix])
            require(response.get("IsTruncated") is not True, "S3 cleanup listing incomplete")
            validate_s3_cleanup([*response.get("Versions", []), *response.get("DeleteMarkers", [])])
            for item_key in (test_key, guard_key):
                item = cli.invoke(
                    "DDB_GET_ITEM",
                    [
                        "--table-name",
                        table,
                        "--consistent-read",
                        "--key",
                        json.dumps({key_name: {"S": item_key}}),
                    ],
                )
                require("Item" not in item, "lease residue")
        return {
            "case": case,
            "correlation": correlation,
            "expected_fault": expected_failure,
            "injected": injected,
            "cleanup_complete": True,
            "prefix_fingerprint": sha256(prefix.encode()).hexdigest(),
        }


def run_capability(expected_sha: str, preflight: dict[str, str], output: Path) -> dict[str, Any]:
    root = _root()
    _prepare_output(output)
    _context(expected_sha)
    for key in (
        "run_id",
        "run_attempt",
        "artifact_id",
        "artifact_sha256",
        "inspection_sha256",
    ):
        require(bool(preflight.get(key)), f"preflight {key} required")
    for key in ("run_id", "run_attempt", "artifact_id"):
        require(preflight[key].isdigit() and int(preflight[key]) > 0, f"preflight {key} malformed")
    for key in ("artifact_sha256", "inspection_sha256"):
        require(
            len(preflight[key]) == 64 and all(c in "0123456789abcdef" for c in preflight[key]),
            f"preflight {key} malformed",
        )
    target = read_object(root / ".github/ledgerguard-target.json")
    cli = AwsCli(target["region"])
    state = "FAILED"
    checks: dict[str, Any] = {}
    cases = []
    after_inventory: dict[str, Any] = {}
    error = None
    try:
        checks = _read_only_checks(cli, root, expected_sha)
        for case in ("after_s3", "after_lease", "after_glue", "normal"):
            cases.append(
                _capability_case(cli, root, expected_sha, case, preflight["inspection_sha256"][:16])
            )
        _, _, _, control_plane, _, inventory, _ = _contracts(root)
        after_inventory = _inventory_checks(cli, inventory, control_plane)
        state = "PASSED"
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    identity = checks.pop(
        "identity",
        {
            "account_match": False,
            "region_match": False,
            "role_match": False,
            "identity_fingerprint": "0" * 64,
        },
    )
    evidence = {
        "schema_version": "1.0",
        "classification": "CAPABILITY_PROBE",
        "repository": REPOSITORY,
        "event": "workflow_dispatch",
        "ref": MAIN_REF,
        "commit": expected_sha,
        "checkout_commit": expected_sha,
        "workflow_path": ".github/workflows/part3-stage2-capability.yml",
        "credential_mode": "GITHUB_OIDC",
        "authority_digests": _authority_digests(
            root, ".github/workflows/part3-stage2-capability.yml"
        ),
        "run_id": os.environ.get("GITHUB_RUN_ID", "0"),
        "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT", "0"),
        "identity": identity,
        "checks": {
            "state": state,
            "read_only": checks,
            "cases": cases,
            "after_inventory": after_inventory,
            "preflight": preflight,
            "error": error,
        },
        "api_journal": cli.journal,
        "mutation_journal": [row for row in cli.journal if row["operation"] in MUTATING_OPERATIONS],
        "cleanup": {"required": True, "complete": state == "PASSED"},
        "managed_reconciliation_started": False,
        "project_complete": False,
    }
    write_json(output / "evidence.json", evidence)
    cli.write_journal(output / "api-journal.json")
    write_json(output / "mutation-journal.json", evidence["mutation_journal"])
    finalize_artifact(output)
    if state != "PASSED":
        raise Stage2Rejected(error or "capability probe failed")
    return evidence


def run_recovery(
    expected_sha: str,
    failed_run_id: str,
    failed_run_attempt: str,
    failed_artifact_id: str,
    journal_sha256: str,
    output: Path,
) -> dict[str, Any]:
    root = _root()
    _prepare_output(output)
    _context(expected_sha)
    require(failed_run_id.isdigit() and int(failed_run_id) > 0, "failed run ID malformed")
    require(
        failed_run_attempt.isdigit() and int(failed_run_attempt) > 0,
        "failed run attempt malformed",
    )
    require(
        failed_artifact_id.isdigit() and int(failed_artifact_id) > 0,
        "failed artifact ID malformed",
    )
    require(
        len(journal_sha256) == 64 and all(c in "0123456789abcdef" for c in journal_sha256),
        "journal digest malformed",
    )
    target, _, _, control, _, _, _ = _contracts(root)
    cli = AwsCli(target["region"])
    bucket = control["backend"]["bucket"]
    lease = control["lease"]
    key_name = lease["partition_key"]
    removed = {"s3_versions": 0, "lease_items": 0, "glue_jobs": 0}
    state = "FAILED"
    error = None
    identity = {
        "account_match": False,
        "region_match": False,
        "role_match": False,
        "identity_fingerprint": "0" * 64,
    }
    try:
        toolchain = cli.version()
        caller = cli.invoke("STS_GET_CALLER_IDENTITY")
        identity = validate_identity(caller["Account"], target["region"], caller["Arn"], target)
        for case in ("after_s3", "after_lease", "after_glue", "normal"):
            prefix = f"qualification/{expected_sha}/{failed_run_id}/{failed_run_attempt}/{case}"
            versions = cli.invoke("S3_LIST_VERSIONS", ["--bucket", bucket, "--prefix", prefix])
            require(versions.get("IsTruncated") is not True, "S3 recovery listing incomplete")
            for row in [*versions.get("Versions", []), *versions.get("DeleteMarkers", [])]:
                cli.invoke(
                    "S3_DELETE_OBJECT",
                    ["--bucket", bucket, "--key", row["Key"], "--version-id", row["VersionId"]],
                )
                removed["s3_versions"] += 1
            final_versions = cli.invoke(
                "S3_LIST_VERSIONS", ["--bucket", bucket, "--prefix", prefix]
            )
            require(
                final_versions.get("IsTruncated") is not True,
                "S3 recovery verification listing incomplete",
            )
            validate_s3_cleanup(
                [*final_versions.get("Versions", []), *final_versions.get("DeleteMarkers", [])]
            )
            for kind in ("test",):
                item_key = (
                    f"{lease['key_namespace']}/{expected_sha}/{failed_run_id}/"
                    f"{failed_run_attempt}/{case}/{kind}"
                )
                key = json.dumps({key_name: {"S": item_key}})
                current = cli.invoke(
                    "DDB_GET_ITEM",
                    ["--table-name", lease["table"], "--consistent-read", "--key", key],
                ).get("Item")
                if current:
                    require(
                        current.get("commit", {}).get("S") == expected_sha
                        and current.get("run_id", {}).get("S") == failed_run_id
                        and current.get("run_attempt", {}).get("S") == failed_run_attempt,
                        "recovery item identity differs",
                    )
                    owner = current["owner"]["S"]
                    cli.invoke(
                        "DDB_DELETE_ITEM",
                        [
                            "--table-name",
                            lease["table"],
                            "--key",
                            key,
                            "--condition-expression",
                            "#o = :owner AND #c = :commit AND #r = :run AND #a = :attempt",
                            "--expression-attribute-names",
                            json.dumps(
                                {
                                    "#o": "owner",
                                    "#c": "commit",
                                    "#r": "run_id",
                                    "#a": "run_attempt",
                                }
                            ),
                            "--expression-attribute-values",
                            json.dumps(
                                {
                                    ":owner": {"S": owner},
                                    ":commit": {"S": expected_sha},
                                    ":run": {"S": failed_run_id},
                                    ":attempt": {"S": failed_run_attempt},
                                }
                            ),
                        ],
                    )
                    removed["lease_items"] += 1
            job_name = (
                f"ledgerguard-stage2-{failed_run_id}-{failed_run_attempt}-{case.replace('_', '-')}"
            )
            try:
                cli.invoke("GLUE_GET_JOB", ["--job-name", job_name])
            except Stage2Rejected as exc:
                require("EntityNotFoundException" in str(exc), "Glue recovery lookup failed")
            else:
                cli.invoke("GLUE_DELETE_JOB", ["--job-name", job_name])
                removed["glue_jobs"] += 1
                try:
                    cli.invoke("GLUE_GET_JOB", ["--job-name", job_name])
                    raise Stage2Rejected("Glue recovery left job residue")
                except Stage2Rejected as exc:
                    require(
                        "EntityNotFoundException" in str(exc),
                        "Glue recovery absence failed for wrong reason",
                    )
        guard_key = f"{lease['key_namespace']}/qualification"
        guard = cli.invoke(
            "DDB_GET_ITEM",
            [
                "--table-name",
                lease["table"],
                "--consistent-read",
                "--key",
                json.dumps({key_name: {"S": guard_key}}),
            ],
        ).get("Item")
        if guard:
            require(
                guard.get("commit", {}).get("S") == expected_sha
                and guard.get("run_id", {}).get("S") == failed_run_id
                and guard.get("run_attempt", {}).get("S") == failed_run_attempt,
                "recovery guard identity differs",
            )
            cli.invoke(
                "DDB_DELETE_ITEM",
                [
                    "--table-name",
                    lease["table"],
                    "--key",
                    json.dumps({key_name: {"S": guard_key}}),
                    "--condition-expression",
                    "#o = :owner AND #c = :commit AND #r = :run AND #a = :attempt",
                    "--expression-attribute-names",
                    json.dumps(
                        {
                            "#o": "owner",
                            "#c": "commit",
                            "#r": "run_id",
                            "#a": "run_attempt",
                        }
                    ),
                    "--expression-attribute-values",
                    json.dumps(
                        {
                            ":owner": guard["owner"],
                            ":commit": {"S": expected_sha},
                            ":run": {"S": failed_run_id},
                            ":attempt": {"S": failed_run_attempt},
                        }
                    ),
                ],
            )
            removed["lease_items"] += 1
        state = "PASSED"
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    evidence = {
        "schema_version": "1.0",
        "classification": "RECOVERY_CLEANUP",
        "repository": REPOSITORY,
        "event": "workflow_dispatch",
        "ref": MAIN_REF,
        "commit": expected_sha,
        "checkout_commit": expected_sha,
        "workflow_path": ".github/workflows/part3-stage2-recovery.yml",
        "credential_mode": "GITHUB_OIDC",
        "authority_digests": _authority_digests(
            root, ".github/workflows/part3-stage2-recovery.yml"
        ),
        "run_id": os.environ.get("GITHUB_RUN_ID", "0"),
        "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT", "0"),
        "identity": identity,
        "checks": {
            "state": state,
            "failed_run_id": failed_run_id,
            "failed_run_attempt": failed_run_attempt,
            "failed_artifact_id": failed_artifact_id,
            "journal_sha256": journal_sha256,
            "toolchain": toolchain if state == "PASSED" else {},
            "removed": removed,
            "error": error,
        },
        "api_journal": cli.journal,
        "mutation_journal": [row for row in cli.journal if row["operation"] in MUTATING_OPERATIONS],
        "cleanup": {"required": True, "complete": state == "PASSED"},
        "managed_reconciliation_started": False,
        "project_complete": False,
    }
    write_json(output / "evidence.json", evidence)
    cli.write_journal(output / "api-journal.json")
    write_json(output / "mutation-journal.json", evidence["mutation_journal"])
    finalize_artifact(output)
    if state != "PASSED":
        raise Stage2Rejected(error or "recovery cleanup failed")
    return evidence
