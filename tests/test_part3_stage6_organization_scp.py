from __future__ import annotations

import hashlib
import json
import sys
import zipfile
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

import tools.part3_stage6.organization_scp as scp
from tools import adjudicate_part3_stage6_organization_scp as command
from tools.part3_stage6.organization_scp import (
    ACCOUNT,
    REGION,
    ScpRequest,
    adjudicate_service_control_policies,
    successor_required_requests,
    validate_observation_archive,
)

SOURCE_COMMIT = "a" * 40
SOURCE_TREE = "b" * 40
ANCHOR = "c" * 64
NOW = 1_800_000_000
MANAGEMENT = "111122223333"


def canonical(value: Any) -> bytes:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False).encode() + b"\n"


def full_access() -> dict[str, Any]:
    return {
        "Version": "2012-10-17",
        "Statement": [{"Effect": "Allow", "Action": "*", "Resource": "*"}],
    }


def restrictions() -> dict[str, Any]:
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "EastRegionGuard",
                "Effect": "Deny",
                "NotAction": ["iam:*", "organizations:*", "sts:*"],
                "Resource": "*",
                "Condition": {"StringEquals": {"aws:RequestedRegion": "us-east-1"}},
            },
            {
                "Sid": "RegionFloor",
                "Effect": "Deny",
                "NotAction": ["iam:*", "organizations:*"],
                "Resource": "*",
                "Condition": {
                    "StringNotEquals": {
                        "aws:RequestedRegion": [REGION, "us-east-1", "unspecified"]
                    }
                },
            },
        ],
    }


def managed_guard() -> dict[str, Any]:
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "ProtectManagedRoles",
                "Effect": "Deny",
                "Action": ["iam:CreateRole", "iam:DeleteRole", "iam:AttachRolePolicy"],
                "Resource": "arn:*:iam::*:role/managed/*",
                "Condition": {
                    "StringNotLike": {
                        "aws:PrincipalArn": "arn:*:iam::*:role/managed/ManagementRole"
                    }
                },
            }
        ],
    }


def observation() -> dict[str, Any]:
    documents = [full_access(), restrictions(), managed_guard()]
    identifiers = ["p-full", "p-region", "p-managed"]
    policies = []
    for identifier, document in zip(identifiers, documents, strict=True):
        policies.append(
            {
                "summary": {
                    "Id": identifier,
                    "Arn": (
                        f"arn:aws:organizations::{MANAGEMENT}:policy/"
                        f"o-org/service_control_policy/{identifier}"
                    ),
                    "Name": identifier,
                    "Description": "test",
                    "Type": "SERVICE_CONTROL_POLICY",
                    "AwsManaged": identifier == "p-full",
                },
                "document": document,
                "document_sha256": hashlib.sha256(canonical(document)).hexdigest(),
                "full_access": identifier == "p-full",
            }
        )
    return {
        "schema_version": "ledgerguard.stage6-organizations-observation.v1",
        "status": "OBSERVED",
        "source": {"commit": SOURCE_COMMIT, "tree": SOURCE_TREE},
        "anchor_preflight_failure_sha256": ANCHOR,
        "target_account": ACCOUNT,
        "caller_identity": {
            "Account": MANAGEMENT,
            "Arn": f"arn:aws:sts::{MANAGEMENT}:assumed-role/Administrator/session",
            "UserId": "test",
        },
        "organization": {
            "Id": "o-example",
            "Arn": f"arn:aws:organizations::{MANAGEMENT}:organization/o-example",
            "FeatureSet": "ALL",
            "MasterAccountId": MANAGEMENT,
            "MasterAccountArn": (
                f"arn:aws:organizations::{MANAGEMENT}:account/o-example/{MANAGEMENT}"
            ),
            "MasterAccountEmail": "private@example.invalid",
            "AvailablePolicyTypes": [
                {"Type": "SERVICE_CONTROL_POLICY", "Status": "ENABLED"}
            ],
        },
        "target_chain": [ACCOUNT, "r-root"],
        "attachments": {ACCOUNT: ["p-full"], "r-root": identifiers},
        "policies": policies,
        "all_attached_scps_full_access": False,
        "completed_epoch": NOW - 10,
        "mutating_aws_calls": 0,
        "workload_calls": 0,
        "stage6_complete": False,
    }


