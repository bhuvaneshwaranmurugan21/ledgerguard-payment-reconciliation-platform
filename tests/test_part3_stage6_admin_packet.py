from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

import tools.part3_stage6.admin_packet as packet
from tools.part3_stage4.iam import runtime_policies

KEY = "arn:aws:kms:ap-southeast-2:857229544428:key/11111111-2222-3333-4444-555555555555"


def module() -> dict[str, Any]:
    return {
        "locals": {
            "log_names": {
                "glue_error": "/${local.name}/glue/error",
                "glue_output": "/${local.name}/glue/output",
                "workflow": "/aws/vendedlogs/states/${local.name}",
                "validator": "/aws/lambda/${local.name}-validator",
                "controller": "/aws/lambda/${local.name}-controller",
            },
            "runtime_statements": {
                role: [] for role in ("glue", "workflow", "validator", "controller")
            },
            "role_log_keys": {
                "glue": ["glue_error", "glue_output"],
                "workflow": ["workflow"],
                "validator": ["validator"],
                "controller": ["controller"],
            },
        }
    }


def release(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[dict[str, Any], Path]:
    directory = tmp_path / "release"
    directory.mkdir(parents=True)
    members = {
        "runtime.zip": b"runtime",
        "ledgerguard_stage5_job.py": b"script",
        "ledgerguard.gluewheels.zip": b"wheels",
    }
    digests = {}
    for name, data in members.items():
        (directory / name).write_bytes(data)
        digests[name] = hashlib.sha256(data).hexdigest()
    definition = json.dumps({"TimeoutSeconds": 1800}, separators=(",", ":"))
    handler = json.dumps({"operation_id": "release-qual1"}, separators=(",", ":"))
    value = {
        "schema_version": "ledgerguard.stage5-terraform-release.v1",
        "source_commit": "a" * 40,
        "source_tree": "b" * 40,
        "definition": definition,
        "definition_sha256": hashlib.sha256(definition.encode()).hexdigest(),
        "runtime_package_sha256": digests["runtime.zip"],
        "handler_config": handler,
        "handler_config_sha256": hashlib.sha256(handler.encode()).hexdigest(),
        "manifest_sha256": "c" * 64,
        "script_sha256": digests["ledgerguard_stage5_job.py"],
        "wheels_sha256": digests["ledgerguard.gluewheels.zip"],
    }
    value["script_key"] = f"deployment/{value['script_sha256']}/ledgerguard_stage5_job.py"
    value["wheels_key"] = f"deployment/{value['wheels_sha256']}/ledgerguard.gluewheels.zip"
    monkeypatch.setattr(
        packet, "EXPECTED_STAGE5", {key: value[key] for key in packet.EXPECTED_STAGE5}
    )
    return value, directory


def trust() -> dict[str, Any]:
    return {
        "policy": {
            "Version": "2012-10-17",
            "Statement": [{"Effect": "Allow", "Action": "sts:AssumeRoleWithWebIdentity"}],
        },
        "maximum_session_duration_seconds": 3600,
    }


def build(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    value, directory = release(tmp_path, monkeypatch)
    return packet.compose_successor_packet(
        provider={"statements": []},
        module=module(),
        trust=trust(),
        release=value,
        release_dir=directory,
        backend_kms_key_arn=KEY,
        source_commit="d" * 40,
        source_tree="e" * 40,
    )


def test_packet_is_private_offline_and_stage5_bound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = build(tmp_path, monkeypatch)
    assert result["classification"] == "PRIVATE_DESIRED_NOT_INSTALLED_NOT_EFFECTIVELY_VERIFIED"
    assert result["installation"] == {
        "performed": False,
        "executor_self_remediation": False,
        "requires_separate_administrator": True,
        "requires_pre_change_snapshot": True,
        "requires_rollback_journal": True,
        "requires_post_change_exact_parity": True,
        "requires_effective_permission_probe": True,
        "requires_restriction_adjudication": True,
    }
    assert result["safety"] == {"roles": 4, "workload_start_allows": 0, "required_denies": 16}
    assert result["aws_calls"] == 0
    assert result["stage6_complete"] is False
    assert set(result["document_sha256"]) == set(result["documents"])


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        ("source_commit", "release identity"),
        ("definition_sha256", "release identity"),
        ("handler_config_sha256", "release identity"),
        ("script_sha256", "release identity"),
    ],
)
def test_release_identity_mutations_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str, match: str
) -> None:
    value, directory = release(tmp_path, monkeypatch)
    value[mutation] = "0" * len(str(value[mutation]))
    with pytest.raises(ValueError, match=match):
        packet.validate_release(value, directory)


