"""Trusted execution admission and durable run registration transitions.

These functions are the first concrete handler transitions.  Deployment supplies
one immutable execution-input reference and its qualified runtime identity.  The
Step Functions request can select neither different bytes nor a different run.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from hashlib import sha256
from typing import Any, cast

from jsonschema import Draft202012Validator

from ledgerguard.stage3.canonical import canonical_bytes
from ledgerguard.stage3.paths import parse_s3_uri

from .admission import Release, admit_execution
from .athena import fixed_queries
from .authority import Attempt
from .contracts import OBJECT, RUNTIME, ControlRejected, closed, job_arguments, strict_json
from .glue_run import start_request
from .objects import VersionedObjects

ACCOUNT_ID = "857229544428"
REGION = "ap-southeast-2"
_OPERATION = r"[a-z0-9][a-z0-9-]{7,31}"
_OWNER = re.compile(
    rf"arn:aws:states:{REGION}:{ACCOUNT_ID}:execution:[A-Za-z0-9_-]{{1,80}}:"
    r"[A-Za-z0-9_-]{1,80}"
)
_CONFIG = closed(
    {
        "schema_version": {"const": "ledgerguard.handler-config.v1"},
        "operation_id": {"type": "string", "pattern": rf"^{_OPERATION}$"},
        "execution_input": OBJECT,
        "release_manifest_sha256": {"type": "string", "pattern": r"^[0-9a-f]{64}$"},
        "runtime": RUNTIME,
    }
)


@dataclass(frozen=True)
class HandlerConfig:
    operation_id: str
    execution_input: dict[str, Any]
    release: Release

    @property
    def bucket(self) -> str:
        return f"ledgerguard-p3-{ACCOUNT_ID}-{self.operation_id}"

    @property
    def table(self) -> str:
        return f"ledgerguard-p3-{self.operation_id}-control"


def parse_config(raw: bytes, trusted_sha256: str) -> HandlerConfig:
    """Parse the exact deployment-controlled handler configuration."""
    if type(trusted_sha256) is not str or re.fullmatch(r"[0-9a-f]{64}", trusted_sha256) is None:
        raise ControlRejected("invalid handler configuration digest")
    if sha256(raw).hexdigest() != trusted_sha256:
        raise ControlRejected("handler configuration digest differs")
    value = strict_json(raw)
    if not Draft202012Validator(_CONFIG).is_valid(value):
        raise ControlRejected("invalid handler configuration")
    if value["execution_input"]["version_id"] == "null":
        raise ControlRejected("invalid handler configuration")
    operation = value["operation_id"]
    bucket = f"ledgerguard-p3-{ACCOUNT_ID}-{operation}"
    location = parse_s3_uri(value["execution_input"]["uri"])
    if (
        location.bucket != bucket
        or len(location.segments) != 4
        or location.segments[0] != "runs"
        or location.segments[2:] != ("inputs", "execution-input.json")
    ):
        raise ControlRejected("execution input is outside the deployed run")
    runtime = value["runtime"]
    return HandlerConfig(
        operation,
        dict(value["execution_input"]),
        Release(value["release_manifest_sha256"], **runtime),
    )


def read_reference(
    objects: VersionedObjects,
    reference: Mapping[str, Any],
    *,
    maximum_bytes: int,
) -> bytes:
    """Stream and bind one exact object version without accepting latest aliases."""
    if not Draft202012Validator(OBJECT).is_valid(reference):
        raise ControlRejected("invalid object reference")
    if reference["version_id"] == "null" or not 1 <= reference["size_bytes"] <= maximum_bytes:
        raise ControlRejected("object reference is unversioned or outside its byte bound")
    digest = sha256()
    parts = []
    size = 0
    for chunk in objects.chunks(reference["uri"], reference["version_id"]):
        if type(chunk) is not bytes:
            raise ControlRejected("object stream returned non-bytes")
        size += len(chunk)
        if size > reference["size_bytes"]:
            raise ControlRejected("object stream exceeds its declared size")
        digest.update(chunk)
        parts.append(chunk)
    if size != reference["size_bytes"] or digest.hexdigest() != reference["sha256"]:
        raise ControlRejected("object bytes differ from their reference")
    return b"".join(parts)


def _invocation(event: Any, action: str) -> tuple[str, dict[str, Any]]:
    if type(event) is not dict or set(event) != {"action", "execution_arn", "state"}:
        raise ControlRejected("handler invocation shape differs")
    if event["action"] != action or _OWNER.fullmatch(event["execution_arn"]) is None:
        raise ControlRejected("handler action or execution owner differs")
    if type(event["state"]) is not dict:
        raise ControlRejected("handler state is not an object")
    # Detach from the Lambda request so subsequent caller mutation cannot change it.
    return event["execution_arn"], strict_json(canonical_bytes(event["state"]))


def validate_execution(
    event: Any,
    config: HandlerConfig,
    objects: VersionedObjects,
) -> dict[str, Any]:
    """Admit the one deployment-bound execution input before any managed side effect."""
    _owner, state = _invocation(event, "validate-execution")
    if state != {"execution_input_sha256": config.execution_input["sha256"]}:
        raise ControlRejected("workflow input is not the deployed execution identity")
    raw = read_reference(objects, config.execution_input, maximum_bytes=131072)
    candidate = strict_json(raw)
    arguments = job_arguments(candidate.get("job", {}))
    admitted = admit_execution(
        raw,
        config.release,
        arguments,
        cast(dict[str, Any], candidate["expected_results"]),
        cast(dict[str, Any], candidate["input_inventory"]),
    )
    if arguments.workload_bucket != config.bucket:
        raise ControlRejected("job bucket differs from deployed operation")
    identity = sha256(raw).hexdigest()
    database = f"ledgerguard_p3_{config.operation_id.replace('-', '_')}_reconciliation"
    workgroup = f"ledgerguard-p3-{config.operation_id}-checks"
    queries = {}
    for query in fixed_queries(database, arguments.run_id, arguments.attempt_id):
        family = query.family
        token = sha256(canonical_bytes({"identity": identity, "family": family})).hexdigest()
        queries[family] = {
            "sql": query.sql,
            "sql_sha256": query.sha256,
            "client_request_token": token,
            "output_location": (
                f"s3://{config.bucket}/query-results/{arguments.run_id}/"
                f"{arguments.attempt_id}/{family}/"
            ),
        }
    return {
        "control": {
            "schema_version": "ledgerguard.active-run.v1",
            "execution_input_sha256": identity,
            "execution": admitted,
            "glue_start": start_request(
                f"ledgerguard-p3-{config.operation_id}-reconciliation", arguments
            ),
            "athena_database": database,
            "athena_workgroup": workgroup,
            "queries": queries,
            "replay_committed": False,
        },
        "managed": {"athena": {}},
    }


def register_run(event: Any, authority: Any) -> dict[str, Any]:
    """Register and fence one exact attempt, or prove a committed replay."""
    owner, state = _invocation(event, "register-run")
    if set(state) != {"control", "managed"} or state.get("managed") != {"athena": {}}:
        raise ControlRejected("validated run state shape differs")
    control = state["control"]
    if type(control) is not dict or control.get("schema_version") != "ledgerguard.active-run.v1":
        raise ControlRejected("validated control state differs")
    execution = control.get("execution")
    if type(execution) is not dict:
        raise ControlRejected("validated execution is missing")
    arguments = job_arguments(execution.get("job", {}))
    namespace = execution.get("namespace")
    identity = control.get("execution_input_sha256")
    committed = authority.register(namespace, arguments.run_id, identity)
    if committed is not None:
        control["replay_committed"] = True
        control["committed_sha256"] = committed
        return state
    attempt: Attempt = authority.admit(
        namespace,
        arguments.run_id,
        identity,
        arguments.attempt_id,
        owner,
    )
    control["attempt"] = asdict(attempt)
    control["predecessor"] = execution["predecessor"]
    return state
