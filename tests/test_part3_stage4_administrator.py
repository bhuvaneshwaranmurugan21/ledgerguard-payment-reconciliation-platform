from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from tools.part3_stage4.administrator import (
    BACKEND_BUCKET,
    DEPLOY_ROLE,
    LEASE_KEY,
    compose,
    partition_policies,
    statement,
)
from tools.part3_stage4.iam import ACCOUNT, REGION, WORKLOAD_STARTS, identities
from tools.part3_stage4.resources import expand_addresses, parse_module

ROOT = Path(__file__).resolve().parents[1]
# Syntactic test vector only. Never exported as an observed AWS ARN or admin packet.
KEY_VECTOR = f"arn:aws:kms:{REGION}:{ACCOUNT}:key/00000000-0000-0000-0000-000000000001"
OPERATION = "platform-canary-01"


def contract(name: str) -> dict[str, Any]:
    return json.loads((ROOT / f"spec/part3-stage4-{name}-v1.json").read_text())


@pytest.fixture
def module() -> dict[str, Any]:
    return parse_module(ROOT / "infra/part3")


def test_resource_inventory_is_actually_expanded(module: dict[str, Any]) -> None:
    addresses = expand_addresses(module, contract("catalog"), contract("resource-inventory"))
    assert len(addresses) == 33
    assert 'aws_iam_role.runtime["glue"]' in addresses
    assert 'aws_glue_catalog_table.candidate["bank_allocations"]' in addresses


@pytest.mark.parametrize(
    "failure",
    ["count", "expression", "empty", "not-map", "extra", "count-lie", "duplicate", "rename"],
)
def test_changed_expansion_cannot_hide_behind_declared_count(
    module: dict[str, Any], failure: str
) -> None:
    inventory, catalog = contract("resource-inventory"), contract("catalog")
    if failure == "count":
        module["resource"]["aws_glue_job.reconciliation"]["count"] = 2
    if failure == "expression":
        module["resource"]["aws_iam_role.runtime"]["for_each"] = "${unknown}"
    if failure == "empty":
        module["locals"]["services"] = {}
    if failure == "not-map":
        module["locals"]["services"] = ["glue"]
    if failure == "rename":
        module["locals"]["services"]["unapproved"] = module["locals"]["services"].pop("glue")
    if failure == "extra":
        module["locals"]["services"]["unapproved"] = "ec2.amazonaws.com"
    if failure == "count-lie":
        inventory["managed_address_count"] = 34
    if failure == "duplicate":
        inventory["members"].append(inventory["members"][0])
    with pytest.raises(ValueError):
        expand_addresses(module, catalog, inventory)


