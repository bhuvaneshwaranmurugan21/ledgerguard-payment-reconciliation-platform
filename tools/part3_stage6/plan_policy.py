"""Fail-closed structural policy for the Stage 6 saved Terraform plan JSON."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

AWS_PROVIDER = "registry.terraform.io/hashicorp/aws"
CRITICAL_UNKNOWN_TERMS = {
    "account",
    "action",
    "acl",
    "architecture",
    "arn",
    "boundary",
    "bucket",
    "encryption",
    "engine",
    "kms",
    "lifecycle",
    "name",
    "policy",
    "principal",
    "public",
    "region",
    "resource",
    "retention",
    "role",
    "runtime",
    "service",
    "tags",
    "version",
}

# Provider-computed identities are expected for creates and are not configuration
# ambiguity.  They are admitted only at these exact paths; all other critical
# unknowns remain terminal failures and their source relationships are checked by
# ``relationships.validate_relationships``.
COMPUTED_UNKNOWN_PATHS = {
    "aws_s3_bucket": {
        "arn",
        "bucket_domain_name",
        "bucket_regional_domain_name",
        "hosted_zone_id",
        "id",
        "region",
    },
    "aws_s3_bucket_public_access_block": {"bucket", "id"},
    "aws_s3_bucket_ownership_controls": {"bucket", "id"},
    "aws_s3_bucket_versioning": {"bucket", "id"},
    "aws_s3_bucket_server_side_encryption_configuration": {"bucket", "id"},
    "aws_s3_bucket_policy": {"bucket", "id", "policy"},
    "aws_s3_bucket_lifecycle_configuration": {"bucket", "id"},
    "aws_dynamodb_table": {"arn", "id", "stream_arn", "stream_label"},
    "aws_cloudwatch_log_group": {"arn", "id"},
    "aws_iam_role": {"arn", "create_date", "id", "unique_id"},
    "aws_iam_role_policy": {"id", "policy", "role"},
    "aws_glue_job": {"arn", "id", "role_arn"},
    "aws_lambda_function": {
        "arn",
        "code_sha256",
        "id",
        "invoke_arn",
        "last_modified",
        "qualified_arn",
        "qualified_invoke_arn",
        "signing_job_arn",
        "signing_profile_version_arn",
        "source_code_size",
        "version",
        "role",
    },
    "aws_sfn_state_machine": {"arn", "creation_date", "id", "role_arn", "status"},
    "aws_glue_catalog_database": {"arn", "id"},
    "aws_glue_catalog_table": {"arn", "database_name", "id"},
    "aws_athena_workgroup": {"arn", "id"},
    "aws_cloudwatch_metric_alarm": {"arn", "id"},
}


def canonical_digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _object(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    return value


def _list(value: Any, name: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{name} must be an array")
    return value


def _unknown_paths(value: Any, prefix: tuple[str, ...] = ()) -> list[tuple[str, ...]]:
    if value is True:
        return [prefix]
    if value in (False, None):
        return []
    if isinstance(value, dict):
        result: list[tuple[str, ...]] = []
        for key, child in value.items():
            if not isinstance(key, str):
                raise ValueError("unknown-value key must be a string")
            result.extend(_unknown_paths(child, (*prefix, key)))
        return result
    if isinstance(value, list):
        result = []
        for index, child in enumerate(value):
            result.extend(_unknown_paths(child, (*prefix, str(index))))
        return result
    raise ValueError("unknown-value tree has an invalid leaf")


def _critical(path: tuple[str, ...]) -> bool:
    return any(
        term in token.lower().replace("-", "_").split("_")
        for token in path
        for term in CRITICAL_UNKNOWN_TERMS
    )


def _address_type(address: str) -> str:
    base = address.split("[", 1)[0]
    if "." not in base:
        raise ValueError(f"invalid managed address: {address}")
    return base.split(".", 1)[0]


def _admitted_computed_unknown(resource_type: str, path: tuple[str, ...]) -> bool:
    if len(path) == 1 and path[0] in COMPUTED_UNKNOWN_PATHS.get(resource_type, set()):
        return True
    return (resource_type, path) in {
        ("aws_sfn_state_machine", ("logging_configuration", "0", "log_destination")),
        ("aws_cloudwatch_metric_alarm", ("dimensions", "StateMachineArn")),
    }


def validate_saved_plan(
    plan: dict[str, Any],
    expected_addresses: list[str],
    *,
    expected_terraform_version: str = "1.13.1",
) -> dict[str, Any]:
    """Validate graph/action invariants of JSON rendered from one saved plan.

    Exact resource-property controls are a separate required evaluator. Passing
    this function alone never admits a plan or satisfies S6-G02.
    """
    if plan.get("format_version") != "1.2":
        raise ValueError("Terraform plan format differs")
    if plan.get("terraform_version") != expected_terraform_version:
        raise ValueError("Terraform version differs")
    if len(expected_addresses) != len(set(expected_addresses)) or len(expected_addresses) != 33:
        raise ValueError("expected address authority differs")

    if _list(plan.get("resource_drift", []), "resource_drift"):
        raise ValueError("refresh found resource drift")
    if _object(plan.get("output_changes", {}), "output_changes"):
        raise ValueError("unadmitted output changes")
    for check in _list(plan.get("checks", []), "checks"):
        status = _object(check, "check").get("status")
        if status != "pass":
            raise ValueError("Terraform check did not pass")

    changes = _list(plan.get("resource_changes"), "resource_changes")
    if len(changes) != 33:
        raise ValueError("saved plan must contain exactly 33 resource changes")
    observed: list[str] = []
    unknown_paths: dict[str, list[str]] = {}
    for raw in changes:
        row = _object(raw, "resource change")
        address = row.get("address")
        if not isinstance(address, str):
            raise ValueError("resource change address missing")
        if row.get("mode") != "managed":
            raise ValueError(f"non-managed resource change: {address}")
        expected_type = _address_type(address)
        if row.get("type") != expected_type:
            raise ValueError(f"resource type differs: {address}")
        if row.get("provider_name") != AWS_PROVIDER:
            raise ValueError(f"provider differs: {address}")
        if any(name in row for name in ("previous_address", "deposed", "module_address")):
            raise ValueError(f"moved, deposed or module resource present: {address}")
        change = _object(row.get("change"), f"change {address}")
        if change.get("actions") != ["create"]:
            raise ValueError(f"non-create action: {address}")
        if change.get("before") is not None:
            raise ValueError(f"create has prior state: {address}")
        if not isinstance(change.get("after"), dict):
            raise ValueError(f"create has no determinate after object: {address}")
        if change.get("importing") is not None or change.get("generated_config") is not None:
            raise ValueError(f"import or generated configuration present: {address}")
        if _list(change.get("replace_paths", []), f"replace_paths {address}"):
            raise ValueError(f"replacement path present: {address}")
        paths = _unknown_paths(change.get("after_unknown", {}))
        critical = [
            ".".join(path)
            for path in paths
            if _critical(path) and not _admitted_computed_unknown(expected_type, path)
        ]
        if critical:
            raise ValueError(f"security-critical unknown present: {address}: {critical[0]}")
        unknown_paths[address] = [".".join(path) for path in paths]
        observed.append(address)

    if len(observed) != len(set(observed)):
        raise ValueError("duplicate resource change address")
    if sorted(observed) != sorted(expected_addresses):
        raise ValueError("saved plan address inventory differs")

    prior = _object(plan.get("prior_state"), "prior_state")
    values = _object(prior.get("values", {}), "prior_state.values")
    root_module = _object(values.get("root_module", {}), "prior_state root module")
    if root_module.get("resources") not in (None, []):
        raise ValueError("prior workload state is not empty")
    if root_module.get("child_modules") not in (None, []):
        raise ValueError("prior state contains child modules")

    configuration = _object(plan.get("configuration"), "configuration")
    config_root = _object(configuration.get("root_module"), "configuration root module")
    if config_root.get("module_calls") not in (None, {}):
        raise ValueError("unadmitted module call")
    config_resources = _list(config_root.get("resources"), "configuration resources")
    if not config_resources:
        raise ValueError("configuration resources missing")
    for raw_resource in config_resources:
        resource = _object(raw_resource, "configuration resource")
        address = resource.get("address")
        if not isinstance(address, str):
            raise ValueError("configuration resource address missing")
        if resource.get("mode") != "managed":
            raise ValueError(f"configuration data source is not admitted: {address}")
        if resource.get("provider_config_key") != "aws":
            raise ValueError(f"configuration provider differs: {address}")
        if resource.get("provisioners") not in (None, []):
            raise ValueError(f"configuration provisioner is not admitted: {address}")
    providers = _object(configuration.get("provider_config"), "provider_config")
    if not providers or any(
        _object(provider, "provider").get("full_name") != AWS_PROVIDER
        for provider in providers.values()
    ):
        raise ValueError("provider configuration differs")

    return {
        "classification": "SAVED_PLAN_STRUCTURAL_POLICY_PASSED_PROPERTY_POLICY_STILL_REQUIRED",
        "terraform_version": expected_terraform_version,
        "resource_changes": 33,
        "create_actions": 33,
        "other_actions": 0,
        "address_inventory_sha256": hashlib.sha256(
            ("\n".join(sorted(observed)) + "\n").encode()
        ).hexdigest(),
        "plan_json_sha256": canonical_digest(plan),
        "benign_computed_unknown_count": sum(len(paths) for paths in unknown_paths.values()),
        "property_policy_required": True,
        "aws_calls": 0,
        "stage6_complete": False,
    }


def expected_addresses(root: Path) -> list[str]:
    inventory = json.loads(
        (root / "spec/part3-stage4-resource-inventory-v1.json").read_text(encoding="utf-8")
    )
    return sorted(row["address"] for row in inventory["members"])
