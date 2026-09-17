"""Admit real OIDC sessions without creating a workload or persistent resource."""

from __future__ import annotations

import hashlib
import json
import re
import time
from typing import Any

ACCOUNT = "857229544428"
REGION = "ap-southeast-2"
BACKEND_BUCKET = f"ledgerguard-tfstate-{ACCOUNT}-{REGION}"
BACKEND_KMS_KEY_ARN = (
    f"arn:aws:kms:{REGION}:{ACCOUNT}:key/f1298457-395b-4e16-8c11-50ee669be834"
)
BUCKET_ENCRYPTION_ALGORITHMS = frozenset({"AES256", "aws:kms", "aws:kms:dsse"})
LEASE_TABLE = "ledgerguard-operation-leases"
LEASE_KEY = "ledgerguard/part3/platform/deployment"
STATE_LOCK_KEY = "ledgerguard/terraform/part3/platform/release-qual1/terraform.tfstate.tflock"
ROLE_NAMES = {
    "deploy": "LedgerGuardGitHubOidcRole",
    "read": "LedgerGuardPart3ReadOnlyRole",
    "recovery": "LedgerGuardPart3RecoveryRole",
}
HEX40 = re.compile(r"^[0-9a-f]{40}$")
LEASE_NO_WRITE_CODE = "ConditionalCheckFailedException"
LOCK_NO_WRITE_CODE = "NoSuchUpload"
ACCESS_DENIED_CODES = {"AccessDenied", "AccessDeniedException", "UnauthorizedOperation"}
READ_LOCK_NONMUTATING_CODES = ACCESS_DENIED_CODES | {LOCK_NO_WRITE_CODE}
RECOVERY_ABSENT_CODES = {
    "stop_missing_glue": {"EntityNotFoundException"},
    "stop_missing_execution": {"ExecutionDoesNotExist"},
    "stop_missing_query": {"InvalidRequestException"},
}
GLUE_ABSENT_BATCH_SUMMARY = {
    "successful_submission_count": 0,
    "error_count": 1,
    "error_code": "EntityNotFoundException",
    "request_identity_match": True,
}


def validate_backend_kms_key_arn(value: str) -> str:
    pattern = rf"arn:aws:kms:{REGION}:{ACCOUNT}:key/(?:[0-9a-f-]{{36}}|mrk-[0-9a-f]{{32}})"
    if re.fullmatch(pattern, value) is None:
        raise ValueError("exact backend KMS key ARN required")
    return value