def journal(value: dict[str, Any]) -> list[dict[str, Any]]:
    chain = value["target_chain"]
    policies = value["policies"]
    operations = (
        [("sts", "get-caller-identity"), ("organizations", "describe-organization")]
        + [("organizations", "list-parents")] * (len(chain) - 1)
        + [("organizations", "list-policies-for-target")] * len(chain)
        + [("organizations", "describe-policy")] * len(policies)
    )
    return [
        {
            "index": index,
            "service": service,
            "operation": operation,
            "exit_code": 0,
            "classification": "SUCCESS",
            "arguments": [],
            "started_epoch": value["completed_epoch"] - 2,
            "completed_epoch": value["completed_epoch"] - 1,
            "stdout_sha256": hashlib.sha256(b"{}\n").hexdigest(),
            "stderr_sha256": hashlib.sha256(b"").hexdigest(),
        }
        for index, (service, operation) in enumerate(operations)
    ]


def archive(tmp_path: Path, value: dict[str, Any] | None = None) -> tuple[Path, str]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    observed = observation() if value is None else value
    rows = journal(observed)
    members = {
        "organizations-observation.json": json.dumps(observed, indent=2).encode() + b"\n",
        "api-journal.json": json.dumps(rows, indent=2).encode() + b"\n",
    }
    for row in rows:
        label = f"{row['index']:03d}-{row['service']}-{row['operation']}"
        members[f"raw-aws/{label}.stdout"] = b"{}\n"
        members[f"raw-aws/{label}.stderr"] = b""
    manifest = {
        name: {"sha256": hashlib.sha256(body).hexdigest(), "size_bytes": len(body)}
        for name, body in members.items()
    }
    members["EVIDENCE-MANIFEST.json"] = json.dumps(manifest, indent=2).encode() + b"\n"
    path = tmp_path / "observation.zip"
    with zipfile.ZipFile(path, "w") as output:
        for name, body in members.items():
            output.writestr(name, body)
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def raw_archive(tmp_path: Path, members: dict[str, bytes]) -> tuple[Path, str]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "raw.zip"
    with zipfile.ZipFile(path, "w") as output:
        for name, body in members.items():
            output.writestr(name, body)
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def validate(path: Path, digest: str) -> dict[str, Any]:
    return validate_observation_archive(
        path,
        archive_sha256=digest,
        source_commit=SOURCE_COMMIT,
        source_tree=SOURCE_TREE,
        anchor_preflight_failure_sha256=ANCHOR,
        now_epoch=NOW,
    )


def requests() -> list[ScpRequest]:
    administrator = f"arn:aws:iam::{ACCOUNT}:role/LedgerGuardStage6Administrator"
    return [
        ScpRequest(
            "iam:CreateRole",
            f"arn:aws:iam::{ACCOUNT}:role/LedgerGuardPart3ReadOnlyRole",
            "us-east-1",
            administrator,
            "administrator-transaction",
        ),
        ScpRequest(
            "lambda:GetFunction",
            f"arn:aws:lambda:{REGION}:{ACCOUNT}:function:ledgerguard",
            REGION,
            administrator,
            "desired-policy:test",
        ),
    ]


def test_exact_private_observation_and_nontrivial_scps_are_admitted(tmp_path: Path) -> None:
    path, digest = archive(tmp_path)
    observed = validate(path, digest)
    result = adjudicate_service_control_policies(observed, requests())
    assert result == {
        "classification": "ORGANIZATION_SCP_OBSERVED_AND_ADMITTED",
        "target_to_root_chain_complete": True,
        "attached_policies": 3,
        "explicit_denies_evaluated": 3,
        "required_requests_evaluated": 2,
        "region": REGION,
        "mutating_aws_calls": 0,
        "workload_calls": 0,
        "stage6_complete": False,
    }


@pytest.mark.parametrize(
    ("change", "match"),
    [
        (lambda value: value.update(status="FAILED"), "status"),
        (lambda value: value["source"].update(commit="0" * 40), "source binding"),
        (lambda value: value.update(anchor_preflight_failure_sha256="0" * 64), "anchor"),
        (lambda value: value.update(target_account="000000000000"), "target account"),
        (lambda value: value.update(mutating_aws_calls=1), "prohibited boundary"),
        (lambda value: value.update(completed_epoch=NOW - 86_401), "stale"),
        (lambda value: value["caller_identity"].update(Account="000000000000"), "caller"),
        (lambda value: value.update(target_chain=[ACCOUNT]), "chain"),
        (lambda value: value["attachments"].pop("r-root"), "attachment target"),
        (lambda value: value["attachments"][ACCOUNT].clear(), "non-empty strings"),
        (lambda value: value["policies"][0].update(document_sha256="0" * 64), "digest"),
        (lambda value: value["policies"][0].update(full_access=False), "classification"),
    ],
)
def test_observation_mutations_fail_closed(tmp_path: Path, change, match: str) -> None:
    value = observation()
    change(value)
    path, digest = archive(tmp_path, value)
    with pytest.raises(ValueError, match=match):
        validate(path, digest)


