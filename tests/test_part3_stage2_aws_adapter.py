from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ledgerguard.stage2.aws_cli import AwsCli
from ledgerguard.stage2.control import Stage2Rejected


def test_adapter_invokes_only_allowlisted_command_and_records_digest(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls = []

    def run(command: list[str], **kwargs: object) -> SimpleNamespace:
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout='{"Account":"857229544428"}', stderr="")

    monkeypatch.setattr("subprocess.run", run)
    cli = AwsCli("ap-southeast-2")
    assert cli.invoke("STS_GET_CALLER_IDENTITY")["Account"] == "857229544428"
    assert calls[0][0] == [
        "aws",
        "sts",
        "get-caller-identity",
        "--region",
        "ap-southeast-2",
        "--output",
        "json",
        "--no-cli-pager",
    ]
    assert (
        cli.journal[0]["operation"] == "STS_GET_CALLER_IDENTITY"
        and len(cli.journal[0]["response_sha256"]) == 64
    )
    cli.write_journal(tmp_path / "journal.json")
    assert json.loads((tmp_path / "journal.json").read_text())[0]["returncode"] == 0


@pytest.mark.parametrize("operation,args", [("UNKNOWN", []), ("GLUE_GET_JOB", ["start-job-run"])])
def test_adapter_rejects_unknown_or_forbidden_operation_before_process(
    monkeypatch: pytest.MonkeyPatch, operation: str, args: list[str]
) -> None:
    monkeypatch.setattr(
        "subprocess.run",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("process must not run")),
    )
    with pytest.raises(Stage2Rejected):
        AwsCli("ap-southeast-2").invoke(operation, args)


def test_adapter_sanitizes_failed_aws_response(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "subprocess.run",
        lambda *a, **k: SimpleNamespace(
            returncode=254, stdout="", stderr="denied for 857229544428 AKIAABCDEFGHIJKLMNOP"
        ),
    )
    cli = AwsCli("ap-southeast-2")
    with pytest.raises(Stage2Rejected, match="<ACCOUNT>"):
        cli.invoke("STS_GET_CALLER_IDENTITY")
    assert "857229544428" not in cli.journal[0]["error"] and "AKIA" not in cli.journal[0]["error"]


def test_adapter_rejects_non_json_or_non_object(monkeypatch: pytest.MonkeyPatch) -> None:
    cli = AwsCli("ap-southeast-2")
    monkeypatch.setattr(
        "subprocess.run",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout="not-json", stderr=""),
    )
    with pytest.raises(Stage2Rejected, match="non-JSON"):
        cli.invoke("STS_GET_CALLER_IDENTITY")
    monkeypatch.setattr(
        "subprocess.run", lambda *a, **k: SimpleNamespace(returncode=0, stdout="[]", stderr="")
    )
    with pytest.raises(Stage2Rejected, match="object response"):
        cli.invoke("STS_GET_CALLER_IDENTITY")


@pytest.mark.parametrize("version,accepted", [("2.36.40", True), ("1.42.0", False)])
def test_adapter_requires_and_captures_aws_cli_v2(
    monkeypatch: pytest.MonkeyPatch, version: str, accepted: bool
) -> None:
    monkeypatch.setattr(
        "subprocess.run",
        lambda *a, **k: SimpleNamespace(
            returncode=0, stdout=f"aws-cli/{version} Python/3.13 Linux/6 botocore/2\n", stderr=""
        ),
    )
    cli = AwsCli("ap-southeast-2")
    if accepted:
        assert cli.version() == {"aws_cli": version}
    else:
        with pytest.raises(Stage2Rejected, match="AWS CLI v2 required"):
            cli.version()


def test_global_billing_operations_use_required_endpoint_region(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[list[str]] = []

    def run(command: list[str], **kwargs: object) -> SimpleNamespace:
        commands.append(command)
        return SimpleNamespace(returncode=0, stdout="{}", stderr="")

    monkeypatch.setattr("subprocess.run", run)
    AwsCli("ap-southeast-2").invoke("CE_GET_COST")
    assert commands[0][commands[0].index("--region") + 1] == "us-east-1"
