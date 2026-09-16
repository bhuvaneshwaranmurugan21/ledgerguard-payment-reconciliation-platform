from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

import tools.part3_stage6.property_policy as policy
from tools.part3_stage6.plan_policy import expected_addresses

ROOT = Path(__file__).resolve().parents[1]
CATALOG = json.loads((ROOT / "spec/part3-stage4-catalog-v1.json").read_text())["tables"]
OPERATION = "release-qual1"
EXPIRY = "2026-09-16T00:00:00Z"
NAME = f"ledgerguard-p3-{OPERATION}"
BUCKET = f"ledgerguard-p3-857229544428-{OPERATION}"
TAGS = {
    "ExpiresAt": EXPIRY,
    "ManagedBy": "Terraform",
    "OperationId": OPERATION,
    "Part": "3",
    "Project": "LedgerGuard",
}
SERVICES = {
    "glue": "glue.amazonaws.com",
    "workflow": "states.amazonaws.com",
    "validator": "lambda.amazonaws.com",
    "controller": "lambda.amazonaws.com",
}
BOUNDARIES = {
    role: f"arn:aws:iam::857229544428:policy/LedgerGuardPart3-{role}-Boundary-v1"
    for role in SERVICES
}
POLICIES = {role: {"Version": "2012-10-17", "Statement": []} for role in SERVICES}