def test_archive_digest_manifest_and_journal_fail_closed(tmp_path: Path) -> None:
    path, digest = archive(tmp_path)
    with pytest.raises(ValueError, match="archive digest"):
        validate(path, "0" * 64)
    assert validate(path, digest)["status"] == "OBSERVED"

    with zipfile.ZipFile(path, "a") as output:
        output.writestr("unbound", b"private")
    changed = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="manifest inventory"):
        validate(path, changed)


def test_archive_envelope_and_argument_shapes_fail_closed(tmp_path: Path) -> None:
    path, digest = archive(tmp_path)
    with pytest.raises(ValueError, match="source commit invalid"):
        validate_observation_archive(
            path,
            archive_sha256=digest,
            source_commit="bad",
            source_tree=SOURCE_TREE,
            anchor_preflight_failure_sha256=ANCHOR,
            now_epoch=NOW,
        )
    with pytest.raises(ValueError, match="missing or unsafe"):
        validate_observation_archive(
            tmp_path / "missing.zip",
            archive_sha256=digest,
            source_commit=SOURCE_COMMIT,
            source_tree=SOURCE_TREE,
            anchor_preflight_failure_sha256=ANCHOR,
            now_epoch=NOW,
        )
    unsafe, unsafe_sha = raw_archive(tmp_path, {"../unsafe": b"x"})
    with pytest.raises(ValueError, match="member is unsafe"):
        validate_observation_archive(
            unsafe,
            archive_sha256=unsafe_sha,
            source_commit=SOURCE_COMMIT,
            source_tree=SOURCE_TREE,
            anchor_preflight_failure_sha256=ANCHOR,
            now_epoch=NOW,
        )
    incomplete, incomplete_sha = raw_archive(tmp_path, {"EVIDENCE-MANIFEST.json": b"{}"})
    with pytest.raises(ValueError, match="required members"):
        validate_observation_archive(
            incomplete,
            archive_sha256=incomplete_sha,
            source_commit=SOURCE_COMMIT,
            source_tree=SOURCE_TREE,
            anchor_preflight_failure_sha256=ANCHOR,
            now_epoch=NOW,
        )


def test_manifest_row_and_container_shapes_fail_closed(tmp_path: Path) -> None:
    observed = observation()
    members = {
        "organizations-observation.json": json.dumps(observed).encode(),
        "api-journal.json": json.dumps(journal(observed)).encode(),
    }
    manifest = {
        name: {"sha256": hashlib.sha256(body).hexdigest(), "size_bytes": len(body)}
        for name, body in members.items()
    }
    manifest["api-journal.json"]["size_bytes"] += 1
    members["EVIDENCE-MANIFEST.json"] = json.dumps(manifest).encode()
    path, digest = raw_archive(tmp_path, members)
    with pytest.raises(ValueError, match="manifest binding"):
        validate(path, digest)

    value = observation()
    value["organization"] = []
    path, digest = archive(tmp_path / "container", value)
    with pytest.raises(ValueError, match="organization must be an object"):
        validate(path, digest)


def test_explicit_deny_condition_and_unsupported_policy_shapes_fail() -> None:
    observed = observation()
    denied = requests()
    denied[1] = ScpRequest(
        denied[1].action,
        denied[1].resource,
        "us-east-1",
        denied[1].principal_arn,
        denied[1].purpose,
    )
    with pytest.raises(ValueError, match="SCP denies required"):
        adjudicate_service_control_policies(observed, denied)

    managed = deepcopy(requests())
    managed[0] = ScpRequest(
        managed[0].action,
        f"arn:aws:iam::{ACCOUNT}:role/managed/Protected",
        managed[0].requested_region,
        managed[0].principal_arn,
        managed[0].purpose,
    )
    with pytest.raises(ValueError, match="SCP denies required"):
        adjudicate_service_control_policies(observed, managed)

    changed = observation()
    changed["policies"][1]["document"]["Statement"][0]["Condition"] = {
        "ArnEquals": {"aws:PrincipalArn": "*"}
    }
    with pytest.raises(ValueError, match="operator"):
        adjudicate_service_control_policies(changed, requests())

    changed = observation()
    changed["policies"][1]["document"]["Statement"][0]["Condition"] = {
        "StringEquals": {"aws:Unknown": "value"}
    }
    with pytest.raises(ValueError, match="key"):
        adjudicate_service_control_policies(changed, requests())


