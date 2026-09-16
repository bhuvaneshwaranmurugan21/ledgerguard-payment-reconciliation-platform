from __future__ import annotations

import subprocess
from typing import Any

import pytest

import tools.part3_stage6.aws_cli as stage6_cli
import tools.part3_stage6.live as live
from ledgerguard.stage2.aws_cli import AwsCli
from ledgerguard.stage2.control import Stage2Rejected
from tools.part3_stage6.aws_cli import EXTRA_COMMANDS


class FakeCli:
    def __init__(self, responses: dict[str, Any]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, list[str]]] = []

    def invoke(self, operation: str, arguments: list[str] | None = None) -> dict[str, Any]:
        self.calls.append((operation, arguments or []))
        value = self.responses[operation]
        return value() if callable(value) else value


def empty_inventory_responses() -> dict[str, Any]:
    return {
        "S3_LIST_BUCKETS": {"Buckets": []},
        "DDB_LIST_TABLES": {"TableNames": []},
        "GLUE_GET_JOBS": {"Jobs": []},
        "GLUE_GET_DATABASES": {"DatabaseList": []},
        "LAMBDA_LIST_FUNCTIONS": {"Functions": []},
        "SFN_LIST": {"stateMachines": []},
        "ATHENA_LIST_WORKGROUPS": {"WorkGroups": []},
        "CLOUDWATCH_DESCRIBE_ALARMS": {"MetricAlarms": []},
        "IAM_LIST_ROLES": {"Roles": []},
        "TAG_GET_RESOURCES": {"ResourceTagMappingList": []},
        "LOGS_DESCRIBE_GROUPS": {"logGroups": []},
    }


def test_extended_inventory_operations_are_narrowly_allowlisted() -> None:
    assert {
        "IAM_GET_ACCOUNT_SUMMARY",
        "IAM_LIST_ROLES",
        "IAM_GET_POLICY",
        "IAM_GET_POLICY_VERSION",
        "IAM_LIST_POLICY_VERSIONS",
        "GLUE_GET_DATABASES",
        "ATHENA_LIST_WORKGROUPS",
        "LAMBDA_LIST_FUNCTIONS",
        "CLOUDWATCH_DESCRIBE_ALARMS",
    } == set(EXTRA_COMMANDS)
    assert "TAG_GET_RESOURCES" not in EXTRA_COMMANDS


def test_stage6_cli_delegates_accepted_operations(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        AwsCli,
        "invoke",
        lambda self, operation, arguments=None: {"operation": operation, "arguments": arguments},
    )
    assert stage6_cli.Stage6AwsCli("ap-southeast-2").invoke(
        "STS_GET_CALLER_IDENTITY", ["--query", "Account"]
    ) == {"operation": "STS_GET_CALLER_IDENTITY", "arguments": ["--query", "Account"]}


def test_stage6_cli_executes_and_journals_extra_reads(monkeypatch: pytest.MonkeyPatch) -> None:
    observed: list[list[str]] = []

    def run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        observed.append(command)
        return subprocess.CompletedProcess(command, 0, '{"Roles": []}', "")

    monkeypatch.setattr(stage6_cli.subprocess, "run", run)
    cli = stage6_cli.Stage6AwsCli("ap-southeast-2")
    assert cli.invoke("IAM_LIST_ROLES", ["--path-prefix", "/ledgerguard/"]) == {"Roles": []}
    assert observed == [
        [
            "aws",
            "iam",
            "list-roles",
            "--path-prefix",
            "/ledgerguard/",
            "--region",
            "ap-southeast-2",
            "--output",
            "json",
            "--no-cli-pager",
        ]
    ]
    assert cli.journal[0]["operation"] == "IAM_LIST_ROLES"
    assert cli.journal[0]["returncode"] == 0