def release(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    definition = json.dumps(
        {"StartAt": "Done", "States": {"Done": {"Type": "Succeed"}}, "TimeoutSeconds": 1800},
        separators=(",", ":"),
    )
    handler = json.dumps({"operation_id": OPERATION}, separators=(",", ":"))
    result = {
        "source_commit": "a" * 40,
        "source_tree": "b" * 40,
        "definition": definition,
        "definition_sha256": hashlib.sha256(definition.encode()).hexdigest(),
        "runtime_package_sha256": "c" * 64,
        "handler_config": handler,
        "handler_config_sha256": hashlib.sha256(handler.encode()).hexdigest(),
        "manifest_sha256": "d" * 64,
        "script_sha256": "e" * 64,
        "wheels_sha256": "f" * 64,
        "validator_sha256_base64": "A" * 43 + "=",
        "controller_sha256_base64": "B" * 43 + "=",
        "validator_zip": "validator.zip",
        "controller_zip": "controller.zip",
    }
    result["script_key"] = f"deployment/{result['script_sha256']}/ledgerguard_stage5_job.py"
    result["wheels_key"] = f"deployment/{result['wheels_sha256']}/ledgerguard.gluewheels.zip"
    monkeypatch.setattr(
        policy,
        "EXPECTED_RELEASE",
        {key: result[key] for key in policy.EXPECTED_RELEASE},
    )
    return result


def plan(release_value: dict[str, Any]) -> dict[str, Any]:
    after = {address: {} for address in expected_addresses(ROOT)}
    after["aws_s3_bucket.workload"] = {"bucket": BUCKET, "force_destroy": False, "tags_all": TAGS}
    after["aws_s3_bucket_public_access_block.workload"] = {
        "block_public_acls": True,
        "block_public_policy": True,
        "ignore_public_acls": True,
        "restrict_public_buckets": True,
    }
    after["aws_s3_bucket_ownership_controls.workload"] = {
        "rule": [{"object_ownership": "BucketOwnerEnforced"}]
    }
    after["aws_s3_bucket_versioning.workload"] = {
        "versioning_configuration": [{"status": "Enabled"}]
    }
    after["aws_s3_bucket_server_side_encryption_configuration.workload"] = {
        "rule": [{"apply_server_side_encryption_by_default": [{"sse_algorithm": "AES256"}]}]
    }
    after["aws_s3_bucket_lifecycle_configuration.workload"] = {
        "rule": [
            {
                "id": "AbortIncompleteUploads",
                "status": "Enabled",
                "filter": [{}],
                "abort_incomplete_multipart_upload": [{"days_after_initiation": 1}],
            },
            *[
                {
                    "id": rule_id,
                    "status": "Enabled",
                    "filter": [{"prefix": prefix}],
                    "expiration": [{"days": 7}],
                    "noncurrent_version_expiration": [{"noncurrent_days": 7}],
                }
                for rule_id, prefix in (
                    ("ExpireEphemeralRuns", "runs/"),
                    ("ExpireGlueTemporaryData", "temporary/glue/"),
                    ("ExpireQueryResults", "query-results/"),
                )
            ],
        ]
    }
    after["aws_s3_bucket_policy.workload"] = {
        "policy": json.dumps(
            {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Sid": "DenyInsecureTransport",
                        "Effect": "Deny",
                        "Principal": "*",
                        "Action": "s3:*",
                        "Resource": [f"arn:aws:s3:::{BUCKET}", f"arn:aws:s3:::{BUCKET}/*"],
                        "Condition": {"Bool": {"aws:SecureTransport": "false"}},
                    }
                ],
            }
        )
    }
    after["aws_dynamodb_table.control"] = {
        "name": f"{NAME}-control",
        "billing_mode": "PAY_PER_REQUEST",
        "hash_key": "pk",
        "range_key": "sk",
        "tags_all": TAGS,
        "attribute": [{"name": "pk", "type": "S"}, {"name": "sk", "type": "S"}],
        "point_in_time_recovery": [{"enabled": True}],
        "server_side_encryption": [{"enabled": True}],
    }
    logs = {
        "glue_error": f"/{NAME}/glue/error",
        "glue_output": f"/{NAME}/glue/output",
        "workflow": f"/aws/vendedlogs/states/{NAME}",
        "validator": f"/aws/lambda/{NAME}-validator",
        "controller": f"/aws/lambda/{NAME}-controller",
    }
    for key, value in logs.items():
        after[f'aws_cloudwatch_log_group.platform["{key}"]'] = {
            "name": value,
            "retention_in_days": 7,
            "tags_all": TAGS,
        }
    for role, service in SERVICES.items():
        after[f'aws_iam_role.runtime["{role}"]'] = {
            "name": f"{NAME}-{role}",
            "path": "/ledgerguard/",
            "permissions_boundary": BOUNDARIES[role],
            "tags_all": TAGS,
            "assume_role_policy": json.dumps(
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
                separators=(",", ":"),
            ),
        }
        after[f'aws_iam_role_policy.runtime["{role}"]'] = {
            "name": f"{NAME}-{role}",
            "policy": json.dumps(POLICIES[role]),
        }
    after["aws_glue_job.reconciliation"] = {
        "name": f"{NAME}-reconciliation",
        "glue_version": "5.1",
        "worker_type": "G.1X",
        "number_of_workers": 2,
        "timeout": 15,
        "max_retries": 0,
        "execution_class": "STANDARD",
        "tags_all": TAGS,
        "execution_property": [{"max_concurrent_runs": 1}],
        "command": [
            {
                "name": "glueetl",
                "python_version": "3",
                "script_location": f"s3://{BUCKET}/{release_value['script_key']}",
            }
        ],
        "default_arguments": {
            "--additional-python-modules": f"s3://{BUCKET}/{release_value['wheels_key']}",
            "--python-modules-installer-option": "--no-index",
            "--enable-observability-metrics": "true",
            "--enable-metrics": "",
            "--enable-s3-parquet-optimized-committer": "true",
            "--custom-logGroup-prefix": f"/{NAME}/glue",
            "--job-bookmark-option": "job-bookmark-disable",
            "--TempDir": f"s3://{BUCKET}/temporary/glue/",
        },
        "non_overridable_arguments": {
            "--release-manifest-sha256": release_value["manifest_sha256"],
            "--runtime-source-commit": release_value["source_commit"],
            "--runtime-source-tree": release_value["source_tree"],
            "--runtime-package-sha256": release_value["runtime_package_sha256"],
            "--runtime-script-sha256": release_value["script_sha256"],
            "--runtime-wheels-sha256": release_value["wheels_sha256"],
        },
    }
    for role in ("validator", "controller"):
        after[f"aws_lambda_function.{role}"] = {
            "function_name": f"{NAME}-{role}",
            "runtime": "python3.11",
            "handler": f"ledgerguard_control.{role}.handler",
            "filename": release_value[f"{role}_zip"],
            "source_code_hash": release_value[f"{role}_sha256_base64"],
            "timeout": 60,
            "memory_size": 512,
            "reserved_concurrent_executions": 1,
            "tags_all": TAGS,
            "tracing_config": [{"mode": "Active"}],
            "environment": [
                {
                    "variables": {
                        "WORKLOAD_BUCKET": BUCKET,
                        "CONTROL_TABLE": f"{NAME}-control",
                        "HANDLER_CONFIG_JSON": release_value["handler_config"],
                        "HANDLER_CONFIG_SHA256": release_value["handler_config_sha256"],
                    }
                }
            ],
        }
    after["aws_sfn_state_machine.reconciliation"] = {
        "name": f"{NAME}-reconciliation",
        "type": "STANDARD",
        "definition": release_value["definition"],
        "tags_all": TAGS,
        "logging_configuration": [{"level": "ALL", "include_execution_data": False}],
    }
    after["aws_glue_catalog_database.reconciliation"] = {
        "catalog_id": "857229544428",
        "name": f"{NAME.replace('-', '_')}_reconciliation",
    }
    for table in ("transactions", "settlements", "bank_allocations"):
        after[f'aws_glue_catalog_table.candidate["{table}"]'] = {
            "catalog_id": "857229544428",
            "name": table,
            "table_type": "EXTERNAL_TABLE",
            "parameters": {
                "EXTERNAL": "TRUE",
                "classification": "parquet",
                "projection.enabled": "true",
                "projection.run_id.type": "injected",
                "projection.attempt_id.type": "injected",
                "storage.location.template": (
                    f"s3://{BUCKET}/runs/${{run_id}}/attempts/${{attempt_id}}/candidates/"
                    f"{table.replace('_', '-')}/"
                ),
            },
            "partition_keys": [
                {"name": "run_id", "type": "string"},
                {"name": "attempt_id", "type": "string"},
            ],
            "storage_descriptor": [
                {
                    "location": f"s3://{BUCKET}/catalog-unselected/{table}/",
                    "input_format": (
                        "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat"
                    ),
                    "output_format": (
                        "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat"
                    ),
                    "columns": CATALOG[table],
                    "ser_de_info": [
                        {
                            "serialization_library": (
                                "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe"
                            ),
                            "parameters": {"serialization.format": "1"},
                        }
                    ],
                }
            ],
        }
    after["aws_athena_workgroup.reconciliation"] = {
        "name": f"{NAME}-checks",
        "state": "ENABLED",
        "force_destroy": False,
        "tags_all": TAGS,
        "configuration": [
            {
                "enforce_workgroup_configuration": True,
                "bytes_scanned_cutoff_per_query": 104857600,
                "publish_cloudwatch_metrics_enabled": True,
                "engine_version": [{"selected_engine_version": "Athena engine version 3"}],
                "result_configuration": [
                    {
                        "output_location": f"s3://{BUCKET}/query-results/",
                        "expected_bucket_owner": "857229544428",
                        "encryption_configuration": [{"encryption_option": "SSE_S3"}],
                    }
                ],
            }
        ],
    }
    alarm_common = {
        "comparison_operator": "GreaterThanThreshold",
        "evaluation_periods": 1,
        "period": 60,
        "statistic": "Sum",
        "threshold": 0,
        "treat_missing_data": "missing",
        "tags_all": TAGS,
    }
    for role in ("validator", "controller"):
        after[f'aws_cloudwatch_metric_alarm.control_errors["{role}"]'] = {
            **alarm_common,
            "alarm_name": f"{NAME}-{role}-errors",
            "metric_name": "Errors",
            "namespace": "AWS/Lambda",
            "dimensions": {"FunctionName": f"{NAME}-{role}"},
        }
    after["aws_cloudwatch_metric_alarm.workflow_failure"] = {
        **alarm_common,
        "alarm_name": f"{NAME}-workflow-failure",
        "metric_name": "ExecutionsFailed",
        "namespace": "AWS/States",
    }
    return {
        "resource_changes": [
            {"address": address, "change": {"after": value}} for address, value in after.items()
        ]
    }


