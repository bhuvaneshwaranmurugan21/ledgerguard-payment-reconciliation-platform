"""Generate the private, Stage-5-bound successor IAM review packet.

This module is deliberately offline.  It composes desired documents and proves
their source/release binding, but cannot install IAM or assert effective AWS
permissions.  Installation remains a separate administrator transaction.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from tools.part3_stage4.administrator import compose, identity_contract
from tools.part3_stage4.iam import (
    ACCOUNT,
    REGION,
    ROLES,
    WORKLOAD_STARTS,
    identities,
    resolve,
    runtime_boundaries,
)

EXPECTED_STAGE5 = {
    "source_commit": "38576ff8b0592b53cd65fe3cf4241e077484afd8",
    "source_tree": "d789912c580bc4fd7f8059dd5e0ea766cd251750",
    "definition_sha256": "e9233f551153fe4053575609423802eeed8741612cc16be5017d097746f693d5",
    "runtime_package_sha256": "1dde69c7338d898daa660acd800264d817d15f73bae9b2071156eb909f2291b8",
    "handler_config_sha256": "f0bd3462aab632c8bccc378d428f3c07eb492f939eb6ff4a0e2e8d2809c1a25a",
    "manifest_sha256": "dc40c27d49967f2868142465a5b2bcb6a107b2769e8180ec541dad83af26175a",
    "script_sha256": "f1051163b8c0e961f01a15195c27502a1bb485bc3886d5f533d47ee905b36383",
    "wheels_sha256": "c54d226465141b0a0c368a3745971de85dbb4f23f409658917cb6952d8f61db4",
}
HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode() + b"\n"


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def validate_release(release: dict[str, Any], release_dir: Path) -> dict[str, str]:
    """Admit the exact accepted Stage 5 Terraform release and real package bytes."""
    if release.get("schema_version") != "ledgerguard.stage5-terraform-release.v1":
        raise ValueError("Stage 5 Terraform release schema differs")
    for key, expected in EXPECTED_STAGE5.items():
        if release.get(key) != expected:
            raise ValueError(f"accepted Stage 5 release identity differs: {key}")
    handler = json.loads(str(release.get("handler_config", "")))
    if handler.get("operation_id") != "release-qual1":
        raise ValueError("accepted Stage 5 operation identity differs")
    definition = str(release.get("definition", ""))
    if hashlib.sha256(definition.encode()).hexdigest() != release["definition_sha256"]:
        raise ValueError("Stage 5 definition bytes differ")
    if (
        hashlib.sha256(str(release["handler_config"]).encode()).hexdigest()
        != release["handler_config_sha256"]
    ):
        raise ValueError("Stage 5 handler configuration bytes differ")
    files = {
        "runtime.zip": release["runtime_package_sha256"],
        "ledgerguard_stage5_job.py": release["script_sha256"],
        "ledgerguard.gluewheels.zip": release["wheels_sha256"],
    }
    for name, expected in files.items():
        path = release_dir / name
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"Stage 5 release member missing or unsafe: {name}")
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(f"Stage 5 release member digest differs: {name}")
    return {name: expected for name, expected in files.items()}


def _all_statements(documents: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        statement for document in documents.values() for statement in document.get("Statement", [])
    ]


def stage5_runtime_policies(
    module: dict[str, Any], operation_id: str, objects: dict[str, str]
) -> dict[str, Any]:
    """Render runtime grants for the accepted Stage 5 script without editing Stage 4."""
    names = identities(operation_id)
    if set(objects) != {"script_key", "wheels_key"}:
        raise ValueError("deployment object inventory differs")
    for field, suffix in (
        ("script_key", "ledgerguard_stage5_job.py"),
        ("wheels_key", "ledgerguard.gluewheels.zip"),
    ):
        if not re.fullmatch(
            r"deployment/[0-9a-f]{64}/" + re.escape(suffix), objects.get(field, "")
        ):
            raise ValueError("unqualified Stage 5 deployment object: " + field)
    bindings = {"local." + key: value for key, value in names.items()}
    bindings.update({"var.stage5_release." + key: value for key, value in objects.items()})
    bindings.update(
        {f'local.function_arns["{role}"]': arn for role, arn in names["function_arns"].items()}
    )
    logs = resolve(module["locals"]["log_names"], bindings)
    result: dict[str, Any] = {}
    for role in ROLES:
        statements = resolve(module["locals"]["runtime_statements"][role], bindings)
        keys = module["locals"]["role_log_keys"][role]
        if keys:
            statements.append(
                {
                    "Sid": "WriteOwnStructuredLogs",
                    "Effect": "Allow",
                    "Action": ["logs:CreateLogStream", "logs:PutLogEvents"],
                    "Resource": [
                        f"arn:aws:logs:{REGION}:{ACCOUNT}:log-group:{logs[key]}:*" for key in keys
                    ],
                }
            )
        if role in ("validator", "controller"):
            statements.append(
                {
                    "Sid": "LambdaTraceTelemetry",
                    "Effect": "Allow",
                    "Action": ["xray:PutTraceSegments", "xray:PutTelemetryRecords"],
                    "Resource": ["*"],
                    "Condition": {"StringEquals": {"aws:RequestedRegion": REGION}},
                }
            )
        result[role] = {"Version": "2012-10-17", "Statement": statements}
    return result


def validate_runtime_boundaries(
    policies: dict[str, Any], boundaries: dict[str, Any]
) -> dict[str, Any]:
    """Prove every runtime ceiling contains the non-bypassable safety denies."""
    if set(policies) != set(ROLES) or set(boundaries) != set(ROLES):
        raise ValueError("runtime role inventory differs")
    for role in ROLES:
        allowed = _all_statements({role: policies[role]})
        for statement in allowed:
            actions = statement.get("Action", [])
            actions = [actions] if isinstance(actions, str) else actions
            if statement.get("Effect") == "Allow" and set(actions) & set(WORKLOAD_STARTS):
                raise ValueError(f"runtime policy can start a workload: {role}")
        denied = {
            statement.get("Sid"): statement
            for statement in _all_statements({role: boundaries[role]})
            if statement.get("Effect") == "Deny"
        }
        if set(denied) != {
            "NoPart3WorkloadStart",
            "NoIdentityChaining",
            "NoPart3BusinessObjects",
            "NoPart3BusinessRecords",
        }:
            raise ValueError(f"runtime boundary deny inventory differs: {role}")
        actions = denied["NoPart3WorkloadStart"].get("Action")
        if actions != WORKLOAD_STARTS:
            raise ValueError(f"runtime workload-start deny differs: {role}")
    return {"roles": len(ROLES), "workload_start_allows": 0, "required_denies": 4 * len(ROLES)}


def compose_successor_packet(
    *,
    provider: dict[str, Any],
    module: dict[str, Any],
    trust: dict[str, Any],
    release: dict[str, Any],
    release_dir: Path,
    backend_kms_key_arn: str,
    source_commit: str,
    source_tree: str,
) -> dict[str, Any]:
    """Return a checksum-bound private review packet without contacting AWS."""
    if not re.fullmatch(r"[0-9a-f]{40}", source_commit) or not re.fullmatch(
        r"[0-9a-f]{40}", source_tree
    ):
        raise ValueError("Stage 6 source identity invalid")
    release_files = validate_release(release, release_dir)
    operation_id = "release-qual1"
    administrator = compose(provider, module, operation_id, backend_kms_key_arn)
    identities = identity_contract(administrator, trust)
    policies = stage5_runtime_policies(
        module,
        operation_id,
        {"script_key": release["script_key"], "wheels_key": release["wheels_key"]},
    )
    boundaries = runtime_boundaries(policies, operation_id)
    safety = validate_runtime_boundaries(policies, boundaries)
    documents = {
        "administrator": administrator,
        "identity_contract": identities,
        "runtime_policies": policies,
        "runtime_boundaries": boundaries,
    }
    return {
        "schema_version": "ledgerguard.part3-stage6-successor-iam-review.v1",
        "classification": "PRIVATE_DESIRED_NOT_INSTALLED_NOT_EFFECTIVELY_VERIFIED",
        "stage6_source": {"commit": source_commit, "tree": source_tree},
        "accepted_stage5": dict(EXPECTED_STAGE5),
        "release_files": release_files,
        "documents": documents,
        "document_sha256": {name: _digest(value) for name, value in documents.items()},
        "safety": safety,
        "installation": {
            "performed": False,
            "executor_self_remediation": False,
            "requires_separate_administrator": True,
            "requires_pre_change_snapshot": True,
            "requires_rollback_journal": True,
            "requires_post_change_exact_parity": True,
            "requires_effective_permission_probe": True,
            "requires_restriction_adjudication": True,
        },
        "aws_calls": 0,
        "stage6_complete": False,
    }