def test_condition_and_selector_semantics_cover_positive_and_negative_forms() -> None:
    request = requests()[0]
    assert scp._condition_matches(None, request) is True
    assert scp._condition_matches(
        {"StringLike": {"aws:PrincipalArn": "arn:aws:iam::*:role/LedgerGuard*"}}, request
    ) is True
    assert scp._condition_matches(
        {"StringLike": {"aws:PrincipalArn": "arn:aws:iam::*:role/Other"}}, request
    ) is False
    assert scp._condition_matches(
        {"StringNotLike": {"aws:PrincipalArn": "arn:aws:iam::*:role/Other"}}, request
    ) is True
    assert scp._selector_matches(
        {"NotResource": "arn:aws:iam::*:role/managed/*"},
        "Resource",
        "NotResource",
        request.resource,
    ) is True
    with pytest.raises(ValueError, match="exactly one"):
        scp._selector_matches({}, "Action", "NotAction", request.action)
    with pytest.raises(ValueError, match="exactly one"):
        scp._selector_matches(
            {"Action": "*", "NotAction": "iam:*"}, "Action", "NotAction", request.action
        )


def test_observation_inventory_policy_and_journal_failures(tmp_path: Path) -> None:
    cases = []
    value = observation()
    value["schema_version"] = "wrong"
    cases.append((value, "schema"))
    value = observation()
    value["completed_epoch"] = True
    cases.append((value, "completion time"))
    value = observation()
    value["organization"].pop("MasterAccountId")
    cases.append((value, "management account"))
    value = observation()
    value["organization"]["AvailablePolicyTypes"] = []
    cases.append((value, "SCP support"))
    value = observation()
    value["attachments"][ACCOUNT] = ["bad id"]
    cases.append((value, "policy identity"))
    value = observation()
    value["policies"] = []
    cases.append((value, "policy inventory is empty"))
    value = observation()
    value["policies"][1]["summary"]["Type"] = "TAG_POLICY"
    cases.append((value, "policy summary"))
    value = observation()
    value["policies"].pop()
    cases.append((value, "described policy inventory"))
    value = observation()
    value["attachments"][ACCOUNT] = ["p-region"]
    cases.append((value, "allow path"))
    for index, (value, match) in enumerate(cases):
        path, digest = archive(tmp_path / str(index), value)
        with pytest.raises(ValueError, match=match):
            validate(path, digest)

    value = observation()
    path, digest = archive(tmp_path / "journal-count", value)
    with zipfile.ZipFile(path, "r") as source:
        members = {name: source.read(name) for name in source.namelist()}
    rows = json.loads(members["api-journal.json"])
    rows.pop()
    members["api-journal.json"] = json.dumps(rows).encode()
    manifest = json.loads(members["EVIDENCE-MANIFEST.json"])
    manifest["api-journal.json"] = {
        "sha256": hashlib.sha256(members["api-journal.json"]).hexdigest(),
        "size_bytes": len(members["api-journal.json"]),
    }
    members["EVIDENCE-MANIFEST.json"] = json.dumps(manifest).encode()
    path, digest = raw_archive(tmp_path / "short", members)
    with pytest.raises(ValueError, match="call inventory"):
        validate(path, digest)


def test_journal_failure_and_operation_order_fail_closed(tmp_path: Path) -> None:
    for label, mutate, match in (
        ("failed", lambda rows: rows[0].update(exit_code=1), "failed or reordered"),
        ("order", lambda rows: rows[0].update(operation="wrong"), "operation inventory"),
    ):
        observed = observation()
        rows = journal(observed)
        mutate(rows)
        members = {
            "organizations-observation.json": json.dumps(observed).encode(),
            "api-journal.json": json.dumps(rows).encode(),
        }
        for row in rows:
            raw_label = f"{row['index']:03d}-{row['service']}-{row['operation']}"
            members[f"raw-aws/{raw_label}.stdout"] = b"{}\n"
            members[f"raw-aws/{raw_label}.stderr"] = b""
        manifest = {
            name: {"sha256": hashlib.sha256(body).hexdigest(), "size_bytes": len(body)}
            for name, body in members.items()
        }
        members["EVIDENCE-MANIFEST.json"] = json.dumps(manifest).encode()
        path, digest = raw_archive(tmp_path / label, members)
        with pytest.raises(ValueError, match=match):
            validate(path, digest)