def test_exact_determinate_properties_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    release_value = release(monkeypatch)
    result = policy.validate_properties(
        plan(release_value),
        operation_id=OPERATION,
        expires_at=EXPIRY,
        permissions_boundary_arns=BOUNDARIES,
        stage5_release=release_value,
        runtime_policy_documents=POLICIES,
        catalog_tables=CATALOG,
    )
    assert result["resources_validated"] == 33
    assert result["stage6_complete"] is False


@pytest.mark.parametrize(
    ("address", "path", "value"),
    [
        ("aws_s3_bucket.workload", "force_destroy", True),
        ("aws_dynamodb_table.control", "billing_mode", "PROVISIONED"),
        ("aws_glue_job.reconciliation", "number_of_workers", 3),
        ("aws_lambda_function.validator", "reserved_concurrent_executions", 2),
        ("aws_sfn_state_machine.reconciliation", "type", "EXPRESS"),
        ("aws_athena_workgroup.reconciliation", "force_destroy", True),
        ('aws_cloudwatch_log_group.platform["workflow"]', "retention_in_days", 0),
        ('aws_iam_role.runtime["glue"]', "permissions_boundary", None),
    ],
)
def test_security_property_drift_fails(
    monkeypatch: pytest.MonkeyPatch, address: str, path: str, value: Any
) -> None:
    release_value = release(monkeypatch)
    changed = plan(release_value)
    row = next(item for item in changed["resource_changes"] if item["address"] == address)
    row["change"]["after"][path] = value
    with pytest.raises(ValueError, match="differs"):
        policy.validate_properties(
            changed,
            operation_id=OPERATION,
            expires_at=EXPIRY,
            permissions_boundary_arns=BOUNDARIES,
            stage5_release=release_value,
            runtime_policy_documents=POLICIES,
            catalog_tables=CATALOG,
        )


