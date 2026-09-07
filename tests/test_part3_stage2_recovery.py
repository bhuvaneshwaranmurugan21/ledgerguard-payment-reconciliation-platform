from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from ledgerguard.stage2.control import Stage2Rejected
from tools.part3_stage2_runtime import (
    _capability_case,
    _inventory_checks,
    _prepare_output,
    _root,
    run_read_only,
    run_recovery,
)

ROOT = Path(__file__).resolve().parents[1]


class StatefulAws:
    def __init__(self) -> None:
        self.region = "ap-southeast-2"
        self.journal: list[dict[str, Any]] = []
        self.items: dict[str, dict[str, Any]] = {}
        self.versions: dict[tuple[str, str], str] = {}
        self.jobs: dict[str, dict[str, Any]] = {}

    def invoke(self, operation: str, arguments: list[str] | None = None) -> dict[str, Any]:
        args = list(arguments or [])
        self.journal.append({"operation": operation})

        def value(flag: str) -> str:
            return args[args.index(flag) + 1]

        if operation == "DDB_PUT_ITEM":
            item = json.loads(value("--item"))
            key = item["lease_key"]["S"]
            if key in self.items and "attribute_not_exists" in value("--condition-expression"):
                now = int(json.loads(value("--expression-attribute-values"))[":now"]["N"])
                requested_owner = json.loads(value("--expression-attribute-values"))[":owner"]["S"]
                if (
                    int(self.items[key]["expires_epoch"]["N"]) >= now
                    and self.items[key]["owner"]["S"] != requested_owner
                ):
                    raise Stage2Rejected("ConditionalCheckFailedException")
            if key in self.items and value("--condition-expression") == "#o = :owner":
                owner = json.loads(value("--expression-attribute-values"))[":owner"]["S"]
                if self.items[key]["owner"]["S"] != owner:
                    raise Stage2Rejected("ConditionalCheckFailedException")
            self.items[key] = item
            return {}
        if operation == "DDB_DELETE_ITEM":
            key = json.loads(value("--key"))["lease_key"]["S"]
            wanted = json.loads(value("--expression-attribute-values"))[":owner"]["S"]
            if key not in self.items or self.items[key]["owner"]["S"] != wanted:
                raise Stage2Rejected("ConditionalCheckFailedException")
            del self.items[key]
            return {}
        if operation == "DDB_GET_ITEM":
            key = json.loads(value("--key"))["lease_key"]["S"]
            return {"Item": self.items[key]} if key in self.items else {}
        if operation == "S3_PUT_OBJECT":
            key = value("--key")
            version = f"v{len(self.versions) + 1}"
            self.versions[(key, version)] = value("--body")
            result = {"VersionId": version}
            if "--metadata" in args:
                result["metadata"] = value("--metadata")
            return result
        if operation == "S3_HEAD_OBJECT":
            key = value("--key")
            body = next(body for (item, _), body in self.versions.items() if item == key)
            digest = Path(body).read_bytes()
            import hashlib

            return {
                "Metadata": {"sha256": hashlib.sha256(digest).hexdigest()},
                "ServerSideEncryption": "aws:kms",
            }
        if operation == "S3_GET_OBJECT":
            key = value("--key")
            version = value("--version-id")
            Path(args[-1]).write_bytes(Path(self.versions[(key, version)]).read_bytes())
            return {}
        if operation == "S3_DELETE_OBJECT":
            self.versions.pop((value("--key"), value("--version-id")), None)
            return {}
        if operation == "S3_LIST_VERSIONS":
            prefix = value("--prefix")
            return {
                "Versions": [
                    {"Key": key, "VersionId": version}
                    for key, version in self.versions
                    if key.startswith(prefix)
                ],
                "DeleteMarkers": [],
            }
        if operation == "GLUE_CREATE_JOB":
            definition = json.loads(value("--cli-input-json"))
            self.jobs[definition["Name"]] = definition
            return {"Name": definition["Name"]}
        if operation == "GLUE_GET_JOB":
            name = value("--job-name")
            if name not in self.jobs:
                raise Stage2Rejected("EntityNotFoundException")
            return {"Job": dict(self.jobs[name])}
        if operation == "GLUE_GET_JOB_RUNS":
            return {"JobRuns": []}
        if operation == "GLUE_GET_TAGS":
            name = value("--resource-arn").rsplit("/", 1)[1]
            return {"Tags": self.jobs[name]["Tags"]}
        if operation == "GLUE_DELETE_JOB":
            del self.jobs[value("--job-name")]
            return {}
        if operation == "STS_GET_CALLER_IDENTITY":
            return {
                "Account": "857229544428",
                "Arn": (
                    "arn:aws:sts::857229544428:assumed-role/LedgerGuardGitHubOidcRole/recovery"
                ),
            }
        raise AssertionError(operation)

    def write_journal(self, path: Path) -> None:
        path.write_text(json.dumps(self.journal) + "\n")

    def version(self) -> dict[str, str]:
        return {"aws_cli": "2.36.40"}