def validate_bucket_encryption(value: Any) -> str:
    try:
        rules = value["ServerSideEncryptionConfiguration"]["Rules"]
        algorithm = rules[0]["ApplyServerSideEncryptionByDefault"]["SSEAlgorithm"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError("backend bucket encryption observation is incomplete") from exc
    if not isinstance(algorithm, str) or algorithm not in BUCKET_ENCRYPTION_ALGORITHMS:
        raise ValueError("backend bucket encryption algorithm is unsupported")
    return algorithm


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode() + b"\n"


def response_digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def validate_caller(caller: dict[str, Any], role: str) -> dict[str, str]:
    if role not in ROLE_NAMES:
        raise ValueError("unknown Stage 6 role")
    expected_name = ROLE_NAMES[role]
    if caller.get("Account") != ACCOUNT:
        raise ValueError("unexpected AWS account")
    arn = caller.get("Arn")
    if not isinstance(arn, str) or f":assumed-role/{expected_name}/" not in arn:
        raise ValueError("unexpected OIDC role session")
    return {
        "kind": role,
        "name": expected_name,
        "arn": f"arn:aws:iam::{ACCOUNT}:role/{expected_name}",
    }


def validate_outcomes(role: str, outcomes: dict[str, dict[str, Any]]) -> dict[str, bool]:
    if role not in ROLE_NAMES:
        raise ValueError("unknown Stage 6 role")
    required_reads = {
        "get_role",
        "get_bucket_location",
        "get_bucket_encryption",
        "describe_lease_table",
        "describe_key",
    }
    required = required_reads | {"conditional_lease_noop", "conditional_lock_noop"}
    if role == "recovery":
        required |= {"stop_missing_glue", "stop_missing_execution", "stop_missing_query"}
    if set(outcomes) != required:
        raise ValueError("role probe operation inventory differs")
    if any(outcomes[name].get("returncode") != 0 for name in required_reads):
        raise ValueError("positive read probe failed")
    for name, outcome in outcomes.items():
        if not isinstance(outcome, dict):
            raise ValueError(f"role probe outcome invalid: {name}")
        returncode = outcome.get("returncode")
        if not isinstance(returncode, int) or isinstance(returncode, bool):
            raise ValueError(f"role probe return code invalid: {name}")
        error_code = outcome.get("error_code")
        if error_code is not None and not isinstance(error_code, str):
            raise ValueError(f"role probe error code invalid: {name}")
        if re.fullmatch(r"[0-9a-f]{64}", str(outcome.get("response_sha256", ""))) is None:
            raise ValueError(f"role probe response binding invalid: {name}")
    if role == "read":
        lease = outcomes["conditional_lease_noop"]
        lock = outcomes["conditional_lock_noop"]
        if lease.get("returncode") == 0 or lease.get("error_code") not in ACCESS_DENIED_CODES:
            raise ValueError("read-only lease mutation denial was not effective")
        # S3 can resolve a deliberately nonexistent multipart-upload ID before
        # returning an authorization denial.  NoSuchUpload therefore proves
        # this exact request was non-mutating, while the exact installed IAM
        # policy remains the authority for absence of s3:PutObject.
        if lock.get("returncode") == 0 or lock.get("error_code") not in READ_LOCK_NONMUTATING_CODES:
            raise ValueError("read-only lock request was not proven non-mutating")
    else:
        lease = outcomes["conditional_lease_noop"]
        lock = outcomes["conditional_lock_noop"]
        if (
            lease.get("returncode") == 0
            or lease.get("error_code") != LEASE_NO_WRITE_CODE
            or lock.get("returncode") == 0
            or lock.get("error_code") != LOCK_NO_WRITE_CODE
        ):
            raise ValueError("bounded mutation permission was not effectively reached")
    if role == "recovery":
        for name, admitted_codes in RECOVERY_ABSENT_CODES.items():
            outcome = outcomes[name]
            # Glue BatchStopJobRun uses an HTTP-200 batch envelope for per-run
            # failures.  Admit it only when there were zero successful stops,
            # exactly one absent-run error, and its identity matched our fixed
            # nonexistent request.  The raw response remains digest-bound.
            if name == "stop_missing_glue" and (
                outcome.get("returncode") == 0
                and outcome.get("error_code") is None
                and outcome.get("batch_stop_summary") == GLUE_ABSENT_BATCH_SUMMARY
            ):
                continue
            # Athena StopQueryExecution is idempotent and may return success for
            # the fixed nonexistent UUID. Glue and Step Functions must report
            # their service-specific absent-resource errors.
            if name == "stop_missing_query" and (
                outcome.get("returncode") == 0 and outcome.get("error_code") is None
            ):
                continue
            if outcome.get("returncode") == 0 or outcome.get("error_code") not in admitted_codes:
                raise ValueError(f"recovery no-op permission probe failed: {name}")
    return {
        "real_oidc_session": True,
        "positive_reads_effective": True,
        "conditional_mutation_outcome_admitted": True,
        "backend_lock_request_nonmutating": True,
        "recovery_noop_controls_admitted": True,
        "persistent_mutation_absent": True,
        "workload_start_absent": True,
    }


def build_receipt(
    *,
    source_commit: str,
    source_tree: str,
    role: str,
    caller: dict[str, Any],
    outcomes: dict[str, dict[str, Any]],
    run_id: str,
    run_attempt: str,
    completed_epoch: int | None = None,
) -> dict[str, Any]:
    if HEX40.fullmatch(source_commit) is None or HEX40.fullmatch(source_tree) is None:
        raise ValueError("source identity invalid")
    if re.fullmatch(r"[1-9][0-9]*", run_id) is None or re.fullmatch(
        r"[1-9][0-9]*", run_attempt
    ) is None:
        raise ValueError("workflow identity invalid")
    identity = validate_caller(caller, role)
    checks = validate_outcomes(role, outcomes)
    return {
        "schema_version": "ledgerguard.part3-stage6-real-role-probe.v1",
        "classification": "REAL_OIDC_ROLE_EFFECTIVELY_PROBED_NO_WORKLOAD",
        "source": {
            "commit": source_commit,
            "tree": source_tree,
            "ref": "refs/heads/main",
            "event": "workflow_dispatch",
            "workflow_run_id": run_id,
            "workflow_run_attempt": run_attempt,
        },
        "target": {"account": ACCOUNT, "region": REGION, "operation_id": "release-qual1"},
        "role": identity,
        "checks": checks,
        "outcomes": outcomes,
        "calls": {
            "aws_calls": 1 + len(outcomes),
            "persistent_mutations": 0,
            "workload_start_calls": 0,
            "workload_executions": 0,
        },
        "completed_epoch": int(time.time()) if completed_epoch is None else completed_epoch,
    }


def validate_receipt(
    value: dict[str, Any], *, source_commit: str, source_tree: str, role: str
) -> dict[str, Any]:
    if role not in ROLE_NAMES:
        raise ValueError("unknown Stage 6 role")
    if value.get("schema_version") != "ledgerguard.part3-stage6-real-role-probe.v1":
        raise ValueError("role probe schema differs")
    if value.get("classification") != "REAL_OIDC_ROLE_EFFECTIVELY_PROBED_NO_WORKLOAD":
        raise ValueError("role probe classification differs")
    source = value.get("source")
    if not isinstance(source, dict) or {
        key: source.get(key) for key in ("commit", "tree", "ref", "event")
    } != {
        "commit": source_commit,
        "tree": source_tree,
        "ref": "refs/heads/main",
        "event": "workflow_dispatch",
    }:
        raise ValueError("role probe source differs")
    if re.fullmatch(r"[1-9][0-9]*", str(source.get("workflow_run_id", ""))) is None or re.fullmatch(
        r"[1-9][0-9]*", str(source.get("workflow_run_attempt", ""))
    ) is None:
        raise ValueError("role probe workflow identity invalid")
    expected_identity = {
        "kind": role,
        "name": ROLE_NAMES[role],
        "arn": f"arn:aws:iam::{ACCOUNT}:role/{ROLE_NAMES[role]}",
    }
    if value.get("role") != expected_identity:
        raise ValueError("role probe identity differs")
    outcomes = value.get("outcomes")
    if not isinstance(outcomes, dict):
        raise ValueError("role probe outcomes invalid")
    expected_checks = validate_outcomes(role, outcomes)
    checks = value.get("checks")
    if checks != expected_checks:
        raise ValueError("role probe checks incomplete")
    calls = value.get("calls")
    if not isinstance(calls, dict) or calls.get("persistent_mutations") != 0:
        raise ValueError("role probe persistent mutation differs")
    if calls.get("aws_calls") != 1 + len(outcomes):
        raise ValueError("role probe AWS call count differs")
    if calls.get("workload_start_calls") != 0 or calls.get("workload_executions") != 0:
        raise ValueError("role probe crossed workload boundary")
    completed_epoch = value.get("completed_epoch")
    if (
        not isinstance(completed_epoch, int)
        or isinstance(completed_epoch, bool)
        or completed_epoch <= 0
    ):
        raise ValueError("role probe completion time invalid")
    return {
        "classification": "REAL_ROLE_PROBE_ADMITTED",
        "role": role,
        "receipt_sha256": response_digest(value),
        "persistent_mutations": 0,
        "workload_start_calls": 0,
    }