def test_journal_byte_and_raw_inventory_bindings_fail_closed(tmp_path: Path) -> None:
    for label, alter_row, extra, match in (
        (
            "byte",
            lambda rows: rows[0].update(stdout_sha256="0" * 64),
            False,
            "byte or time binding",
        ),
        ("extra", lambda rows: None, True, "raw API member inventory"),
    ):
        observed = observation()
        rows = journal(observed)
        alter_row(rows)
        members = {
            "organizations-observation.json": json.dumps(observed).encode(),
            "api-journal.json": json.dumps(rows).encode(),
        }
        for row in rows:
            raw_label = f"{row['index']:03d}-{row['service']}-{row['operation']}"
            members[f"raw-aws/{raw_label}.stdout"] = b"{}\n"
            members[f"raw-aws/{raw_label}.stderr"] = b""
        if extra:
            members["raw-aws/unexpected"] = b"private"
        manifest = {
            name: {"sha256": hashlib.sha256(body).hexdigest(), "size_bytes": len(body)}
            for name, body in members.items()
        }
        members["EVIDENCE-MANIFEST.json"] = json.dumps(manifest).encode()
        path, digest = raw_archive(tmp_path / label, members)
        with pytest.raises(ValueError, match=match):
            validate(path, digest)


def test_aggregate_full_access_classification_is_bound(tmp_path: Path) -> None:
    value = observation()
    value["all_attached_scps_full_access"] = True
    path, digest = archive(tmp_path, value)
    with pytest.raises(ValueError, match="aggregate full-access"):
        validate(path, digest)


def test_scp_policy_language_drift_is_rejected() -> None:
    assert scp._full_access(None) is False
    changes = []
    value = observation()
    value["policies"] = []
    changes.append((value, "policy inventory is empty"))
    value = observation()
    value["policies"][0]["document"]["Version"] = "2008-10-17"
    changes.append((value, "policy version"))
    value = observation()
    value["policies"][0]["document"]["Statement"] = []
    changes.append((value, "statement inventory"))
    value = observation()
    value["policies"][0]["document"]["Statement"][0]["Action"] = "s3:*"
    changes.append((value, "non-full-access"))
    value = observation()
    value["policies"][1]["document"]["Statement"][0]["Effect"] = "Maybe"
    changes.append((value, "effect"))
    value = observation()
    value["policies"][1]["document"]["Statement"][0]["Principal"] = "*"
    changes.append((value, "unsupported fields"))
    for changed, match in changes:
        with pytest.raises(ValueError, match=match):
            adjudicate_service_control_policies(changed, requests())


def packet() -> dict[str, Any]:
    role_arns = {
        f"arn:aws:iam::{ACCOUNT}:role/LedgerGuardGitHubOidcRole",
        f"arn:aws:iam::{ACCOUNT}:role/LedgerGuardPart3ReadOnlyRole",
        f"arn:aws:iam::{ACCOUNT}:role/LedgerGuardPart3RecoveryRole",
    }
    policy_arns = {
        f"arn:aws:iam::{ACCOUNT}:policy/LedgerGuardPart3-{index}" for index in range(7)
    }
    policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": ["s3:GetObject", "s3:ListBucket"],
                "Resource": ["arn:aws:s3:::ledgerguard-test", "arn:aws:s3:::ledgerguard-test/*"],
            }
        ],
    }
    return {
        "documents": {
            "administrator": {
                "backend": {
                    "bucket": "ledgerguard-test",
                    "kms_key_id": (
                        f"arn:aws:kms:{REGION}:{ACCOUNT}:key/"
                        "00000000-0000-0000-0000-000000000000"
                    ),
                }
            },
            "identity_contract": {
                "roles": {arn: {"role_name": arn.rsplit("/", 1)[-1]} for arn in role_arns},
                "policies": {arn: deepcopy(policy) for arn in policy_arns},
            },
            "runtime_policies": {
                role: deepcopy(policy) for role in ("glue", "workflow", "validator", "controller")
            },
            "runtime_boundaries": {
                role: deepcopy(policy) for role in ("glue", "workflow", "validator", "controller")
            },
        }
    }


