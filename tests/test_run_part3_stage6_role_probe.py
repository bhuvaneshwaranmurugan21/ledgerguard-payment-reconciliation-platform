from __future__ import annotations

from typing import Any

import pytest

from tools import run_part3_stage6_role_probe as runner
from tools.part3_stage6.role_probe import (
    ACCOUNT,
    BACKEND_KMS_KEY_ARN,
    ROLE_NAMES,
    validate_outcomes,
)


def _row(returncode: int = 0, error_code: str | None = None) -> dict[str, Any]:
    return {
        "returncode": returncode,
        "error_code": error_code,
        "response_sha256": "0" * 64,
    }


def test_runner_uses_reviewed_kms_key_when_bucket_default_is_sse_s3(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str, list[str]]] = []

    def invoke(
        service: str, operation: str, arguments: list[str]
    ) -> tuple[dict[str, Any], Any]:
        calls.append((service, operation, arguments))
        if (service, operation) == ("sts", "get-caller-identity"):
            return _row(), {
                "Account": ACCOUNT,
                "Arn": (
                    f"arn:aws:sts::{ACCOUNT}:assumed-role/"
                    f"{ROLE_NAMES['deploy']}/probe"
                ),
            }
        if (service, operation) == ("s3api", "get-bucket-encryption"):
            return _row(), {
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
        if (service, operation) == ("dynamodb", "update-item"):
            return _row(254, "ConditionalCheckFailedException"), None
        if (service, operation) == ("s3api", "upload-part"):
            return _row(254, "NoSuchUpload"), None
        return _row(), {}

    monkeypatch.setattr(runner, "_invoke", invoke)
    caller, outcomes = runner.run("deploy")

    assert caller["Account"] == ACCOUNT
    assert validate_outcomes("deploy", outcomes)["persistent_mutation_absent"] is True
    describe_key_calls = [
        arguments
        for service, operation, arguments in calls
        if (service, operation) == ("kms", "describe-key")
    ]
    assert describe_key_calls == [["--key-id", BACKEND_KMS_KEY_ARN]]


def test_runner_fails_closed_before_using_an_unreviewed_kms_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def invoke(
        service: str, operation: str, arguments: list[str]
    ) -> tuple[dict[str, Any], Any]:
        if (service, operation) == ("sts", "get-caller-identity"):
            return _row(), {
                "Account": ACCOUNT,
                "Arn": (
                    f"arn:aws:sts::{ACCOUNT}:assumed-role/"
                    f"{ROLE_NAMES['deploy']}/probe"
                ),
            }
        if (service, operation) == ("s3api", "get-bucket-encryption"):
            return _row(), {
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
        raise AssertionError("unreviewed KMS key must fail before further AWS calls")

    monkeypatch.setattr(runner, "_invoke", invoke)
    monkeypatch.setattr(runner, "BACKEND_KMS_KEY_ARN", "alias/unreviewed")

    with pytest.raises(ValueError, match="exact backend KMS key ARN"):
        runner.run("deploy")