@pytest.mark.parametrize(
    ("key", "value", "message"),
    [
        ("manifest_sha256", 1, "digest invalid"),
        ("manifest_sha256", "x" * 64, "digest invalid"),
        ("validator_sha256_base64", 1, "base64 digest invalid"),
        ("validator_sha256_base64", "short", "base64 digest invalid"),
        ("validator_zip", 1, "archive path invalid"),
        ("validator_zip", "validator.tar", "archive path invalid"),
    ],
)
def test_release_shape_drift_fails(
    monkeypatch: pytest.MonkeyPatch, key: str, value: Any, message: str
) -> None:
    release_value = release(monkeypatch)
    release_value[key] = value
    with pytest.raises(ValueError, match=message):
        policy.validate_properties(
            plan(release_value),
            operation_id=OPERATION,
            expires_at=EXPIRY,
            permissions_boundary_arns=BOUNDARIES,
            stage5_release=release_value,
            runtime_policy_documents=POLICIES,
            catalog_tables=CATALOG,
        )


@pytest.mark.parametrize(
    ("operation", "expiry", "boundaries", "message"),
    [
        ("bad", EXPIRY, BOUNDARIES, "operation identity"),
        (OPERATION, 1, BOUNDARIES, "operation expiry"),
        (OPERATION, "2026-09-16", BOUNDARIES, "operation expiry"),
        (OPERATION, EXPIRY, {}, "boundary role inventory"),
    ],
)
def test_execution_input_drift_fails(
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    expiry: Any,
    boundaries: dict[str, str],
    message: str,
) -> None:
    release_value = release(monkeypatch)
    with pytest.raises(ValueError, match=message):
        policy.validate_properties(
            plan(release_value),
            operation_id=operation,
            expires_at=expiry,
            permissions_boundary_arns=boundaries,
            stage5_release=release_value,
            runtime_policy_documents=POLICIES,
            catalog_tables=CATALOG,
        )


