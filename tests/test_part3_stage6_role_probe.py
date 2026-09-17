from __future__ import annotations

from copy import deepcopy

import pytest

from tools.part3_stage6.role_probe import (
    ACCOUNT,
    BACKEND_KMS_KEY_ARN,
    ROLE_NAMES,
    build_receipt,
    validate_backend_kms_key_arn,
    validate_bucket_encryption,
    validate_caller,
    validate_outcomes,
    validate_receipt,
)

COMMIT = "a" * 40
TREE = "b" * 40


def caller(role: str) -> dict[str, str]:
    return {
        "Account": ACCOUNT,
        "Arn": f"arn:aws:sts::{ACCOUNT}:assumed-role/{ROLE_NAMES[role]}/probe",
    }


def outcomes(role: str) -> dict[str, dict[str, object]]:
    value = {
        name: {"returncode": 0, "error_code": None, "response_sha256": "0" * 64}
        for name in (
            "get_role",
            "get_bucket_location",
            "get_bucket_encryption",
            "describe_lease_table",
            "describe_key",
        )
    }
    noop_code = "AccessDenied" if role == "read" else "ConditionalCheckFailedException"
    value["conditional_lease_noop"] = {
        "returncode": 254,
        "error_code": noop_code,
        "response_sha256": "0" * 64,
    }
    value["conditional_lock_noop"] = {
        "returncode": 254,
        "error_code": "AccessDenied" if role == "read" else "NoSuchUpload",
        "response_sha256": "0" * 64,
    }
    if role == "recovery":
        for name, code in (
            ("stop_missing_glue", "EntityNotFoundException"),
            ("stop_missing_execution", "ExecutionDoesNotExist"),
            ("stop_missing_query", "InvalidRequestException"),
        ):
            value[name] = {"returncode": 254, "error_code": code, "response_sha256": "0" * 64}
    return value


def receipt(role: str = "deploy") -> dict[str, object]:
    return build_receipt(
        source_commit=COMMIT,
        source_tree=TREE,
        role=role,
        caller=caller(role),
        outcomes=outcomes(role),
        run_id="123",
        run_attempt="1",
        completed_epoch=1_800_000_000,
    )


@pytest.mark.parametrize("role", sorted(ROLE_NAMES))
def test_real_role_receipts_are_exact_and_nonmutating(role: str) -> None:
    value = receipt(role)
    result = validate_receipt(value, source_commit=COMMIT, source_tree=TREE, role=role)
    assert result["role"] == role
    assert result["persistent_mutations"] == 0
    assert result["workload_start_calls"] == 0
    assert len(result["receipt_sha256"]) == 64


def test_backend_kms_key_is_exact_and_fail_closed() -> None:
    assert validate_backend_kms_key_arn(BACKEND_KMS_KEY_ARN) == BACKEND_KMS_KEY_ARN
    for changed in (
        BACKEND_KMS_KEY_ARN.replace(ACCOUNT, "000000000000"),
        BACKEND_KMS_KEY_ARN.replace("ap-southeast-2", "us-east-1"),
        "alias/ledgerguard",
        "",
    ):
        with pytest.raises(ValueError, match="exact backend KMS key ARN"):
            validate_backend_kms_key_arn(changed)


def test_bucket_encryption_is_observed_without_becoming_the_key_source() -> None:
    for algorithm in ("AES256", "aws:kms", "aws:kms:dsse"):
        observed = {
            "ServerSideEncryptionConfiguration": {
                "Rules": [
                    {
                        "ApplyServerSideEncryptionByDefault": {
                            "SSEAlgorithm": algorithm
                        }
                    }
                ]
            }
        }
        assert validate_bucket_encryption(observed) == algorithm
    for changed in ({}, [], {"ServerSideEncryptionConfiguration": {"Rules": []}}):
        with pytest.raises(ValueError, match="observation is incomplete"):
            validate_bucket_encryption(changed)
    with pytest.raises(ValueError, match="algorithm is unsupported"):
        validate_bucket_encryption(
            {
                "ServerSideEncryptionConfiguration": {
                    "Rules": [
                        {
                            "ApplyServerSideEncryptionByDefault": {
                                "SSEAlgorithm": "unreviewed"
                            }
                        }
                    ]
                }
            }
        )


def test_caller_and_source_identity_fail_closed() -> None:
    with pytest.raises(ValueError, match="unknown"):
        validate_caller(caller("deploy"), "other")
    wrong = caller("deploy")
    wrong["Account"] = "000000000000"
    with pytest.raises(ValueError, match="account"):
        validate_caller(wrong, "deploy")
    wrong = caller("deploy")
    wrong["Arn"] = "arn:aws:sts::857229544428:assumed-role/Other/probe"
    with pytest.raises(ValueError, match="role session"):
        validate_caller(wrong, "deploy")
    with pytest.raises(ValueError, match="source identity"):
        build_receipt(
            source_commit="bad",
            source_tree=TREE,
            role="deploy",
            caller=caller("deploy"),
            outcomes=outcomes("deploy"),
            run_id="1",
            run_attempt="1",
        )
    with pytest.raises(ValueError, match="workflow identity"):
        build_receipt(
            source_commit=COMMIT,
            source_tree=TREE,
            role="deploy",
            caller=caller("deploy"),
            outcomes=outcomes("deploy"),
            run_id="0",
            run_attempt="1",
        )