def test_stage6_cli_fail_closed_responses(monkeypatch: pytest.MonkeyPatch) -> None:
    cli = stage6_cli.Stage6AwsCli("ap-southeast-2")
    with pytest.raises(Stage2Rejected, match="forbidden AWS argument"):
        cli.invoke("IAM_LIST_ROLES", ["start-execution"])

    def failed(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 1, "", "denied in 857229544428")

    monkeypatch.setattr(stage6_cli.subprocess, "run", failed)
    with pytest.raises(Stage2Rejected, match="AWS operation failed"):
        cli.invoke("IAM_LIST_ROLES")
    assert "857229544428" not in cli.journal[-1]["error"]

    def malformed(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 0, "not-json", "")

    monkeypatch.setattr(stage6_cli.subprocess, "run", malformed)
    with pytest.raises(Stage2Rejected, match="non-JSON"):
        cli.invoke("IAM_LIST_ROLES")

    def non_object(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 0, "[]", "")

    monkeypatch.setattr(stage6_cli.subprocess, "run", non_object)
    with pytest.raises(Stage2Rejected, match="object response"):
        cli.invoke("IAM_LIST_ROLES")


def test_observe_identity_contract_reads_exact_default_versions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    role_arn = "arn:aws:iam::857229544428:role/Test"
    policy_arn = "arn:aws:iam::857229544428:policy/Test"
    expected = {
        "roles": {
            role_arn: {
                "role_name": "Test",
                "path": "/",
                "trust_policy": {"Version": "2012-10-17"},
                "maximum_session_duration_seconds": 3600,
                "permissions_boundary": None,
                "inline_policies": {},
                "attached_policy_arns": [policy_arn],
            }
        },
        "policies": {policy_arn: {"Version": "2012-10-17", "Statement": []}},
    }
    fake = FakeCli(
        {
            "IAM_GET_ROLE": {
                "Role": {
                    "Path": "/",
                    "AssumeRolePolicyDocument": {"Version": "2012-10-17"},
                    "MaxSessionDuration": 3600,
                }
            },
            "IAM_LIST_ROLE_POLICIES": {"PolicyNames": []},
            "IAM_LIST_ATTACHED_ROLE_POLICIES": {"AttachedPolicies": [{"PolicyArn": policy_arn}]},
            "IAM_LIST_ROLE_TAGS": {"Tags": [{"Key": "Project", "Value": "LedgerGuard"}]},
            "IAM_GET_POLICY": {"Policy": {"DefaultVersionId": "v1"}},
            "IAM_GET_POLICY_VERSION": {
                "PolicyVersion": {
                    "VersionId": "v1",
                    "IsDefaultVersion": True,
                    "Document": expected["policies"][policy_arn],
                }
            },
        }
    )
    result = live.observe_identity_contract(fake, expected)  # type: ignore[arg-type]
    assert result["equal"] is True
    assert len(result["snapshot_sha256"]) == 64
    assert [operation for operation, _ in fake.calls][-2:] == [
        "IAM_GET_POLICY",
        "IAM_GET_POLICY_VERSION",
    ]


def backend_responses(key: str) -> dict[str, Any]:
    return {
        "S3_GET_BUCKET_LOCATION": {"LocationConstraint": "ap-southeast-2"},
        "S3_GET_BUCKET_VERSIONING": {"Status": "Enabled"},
        "S3_GET_BUCKET_ENCRYPTION": {
            "ServerSideEncryptionConfiguration": {
                "Rules": [
                    {
                        "ApplyServerSideEncryptionByDefault": {
                            "SSEAlgorithm": "aws:kms",
                            "KMSMasterKeyID": key,
                        }
                    }
                ]
            }
        },
        "S3_GET_PUBLIC_ACCESS": {
            "PublicAccessBlockConfiguration": {
                key: True
                for key in (
                    "BlockPublicAcls",
                    "IgnorePublicAcls",
                    "BlockPublicPolicy",
                    "RestrictPublicBuckets",
                )
            }
        },
        "S3_GET_BUCKET_POLICY": {"Policy": "{}"},
        "S3_GET_OWNERSHIP": {
            "OwnershipControls": {"Rules": [{"ObjectOwnership": "BucketOwnerEnforced"}]}
        },
        "S3_GET_LIFECYCLE": {"Rules": []},
        "S3_LIST_VERSIONS": {"Versions": [], "DeleteMarkers": []},
    }