@pytest.mark.parametrize(
    ("address", "value", "message"),
    [
        (
            "aws_s3_bucket_server_side_encryption_configuration.workload",
            {"rule": None},
            "bucket encryption",
        ),
        (
            "aws_s3_bucket_lifecycle_configuration.workload",
            {"rule": None},
            "bucket lifecycle",
        ),
        (
            "aws_sfn_state_machine.reconciliation",
            {
                "name": f"{NAME}-reconciliation",
                "type": "STANDARD",
                "definition": None,
                "tags_all": TAGS,
                "logging_configuration": None,
            },
            "property differs|logging",
        ),
        (
            "aws_athena_workgroup.reconciliation",
            {
                "name": f"{NAME}-checks",
                "state": "ENABLED",
                "force_destroy": False,
                "tags_all": TAGS,
                "configuration": None,
            },
            "Athena configuration",
        ),
    ],
)
def test_required_nested_property_objects_fail(
    monkeypatch: pytest.MonkeyPatch, address: str, value: Any, message: str
) -> None:
    release_value = release(monkeypatch)
    changed = plan(release_value)
    row = next(item for item in changed["resource_changes"] if item["address"] == address)
    row["change"]["after"] = value
    with pytest.raises(ValueError, match=message):
        policy.validate_properties(
            changed,
            operation_id=OPERATION,
            expires_at=EXPIRY,
            permissions_boundary_arns=BOUNDARIES,
            stage5_release=release_value,
            runtime_policy_documents=POLICIES,
            catalog_tables=CATALOG,
        )


def test_invalid_and_duplicate_resource_rows_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    release_value = release(monkeypatch)
    with pytest.raises(ValueError, match="must be an object"):
        policy.validate_properties(
            {"resource_changes": [None]},
            operation_id=OPERATION,
            expires_at=EXPIRY,
            permissions_boundary_arns=BOUNDARIES,
            stage5_release=release_value,
            runtime_policy_documents=POLICIES,
            catalog_tables=CATALOG,
        )
    changed = plan(release_value)
    changed["resource_changes"].append(changed["resource_changes"][0])
    with pytest.raises(ValueError, match="duplicate"):
        policy.validate_properties(
            changed,
            operation_id=OPERATION,
            expires_at=EXPIRY,
            permissions_boundary_arns=BOUNDARIES,
            stage5_release=release_value,
            runtime_policy_documents=POLICIES,
            catalog_tables=CATALOG,
        )


def test_incomplete_resource_inventory_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    release_value = release(monkeypatch)
    changed = plan(release_value)
    changed["resource_changes"].pop()
    with pytest.raises(ValueError, match="exactly 33"):
        policy.validate_properties(
            changed,
            operation_id=OPERATION,
            expires_at=EXPIRY,
            permissions_boundary_arns=BOUNDARIES,
            stage5_release=release_value,
            runtime_policy_documents=POLICIES,
            catalog_tables=CATALOG,
        )


def test_state_machine_logging_object_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    release_value = release(monkeypatch)
    changed = plan(release_value)
    row = next(
        item
        for item in changed["resource_changes"]
        if item["address"] == "aws_sfn_state_machine.reconciliation"
    )
    row["change"]["after"]["logging_configuration"] = None
    with pytest.raises(ValueError, match="state machine logging"):
        policy.validate_properties(
            changed,
            operation_id=OPERATION,
            expires_at=EXPIRY,
            permissions_boundary_arns=BOUNDARIES,
            stage5_release=release_value,
            runtime_policy_documents=POLICIES,
            catalog_tables=CATALOG,
        )


