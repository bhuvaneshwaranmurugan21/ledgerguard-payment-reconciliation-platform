from __future__ import annotations

from typing import Any

import pytest

from tools import run_part3_stage6_role_probe as runner
from tools.part3_stage6.role_probe import ACCOUNT, REGION, validate_outcomes

KEY_ARN = f"arn:aws:kms:{REGION}:{ACCOUNT}:key/11111111-2222-3333-4444-555555555555"


def encryption(key: object = KEY_ARN) -> dict[str, object]:
    return {
        "ServerSideEncryptionConfiguration": {
            "Rules": [
                {"ApplyServerSideEncryptionByDefault": {"KMSMasterKeyID": key}}
            ]
        }
    }


def test_error_code_and_exact_backend_key_parsing() -> None:
    assert runner._error_code("An error occurred (AccessDenied) when calling") == "AccessDenied"
    assert runner._error_code("plain failure") is None
    assert runner._kms_key_arn(encryption()) == KEY_ARN
    for changed in ({}, encryption("bad"), encryption(1)):
        with pytest.raises(ValueError, match=r"backend KMS|exact backend"):
            runner._kms_key_arn(changed)


@pytest.mark.parametrize("role", ("deploy", "read", "recovery"))
def test_run_uses_read_discovery_and_only_bounded_noops(
    monkeypatch: pytest.MonkeyPatch, role: str
) -> None:
    calls: list[tuple[str, str, list[str]]] = []

    def invoke(service: str, operation: str, arguments: list[str]) -> tuple[dict[str, Any], Any]:
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

    def invoke(service: str, operation: str, arguments: list[str]) -> tuple[dict[str, Any], Any]:
        row = {"returncode": 0, "error_code": None, "response_sha256": "0" * 64}
        if service == "sts":
            return row, {"Account": ACCOUNT}
        return row, {}

    monkeypatch.setattr(runner, "_invoke", invoke)
    with pytest.raises(ValueError, match="backend KMS"):
        runner.run("deploy")
