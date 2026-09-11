from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from tools.part3_stage4.administrator import (
    ADMINISTRATOR_ROLES,
    BACKEND_BUCKET,
    DEPLOY_ROLE,
    LEASE_KEY,
    READ_ROLE,
    RESCUE_ROLE,
    admit_identity_snapshot,
    compose,
    identity_contract,
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


def desired_identities(module: dict[str, Any]) -> dict[str, Any]:
    trust = json.loads((ROOT / "contracts/part3-stage2-oidc-trust-v1.json").read_text())
    return identity_contract(
        compose(contract("provider-actions"), module, OPERATION, KEY_VECTOR), trust
    )


def local_snapshot_vector(expected: dict[str, Any]) -> dict[str, Any]:
    """Local contract vector; not an AWS response or live qualification artifact."""
    return {
        "pagination_complete": True,
        "read_errors": [],
        "roles": deepcopy(expected["roles"]),
        "policies": {
            arn: {
                "document": deepcopy(doc),
                "default_version_id": "v1",
                "observed_version_id": "v1",
                "is_default_version": True,
            }
            for arn, doc in expected["policies"].items()
        },
    }


def test_all_bootstrap_identities_can_observe_the_complete_successor(
    module: dict[str, Any],
) -> None:
    packet = compose(contract("provider-actions"), module, OPERATION, KEY_VECTOR)
    desired = desired_identities(module)
    assert packet["read_identity"] == READ_ROLE and packet["rescue_identity"] == RESCUE_ROLE
    assert packet["administrator_roles"] == ADMINISTRATOR_ROLES
    assert len(set(ADMINISTRATOR_ROLES.values())) == 3
    assert set(desired["roles"]) == set(ADMINISTRATOR_ROLES.values())
    assert desired["workload_destroy_targets"] == []
    assert desired["effective_permissions_verified"] is False
    trust = json.loads((ROOT / "contracts/part3-stage2-oidc-trust-v1.json").read_text())
    for kind in ("read", "deploy"):
        rows = {r["Sid"]: r for p in packet[kind + "_policies"].values() for r in p["Statement"]}
        assert set(ADMINISTRATOR_ROLES.values()).issubset(
            rows["ReadRuntimeAndDeployIdentity"]["Resource"]
        )
        assert set(desired["policies"]).issubset(rows["ReadApprovedPolicyVersions"]["Resource"])
        for row in rows.values():
            if row["Effect"] == "Allow" and set(row["Resource"]) & set(
                ADMINISTRATOR_ROLES.values()
            ):
                assert all(action.startswith(("iam:Get", "iam:List")) for action in row["Action"])
    for arn, role in desired["roles"].items():
        assert role["role_name"] == arn.rsplit("/", 1)[1]
        assert role["path"] == "/" and role["permissions_boundary"] is None
        assert role["inline_policies"] == {}
        assert role["trust_policy"] == trust["policy"]
        assert role["maximum_session_duration_seconds"] == 3600
        assert 0 < len(role["attached_policy_arns"]) <= 10
    assert desired["roles"][RESCUE_ROLE]["attached_policy_arns"] == sorted(
        desired["roles"][DEPLOY_ROLE]["attached_policy_arns"]
        + [f"arn:aws:iam::{ACCOUNT}:policy/{name}" for name in packet["rescue_delta_policies"]]
    )
    assert all("Read-v1" in arn for arn in desired["roles"][READ_ROLE]["attached_policy_arns"])


@pytest.mark.parametrize("count", [0, 11])
def test_bootstrap_contract_rejects_invalid_attachment_count(
    module: dict[str, Any], count: int
) -> None:
    packet = compose(contract("provider-actions"), module, OPERATION, KEY_VECTOR)
    packet["read_policies"] = {str(i): {} for i in range(count)}
    trust = json.loads((ROOT / "contracts/part3-stage2-oidc-trust-v1.json").read_text())
    with pytest.raises(ValueError, match="quota envelope"):
        identity_contract(packet, trust)


def test_document_parity_does_not_claim_effective_permission(module: dict[str, Any]) -> None:
    desired = desired_identities(module)
    observed = local_snapshot_vector(desired)
    before = deepcopy(observed)
    result = admit_identity_snapshot(desired, observed)
    assert result["equal"] is True and result["identity_count"] == 3
    assert result["effective_permissions_verified"] is False
    assert result["aws_execution_authorized"] is False
    assert result["classification"] == "IAM_DOCUMENT_PARITY_ONLY"
    assert observed == before


@pytest.mark.parametrize(
    "fault",
    [
        "pagination",
        "errors",
        "missing-role",
        "extra-role",
        "trust",
        "boundary",
        "duration",
        "inline",
        "extra-attachment",
        "missing-attachment",
        "wrong-name",
        "wrong-path",
        "missing-policy",
        "extra-policy",
        "changed-policy",
        "lost-deny",
        "stale-version",
        "not-default",
        "invalid-version",
        "integer-default-flag",
    ],
)
def test_successor_parity_rejects_permission_and_observation_drift(
    module: dict[str, Any], fault: str
) -> None:
    desired = desired_identities(module)
    observed = local_snapshot_vector(desired)
    role = observed["roles"][DEPLOY_ROLE]
    arn = next(iter(observed["policies"]))
    version = observed["policies"][arn]
    if fault == "pagination":
        observed["pagination_complete"] = False
    if fault == "errors":
        observed["read_errors"] = ["AccessDenied"]
    if fault == "missing-role":
        del observed["roles"][READ_ROLE]
    if fault == "extra-role":
        observed["roles"]["unexpected"] = deepcopy(role)
    if fault == "trust":
        role["trust_policy"]["Statement"][0].pop("Condition")
    if fault == "boundary":
        role["permissions_boundary"] = "unreviewed-boundary"
    if fault == "duration":
        role["maximum_session_duration_seconds"] = 43200
    if fault == "inline":
        role["inline_policies"]["old-policy"] = {"Statement": []}
    if fault == "extra-attachment":
        role["attached_policy_arns"].append("unreviewed-policy")
    if fault == "missing-attachment":
        role["attached_policy_arns"].pop()
    if fault == "wrong-name":
        role["role_name"] = "another-role"
    if fault == "wrong-path":
        role["path"] = "/another/"
    if fault == "missing-policy":
        del observed["policies"][arn]
    if fault == "extra-policy":
        observed["policies"]["unreviewed-policy"] = deepcopy(version)
    if fault == "changed-policy":
        version["document"]["Statement"][0]["Action"] = ["iam:*"]
    if fault == "lost-deny":
        for row in observed["policies"].values():
            row["document"]["Statement"] = [
                s for s in row["document"]["Statement"] if s["Effect"] != "Deny"
            ]
    if fault == "stale-version":
        version["observed_version_id"] = "v2"
    if fault == "not-default":
        version["is_default_version"] = False
    if fault == "invalid-version":
        version["default_version_id"] = "v0"
    if fault == "integer-default-flag":
        version["is_default_version"] = 1
    with pytest.raises(ValueError):
        admit_identity_snapshot(desired, observed)