def test_backend_observation_and_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    key = "arn:aws:kms:ap-southeast-2:857229544428:key/11111111-2222-3333-4444-555555555555"
    monkeypatch.setattr(live, "validate_backend", lambda *args: {"verified": True})
    monkeypatch.setattr(live, "validate_backend_lifecycle", lambda *args: {"verified": True})
    monkeypatch.setattr(live, "validate_tls_only_bucket_policy", lambda *args: {"verified": True})
    fake = FakeCli(backend_responses(key))
    result = live.observe_backend(fake, key, {"backend": {}})  # type: ignore[arg-type]
    assert all(result.values())
    changed = backend_responses(key)
    changed["S3_LIST_VERSIONS"] = {"IsTruncated": True}
    with pytest.raises(ValueError, match="pagination"):
        live.observe_backend(FakeCli(changed), key, {"backend": {}})  # type: ignore[arg-type]
    changed = backend_responses(key)
    changed["S3_LIST_VERSIONS"] = {"Versions": [{"Key": live.STATE_KEY, "IsLatest": True}]}
    result = live.observe_backend(FakeCli(changed), key, {"backend": {}})  # type: ignore[arg-type]
    assert result["exact_state_absent"] is False
    changed = backend_responses(key)
    changed["S3_LIST_VERSIONS"] = {
        "Versions": [{"Key": live.STATE_KEY, "IsLatest": False}],
        "DeleteMarkers": [{"Key": live.STATE_KEY, "IsLatest": True}],
    }
    result = live.observe_backend(FakeCli(changed), key, {"backend": {}})  # type: ignore[arg-type]
    assert result["exact_state_absent"] is True


def test_lease_is_conditional_and_owner_bound() -> None:
    owner = "owner-token"
    fake = FakeCli(
        {
            "DDB_PUT_ITEM": {},
            "DDB_GET_ITEM": {"Item": {"owner_token": {"S": owner}}},
        }
    )
    assert live.acquire_lease(fake, owner, 123)["owner_readback_equal"] is True  # type: ignore[arg-type]
    put_args = fake.calls[0][1]
    assert "attribute_not_exists(lease_key)" in put_args
    fake = FakeCli({"DDB_PUT_ITEM": {}, "DDB_GET_ITEM": {"Item": {"owner_token": {"S": "other"}}}})
    with pytest.raises(ValueError, match="readback"):
        live.acquire_lease(fake, owner, 123)  # type: ignore[arg-type]
    release = FakeCli({"DDB_DELETE_ITEM": {}, "DDB_GET_ITEM": {}})
    assert live.release_lease(release, owner)["lease_owner_absent_after_release"] is True  # type: ignore[arg-type]
    assert "owner_token = :owner" in release.calls[0][1]


def test_exact_inventory_detection() -> None:
    empty = FakeCli(empty_inventory_responses())
    assert live.observe_clean_inventory(empty)["expected_operation_resources"] == 0  # type: ignore[arg-type]
    assert ("GLUE_GET_DATABASES", ["--max-results", "100"]) in empty.calls
    present_responses = empty_inventory_responses()
    present_responses["S3_LIST_BUCKETS"] = {
        "Buckets": [{"Name": "ledgerguard-p3-857229544428-release-qual1"}]
    }
    present = FakeCli(present_responses)
    with pytest.raises(ValueError, match="not clean"):
        live.observe_clean_inventory(present)  # type: ignore[arg-type]
    other_responses = empty_inventory_responses()
    other_responses["DDB_LIST_TABLES"] = {"TableNames": ["ledgerguard-old-workload"]}
    other = FakeCli(other_responses)
    with pytest.raises(ValueError, match="other LedgerGuard"):
        live.observe_clean_inventory(other)  # type: ignore[arg-type]


