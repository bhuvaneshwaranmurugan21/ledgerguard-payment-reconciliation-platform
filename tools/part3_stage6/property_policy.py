"""Property-level admission for the exact Part 3 Stage 6 Terraform plan."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from ledgerguard.stage2.control import validate_tls_only_bucket_policy

ACCOUNT = "857229544428"
REGION = "ap-southeast-2"
BOUNDARY_PREFIX = f"arn:aws:iam::{ACCOUNT}:policy/LedgerGuardPart3-"
HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
EXPECTED_RELEASE = {
    "source_commit": "38576ff8b0592b53cd65fe3cf4241e077484afd8",
    "source_tree": "d789912c580bc4fd7f8059dd5e0ea766cd251750",
    "definition_sha256": "e9233f551153fe4053575609423802eeed8741612cc16be5017d097746f693d5",
    "runtime_package_sha256": ("1dde69c7338d898daa660acd800264d817d15f73bae9b2071156eb909f2291b8"),
    "handler_config_sha256": "f0bd3462aab632c8bccc378d428f3c07eb492f939eb6ff4a0e2e8d2809c1a25a",
}


def _obj(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _rows(plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for raw in plan.get("resource_changes", []):
        row = _obj(raw, "resource change")
        address = row.get("address")
        if not isinstance(address, str) or address in result:
            raise ValueError("invalid or duplicate property-policy address")
        result[address] = _obj(_obj(row.get("change"), address).get("after"), address)
    return result


def _equal(actual: Any, expected: Any, label: str) -> None:
    if actual != expected:
        raise ValueError(f"property differs: {label}")


def _subset(actual: dict[str, Any], expected: dict[str, Any], label: str) -> None:
    for key, value in expected.items():
        _equal(actual.get(key), value, f"{label}.{key}")


def _tags(operation_id: str, expires_at: str) -> dict[str, str]:
    return {
        "ExpiresAt": expires_at,
        "ManagedBy": "Terraform",
        "OperationId": operation_id,
        "Part": "3",
        "Project": "LedgerGuard",
    }


def _release(release: dict[str, Any], operation_id: str) -> None:
    for key, expected in EXPECTED_RELEASE.items():
        _equal(release.get(key), expected, f"release.{key}")
    for key in ("manifest_sha256", "script_sha256", "wheels_sha256"):
        if not isinstance(release.get(key), str) or HEX64.fullmatch(release[key]) is None:
            raise ValueError(f"release digest invalid: {key}")
    for key in ("validator_sha256_base64", "controller_sha256_base64"):
        value = release.get(key)
        if not isinstance(value, str) or len(value) != 44:
            raise ValueError(f"release base64 digest invalid: {key}")
    for key in ("validator_zip", "controller_zip"):
        value = release.get(key)
        if not isinstance(value, str) or not value.endswith(".zip"):
            raise ValueError(f"release archive path invalid: {key}")
    _equal(
        release.get("script_key"),
        f"deployment/{release['script_sha256']}/ledgerguard_stage5_job.py",
        "release.script_key",
    )
    _equal(
        release.get("wheels_key"),
        f"deployment/{release['wheels_sha256']}/ledgerguard.gluewheels.zip",
        "release.wheels_key",
    )
    definition = json.loads(release["definition"])
    _equal(definition.get("TimeoutSeconds"), 1800, "release.definition.TimeoutSeconds")
    _equal(
        hashlib.sha256(release["definition"].encode()).hexdigest(),
        release["definition_sha256"],
        "release.definition digest",
    )
    handler = json.loads(release["handler_config"])
    _equal(handler.get("operation_id"), operation_id, "release.handler operation")
    _equal(
        hashlib.sha256(release["handler_config"].encode()).hexdigest(),
        release["handler_config_sha256"],
        "release.handler digest",
    )


def validate_properties(
    plan: dict[str, Any],
    *,
    operation_id: str,
    expires_at: str,
    permissions_boundary_arns: dict[str, str],
    stage5_release: dict[str, Any],
    runtime_policy_documents: dict[str, Any],
    catalog_tables: dict[str, Any],
) -> dict[str, Any]:
    """Validate all determinate security, scope, runtime and cost properties."""
    if re.fullmatch(r"[a-z0-9][a-z0-9-]{7,31}", operation_id) is None:
        raise ValueError("operation identity invalid")
    if not isinstance(expires_at, str) or not expires_at.endswith("Z"):
        raise ValueError("operation expiry invalid")
    services = {
        "glue": "glue.amazonaws.com",
        "workflow": "states.amazonaws.com",
        "validator": "lambda.amazonaws.com",
        "controller": "lambda.amazonaws.com",
    }
    if set(permissions_boundary_arns) != set(services):
        raise ValueError("boundary role inventory differs")
    for role in services:
        _equal(
            permissions_boundary_arns[role],
            f"{BOUNDARY_PREFIX}{role}-Boundary-v1",
            f"boundary.{role}",
        )
    _release(stage5_release, operation_id)
    rows = _rows(plan)
    if len(rows) != 33:
        raise ValueError("property policy requires exactly 33 resources")

    name = f"ledgerguard-p3-{operation_id}"
    bucket = f"ledgerguard-p3-{ACCOUNT}-{operation_id}"
    tags = _tags(operation_id, expires_at)

    _subset(
        rows["aws_s3_bucket.workload"],
        {"bucket": bucket, "force_destroy": False, "tags_all": tags},
        "bucket",
    )
    _subset(
        rows["aws_s3_bucket_public_access_block.workload"],
        {
            "block_public_acls": True,
            "block_public_policy": True,
            "ignore_public_acls": True,
            "restrict_public_buckets": True,
        },
        "public access",
    )
    _equal(
        rows["aws_s3_bucket_ownership_controls.workload"].get("rule"),
        [{"object_ownership": "BucketOwnerEnforced"}],
        "ownership",
    )
    _equal(
        rows["aws_s3_bucket_versioning.workload"].get("versioning_configuration"),
        [{"status": "Enabled"}],
        "versioning",
    )
    encryption = rows["aws_s3_bucket_server_side_encryption_configuration.workload"].get("rule")
    if (
        not isinstance(encryption, list)
        or encryption[0]["apply_server_side_encryption_by_default"][0]["sse_algorithm"] != "AES256"
    ):
        raise ValueError("bucket encryption differs")
    lifecycle = rows["aws_s3_bucket_lifecycle_configuration.workload"].get("rule")
    if not isinstance(lifecycle, list):
        raise ValueError("bucket lifecycle missing")
    lifecycle_projection = sorted((r.get("id"), r.get("status")) for r in lifecycle)
    _equal(
        lifecycle_projection,
        [
            ("AbortIncompleteUploads", "Enabled"),
            ("ExpireEphemeralRuns", "Enabled"),
            ("ExpireGlueTemporaryData", "Enabled"),
            ("ExpireQueryResults", "Enabled"),
        ],
        "lifecycle rules",
    )
    expected_lifecycle = {
        "AbortIncompleteUploads": {
            "abort_incomplete_multipart_upload": [{"days_after_initiation": 1}],
            "filter": [{}],
        },
        "ExpireEphemeralRuns": {
            "expiration": [{"days": 7}],
            "filter": [{"prefix": "runs/"}],
            "noncurrent_version_expiration": [{"noncurrent_days": 7}],
        },
        "ExpireGlueTemporaryData": {
            "expiration": [{"days": 7}],
            "filter": [{"prefix": "temporary/glue/"}],
            "noncurrent_version_expiration": [{"noncurrent_days": 7}],
        },
        "ExpireQueryResults": {
            "expiration": [{"days": 7}],
            "filter": [{"prefix": "query-results/"}],
            "noncurrent_version_expiration": [{"noncurrent_days": 7}],
        },
    }
    for rule in lifecycle:
        rule_id = rule["id"]
        _subset(rule, expected_lifecycle[rule_id], f"lifecycle.{rule_id}")
    bucket_policy = rows["aws_s3_bucket_policy.workload"].get("policy")
    if bucket_policy is not None and not isinstance(bucket_policy, str):
        raise ValueError("bucket policy missing")
    if (
        isinstance(bucket_policy, str)
        and validate_tls_only_bucket_policy(bucket_policy, bucket)["verified"] is not True
    ):
        raise ValueError("bucket TLS-only policy differs")

    ddb = rows["aws_dynamodb_table.control"]
    _subset(
        ddb,
        {
            "name": f"{name}-control",
            "billing_mode": "PAY_PER_REQUEST",
            "hash_key": "pk",
            "range_key": "sk",
            "tags_all": tags,
        },
        "control table",
    )
    _equal(
        sorted(ddb.get("attribute", []), key=lambda row: row["name"]),
        [{"name": "pk", "type": "S"}, {"name": "sk", "type": "S"}],
        "control attributes",
    )
    _equal(ddb.get("point_in_time_recovery"), [{"enabled": True}], "control PITR")
    _equal(ddb.get("server_side_encryption"), [{"enabled": True}], "control encryption")

    log_names = {
        "glue_error": f"/{name}/glue/error",
        "glue_output": f"/{name}/glue/output",
        "workflow": f"/aws/vendedlogs/states/{name}",
        "validator": f"/aws/lambda/{name}-validator",
        "controller": f"/aws/lambda/{name}-controller",
    }
    for key, log_name in log_names.items():
        _subset(
            rows[f'aws_cloudwatch_log_group.platform["{key}"]'],
            {"name": log_name, "retention_in_days": 7, "tags_all": tags},
            f"log.{key}",
        )

    for role, service in services.items():
        after = rows[f'aws_iam_role.runtime["{role}"]']
        _subset(
            after,
            {
                "name": f"{name}-{role}",
                "path": "/ledgerguard/",
                "permissions_boundary": permissions_boundary_arns[role],
                "tags_all": tags,
            },
            f"role.{role}",
        )
        trust = json.loads(after["assume_role_policy"])
        _equal(
            trust,
            {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Action": "sts:AssumeRole",
                        "Principal": {"Service": service},
                    }
                ],
            },
            f"role.{role}.trust",
        )
        policy = rows[f'aws_iam_role_policy.runtime["{role}"]']
        _equal(policy.get("name"), f"{name}-{role}", f"policy.{role}.name")
        raw_document = policy.get("policy")
        if raw_document is not None:
            if not isinstance(raw_document, str):
                raise ValueError(f"policy.{role}.document differs")
            _equal(
                json.loads(raw_document),
                runtime_policy_documents.get(role),
                f"policy.{role}.document",
            )
        elif role not in runtime_policy_documents:
            raise ValueError(f"policy.{role}.source document missing")

    glue = rows["aws_glue_job.reconciliation"]
    _subset(
        glue,
        {
            "name": f"{name}-reconciliation",
            "glue_version": "5.1",
            "worker_type": "G.1X",
            "number_of_workers": 2,
            "timeout": 15,
            "max_retries": 0,
            "execution_class": "STANDARD",
            "tags_all": tags,
        },
        "glue",
    )
    _equal(glue.get("execution_property"), [{"max_concurrent_runs": 1}], "glue concurrency")
    _equal(
        glue.get("command"),
        [
            {
                "name": "glueetl",
                "python_version": "3",
                "script_location": f"s3://{bucket}/{stage5_release['script_key']}",
            }
        ],
        "glue command",
    )
    _equal(
        glue.get("default_arguments"),
        {
            "--additional-python-modules": f"s3://{bucket}/{stage5_release['wheels_key']}",
            "--python-modules-installer-option": "--no-index",
            "--enable-observability-metrics": "true",
            "--enable-metrics": "",
            "--enable-s3-parquet-optimized-committer": "true",
            "--custom-logGroup-prefix": f"/{name}/glue",
            "--job-bookmark-option": "job-bookmark-disable",
            "--TempDir": f"s3://{bucket}/temporary/glue/",
        },
        "glue default arguments",
    )
    _equal(
        glue.get("non_overridable_arguments"),
        {
            "--release-manifest-sha256": stage5_release["manifest_sha256"],
            "--runtime-source-commit": stage5_release["source_commit"],
            "--runtime-source-tree": stage5_release["source_tree"],
            "--runtime-package-sha256": stage5_release["runtime_package_sha256"],
            "--runtime-script-sha256": stage5_release["script_sha256"],
            "--runtime-wheels-sha256": stage5_release["wheels_sha256"],
        },
        "glue non-overridable arguments",
    )
    for role in ("validator", "controller"):
        fn = rows[f"aws_lambda_function.{role}"]
        _subset(
            fn,
            {
                "function_name": f"{name}-{role}",
                "runtime": "python3.11",
                "handler": f"ledgerguard_control.{role}.handler",
                "filename": stage5_release[f"{role}_zip"],
                "source_code_hash": stage5_release[f"{role}_sha256_base64"],
                "timeout": 60,
                "memory_size": 512,
                "reserved_concurrent_executions": 1,
                "tags_all": tags,
            },
            f"lambda.{role}",
        )
        _equal(fn.get("tracing_config"), [{"mode": "Active"}], f"lambda.{role}.tracing")
        _equal(
            fn.get("environment"),
            [
                {
                    "variables": {
                        "WORKLOAD_BUCKET": bucket,
                        "CONTROL_TABLE": f"{name}-control",
                        "HANDLER_CONFIG_JSON": stage5_release["handler_config"],
                        "HANDLER_CONFIG_SHA256": stage5_release["handler_config_sha256"],
                    }
                }
            ],
            f"lambda.{role}.environment",
        )
    machine = rows["aws_sfn_state_machine.reconciliation"]
    _subset(
        machine,
        {
            "name": f"{name}-reconciliation",
            "type": "STANDARD",
            "definition": stage5_release["definition"],
            "tags_all": tags,
        },
        "state machine",
    )
    logging = machine.get("logging_configuration")
    if (
        not isinstance(logging, list)
        or logging[0].get("level") != "ALL"
        or logging[0].get("include_execution_data") is not False
    ):
        raise ValueError("state machine logging differs")

    database = rows["aws_glue_catalog_database.reconciliation"]
    _subset(
        database,
        {"catalog_id": ACCOUNT, "name": f"{name.replace('-', '_')}_reconciliation"},
        "catalog database",
    )
    for table in ("transactions", "settlements", "bank_allocations"):
        after = rows[f'aws_glue_catalog_table.candidate["{table}"]']
        _subset(
            after,
            {"catalog_id": ACCOUNT, "name": table, "table_type": "EXTERNAL_TABLE"},
            f"catalog.{table}",
        )
        params = after.get("parameters", {})
        _subset(
            params,
            {
                "EXTERNAL": "TRUE",
                "classification": "parquet",
                "projection.enabled": "true",
                "projection.run_id.type": "injected",
                "projection.attempt_id.type": "injected",
            },
            f"catalog.{table}.parameters",
        )
        _equal(
            params.get("storage.location.template"),
            f"s3://{bucket}/runs/${{run_id}}/attempts/${{attempt_id}}/candidates/"
            f"{table.replace('_', '-')}/",
            f"catalog.{table}.template",
        )
        _equal(
            after.get("partition_keys"),
            [{"name": "run_id", "type": "string"}, {"name": "attempt_id", "type": "string"}],
            f"catalog.{table}.partitions",
        )
        descriptor = after.get("storage_descriptor")
        if not isinstance(descriptor, list) or len(descriptor) != 1:
            raise ValueError(f"catalog.{table}.storage descriptor differs")
        _subset(
            descriptor[0],
            {
                "location": f"s3://{bucket}/catalog-unselected/{table}/",
                "input_format": "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat",
                "output_format": "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat",
                "columns": catalog_tables[table],
                "ser_de_info": [
                    {
                        "serialization_library": (
                            "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe"
                        ),
                        "parameters": {"serialization.format": "1"},
                    }
                ],
            },
            f"catalog.{table}.storage",
        )

    workgroup = rows["aws_athena_workgroup.reconciliation"]
    _subset(
        workgroup,
        {"name": f"{name}-checks", "state": "ENABLED", "force_destroy": False, "tags_all": tags},
        "athena",
    )
    config = workgroup.get("configuration")
    if not isinstance(config, list):
        raise ValueError("Athena configuration missing")
    _subset(
        config[0],
        {
            "enforce_workgroup_configuration": True,
            "bytes_scanned_cutoff_per_query": 104857600,
            "publish_cloudwatch_metrics_enabled": True,
        },
        "athena.configuration",
    )
    _equal(
        config[0].get("engine_version"),
        [{"selected_engine_version": "Athena engine version 3"}],
        "athena.engine",
    )
    _equal(
        config[0].get("result_configuration"),
        [
            {
                "output_location": f"s3://{bucket}/query-results/",
                "expected_bucket_owner": ACCOUNT,
                "encryption_configuration": [{"encryption_option": "SSE_S3"}],
            }
        ],
        "athena.results",
    )

    for role in ("validator", "controller"):
        alarm = rows[f'aws_cloudwatch_metric_alarm.control_errors["{role}"]']
        _subset(
            alarm,
            {
                "alarm_name": f"{name}-{role}-errors",
                "comparison_operator": "GreaterThanThreshold",
                "evaluation_periods": 1,
                "metric_name": "Errors",
                "namespace": "AWS/Lambda",
                "period": 60,
                "statistic": "Sum",
                "threshold": 0,
                "treat_missing_data": "missing",
                "dimensions": {"FunctionName": f"{name}-{role}"},
                "tags_all": tags,
            },
            f"alarm.{role}",
        )
    alarm = rows["aws_cloudwatch_metric_alarm.workflow_failure"]
    _subset(
        alarm,
        {
            "alarm_name": f"{name}-workflow-failure",
            "comparison_operator": "GreaterThanThreshold",
            "evaluation_periods": 1,
            "metric_name": "ExecutionsFailed",
            "namespace": "AWS/States",
            "period": 60,
            "statistic": "Sum",
            "threshold": 0,
            "treat_missing_data": "missing",
            "tags_all": tags,
        },
        "alarm.workflow",
    )

    return {
        "classification": "SAVED_PLAN_PROPERTY_POLICY_PASSED",
        "account": ACCOUNT,
        "region": REGION,
        "operation_id_sha256": hashlib.sha256(operation_id.encode()).hexdigest(),
        "resources_validated": 33,
        "release_source_commit": stage5_release["source_commit"],
        "aws_calls": 0,
        "stage6_complete": False,
    }