def test_successor_request_inventory_is_exact_and_scp_compatible() -> None:
    result = successor_required_requests(packet())
    assert len(result) == len(set(result))
    assert len(result) >= 50
    assert {row.requested_region for row in result} == {REGION, "us-east-1"}
    assert adjudicate_service_control_policies(observation(), result)[
        "required_requests_evaluated"
    ] == len(result)


def test_successor_request_inventory_rejects_shape_drift() -> None:
    changed = packet()
    changed["documents"]["identity_contract"]["roles"].popitem()
    with pytest.raises(ValueError, match="role or policy inventory"):
        successor_required_requests(changed)
    changed = packet()
    changed["documents"]["runtime_boundaries"].pop("glue")
    with pytest.raises(ValueError, match="runtime boundary inventory"):
        successor_required_requests(changed)
    changed = packet()
    first = next(iter(changed["documents"]["identity_contract"]["policies"].values()))
    first["Statement"][0]["NotAction"] = first["Statement"][0].pop("Action")
    with pytest.raises(ValueError, match="negative selector"):
        successor_required_requests(changed)
    changed = packet()
    changed["documents"]["administrator"]["backend"]["kms_key_id"] = "wrong"
    with pytest.raises(ValueError, match="backend identity"):
        successor_required_requests(changed)
    changed = packet()
    first = next(iter(changed["documents"]["identity_contract"]["policies"].values()))
    first["Statement"] = "wrong"
    with pytest.raises(ValueError, match="statement inventory"):
        successor_required_requests(changed)
    changed = packet()
    first = next(iter(changed["documents"]["identity_contract"]["policies"].values()))
    first["Statement"].append({"Effect": "Deny", "Action": "*", "Resource": "*"})
    assert len(successor_required_requests(changed)) >= 50


def test_successor_request_inventory_minimum_is_enforced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixed = ScpRequest(
        "iam:GetRole",
        "*",
        "us-east-1",
        f"arn:aws:iam::{ACCOUNT}:role/Admin",
        "fixed",
    )
    monkeypatch.setattr(scp, "_request", lambda *args: fixed)
    with pytest.raises(ValueError, match="unexpectedly small"):
        successor_required_requests(packet())


def test_request_inventory_and_shapes_fail_closed() -> None:
    with pytest.raises(ValueError, match="empty or duplicated"):
        adjudicate_service_control_policies(observation(), requests() * 2)
    changed = requests()
    changed[0] = ScpRequest(
        "invalid",
        changed[0].resource,
        changed[0].requested_region,
        changed[0].principal_arn,
        changed[0].purpose,
    )
    with pytest.raises(ValueError, match="request shape"):
        adjudicate_service_control_policies(observation(), changed)


def test_private_cli_binds_sources_inputs_and_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    observed_path, observed_sha = archive(tmp_path)
    successor = packet()
    successor.update(
        classification="PRIVATE_DESIRED_NOT_INSTALLED_NOT_EFFECTIVELY_VERIFIED",
        stage6_source={"commit": "d" * 40, "tree": "e" * 40},
    )
    successor_path = tmp_path / "successor.json"
    successor_path.write_text(json.dumps(successor))
    output = tmp_path / "adjudication.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "adjudicate",
            "--observation",
            str(observed_path),
            "--observation-sha256",
            observed_sha,
            "--observation-source-commit",
            SOURCE_COMMIT,
            "--observation-source-tree",
            SOURCE_TREE,
            "--preflight-anchor-sha256",
            ANCHOR,
            "--successor-packet",
            str(successor_path),
            "--source-commit",
            "d" * 40,
            "--source-tree",
            "e" * 40,
            "--output",
            str(output),
        ],
    )
    monkeypatch.setattr(
        "tools.part3_stage6.organization_scp.time.time", lambda: float(NOW)
    )
    command.main()
    receipt = json.loads(output.read_text())
    assert receipt["source"] == {"commit": "d" * 40, "tree": "e" * 40}
    assert receipt["bindings"]["observation_sha256"] == observed_sha
    assert receipt["adjudication"]["classification"] == (
        "ORGANIZATION_SCP_OBSERVED_AND_ADMITTED"
    )
    with pytest.raises(ValueError, match="already exists"):
        command.main()