def test_inventory_detects_each_extended_resource_family_and_allows_shared_controls() -> None:
    cases = {
        "GLUE_GET_DATABASES": {
            "DatabaseList": [{"Name": "ledgerguard_p3_release_qual1_reconciliation"}]
        },
        "LAMBDA_LIST_FUNCTIONS": {
            "Functions": [{"FunctionName": "ledgerguard-p3-release-qual1-validator"}]
        },
        "CLOUDWATCH_DESCRIBE_ALARMS": {
            "MetricAlarms": [{"AlarmName": "ledgerguard-p3-release-qual1-workflow-failure"}]
        },
        "IAM_LIST_ROLES": {"Roles": [{"RoleName": "ledgerguard-p3-release-qual1-glue"}]},
        "TAG_GET_RESOURCES": {
            "ResourceTagMappingList": [
                {
                    "ResourceARN": (
                        "arn:aws:lambda:ap-southeast-2:857229544428:function:"
                        "ledgerguard-p3-release-qual1-controller"
                    )
                }
            ]
        },
    }
    for operation, response in cases.items():
        responses = empty_inventory_responses()
        responses[operation] = response
        with pytest.raises(ValueError, match="not clean"):
            live.observe_clean_inventory(FakeCli(responses))  # type: ignore[arg-type]
    shared = empty_inventory_responses()
    shared["TAG_GET_RESOURCES"] = {
        "ResourceTagMappingList": [
            {
                "ResourceARN": (
                    "arn:aws:dynamodb:ap-southeast-2:857229544428:table/"
                    "ledgerguard-operation-leases"
                )
            }
        ]
    }
    assert live.observe_clean_inventory(FakeCli(shared))["expected_operation_resources"] == 0  # type: ignore[arg-type]


def quota_responses() -> dict[str, Any]:
    return {
        "IAM_GET_ACCOUNT_SUMMARY": {
            "SummaryMap": {
                "Roles": 10,
                "RolesQuota": 100,
                "Policies": 20,
                "PoliciesQuota": 100,
            }
        },
        "QUOTAS_LIST": {"Quotas": [{"QuotaCode": "q", "Value": 100.0}]},
    }


def test_quota_visibility_is_live_and_has_headroom() -> None:
    result = live.observe_quota_visibility(FakeCli(quota_responses()))  # type: ignore[arg-type]
    assert set(result) == {
        "iam",
        "lambda",
        "glue",
        "athena",
        "states",
        "dynamodb",
        "cloudwatch",
        "s3",
    }
    changed = quota_responses()
    changed["IAM_GET_ACCOUNT_SUMMARY"] = {"SummaryMap": []}
    with pytest.raises(ValueError, match="IAM quota visibility"):
        live.observe_quota_visibility(FakeCli(changed))  # type: ignore[arg-type]
    changed = quota_responses()
    changed["IAM_GET_ACCOUNT_SUMMARY"] = {"SummaryMap": {"Roles": "10", "RolesQuota": 100}}
    with pytest.raises(ValueError, match="IAM quota values"):
        live.observe_quota_visibility(FakeCli(changed))  # type: ignore[arg-type]
    changed = quota_responses()
    changed["IAM_GET_ACCOUNT_SUMMARY"] = {
        "SummaryMap": {
            "Roles": 99,
            "RolesQuota": 100,
            "Policies": 20,
            "PoliciesQuota": 100,
        }
    }
    with pytest.raises(ValueError, match="headroom"):
        live.observe_quota_visibility(FakeCli(changed))  # type: ignore[arg-type]
    changed = quota_responses()
    changed["QUOTAS_LIST"] = {"Quotas": []}
    with pytest.raises(ValueError, match="quota visibility"):
        live.observe_quota_visibility(FakeCli(changed))  # type: ignore[arg-type]
    changed = quota_responses()
    changed["QUOTAS_LIST"] = {"Quotas": [{"Value": "100"}]}
    with pytest.raises(ValueError, match="quota values"):
        live.observe_quota_visibility(FakeCli(changed))  # type: ignore[arg-type]