@pytest.mark.parametrize("bucket_policy", [{}, "{}"])
def test_bucket_policy_must_be_exact_tls_only(
    monkeypatch: pytest.MonkeyPatch, bucket_policy: Any
) -> None:
    release_value = release(monkeypatch)
    changed = plan(release_value)
    row = next(
        item
        for item in changed["resource_changes"]
        if item["address"] == "aws_s3_bucket_policy.workload"
    )
    row["change"]["after"]["policy"] = bucket_policy
    with pytest.raises(ValueError, match=r"bucket policy|TLS-only"):
        policy.validate_properties(
            changed,
            operation_id=OPERATION,
            expires_at=EXPIRY,
            permissions_boundary_arns=BOUNDARIES,
            stage5_release=release_value,
            runtime_policy_documents=POLICIES,
            catalog_tables=CATALOG,
        )


def test_provider_computed_bucket_and_runtime_policies_use_source_proof(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release_value = release(monkeypatch)
    changed = plan(release_value)
    bucket_row = next(
        item
        for item in changed["resource_changes"]
        if item["address"] == "aws_s3_bucket_policy.workload"
    )
    bucket_row["change"]["after"]["policy"] = None
    runtime_row = next(
        item
        for item in changed["resource_changes"]
        if item["address"] == 'aws_iam_role_policy.runtime["glue"]'
    )
    runtime_row["change"]["after"]["policy"] = None
    result = policy.validate_properties(
        changed,
        operation_id=OPERATION,
        expires_at=EXPIRY,
        permissions_boundary_arns=BOUNDARIES,
        stage5_release=release_value,
        runtime_policy_documents=POLICIES,
        catalog_tables=CATALOG,
    )
    assert result["resources_validated"] == 33


def test_runtime_policy_computed_value_requires_exact_source_document(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release_value = release(monkeypatch)
    changed = plan(release_value)
    runtime_row = next(
        item
        for item in changed["resource_changes"]
        if item["address"] == 'aws_iam_role_policy.runtime["glue"]'
    )
    runtime_row["change"]["after"]["policy"] = []
    with pytest.raises(ValueError, match="document differs"):
        policy.validate_properties(
            changed,
            operation_id=OPERATION,
            expires_at=EXPIRY,
            permissions_boundary_arns=BOUNDARIES,
            stage5_release=release_value,
            runtime_policy_documents=POLICIES,
            catalog_tables=CATALOG,
        )
    runtime_row["change"]["after"]["policy"] = None
    missing = dict(POLICIES)
    missing.pop("glue")
    with pytest.raises(ValueError, match="source document missing"):
        policy.validate_properties(
            changed,
            operation_id=OPERATION,
            expires_at=EXPIRY,
            permissions_boundary_arns=BOUNDARIES,
            stage5_release=release_value,
            runtime_policy_documents=missing,
            catalog_tables=CATALOG,
        )


def test_catalog_storage_descriptor_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    release_value = release(monkeypatch)
    changed = plan(release_value)
    row = next(
        item
        for item in changed["resource_changes"]
        if item["address"] == 'aws_glue_catalog_table.candidate["transactions"]'
    )
    row["change"]["after"]["storage_descriptor"] = None
    with pytest.raises(ValueError, match="storage descriptor"):
        policy.validate_properties(
            changed,
            operation_id=OPERATION,
            expires_at=EXPIRY,
            permissions_boundary_arns=BOUNDARIES,
            stage5_release=release_value,
            runtime_policy_documents=POLICIES,
            catalog_tables=CATALOG,
        )


def test_bucket_policy_validator_must_return_verified(monkeypatch: pytest.MonkeyPatch) -> None:
    release_value = release(monkeypatch)
    monkeypatch.setattr(
        policy, "validate_tls_only_bucket_policy", lambda *args: {"verified": False}
    )
    with pytest.raises(ValueError, match="TLS-only"):
        policy.validate_properties(
            plan(release_value),
            operation_id=OPERATION,
            expires_at=EXPIRY,
            permissions_boundary_arns=BOUNDARIES,
            stage5_release=release_value,
            runtime_policy_documents=POLICIES,
            catalog_tables=CATALOG,
        )
