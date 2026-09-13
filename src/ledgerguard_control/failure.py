"""Immutable terminal-failure evidence and fenced attempt release.

Only transitions that already own an admitted attempt can record authoritative
failure evidence. Earlier admission failures deliberately reach the workflow's
``FailureEvidenceUnavailable`` terminal because no run fence exists to own them.
"""

from __future__ import annotations

from collections.abc import Mapping
from hashlib import sha256
from typing import Any

from ledgerguard.stage3.canonical import canonical_bytes

from .authority import Attempt
from .candidate_validation import _attempt
from .contracts import ControlRejected, validate
from .execution import HandlerConfig, _invocation, validate_execution
from .objects import VersionedObjects
from .publication import ImmutableObjects

FAILURE_STATES = (
    "StartGlue",
    "ValidateCandidate",
    "TransactionsQuery",
    "SettlementsQuery",
    "BankAllocationsQuery",
    "PreparePublication",
    "PublishAuthority",
)
_QUERY_PREFIXES = {
    "StartGlue": (),
    "ValidateCandidate": (),
    "TransactionsQuery": (),
    "SettlementsQuery": ("transactions",),
    "BankAllocationsQuery": ("transactions", "settlements"),
    "PreparePublication": ("transactions", "settlements", "bank_allocations"),
    "PublishAuthority": ("transactions", "settlements", "bank_allocations"),
}


def _text(value: Any, name: str) -> str:
    if type(value) is not str or not 1 <= len(value) <= 1024:
        raise ControlRejected(f"failure {name} differs")
    return value


def _managed_identity(
    managed: Mapping[str, Any], failed_state: str
) -> tuple[str | None, list[str]]:
    if set(managed) - {"athena", "glue"}:
        raise ControlRejected("failure managed state differs")
    glue = managed.get("glue")
    glue_id: str | None = None
    if glue is not None:
        if type(glue) is not dict or set(glue) != {"JobRunId"}:
            raise ControlRejected("failure Glue state differs")
        glue_id = _text(glue["JobRunId"], "Glue identity")
    if failed_state == "StartGlue" and glue is not None:
        raise ControlRejected("failed Glue start cannot claim a terminal run")
    if failed_state != "StartGlue" and glue is None:
        raise ControlRejected("post-Glue failure is missing its run identity")

    athena = managed.get("athena")
    expected = _QUERY_PREFIXES[failed_state]
    if type(athena) is not dict or set(athena) != set(expected):
        raise ControlRejected("failure Athena order differs")
    query_ids = []
    for family in expected:
        value = athena[family]
        if type(value) is not dict or set(value) != {"QueryExecutionId"}:
            raise ControlRejected("failure Athena result differs")
        query_ids.append(_text(value["QueryExecutionId"], "Athena identity"))
    if len(set(query_ids)) != len(query_ids):
        raise ControlRejected("failure Athena identities are not unique")
    return glue_id, query_ids


def _failure_state(
    event: Any,
    config: HandlerConfig,
    objects: VersionedObjects,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], str, str]:
    owner, envelope = _invocation(event, "record-failure")
    if set(envelope) != {"failed_state", "error", "cause", "state"}:
        raise ControlRejected("failure envelope shape differs")
    failed_state = envelope.get("failed_state")
    if failed_state not in FAILURE_STATES:
        raise ControlRejected("failure state is not attempt-owned")
    error = _text(envelope.get("error"), "error")
    cause = _text(envelope.get("cause"), "cause")
    state = envelope.get("state")
    if type(state) is not dict or set(state) != {"control", "managed", "failure"}:
        raise ControlRejected("captured failure state shape differs")
    if state["failure"] != {"Error": error, "Cause": cause}:
        raise ControlRejected("captured failure identity differs")
    control = state.get("control")
    managed = state.get("managed")
    if type(control) is not dict or type(managed) is not dict:
        raise ControlRejected("captured control state differs")

    initial = validate_execution(
        {
            "action": "validate-execution",
            "execution_arn": owner,
            "state": {"execution_input_sha256": config.execution_input["sha256"]},
        },
        config,
        objects,
    )["control"]
    required = set(initial) | {"namespace", "predecessor", "attempt"}
    allowed = required | {"validation_receipt", "query_proofs", "preparation"}
    if not required <= set(control) <= allowed or any(
        control.get(name) != value for name, value in initial.items()
    ):
        raise ControlRejected("failure control state was substituted")
    execution = control["execution"]
    if (
        control.get("namespace") != execution.get("namespace")
        or control.get("predecessor") != execution.get("predecessor")
    ):
        raise ControlRejected("failure registration boundary differs")
    _attempt(control, execution, owner)
    return state, control, execution, failed_state, owner


def record_failure(
    event: Any,
    config: HandlerConfig,
    objects: VersionedObjects,
    immutable: ImmutableObjects,
    authority: Any,
) -> dict[str, Any]:
    """Persist exact failure evidence before idempotently releasing its fence."""
    state, control, execution, failed_state, owner = _failure_state(
        event, config, objects
    )
    managed = state["managed"]
    glue_id, query_ids = _managed_identity(managed, failed_state)
    attempt_value = _attempt(control, execution, owner)
    attempt = Attempt(**attempt_value)
    job = execution["job"]
    envelope = event["state"]
    document = validate(
        "failure-record",
        {
            "schema_version": "ledgerguard.failure-record.v1",
            **{
                name: job[name]
                for name in (
                    "run_id",
                    "attempt_id",
                    "control_record_identity",
                    "policy_sha256",
                    "manifest_sha256",
                    "source_bundle_sha256",
                )
            },
            "execution_arn": owner,
            "fence": attempt.fence,
            "predecessor": execution["predecessor"],
            "failed_state": failed_state,
            "error": envelope["error"],
            "cause": envelope["cause"],
            "glue_job_run_id": glue_id,
            "query_execution_ids": query_ids,
            "candidate_prefix": job["candidate_output_prefix"],
            "recovery_required": True,
        },
    )
    raw = canonical_bytes(document) + b"\n"
    digest = sha256(raw).hexdigest()
    uri = (
        f"s3://{config.bucket}/publications/failure-records/{attempt.run_id}/"
        f"{attempt.attempt_id}/{digest}.json"
    )
    version_id = immutable.put_immutable(uri, raw)
    authority.fail(attempt)
    control["failure_record"] = {
        "uri": uri,
        "version_id": version_id,
        "sha256": digest,
        "size_bytes": len(raw),
    }
    return state