def test_exact_successor_preserves_boundaries_and_separates_rescue(module: dict[str, Any]) -> None:
    result = compose(contract("provider-actions"), module, OPERATION, KEY_VECTOR)
    names = identities(OPERATION)
    rows = {
        row["Sid"]: row
        for policy in result["deploy_policies"].values()
        for row in policy["Statement"]
    }
    assert result["classification"] == "DESIRED_NOT_INSTALLED_OR_AWS_VALIDATED"
    assert result["aws_execution"] is False and result["trust_change"] is False
    assert result["backend"]["bucket"] == BACKEND_BUCKET
    assert (
        result["backend"]["key"]
        == "ledgerguard/terraform/part3/platform/platform-canary-01/terraform.tfstate"
    )
    assert rows["RemoveExactLockOnly"]["Resource"][0].endswith(".tflock")
    assert rows["ConditionalDeploymentLease"]["Condition"]["ForAllValues:StringEquals"][
        "dynamodb:LeadingKeys"
    ] == [LEASE_KEY]
    assert rows["ReadBackendKey"]["Resource"] == [KEY_VECTOR]
    for role in names["role_arns"]:
        create = rows["CreateBounded" + role.title()]
        assert create["Resource"] == [names["role_arns"][role]]
        assert (
            create["Condition"]["StringEquals"]["iam:PermissionsBoundary"]
            == names["boundary_arns"][role]
        )
        assert rows["PassExact" + role.title()]["Resource"] == [names["role_arns"][role]]
        assert (
            "iam:PassedToService" in rows["PassExact" + role.title()]["Condition"]["StringEquals"]
        )
    assert rows["NoDeploymentIdentityWorkloadStart"]["Action"] == WORKLOAD_STARTS
    forbidden = {
        "iam:CreatePolicy",
        "iam:CreatePolicyVersion",
        "iam:AttachRolePolicy",
        "iam:PutRolePermissionsBoundary",
        "iam:DeleteRolePermissionsBoundary",
        "iam:UpdateAssumeRolePolicy",
        "sts:AssumeRole",
        "glue:BatchStopJobRun",
        "states:StopExecution",
        "athena:StopQueryExecution",
        *WORKLOAD_STARTS,
    }
    for row in rows.values():
        assert all(isinstance(arn, str) for arn in row["Resource"])
        if row["Effect"] == "Allow":
            assert forbidden.isdisjoint(row["Action"])
            if DEPLOY_ROLE in row["Resource"]:
                assert all(action.startswith(("iam:Get", "iam:List")) for action in row["Action"])
    for policies in (
        result["read_policies"],
        result["deploy_policies"],
        result["rescue_delta_policies"],
    ):
        assert 0 < len(policies) <= 10
        assert all(
            len(json.dumps(policy, separators=(",", ":"))) <= 6144 for policy in policies.values()
        )
    assert {
        action
        for p in result["rescue_delta_policies"].values()
        for r in p["Statement"]
        for action in r["Action"]
    } == {"glue:BatchStopJobRun", "states:StopExecution", "athena:StopQueryExecution"}
    for p in result["read_policies"].values():
        for row in p["Statement"]:
            if row["Effect"] == "Allow":
                assert all(
                    action.split(":")[1].startswith(
                        ("Get", "List", "Describe", "View", "Validate", "Scan", "Decrypt", "Filter")
                    )
                    for action in row["Action"]
                )


@pytest.mark.parametrize(
    "key",
    [
        "",
        "*",
        "alias/aws/s3",
        KEY_VECTOR.replace(REGION, "us-east-1"),
        KEY_VECTOR.replace(ACCOUNT, "111111111111"),
    ],
)
def test_unobserved_or_wrong_scope_key_cannot_render(module: dict[str, Any], key: str) -> None:
    with pytest.raises(ValueError, match="exact observed"):
        compose(contract("provider-actions"), module, OPERATION, key)


def test_provider_actions_reject_ambiguous_or_broadened_rules(module: dict[str, Any]) -> None:
    original = contract("provider-actions")
    for fault in ("duplicate", "classification", "wildcard", "empty", "bad-type"):
        provider = deepcopy(original)
        if fault == "duplicate":
            provider["statements"].append(provider["statements"][0])
        if fault == "classification":
            provider["statements"][0]["classification"] = "IGNORE"
        if fault == "wildcard":
            provider["statements"][0]["actions"] = ["s3:*"]
        if fault == "empty":
            provider["statements"][0]["resources"] = []
        if fault == "bad-type":
            provider["statements"][0]["resources"] = [3]
        with pytest.raises(ValueError):
            compose(provider, module, OPERATION, KEY_VECTOR)


def test_partitioning_handles_boundaries_without_truncation() -> None:
    a = statement("a", ["s3:GetObject"], ["x" * 4000])
    b = statement("b", ["s3:GetObject"], ["y" * 4000])
    policies = partition_policies([a, b], "Reviewed")
    assert list(policies) == ["Reviewed-01", "Reviewed-02"]
    assert policies["Reviewed-01"]["Statement"] == [a]
    assert policies["Reviewed-02"]["Statement"] == [b]
    huge = statement("huge", ["s3:GetObject"], ["x" * 6145])
    for rows in ([], [huge], [a, huge], [a] * 11):
        with pytest.raises(ValueError):
            partition_policies(rows, "Reviewed")
