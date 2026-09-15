from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

import tools.part3_stage6.terraform as terraform
from tools.part3_stage6.terraform import (
    PlanSession,
    backend_arguments,
    terraform_variables,
    validate_command,
)


def release(tmp_path: Path) -> tuple[dict[str, Any], Path]:
    directory = tmp_path / "release"
    directory.mkdir()
    (directory / "runtime.zip").write_bytes(b"runtime")
    value = {
        "schema_version": "ledgerguard.stage5-terraform-release.v1",
        "validator_zip": "runtime.zip",
        "controller_zip": "runtime.zip",
        "definition": "{}",
    }
    return value, directory


def test_variables_use_real_release_files_and_exact_boundaries(tmp_path: Path) -> None:
    value, directory = release(tmp_path)
    result = terraform_variables(
        value,
        directory,
        operation_id="release-qual1",
        expires_at="2026-09-16T00:00:00Z",
    )
    assert result["stage5_release"]["validator_zip"] == str((directory / "runtime.zip").resolve())
    assert set(result["permissions_boundary_arns"]) == {
        "glue",
        "workflow",
        "validator",
        "controller",
    }
    assert "schema_version" not in result["stage5_release"]


@pytest.mark.parametrize(
    "command",
    [
        ["terraform", "apply"],
        ["terraform", "plan", "-target=x"],
        ["terraform", "plan", "-refresh=false"],
        ["terraform", "plan", "-lock=false"],
        ["terraform", "force-unlock"],
        ["sh", "-c", "terraform plan"],
    ],
)
def test_command_boundary_rejects_non_plan_only_forms(command: list[str]) -> None:
    with pytest.raises(ValueError):
        validate_command(command)


def test_backend_is_exact_and_rejects_other_operation() -> None:
    key = "arn:aws:kms:ap-southeast-2:857229544428:key/11111111-2222-3333-4444-555555555555"
    args = backend_arguments(kms_key_arn=key, operation_id="release-qual1")
    assert "-backend-config=use_lockfile=true" in args
    assert "release-qual1/terraform.tfstate" in " ".join(args)
    with pytest.raises(ValueError, match="operation identity"):
        backend_arguments(kms_key_arn=key, operation_id="another-op")


def test_session_uses_same_saved_binary_for_show(tmp_path: Path) -> None:
    infra = tmp_path / "infra"
    infra.mkdir()
    work = tmp_path / "private"
    observed: list[list[str]] = []
    plan_json = json.dumps({"format_version": "1.2"}).encode()

    def run(command: list[str], cwd: Path) -> subprocess.CompletedProcess[bytes]:
        assert cwd == infra
        observed.append(command)
        if command[1] == "version":
            stdout, code = json.dumps({"terraform_version": "1.13.1"}).encode(), 0
        elif command[1] == "validate":
            stdout, code = json.dumps({"valid": True, "error_count": 0}).encode(), 0
        elif command[1] == "plan":
            Path(next(token[5:] for token in command if token.startswith("-out="))).write_bytes(
                b"binary"
            )
            stdout, code = b"created", 2
        elif command[1] == "show":
            stdout, code = plan_json, 0
        else:
            stdout, code = b"{}", 0
        return subprocess.CompletedProcess(command, code, stdout=stdout, stderr=b"")

    session = PlanSession(infra, work, run)
    plan, digests = session.execute(variables={"x": 1}, backend=["-backend-config=x=y"])
    saved = work / "stage6.tfplan"
    assert observed[-1] == ["terraform", "show", "-json", str(saved)]
    assert plan == {"format_version": "1.2"}
    assert digests["binary_sha256"] == hashlib.sha256(b"binary").hexdigest()
    assert [row["operation"] for row in session.journal] == [
        "terraform-version",
        "terraform-init",
        "terraform-validate",
        "terraform-plan",
        "terraform-show",
    ]
    assert all(row["command"] != ["terraform", "apply"] for row in session.journal)
    init = next(command for command in observed if command[1] == "init")
    assert "-lockfile=readonly" in init


def test_session_rejects_zero_change_plan_and_existing_output(tmp_path: Path) -> None:
    infra = tmp_path / "infra"
    infra.mkdir()
    work = tmp_path / "private"
    work.mkdir()
    session = PlanSession(infra, work)
    with pytest.raises(ValueError, match="new private"):
        session.execute(variables={}, backend=[])


