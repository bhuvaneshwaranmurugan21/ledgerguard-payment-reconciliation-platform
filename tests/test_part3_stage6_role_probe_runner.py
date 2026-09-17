from __future__ import annotations

from typing import Any

import pytest

from tools import run_part3_stage6_role_probe as runner
from tools.part3_stage6.role_probe import (
    ACCOUNT,
    BACKEND_KMS_KEY_ARN,
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