def test_release_bytes_and_operation_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    value, directory = release(tmp_path, monkeypatch)
    (directory / "runtime.zip").write_bytes(b"changed")
    with pytest.raises(ValueError, match="member digest"):
        packet.validate_release(value, directory)
    (directory / "runtime.zip").write_bytes(b"runtime")
    value["handler_config"] = json.dumps({"operation_id": "other-operation"})
    with pytest.raises(ValueError, match="operation identity"):
        packet.validate_release(value, directory)


def test_runtime_policy_accepts_only_frozen_script_generations() -> None:
    objects = {
        "script_key": "deployment/" + "a" * 64 + "/ledgerguard_stage5_job.py",
        "wheels_key": "deployment/" + "b" * 64 + "/ledgerguard.gluewheels.zip",
    }
    result = runtime_policies(
        module(), "release-qual1", objects, script_basename="ledgerguard_stage5_job.py"
    )
    assert set(result) == {"glue", "workflow", "validator", "controller"}
    with pytest.raises(ValueError, match="basename"):
        runtime_policies(module(), "release-qual1", objects, script_basename="arbitrary.py")


def test_runtime_workload_allow_and_missing_deny_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = build(tmp_path, monkeypatch)
    policies = result["documents"]["runtime_policies"]
    boundaries = result["documents"]["runtime_boundaries"]
    policies["glue"]["Statement"].append(
        {"Sid": "Bad", "Effect": "Allow", "Action": ["glue:StartJobRun"], "Resource": "*"}
    )
    with pytest.raises(ValueError, match="start a workload"):
        packet.validate_runtime_boundaries(policies, boundaries)
    policies["glue"]["Statement"].pop()
    boundaries["glue"]["Statement"] = [
        row for row in boundaries["glue"]["Statement"] if row.get("Sid") != "NoIdentityChaining"
    ]
    with pytest.raises(ValueError, match="deny inventory"):
        packet.validate_runtime_boundaries(policies, boundaries)


def test_remaining_release_and_packet_boundaries_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    value, directory = release(tmp_path, monkeypatch)
    value["schema_version"] = "wrong"
    with pytest.raises(ValueError, match="schema"):
        packet.validate_release(value, directory)
    value["schema_version"] = "ledgerguard.stage5-terraform-release.v1"
    value["definition"] = "changed"
    with pytest.raises(ValueError, match="definition bytes"):
        packet.validate_release(value, directory)
    value, directory = release(tmp_path / "second", monkeypatch)
    value["handler_config"] = json.dumps({"operation_id": "release-qual1", "changed": True})
    with pytest.raises(ValueError, match="handler configuration"):
        packet.validate_release(value, directory)
    value, directory = release(tmp_path / "third", monkeypatch)
    (directory / "runtime.zip").unlink()
    with pytest.raises(ValueError, match="missing or unsafe"):
        packet.validate_release(value, directory)
    value, directory = release(tmp_path / "fourth", monkeypatch)
    with pytest.raises(ValueError, match="source identity"):
        packet.compose_successor_packet(
            provider={"statements": []},
            module=module(),
            trust=trust(),
            release=value,
            release_dir=directory,
            backend_kms_key_arn=KEY,
            source_commit="bad",
            source_tree="e" * 40,
        )


def test_runtime_boundary_role_and_action_shapes_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = build(tmp_path, monkeypatch)
    policies = result["documents"]["runtime_policies"]
    boundaries = result["documents"]["runtime_boundaries"]
    removed = policies.pop("glue")
    with pytest.raises(ValueError, match="role inventory"):
        packet.validate_runtime_boundaries(policies, boundaries)
    policies["glue"] = removed
    policies["glue"]["Statement"].append(
        {"Sid": "StringAllow", "Effect": "Allow", "Action": "glue:StartJobRun", "Resource": "*"}
    )
    with pytest.raises(ValueError, match="start a workload"):
        packet.validate_runtime_boundaries(policies, boundaries)
    policies["glue"]["Statement"].pop()
    deny = next(
        row for row in boundaries["glue"]["Statement"] if row.get("Sid") == "NoPart3WorkloadStart"
    )
    deny["Action"] = ["states:StartExecution"]
    with pytest.raises(ValueError, match="workload-start deny"):
        packet.validate_runtime_boundaries(policies, boundaries)