def test_variable_and_backend_input_failures(tmp_path: Path) -> None:
    value, directory = release(tmp_path)
    with pytest.raises(ValueError, match="operation identity"):
        terraform_variables(
            value, directory, operation_id="wrong-operation", expires_at="2026-09-16T00:00:00Z"
        )
    with pytest.raises(ValueError, match="canonical UTC"):
        terraform_variables(value, directory, operation_id="release-qual1", expires_at="tomorrow")
    changed = dict(value)
    changed["schema_version"] = "wrong"
    with pytest.raises(ValueError, match="schema"):
        terraform_variables(
            changed, directory, operation_id="release-qual1", expires_at="2026-09-16T00:00:00Z"
        )
    changed = dict(value)
    changed["validator_zip"] = "../runtime.zip"
    with pytest.raises(ValueError, match="unsafe release archive path"):
        terraform_variables(
            changed, directory, operation_id="release-qual1", expires_at="2026-09-16T00:00:00Z"
        )
    changed = dict(value)
    changed["validator_zip"] = "missing.zip"
    with pytest.raises(ValueError, match="missing or unsafe"):
        terraform_variables(
            changed, directory, operation_id="release-qual1", expires_at="2026-09-16T00:00:00Z"
        )
    with pytest.raises(ValueError, match="KMS"):
        backend_arguments(kms_key_arn="not-a-key", operation_id="release-qual1")


def test_command_requires_all_exact_plan_and_show_bindings(tmp_path: Path) -> None:
    saved = tmp_path / "saved"
    with pytest.raises(ValueError, match="subcommand"):
        validate_command(["terraform"])
    with pytest.raises(ValueError, match="subcommand"):
        validate_command(["terraform", "destroy"])
    with pytest.raises(ValueError, match="init safety"):
        validate_command(["terraform", "init", "-input=false", "-reconfigure"])
    with pytest.raises(ValueError, match="safety arguments"):
        validate_command(["terraform", "plan"], plan_path=saved)
    without_lock = [
        "terraform",
        "plan",
        "-input=false",
        "-refresh=true",
        "-detailed-exitcode",
        f"-out={saved}",
    ]
    with pytest.raises(ValueError, match="safety arguments"):
        validate_command(without_lock, plan_path=saved)
    complete = [
        "terraform",
        "plan",
        "-input=false",
        "-lock=true",
        "-refresh=true",
        "-detailed-exitcode",
        "-out=other",
    ]
    with pytest.raises(ValueError, match="binary plan binding"):
        validate_command(complete, plan_path=saved)
    with pytest.raises(ValueError, match="JSON must come"):
        validate_command(["terraform", "show", "-json", "other"], plan_path=saved)


def test_default_subprocess_adapter_is_covered(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    expected = subprocess.CompletedProcess(["terraform"], 0, stdout=b"{}", stderr=b"")
    monkeypatch.setattr(terraform.subprocess, "run", lambda *args, **kwargs: expected)
    assert terraform._run(["terraform", "version"], tmp_path) is expected


def test_session_failure_modes(tmp_path: Path) -> None:
    missing = PlanSession(tmp_path / "missing", tmp_path / "work")
    with pytest.raises(ValueError, match="source directory"):
        missing.execute(variables={}, backend=[])

    def scenario(name: str):
        infra = tmp_path / name / "infra"
        infra.mkdir(parents=True)
        work = tmp_path / name / "work"

        def run(command: list[str], cwd: Path) -> subprocess.CompletedProcess[bytes]:
            if name == "command-fail" and command[1] == "init":
                return subprocess.CompletedProcess(command, 1, stdout=b"", stderr=b"failed")
            if command[1] == "version":
                version = "1.12.0" if name == "version" else "1.13.1"
                return subprocess.CompletedProcess(
                    command,
                    0,
                    stdout=json.dumps({"terraform_version": version}).encode(),
                    stderr=b"",
                )
            if command[1] == "validate":
                valid = name != "validation"
                return subprocess.CompletedProcess(
                    command,
                    0,
                    stdout=json.dumps({"valid": valid, "error_count": 0 if valid else 1}).encode(),
                    stderr=b"",
                )
            if command[1] == "plan":
                if name != "missing-plan":
                    Path(
                        next(token[5:] for token in command if token.startswith("-out="))
                    ).write_bytes(b"binary")
                return subprocess.CompletedProcess(command, 2, stdout=b"", stderr=b"")
            if command[1] == "show":
                payload: object = [] if name == "nonobject" else {}
                return subprocess.CompletedProcess(
                    command, 0, stdout=json.dumps(payload).encode(), stderr=b""
                )
            return subprocess.CompletedProcess(command, 0, stdout=b"{}", stderr=b"")

        return PlanSession(infra, work, run)

    for name, match in (
        ("command-fail", "init failed"),
        ("version", "version differs"),
        ("validation", "validation failed"),
        ("missing-plan", "regular saved plan"),
        ("nonobject", "must be an object"),
    ):
        with pytest.raises((ValueError, RuntimeError), match=match):
            scenario(name).execute(variables={}, backend=[])