def test_probe_outcome_inventory_and_permissions_fail_closed() -> None:
    with pytest.raises(ValueError, match="unknown"):
        validate_outcomes("other", outcomes("deploy"))
    changed = outcomes("deploy")
    changed.pop("get_role")
    with pytest.raises(ValueError, match="inventory"):
        validate_outcomes("deploy", changed)
    changed = outcomes("deploy")
    changed["get_role"]["returncode"] = 1
    with pytest.raises(ValueError, match="positive read"):
        validate_outcomes("deploy", changed)
    changed = outcomes("read")
    changed["conditional_lock_noop"]["error_code"] = "PreconditionFailed"
    with pytest.raises(ValueError, match="read-only"):
        validate_outcomes("read", changed)
    changed = outcomes("deploy")
    changed["conditional_lease_noop"]["error_code"] = "AccessDenied"
    with pytest.raises(ValueError, match="bounded mutation"):
        validate_outcomes("deploy", changed)
    changed = outcomes("recovery")
    changed["stop_missing_query"]["error_code"] = "AccessDenied"
    with pytest.raises(ValueError, match="recovery no-op"):
        validate_outcomes("recovery", changed)
    changed = outcomes("deploy")
    changed["conditional_lease_noop"]["returncode"] = 0
    with pytest.raises(ValueError, match="bounded mutation"):
        validate_outcomes("deploy", changed)
    changed = outcomes("deploy")
    changed["get_role"]["response_sha256"] = "bad"
    with pytest.raises(ValueError, match="response binding"):
        validate_outcomes("deploy", changed)
    changed = outcomes("deploy")
    changed["conditional_lock_noop"] = []  # type: ignore[assignment]
    with pytest.raises(ValueError, match="outcome invalid"):
        validate_outcomes("deploy", changed)
    changed = outcomes("deploy")
    changed["conditional_lock_noop"]["returncode"] = True
    with pytest.raises(ValueError, match="return code"):
        validate_outcomes("deploy", changed)
    changed = outcomes("deploy")
    changed["conditional_lock_noop"]["error_code"] = 1
    with pytest.raises(ValueError, match="error code"):
        validate_outcomes("deploy", changed)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (("schema_version",), "schema"),
        (("classification",), "classification"),
        (("source", "tree"), "source"),
        (("source", "workflow_run_id"), "workflow identity"),
        (("role", "name"), "identity"),
        (("checks", "real_oidc_session"), "checks"),
        (("calls", "persistent_mutations"), "persistent mutation"),
        (("calls", "workload_start_calls"), "workload boundary"),
        (("calls", "workload_executions"), "workload boundary"),
        (("calls", "aws_calls"), "AWS call count"),
    ],
)
def test_receipt_mutations_fail(mutation: tuple[str, ...], message: str) -> None:
    value = deepcopy(receipt())
    parent = value
    for key in mutation[:-1]:
        parent = parent[key]  # type: ignore[assignment,index]
    key = mutation[-1]
    current = parent[key]  # type: ignore[index]
    parent[key] = False if current is True else "changed" if isinstance(current, str) else 1  # type: ignore[index]
    with pytest.raises(ValueError, match=message):
        validate_receipt(value, source_commit=COMMIT, source_tree=TREE, role="deploy")


def test_receipt_rejects_nonobjects_and_empty_checks() -> None:
    with pytest.raises(ValueError, match="unknown"):
        validate_receipt(receipt(), source_commit=COMMIT, source_tree=TREE, role="other")
    value = receipt()
    value["source"] = []
    with pytest.raises(ValueError, match="source"):
        validate_receipt(value, source_commit=COMMIT, source_tree=TREE, role="deploy")
    value = receipt()
    value["checks"] = {}
    with pytest.raises(ValueError, match="checks"):
        validate_receipt(value, source_commit=COMMIT, source_tree=TREE, role="deploy")
    value = receipt()
    value["outcomes"] = []
    with pytest.raises(ValueError, match="outcomes"):
        validate_receipt(value, source_commit=COMMIT, source_tree=TREE, role="deploy")
    value = receipt()
    value["calls"] = []
    with pytest.raises(ValueError, match="persistent mutation"):
        validate_receipt(value, source_commit=COMMIT, source_tree=TREE, role="deploy")
    value = receipt()
    value["completed_epoch"] = 0
    with pytest.raises(ValueError, match="completion time"):
        validate_receipt(value, source_commit=COMMIT, source_tree=TREE, role="deploy")
