from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

from tools import run_part3_stage6_role_probe as runner
from tools.part3_stage6.role_probe import (
    ACCOUNT,
    BACKEND_KMS_KEY_ARN,
    ROLE_NAMES,
    validate_outcomes,
)


def encryption() -> dict[str, object]:
    return {
        "ServerSideEncryptionConfiguration": {
            "Rules": [
                {
                    "ApplyServerSideEncryptionByDefault": {
                        "SSEAlgorithm": "AES256"
                    }
                }
            ]
        }
    }


def test_error_code_parsing() -> None:
    assert runner._error_code("An error occurred (AccessDenied) when calling") == "AccessDenied"
    assert runner._error_code("plain failure") is None


@pytest.mark.parametrize("role", ("deploy", "read", "recovery"))
def test_run_uses_read_observation_reviewed_key_and_only_bounded_noops(
    monkeypatch: pytest.MonkeyPatch, role: str
) -> None:
    calls: list[tuple[str, str, list[str]]] = []

    def invoke(
        service: str, operation: str, arguments: list[str]
    ) -> tuple[dict[str, Any], Any]:
        calls.append((service, operation, arguments))
        row: dict[str, Any] = {
            "returncode": 0,
            "error_code": None,
            "response_sha256": "0" * 64,
        }
        if (service, operation) == ("sts", "get-caller-identity"):
            return row, {"Account": ACCOUNT, "Arn": "unused-by-run"}
        if (service, operation) == ("s3api", "get-bucket-encryption"):
            return row, encryption()
        negative = {
            ("dynamodb", "update-item"): (
                "AccessDenied" if role == "read" else "ConditionalCheckFailedException"
            ),
            ("s3api", "upload-part"): "AccessDenied" if role == "read" else "NoSuchUpload",
            ("glue", "batch-stop-job-run"): "EntityNotFoundException",
            ("stepfunctions", "stop-execution"): "ExecutionDoesNotExist",
            ("athena", "stop-query-execution"): "InvalidRequestException",
        }
        code = negative.get((service, operation))
        if code is not None:
            row.update(returncode=254, error_code=code)
        return row, {}

    monkeypatch.setattr(runner, "_invoke", invoke)
    caller, outcomes = runner.run(role)
    assert caller["Account"] == ACCOUNT
    assert validate_outcomes(role, outcomes)["persistent_mutation_absent"] is True
    assert ("s3api", "get-bucket-encryption") in [item[:2] for item in calls]
    assert [
        arguments
        for service, operation, arguments in calls
        if (service, operation) == ("kms", "describe-key")
    ] == [["--key-id", BACKEND_KMS_KEY_ARN]]
    assert all(
        operation
        not in {"start-job-run", "start-query-execution", "start-execution", "invoke"}
        for _, operation, _ in calls
    )
    if role != "recovery":
        assert all(
            not operation.startswith("stop-") and operation != "batch-stop-job-run"
            for _, operation, _ in calls
        )


def test_run_rejects_unknown_role_and_incomplete_encryption(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(ValueError, match="unknown"):
        runner.run("other")

    def invoke(
        service: str, operation: str, arguments: list[str]
    ) -> tuple[dict[str, Any], Any]:
        row = {"returncode": 0, "error_code": None, "response_sha256": "0" * 64}
        if service == "sts":
            return row, {"Account": ACCOUNT}
        return row, {}

    monkeypatch.setattr(runner, "_invoke", invoke)
    with pytest.raises(ValueError, match="bucket encryption observation"):
        runner.run("deploy")


def test_main_preserves_sanitized_observation_when_adjudication_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    bad_outcomes = {
        name: {"returncode": 0, "error_code": None, "response_sha256": "0" * 64}
        for name in (
            "get_role",
            "get_bucket_location",
            "get_bucket_encryption",
            "describe_lease_table",
            "describe_key",
        )
    }
    bad_outcomes["conditional_lease_noop"] = {
        "returncode": 254,
        "error_code": "UnexpectedError",
        "response_sha256": "0" * 64,
    }
    bad_outcomes["conditional_lock_noop"] = {
        "returncode": 254,
        "error_code": "NoSuchUpload",
        "response_sha256": "0" * 64,
    }
    monkeypatch.setattr(
        runner,
        "run",
        lambda role: (
            {
                "Account": ACCOUNT,
                "Arn": f"arn:aws:sts::{ACCOUNT}:assumed-role/{ROLE_NAMES[role]}/probe",
            },
            bad_outcomes,
        ),
    )
    monkeypatch.setenv("GITHUB_RUN_ID", "123")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    output = tmp_path / "evidence" / "receipt.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_part3_stage6_role_probe.py",
            "--expected-role",
            "read",
            "--source-commit",
            "a" * 40,
            "--source-tree",
            "b" * 40,
            "--output",
            str(output),
        ],
    )
    with pytest.raises(ValueError, match="lease mutation denial"):
        runner.main()
    observation = json.loads((output.parent / "observation.json").read_text())
    assert observation["expected_role"] == "read"
    assert observation["persistent_mutations"] == 0
    assert observation["workload_start_calls"] == 0
    assert not output.exists()
