"""Validate and adjudicate private AWS Organizations SCP observations.

The observation is collected in the Organizations management account and stays
private.  This module is public source: it verifies the evidence envelope and
evaluates the exact Stage 6 IAM/runtime request inventory without embedding any
observed organization identifiers or policy documents.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import re
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

ACCOUNT = "857229544428"
REGION = "ap-southeast-2"
HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
POLICY_ID = re.compile(r"^p-[A-Za-z0-9]+$")
GLOBAL_US_EAST_1_SERVICES = {"iam", "organizations"}
CONDITION_KEYS = {"aws:RequestedRegion", "aws:PrincipalArn"}
CONDITION_OPERATORS = {"StringEquals", "StringNotEquals", "StringLike", "StringNotLike"}


@dataclass(frozen=True)
class ScpRequest:
    """One exact action/resource/context tuple that an SCP must not deny."""

    action: str
    resource: str
    requested_region: str
    principal_arn: str
    purpose: str


def _canonical(value: Any) -> bytes:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False).encode() + b"\n"


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _strings(value: Any, label: str) -> list[str]:
    values = [value] if isinstance(value, str) else value
    if not isinstance(values, list) or not values or any(not isinstance(x, str) for x in values):
        raise ValueError(f"{label} must contain non-empty strings")
    return values


def _full_access(document: Any) -> bool:
    if not isinstance(document, dict) or document.get("Version") != "2012-10-17":
        return False
    rows = document.get("Statement")
    rows = [rows] if isinstance(rows, dict) else rows
    return bool(rows) and isinstance(rows, list) and all(
        isinstance(row, dict)
        and row.get("Effect") == "Allow"
        and row.get("Action") == "*"
        and row.get("Resource") == "*"
        and "NotAction" not in row
        and "NotResource" not in row
        and "Condition" not in row
        for row in rows
    )


def _safe_members(archive: zipfile.ZipFile) -> list[str]:
    names: list[str] = []
    for info in archive.infolist():
        path = PurePosixPath(info.filename)
        mode = info.external_attr >> 16
        if (
            path.is_absolute()
            or ".." in path.parts
            or info.is_dir()
            or mode & 0o170000 == 0o120000
            or info.filename in names
        ):
            raise ValueError("Organizations observation archive member is unsafe")
        names.append(info.filename)
    return names


def validate_observation_archive(
    path: Path,
    *,
    archive_sha256: str,
    source_commit: str,
    source_tree: str,
    anchor_preflight_failure_sha256: str,
    now_epoch: int | None = None,
    maximum_age_seconds: int = 86_400,
) -> dict[str, Any]:
    """Return the verified private observation, rejecting stale or partial evidence."""
    for value, label, pattern in (
        (archive_sha256, "archive digest", HEX64),
        (source_commit, "source commit", HEX40),
        (source_tree, "source tree", HEX40),
        (anchor_preflight_failure_sha256, "preflight anchor", HEX64),
    ):
        if pattern.fullmatch(value) is None:
            raise ValueError(f"Organizations observation {label} invalid")
    if not path.is_file() or path.is_symlink():
        raise ValueError("Organizations observation archive missing or unsafe")
    archive_bytes = path.read_bytes()
    if _sha256(archive_bytes) != archive_sha256:
        raise ValueError("Organizations observation archive digest differs")
    with zipfile.ZipFile(path) as archive:
        names = _safe_members(archive)
        required = {"EVIDENCE-MANIFEST.json", "api-journal.json", "organizations-observation.json"}
        if not required <= set(names):
            raise ValueError("Organizations observation required members differ")
        manifest = _object(json.loads(archive.read("EVIDENCE-MANIFEST.json")), "manifest")
        if set(manifest) != set(names) - {"EVIDENCE-MANIFEST.json"}:
            raise ValueError("Organizations observation manifest inventory differs")
        for name, row_value in manifest.items():
            row = _object(row_value, f"manifest row {name}")
            body = archive.read(name)
            if row != {"sha256": _sha256(body), "size_bytes": len(body)}:
                raise ValueError(f"Organizations observation manifest binding differs: {name}")
        observation = _object(
            json.loads(archive.read("organizations-observation.json")), "observation"
        )
        journal = json.loads(archive.read("api-journal.json"))
    if observation.get("schema_version") != "ledgerguard.stage6-organizations-observation.v1":
        raise ValueError("Organizations observation schema differs")
    if observation.get("status") != "OBSERVED":
        raise ValueError("Organizations observation status differs")
    if observation.get("source") != {"commit": source_commit, "tree": source_tree}:
        raise ValueError("Organizations observation source binding differs")
    if observation.get("anchor_preflight_failure_sha256") != anchor_preflight_failure_sha256:
        raise ValueError("Organizations observation preflight anchor differs")
    if observation.get("target_account") != ACCOUNT:
        raise ValueError("Organizations observation target account differs")
    if observation.get("mutating_aws_calls") != 0 or observation.get("workload_calls") != 0:
        raise ValueError("Organizations observation crossed a prohibited boundary")
    completed = observation.get("completed_epoch")
    if not isinstance(completed, int) or isinstance(completed, bool):
        raise ValueError("Organizations observation completion time invalid")
    now = int(time.time()) if now_epoch is None else now_epoch
    if completed > now + 60 or now - completed > maximum_age_seconds:
        raise ValueError("Organizations observation is stale or future-dated")

    organization = _object(observation.get("organization"), "organization")
    management_account = organization.get("ManagementAccountId") or organization.get(
        "MasterAccountId"
    )
    if (
        not isinstance(management_account, str)
        or re.fullmatch(r"[0-9]{12}", management_account) is None
    ):
        raise ValueError("Organizations management account is absent")
    if organization.get("FeatureSet") != "ALL" or not any(
        isinstance(row, dict)
        and row.get("Type") == "SERVICE_CONTROL_POLICY"
        and row.get("Status") == "ENABLED"
        for row in organization.get("AvailablePolicyTypes", [])
    ):
        raise ValueError("Organizations SCP support is not enabled")
    caller = _object(observation.get("caller_identity"), "caller identity")
    if caller.get("Account") != management_account or f"::{management_account}:" not in str(
        caller.get("Arn", "")
    ):
        raise ValueError("Organizations observation caller is not the management account")

    chain = observation.get("target_chain")
    if (
        not isinstance(chain, list)
        or len(chain) < 2
        or chain[0] != ACCOUNT
        or not isinstance(chain[-1], str)
        or not chain[-1].startswith("r-")
        or len(set(chain)) != len(chain)
    ):
        raise ValueError("Organizations target-to-root chain differs")
    attachments = _object(observation.get("attachments"), "attachments")
    if set(attachments) != set(chain):
        raise ValueError("Organizations attachment target inventory differs")
    attachment_ids: set[str] = set()
    for target in chain:
        ids = _strings(attachments[target], f"attachments for {target}")
        if len(set(ids)) != len(ids) or any(POLICY_ID.fullmatch(item) is None for item in ids):
            raise ValueError("Organizations attached policy identity differs")
        attachment_ids.update(ids)

    policy_rows = observation.get("policies")
    if not isinstance(policy_rows, list) or not policy_rows:
        raise ValueError("Organizations policy inventory is empty")
    policies: dict[str, dict[str, Any]] = {}
    for value in policy_rows:
        row = _object(value, "policy")
        summary = _object(row.get("summary"), "policy summary")
        policy_id = summary.get("Id")
        document = _object(row.get("document"), "policy document")
        if (
            not isinstance(policy_id, str)
            or POLICY_ID.fullmatch(policy_id) is None
            or policy_id in policies
            or summary.get("Type") != "SERVICE_CONTROL_POLICY"
        ):
            raise ValueError("Organizations policy summary differs")
        if row.get("document_sha256") != _sha256(_canonical(document)):
            raise ValueError("Organizations policy document digest differs")
        if row.get("full_access") is not _full_access(document):
            raise ValueError("Organizations full-access classification differs")
        policies[policy_id] = row
    if set(policies) != attachment_ids:
        raise ValueError("Organizations described policy inventory differs")
    if observation.get("all_attached_scps_full_access") is not all(
        row["full_access"] is True for row in policies.values()
    ):
        raise ValueError("Organizations aggregate full-access classification differs")
    for target in chain:
        if not any(policies[policy_id]["full_access"] is True for policy_id in attachments[target]):
            raise ValueError("Organizations allow path is incomplete")

    if not isinstance(journal, list) or len(journal) != 3 + len(chain) + len(policies):
        raise ValueError("Organizations API journal call inventory differs")
    expected_operations = (
        [("sts", "get-caller-identity"), ("organizations", "describe-organization")]
        + [("organizations", "list-parents")] * (len(chain) - 1)
        + [("organizations", "list-policies-for-target")] * len(chain)
        + [("organizations", "describe-policy")] * len(policies)
    )
    actual_operations = []
    raw_members: set[str] = set()
    for index, value in enumerate(journal):
        row = _object(value, "API journal row")
        if row.get("index") != index or row.get("exit_code") != 0 or row.get(
            "classification"
        ) != "SUCCESS":
            raise ValueError("Organizations API journal contains a failed or reordered call")
        service = str(row.get("service", ""))
        operation = str(row.get("operation", ""))
        label = f"{index:03d}-{service}-{operation}"
        stdout_name = f"raw-aws/{label}.stdout"
        stderr_name = f"raw-aws/{label}.stderr"
        raw_members.update({stdout_name, stderr_name})
        if (
            row.get("stdout_sha256") != _object(manifest.get(stdout_name), stdout_name).get(
                "sha256"
            )
            or row.get("stderr_sha256")
            != _object(manifest.get(stderr_name), stderr_name).get("sha256")
            or row.get("stderr_sha256") != _sha256(b"")
            or not isinstance(row.get("arguments"), list)
            or any(not isinstance(argument, str) for argument in row["arguments"])
            or not isinstance(row.get("started_epoch"), int)
            or not isinstance(row.get("completed_epoch"), int)
            or row["started_epoch"] > row["completed_epoch"]
            or row["completed_epoch"] > completed
        ):
            raise ValueError("Organizations API journal byte or time binding differs")
        actual_operations.append((row.get("service"), row.get("operation")))
    if actual_operations != expected_operations:
        raise ValueError("Organizations API journal operation inventory differs")
    if set(manifest) != {
        "api-journal.json",
        "organizations-observation.json",
        *raw_members,
    }:
        raise ValueError("Organizations raw API member inventory differs")
    return observation


def _glob(pattern: str, value: str, *, casefold: bool) -> bool:
    if casefold:
        pattern, value = pattern.lower(), value.lower()
    return fnmatch.fnmatchcase(value, pattern)


def _condition_matches(condition: Any, request: ScpRequest) -> bool:
    if condition is None:
        return True
    value = _object(condition, "SCP condition")
    if not value or any(operator not in CONDITION_OPERATORS for operator in value):
        raise ValueError("SCP condition operator is unsupported")
    context = {
        "aws:RequestedRegion": request.requested_region,
        "aws:PrincipalArn": request.principal_arn,
    }
    for operator, entries_value in value.items():
        entries = _object(entries_value, f"SCP condition {operator}")
        if not entries or any(key not in CONDITION_KEYS for key in entries):
            raise ValueError("SCP condition key is unsupported")
        for key, expected_value in entries.items():
            expected = _strings(expected_value, f"SCP condition value {key}")
            actual = context[key]
            equals = [actual == item for item in expected]
            likes = [_glob(item, actual, casefold=False) for item in expected]
            matched = {
                "StringEquals": any(equals),
                "StringNotEquals": not any(equals),
                "StringLike": any(likes),
                "StringNotLike": not any(likes),
            }[operator]
            if not matched:
                return False
    return True


def _selector_matches(statement: dict[str, Any], key: str, not_key: str, value: str) -> bool:
    if (key in statement) == (not_key in statement):
        raise ValueError(f"SCP statement must contain exactly one of {key}/{not_key}")
    selected = _strings(statement.get(key, statement.get(not_key)), f"SCP {key} selector")
    casefold = key == "Action"
    matches = any(_glob(pattern, value, casefold=casefold) for pattern in selected)
    return matches if key in statement else not matches


def _deny_matches(statement: dict[str, Any], request: ScpRequest) -> bool:
    if not _selector_matches(statement, "Action", "NotAction", request.action):
        return False
    if not _selector_matches(statement, "Resource", "NotResource", request.resource):
        return False
    return _condition_matches(statement.get("Condition"), request)


def adjudicate_service_control_policies(
    observation: dict[str, Any], requests: list[ScpRequest]
) -> dict[str, Any]:
    """Fail closed unless every required request is outside every attached SCP Deny."""
    if not requests or len(set(requests)) != len(requests):
        raise ValueError("Stage 6 SCP request inventory is empty or duplicated")
    policies = observation.get("policies")
    if not isinstance(policies, list) or not policies:
        raise ValueError("Organizations policy inventory is empty")
    denies: list[tuple[str, dict[str, Any]]] = []
    for policy in policies:
        row = _object(policy, "policy")
        document = _object(row.get("document"), "policy document")
        if document.get("Version") != "2012-10-17":
            raise ValueError("SCP policy version differs")
        statements = document.get("Statement")
        statements = [statements] if isinstance(statements, dict) else statements
        if not isinstance(statements, list) or not statements:
            raise ValueError("SCP statement inventory is empty")
        for statement_value in statements:
            statement = _object(statement_value, "SCP statement")
            if statement.get("Effect") == "Allow":
                if not _full_access({"Version": "2012-10-17", "Statement": [statement]}):
                    raise ValueError("non-full-access SCP Allow is unsupported")
                continue
            if statement.get("Effect") != "Deny":
                raise ValueError("SCP effect is unsupported")
            allowed_keys = {
                "Sid", "Effect", "Action", "NotAction", "Resource", "NotResource", "Condition"
            }
            if set(statement) - allowed_keys:
                raise ValueError("SCP statement contains unsupported fields")
            denies.append((str(statement.get("Sid", "")), statement))
    for request in requests:
        if (
            not request.action
            or ":" not in request.action
            or not request.resource
            or not request.purpose
            or request.requested_region not in {REGION, "us-east-1"}
            or re.fullmatch(r"arn:aws:(iam|sts)::[0-9]{12}:.+", request.principal_arn) is None
        ):
            raise ValueError("Stage 6 SCP request shape differs")
        for sid, statement in denies:
            if _deny_matches(statement, request):
                raise ValueError(f"SCP denies required Stage 6 request: {request.purpose}/{sid}")
    return {
        "classification": "ORGANIZATION_SCP_OBSERVED_AND_ADMITTED",
        "target_to_root_chain_complete": True,
        "attached_policies": len(policies),
        "explicit_denies_evaluated": len(denies),
        "required_requests_evaluated": len(requests),
        "region": REGION,
        "mutating_aws_calls": 0,
        "workload_calls": 0,
        "stage6_complete": False,
    }


def _region_for(action: str) -> str:
    return "us-east-1" if action.split(":", 1)[0].lower() in GLOBAL_US_EAST_1_SERVICES else REGION


def _request(action: str, resource: str, principal: str, purpose: str) -> ScpRequest:
    return ScpRequest(action, resource, _region_for(action), principal, purpose)


def successor_required_requests(packet: dict[str, Any]) -> list[ScpRequest]:
    """Build the exact administrator and desired-permission SCP request inventory."""
    documents = _object(packet.get("documents"), "successor documents")
    identity = _object(documents.get("identity_contract"), "identity contract")
    roles = _object(identity.get("roles"), "identity roles")
    policies = _object(identity.get("policies"), "identity policies")
    runtime = _object(documents.get("runtime_policies"), "runtime policies")
    boundaries = _object(documents.get("runtime_boundaries"), "runtime boundaries")
    administrator = f"arn:aws:iam::{ACCOUNT}:role/LedgerGuardStage6Administrator"
    role_arns = sorted(roles)
    if set(boundaries) != {"glue", "workflow", "validator", "controller"}:
        raise ValueError("runtime boundary inventory differs")
    boundary_arns = {
        f"arn:aws:iam::{ACCOUNT}:policy/LedgerGuardPart3-{role}-Boundary-v1"
        for role in boundaries
    }
    policy_arns = sorted(set(policies) | boundary_arns)
    if len(role_arns) != 3 or len(policies) != 7 or len(policy_arns) != 11:
        raise ValueError("successor IAM role or policy inventory differs")
    administrator_document = _object(documents.get("administrator"), "administrator")
    backend = _object(administrator_document.get("backend"), "backend")
    bucket = str(backend.get("bucket", ""))
    kms_key = str(backend.get("kms_key_id", ""))
    if not bucket or not kms_key.startswith(f"arn:aws:kms:{REGION}:{ACCOUNT}:key/"):
        raise ValueError("successor backend identity differs")
    requests: list[ScpRequest] = []
    admin_actions = {
        "sts:GetCallerIdentity": ["*"],
        "iam:GetAccountSummary": ["*"],
        "iam:GetRole": role_arns,
        "iam:ListRoleTags": role_arns,
        "iam:ListRolePolicies": role_arns,
        "iam:GetRolePolicy": role_arns,
        "iam:ListAttachedRolePolicies": role_arns,
        "iam:GetPolicy": policy_arns,
        "iam:GetPolicyVersion": policy_arns,
        "access-analyzer:ValidatePolicy": ["*"],
        "s3:GetBucketPolicy": [f"arn:aws:s3:::{bucket}"],
        "kms:GetKeyPolicy": [kms_key],
        "iam:CreatePolicy": policy_arns,
        "iam:CreateRole": role_arns[1:],
        "iam:AttachRolePolicy": role_arns,
        "iam:DeleteRolePolicy": [f"arn:aws:iam::{ACCOUNT}:role/LedgerGuardGitHubOidcRole"],
        "iam:PutRolePolicy": [f"arn:aws:iam::{ACCOUNT}:role/LedgerGuardGitHubOidcRole"],
        "iam:DetachRolePolicy": role_arns,
        "iam:DeleteRole": role_arns[1:],
        "iam:DeletePolicy": policy_arns,
    }
    for action, resources in admin_actions.items():
        for resource in resources:
            requests.append(_request(action, resource, administrator, "administrator-transaction"))

    desired_documents = list(policies.items()) + [
        (f"runtime:{role}", document) for role, document in sorted(runtime.items())
    ]
    for name, document_value in desired_documents:
        document = _object(document_value, f"desired policy {name}")
        statements = document.get("Statement")
        statements = [statements] if isinstance(statements, dict) else statements
        if not isinstance(statements, list):
            raise ValueError("desired policy statement inventory differs")
        principal = administrator
        if name.startswith("runtime:"):
            role = name.split(":", 1)[1]
            principal = f"arn:aws:iam::{ACCOUNT}:role/LedgerGuardPart3-{role}-release-qual1"
        for statement_value in statements:
            statement = _object(statement_value, "desired policy statement")
            if statement.get("Effect") != "Allow":
                continue
            if "NotAction" in statement or "NotResource" in statement:
                raise ValueError("desired policy uses unsupported negative selector")
            for action in _strings(statement.get("Action"), "desired policy actions"):
                for resource in _strings(statement.get("Resource"), "desired policy resources"):
                    requests.append(_request(action, resource, principal, f"desired-policy:{name}"))
    unique = list(dict.fromkeys(requests))
    if len(unique) < 50:
        raise ValueError("Stage 6 SCP request inventory is unexpectedly small")
    return unique