def test_collect_preflight_composes_only_admitted_results(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeCli(
        {
            "STS_GET_CALLER_IDENTITY": {
                "Account": live.ACCOUNT,
                "Arn": "arn:aws:sts::857229544428:assumed-role/LedgerGuardGitHubOidcRole/run",
            }
        }
    )
    monkeypatch.setattr(live, "observe_identity_contract", lambda *args: {"equal": True})
    monkeypatch.setattr(
        live,
        "observe_backend",
        lambda *args: {
            key: True
            for key in (
                "exact_bucket",
                "exact_region",
                "versioning_enabled",
                "kms_key_exact",
                "public_access_blocked",
                "tls_only",
                "ownership_enforced",
                "lifecycle_admitted",
                "exact_state_absent",
                "lock_absent_before_lease",
            )
        },
    )
    monkeypatch.setattr(
        live,
        "observe_clean_inventory",
        lambda *args: {
            "pagination_complete": True,
            "access_denied": [],
            "expected_operation_resources": 0,
            "other_ledgerguard_workload_resources": 0,
            "active_glue_runs": 0,
            "active_athena_queries": 0,
            "active_state_machine_executions": 0,
        },
    )
    monkeypatch.setattr(
        live,
        "_cost_headroom_check",
        lambda *args: {"admitted": True, "known_gross_project_spend": "1.00"},
    )
    monkeypatch.setattr(
        live,
        "observe_quota_visibility",
        lambda *args: {
            key: True
            for key in (
                "iam",
                "lambda",
                "glue",
                "athena",
                "states",
                "dynamodb",
                "cloudwatch",
                "s3",
            )
        },
    )
    monkeypatch.setattr(
        live,
        "acquire_lease",
        lambda *args: {
            key: True
            for key in (
                "shared_table_admitted",
                "exact_key",
                "prior_owner_absent",
                "conditionally_acquired",
                "owner_readback_equal",
            )
        },
    )
    result = live.collect_preflight(
        cli=fake,
        expected_identity={},
        administrator_receipt_sha256="a" * 64,
        source_commit="b" * 40,
        source_tree="c" * 40,
        kms_key_arn="key",
        control_plane={},
        cost_contract={"conservative_unbilled_reserve_usd": "1.00"},
        inventory_contract={"complete_pagination_required": True},
        owner_token="owner",
        lease_expires_epoch=123,
        now_epoch=100,
    )  # type: ignore[arg-type]
    assert result["classification"] == "FRESH_EXACT_MAIN_PLAN_ONLY_ADMISSION"
    assert result["budget"]["known_gross_usd"] == "1.00"


@pytest.mark.parametrize("failure", ["identity", "iam", "backend", "inventory-contract", "budget"])
def test_collect_preflight_rejects_each_live_gate(
    monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    account = "000000000000" if failure == "identity" else live.ACCOUNT
    fake = FakeCli(
        {
            "STS_GET_CALLER_IDENTITY": {
                "Account": account,
                "Arn": "arn:aws:sts::857229544428:assumed-role/LedgerGuardGitHubOidcRole/run",
            }
        }
    )
    monkeypatch.setattr(
        live, "observe_identity_contract", lambda *args: {"equal": failure != "iam"}
    )
    monkeypatch.setattr(live, "observe_backend", lambda *args: {"ok": failure != "backend"})
    monkeypatch.setattr(live, "observe_clean_inventory", lambda *args: {})
    monkeypatch.setattr(live, "observe_quota_visibility", lambda *args: {})
    monkeypatch.setattr(
        live, "_cost_headroom_check", lambda *args: {"admitted": failure != "budget"}
    )
    with pytest.raises(ValueError):
        live.collect_preflight(
            cli=fake,
            expected_identity={},
            administrator_receipt_sha256="a" * 64,
            source_commit="b" * 40,
            source_tree="c" * 40,
            kms_key_arn="key",
            control_plane={},
            cost_contract={},
            inventory_contract={"complete_pagination_required": failure != "inventory-contract"},
            owner_token="owner",
            lease_expires_epoch=123,
            now_epoch=100,
        )  # type: ignore[arg-type]
