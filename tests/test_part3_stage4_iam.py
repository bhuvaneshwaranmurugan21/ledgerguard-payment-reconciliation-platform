from __future__ import annotations

import json
from copy import deepcopy
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any

import pytest

from tools.part3_stage4.iam import (
    ROLES,
    WORKLOAD_STARTS,
    exact_policy_set,
    identities,
    resolve,
    runtime_boundaries,
    runtime_policies,
)
from tools.part3_stage4.resources import parse_module

ROOT = Path(__file__).resolve().parents[1]
OBJECTS = json.loads((ROOT / "spec/part3-stage4-runtime-transport-v1.json").read_text())["objects"]
OPERATION = "platform-canary-01"


@pytest.fixture
def policies() -> dict[str, Any]:
    return runtime_policies(parse_module(ROOT / "infra/part3"), OPERATION, OBJECTS)


def test_runtime_task_permissions_are_scoped_and_separated(policies: dict[str, Any]) -> None:
    names = identities(OPERATION)
    assert set(policies) == set(ROLES)
    rows = {role: {s["Sid"]: s for s in p["Statement"]} for role, p in policies.items()}
    assert rows["glue"]["RemoveCommitterTemporaryObjectsOnly"]["Action"] == ["s3:DeleteObject"]
    delete = rows["glue"]["RemoveCommitterTemporaryObjectsOnly"]["Resource"]
    assert any(
        fnmatchcase(
            names["bucket_arn"]
            + "/runs/run-0001/attempts/attempt-01/candidates/transactions/_temporary/0/task",
            p,
        )
        for p in delete
    )
    assert not any(
        fnmatchcase(
            names["bucket_arn"]
            + "/runs/run-0001/attempts/attempt-01/candidates/transactions/part.parquet",
            p,
        )
        for p in delete
    )
    assert rows["validator"]["ReadAuthorityOnly"]["Resource"] == [names["control_arn"]]
    assert all(
        a in ["dynamodb:GetItem", "dynamodb:BatchGetItem", "dynamodb:Query"]
        for a in rows["validator"]["ReadAuthorityOnly"]["Action"]
    )
    assert rows["controller"]["ConditionalControlMetadata"]["Resource"] == [names["control_arn"]]
    assert rows["workflow"]["BoundedGlueIntegration"]["Resource"] == [names["glue_arn"]]
    assert rows["workflow"]["BoundedAthenaIntegration"]["Resource"] == [names["workgroup_arn"]]
    assert rows["workflow"]["InvokeExactControlFunctions"]["Resource"] == list(
        names["function_arns"].values()
    )
    assert len(rows["workflow"]["CatalogReadOnly"]["Resource"]) == 5
    global_exceptions = {"GlueObservability", "StepFunctionsLogDelivery", "LambdaTraceTelemetry"}
    for policy in policies.values():
        for statement in policy["Statement"]:
            assert statement["Effect"] == "Allow"
            assert all("*" not in action and "?" not in action for action in statement["Action"])
            if "*" in statement["Resource"]:
                assert statement["Sid"] in global_exceptions
            for resource in statement["Resource"]:
                assert resource == "*" or "857229544428" in resource
    for role in ["glue", "validator", "controller"]:
        own = rows[role]["WriteOwnStructuredLogs"]["Resource"]
        assert all(names["name"] in arn for arn in own)
    assert "WriteOwnStructuredLogs" not in rows["workflow"]


def test_role_specific_boundaries_block_part3_workloads_and_business_writes(
    policies: dict[str, Any],
) -> None:
    before = deepcopy(policies)
    bounded = runtime_boundaries(policies, OPERATION)
    assert policies == before
    for role in ROLES:
        rows = bounded[role]["Statement"]
        assert [r for r in rows if r["Effect"] == "Allow"] == policies[role]["Statement"]
        denied = {r["Sid"]: r for r in rows if r["Effect"] == "Deny"}
        assert denied["NoPart3WorkloadStart"]["Action"] == WORKLOAD_STARTS
        assert denied["NoPart3WorkloadStart"]["Resource"] == "*"
        assert denied["NoIdentityChaining"]["Action"] == ["sts:AssumeRole"]
        assert "dynamodb:PutItem" in denied["NoPart3BusinessRecords"]["Action"]
        assert "s3:PutObject" in denied["NoPart3BusinessObjects"]["Action"]
        assert len(json.dumps(bounded[role], separators=(",", ":"))) <= 6144


@pytest.mark.parametrize(
    "operation", ["short", "UPPERCASE-0001", "../../unsafe", "x" * 33, "unsafe-0001\n"]
)
def test_invalid_namespace_rejected(operation: str) -> None:
    with pytest.raises(ValueError, match="operation identity"):
        identities(operation)


@pytest.mark.parametrize("field", ["script_key", "wheels_key"])
def test_unqualified_artifact_path_rejected(field: str) -> None:
    objects = dict(OBJECTS)
    objects[field] = "deployment/latest/payload.zip"
    with pytest.raises(ValueError, match="unqualified"):
        runtime_policies(parse_module(ROOT / "infra/part3"), OPERATION, objects)


def test_extra_artifacts_and_missing_roles_rejected(policies: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match="object inventory"):
        runtime_policies({}, OPERATION, dict(OBJECTS, other="extra"))
    policies.pop("glue")
    with pytest.raises(ValueError, match="role inventory"):
        runtime_boundaries(policies, OPERATION)


def test_policy_size_limit_is_enforced(policies: dict[str, Any]) -> None:
    policies["glue"]["Statement"].append(
        {"Sid": "x" * 6145, "Effect": "Allow", "Action": ["s3:GetObject"], "Resource": ["*"]}
    )
    with pytest.raises(ValueError, match="policy size"):
        runtime_boundaries(policies, OPERATION)


def test_reference_resolver_is_bounded_and_preserves_types() -> None:
    bindings: dict[str, Any] = {"local.name": "owned", "local.names": ["one", "two"]}
    assert resolve(
        {"a": ["${local.name}", True, 2, "literal", "prefix-${local.name}"], "b": "${local.names}"},
        bindings,
    ) == {"a": ["owned", True, 2, "literal", "prefix-owned"], "b": ["one", "two"]}
    for expression, reason in [
        ('${file("/etc/passwd")}', "reference"),
        ("${unknown}", "reference"),
        ("arn:${unknown}", "interpolation"),
        ("arn:${local.names}", "interpolation"),
        ("bad-${nested${}}", "unresolved"),
    ]:
        with pytest.raises(ValueError, match=reason):
            resolve(expression, bindings)
    result = resolve("${local.names}", bindings)
    result.append("mutated")
    assert bindings["local.names"] == ["one", "two"]


def test_named_policy_comparison_rejects_missing_excess_or_changed(
    policies: dict[str, Any],
) -> None:
    assert exact_policy_set(policies, deepcopy(policies))["equal"] is True
    observed = deepcopy(policies)
    observed.pop("glue")
    with pytest.raises(ValueError, match=r"missing.*glue"):
        exact_policy_set(policies, observed)
    observed = deepcopy(policies)
    observed["unapproved"] = {}
    with pytest.raises(ValueError, match=r"excess.*unapproved"):
        exact_policy_set(policies, observed)
    observed = deepcopy(policies)
    observed["glue"]["Statement"][0]["Action"] = ["s3:*"]
    with pytest.raises(ValueError, match=r"changed.*glue"):
        exact_policy_set(policies, observed)