@pytest.mark.parametrize("case", ["after_s3", "after_lease", "after_glue", "normal"])
def test_real_capability_cleanup_path_removes_all_state(
    monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    monkeypatch.setenv("GITHUB_RUN_ID", "12345")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    cli = StatefulAws()
    result = _capability_case(cli, ROOT, "a" * 40, case, "correlation")
    assert result["cleanup_complete"] is True
    assert result["expected_fault"] is (case != "normal")
    assert cli.items == {} and cli.versions == {} and cli.jobs == {}


def test_unexpected_api_failure_is_not_reclassified_as_expected_fault(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_RUN_ID", "12345")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")

    class Broken(StatefulAws):
        def invoke(self, operation: str, arguments: list[str] | None = None) -> dict[str, Any]:
            if operation == "S3_HEAD_OBJECT":
                raise Stage2Rejected("AccessDenied")
            return super().invoke(operation, arguments)

    cli = Broken()
    with pytest.raises(Stage2Rejected, match="AccessDenied"):
        _capability_case(cli, ROOT, "a" * 40, "after_s3", "correlation")
    assert cli.items == {} and cli.versions == {}


def test_runtime_root_and_output_admission_are_exact(tmp_path: Path) -> None:
    assert _root() == ROOT
    output = tmp_path / "artifact"
    output.mkdir()
    (output / "dispatch-context.json").write_text("{}\n")
    _prepare_output(output)
    (output / "evidence.json").write_text("{}\n")
    with pytest.raises(Stage2Rejected, match=r"already contains evidence\.json"):
        _prepare_output(output)
    (output / "evidence.json").unlink()
    (output / "mutation-journal.json").write_text("[]\n")
    with pytest.raises(Stage2Rejected, match=r"already contains mutation-journal\.json"):
        _prepare_output(output)


def test_read_only_contract_rejection_records_bootstrap_verdict(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    sha_value = "a" * 40
    monkeypatch.setenv(
        "GITHUB_REPOSITORY",
        "bhuvaneshwaranmurugan21/ledgerguard-payment-reconciliation-platform",
    )
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    monkeypatch.setenv("GITHUB_REF", "refs/heads/main")
    monkeypatch.setenv("GITHUB_SHA", sha_value)
    monkeypatch.setenv("CHECKED_OUT_SHA", sha_value)
    monkeypatch.setenv("GITHUB_RUN_ID", "12345")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")

    class MissingBackend(StatefulAws):
        def invoke(self, operation: str, arguments: list[str] | None = None) -> dict[str, Any]:
            raise Stage2Rejected("NoSuchBucket")

    monkeypatch.setattr("tools.part3_stage2_runtime.AwsCli", lambda region: MissingBackend())
    output = tmp_path / "read-only"
    with pytest.raises(Stage2Rejected, match="NoSuchBucket"):
        run_read_only(sha_value, output)
    evidence = json.loads((output / "evidence.json").read_text())
    assert evidence["checks"]["state"] == "FAILED"
    assert evidence["checks"]["verdict"] == "BLOCKED_BOOTSTRAP_REQUIRED"


def test_recovery_validates_identity_and_removes_only_exact_failed_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    sha_value = "a" * 40
    failed_run_id = "12345"
    cli = StatefulAws()
    key = f"qualification/{sha_value}/{failed_run_id}/1/normal/payload.txt"
    cli.versions[(key, "v1")] = str(ROOT / "README.md")
    item_key = f"ledgerguard/part3/stage2/{sha_value}/{failed_run_id}/1/normal/test"
    cli.items[item_key] = {
        "lease_key": {"S": item_key},
        "owner": {"S": "owner"},
        "commit": {"S": sha_value},
        "run_id": {"S": failed_run_id},
        "run_attempt": {"S": "1"},
    }
    guard_key = "ledgerguard/part3/stage2/qualification"
    cli.items[guard_key] = {
        "lease_key": {"S": guard_key},
        "owner": {"S": "guard-owner"},
        "commit": {"S": sha_value},
        "run_id": {"S": failed_run_id},
        "run_attempt": {"S": "1"},
    }
    cli.jobs[f"ledgerguard-stage2-{failed_run_id}-1-normal"] = {"Name": "recovery-residue"}
    monkeypatch.setattr("tools.part3_stage2_runtime.AwsCli", lambda region: cli)
    monkeypatch.setenv(
        "GITHUB_REPOSITORY",
        "bhuvaneshwaranmurugan21/ledgerguard-payment-reconciliation-platform",
    )
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    monkeypatch.setenv("GITHUB_REF", "refs/heads/main")
    monkeypatch.setenv("GITHUB_SHA", sha_value)
    monkeypatch.setenv("CHECKED_OUT_SHA", sha_value)
    monkeypatch.setenv("GITHUB_RUN_ID", "54321")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    result = run_recovery(
        sha_value,
        failed_run_id,
        "1",
        "999",
        "b" * 64,
        tmp_path / "recovery",
    )
    assert result["checks"]["state"] == "PASSED"
    assert result["identity"]["identity_fingerprint"] != "0" * 64
    assert result["checks"]["removed"] == {
        "s3_versions": 1,
        "lease_items": 2,
        "glue_jobs": 1,
    }
    assert cli.items == {} and cli.versions == {} and cli.jobs == {}


class InventoryAws:
    def __init__(self, change: str | None = None) -> None:
        self.change = change

    def invoke(self, operation: str, arguments: list[str] | None = None) -> dict[str, Any]:
        responses: dict[str, dict[str, Any]] = {
            "S3_LIST_BUCKETS": {"Buckets": [{"Name": "shared"}]},
            "DDB_LIST_TABLES": {"TableNames": ["shared-table"]},
            "GLUE_GET_JOBS": {"Jobs": []},
            "SFN_LIST": {"stateMachines": []},
            "LOGS_DESCRIBE_GROUPS": {"logGroups": []},
            "TAG_GET_RESOURCES": {"ResourceTagMappingList": []},
            "S3_LIST_VERSIONS": {"Versions": [], "DeleteMarkers": [], "IsTruncated": False},
            "DDB_SCAN": {"Items": []},
        }
        if self.change == "s3":
            responses["S3_LIST_VERSIONS"]["Versions"] = [{"Key": "qualification/x"}]
        elif self.change == "lease":
            responses["DDB_SCAN"]["Items"] = [{"lease_key": {"S": "namespace/x"}}]
        elif self.change == "glue":
            responses["GLUE_GET_JOBS"]["Jobs"] = [{"Name": "ledgerguard-stage2-residue"}]
        elif self.change == "workload":
            responses["DDB_LIST_TABLES"]["TableNames"] = ["ledgerguard-business"]
        elif self.change == "truncated":
            responses["S3_LIST_VERSIONS"]["IsTruncated"] = True
        return responses[operation]


def test_complete_service_inventory_accepts_clean_control_plane() -> None:
    inventory = json.loads((ROOT / "contracts/part3-stage2-inventory-v1.json").read_text())
    control = json.loads((ROOT / "contracts/part3-stage2-control-plane-v1.json").read_text())
    result = _inventory_checks(InventoryAws(), inventory, control)  # type: ignore[arg-type]
    assert result["clean"] is True and result["counts"]["probe_residue"] == 0


def test_recovery_refuses_foreign_global_guard(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    sha_value = "a" * 40
    cli = StatefulAws()
    guard_key = "ledgerguard/part3/stage2/qualification"
    cli.items[guard_key] = {
        "lease_key": {"S": guard_key},
        "owner": {"S": "foreign"},
        "commit": {"S": sha_value},
        "run_id": {"S": "other"},
        "run_attempt": {"S": "1"},
    }
    monkeypatch.setattr("tools.part3_stage2_runtime.AwsCli", lambda region: cli)
    for key, value in {
        "GITHUB_REPOSITORY": "bhuvaneshwaranmurugan21/ledgerguard-payment-reconciliation-platform",
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_SHA": sha_value,
        "CHECKED_OUT_SHA": sha_value,
        "GITHUB_RUN_ID": "54321",
        "GITHUB_RUN_ATTEMPT": "1",
    }.items():
        monkeypatch.setenv(key, value)
    with pytest.raises(Stage2Rejected, match="recovery guard identity differs"):
        run_recovery(sha_value, "12345", "1", "999", "b" * 64, tmp_path / "recovery")
    assert guard_key in cli.items


@pytest.mark.parametrize("change", ["s3", "lease", "glue", "workload", "truncated"])
def test_service_inventory_rejects_residue_workload_or_partial_listing(change: str) -> None:
    inventory = json.loads((ROOT / "contracts/part3-stage2-inventory-v1.json").read_text())
    control = json.loads((ROOT / "contracts/part3-stage2-control-plane-v1.json").read_text())
    with pytest.raises(Stage2Rejected):
        _inventory_checks(InventoryAws(change), inventory, control)  # type: ignore[arg-type]
