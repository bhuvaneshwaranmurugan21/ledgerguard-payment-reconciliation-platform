"""Validate source-expression bindings for provider-computed plan relationships."""

from __future__ import annotations

from typing import Any

REQUIRED_REFERENCES = {
    ("aws_s3_bucket_ownership_controls.workload", "bucket"): "aws_s3_bucket.workload.id",
    ("aws_s3_bucket_public_access_block.workload", "bucket"): "aws_s3_bucket.workload.id",
    ("aws_s3_bucket_versioning.workload", "bucket"): "aws_s3_bucket.workload.id",
    (
        "aws_s3_bucket_server_side_encryption_configuration.workload",
        "bucket",
    ): "aws_s3_bucket.workload.id",
    ("aws_s3_bucket_policy.workload", "bucket"): "aws_s3_bucket.workload.id",
    ("aws_s3_bucket_policy.workload", "policy"): "aws_s3_bucket.workload.arn",
    ("aws_s3_bucket_lifecycle_configuration.workload", "bucket"): "aws_s3_bucket.workload.id",
    ("aws_glue_job.reconciliation", "role_arn"): 'aws_iam_role.runtime["glue"].arn',
    ("aws_lambda_function.validator", "role"): 'aws_iam_role.runtime["validator"].arn',
    ("aws_lambda_function.controller", "role"): 'aws_iam_role.runtime["controller"].arn',
    ("aws_sfn_state_machine.reconciliation", "role_arn"): 'aws_iam_role.runtime["workflow"].arn',
    (
        "aws_sfn_state_machine.reconciliation",
        "logging_configuration",
    ): 'aws_cloudwatch_log_group.platform["workflow"].arn',
    (
        "aws_glue_catalog_table.candidate",
        "database_name",
    ): "aws_glue_catalog_database.reconciliation.name",
    (
        "aws_cloudwatch_metric_alarm.workflow_failure",
        "dimensions",
    ): "aws_sfn_state_machine.reconciliation.arn",
    ("aws_iam_role_policy.runtime", "role"): "aws_iam_role.runtime",
}


def _obj(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def validate_relationships(plan: dict[str, Any]) -> dict[str, Any]:
    configuration = _obj(plan.get("configuration"), "configuration")
    root = _obj(configuration.get("root_module"), "root module")
    resources = root.get("resources")
    if not isinstance(resources, list):
        raise ValueError("configuration resources missing")
    indexed: dict[str, dict[str, Any]] = {}
    for raw in resources:
        resource = _obj(raw, "configuration resource")
        address = resource.get("address")
        if not isinstance(address, str) or address in indexed:
            raise ValueError("configuration resource identity invalid")
        indexed[address] = resource
    missing_resources = sorted({address for address, _ in REQUIRED_REFERENCES} - indexed.keys())
    if missing_resources:
        raise ValueError(f"configuration resource missing: {missing_resources[0]}")
    for (address, expression_name), required in REQUIRED_REFERENCES.items():
        expressions = _obj(indexed[address].get("expressions"), f"expressions {address}")
        expression = _obj(
            expressions.get(expression_name), f"expression {address}.{expression_name}"
        )
        references = expression.get("references")
        if not isinstance(references, list) or not all(
            isinstance(item, str) for item in references
        ):
            raise ValueError(f"expression references invalid: {address}.{expression_name}")
        if required not in references:
            raise ValueError(f"required relationship differs: {address}.{expression_name}")
    return {
        "classification": "SAVED_PLAN_SOURCE_RELATIONSHIPS_PASSED",
        "relationships_validated": len(REQUIRED_REFERENCES),
        "aws_calls": 0,
        "stage6_complete": False,
    }
