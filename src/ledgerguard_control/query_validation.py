"""Complete one ordered Athena-query validation transition.

The workflow starts each fixed query.  This handler only re-admits immutable
state, observes the already-started query, checks every result page against an
independently derived expectation, and retains an immutable proof.
"""

from __future__ import annotations

import tempfile
from collections.abc import Mapping
from hashlib import sha256
from pathlib import Path
from typing import Any

from ledgerguard.stage3.canonical import canonical_bytes

from .athena import (
    MAX_EXPECTED_BYTES,
    FixedQuery,
    fixed_queries,
    summarize_expected_rows,
    verify_query,
)
from .athena_aws import AthenaReads, observe_query, persist_query_proof
from .candidate_validation import _attempt, _materialize
from .contracts import MAX_DOCUMENT_BYTES, ControlRejected, job_arguments, strict_json, validate
from .execution import ACCOUNT_ID, HandlerConfig, _invocation, read_reference, validate_execution
from .objects import VersionedObjects, assert_unchanged, snapshot, snapshot_digest
from .publication import ImmutableObjects

FAMILIES = ("transactions", "settlements", "bank_allocations")
MAX_RESULT_BYTES = 8 * 1024 * 1024


def _document(
    objects: VersionedObjects, reference: Mapping[str, Any], kind: str
) -> dict[str, Any]:
    raw = read_reference(objects, reference, maximum_bytes=MAX_DOCUMENT_BYTES)
    value = strict_json(raw)
    if raw != canonical_bytes(value) + b"\n":
        raise ControlRejected(f"{kind} bytes are not canonical")
    return validate(kind, value)


def _query(control: Mapping[str, Any], family: str) -> FixedQuery:
    execution = control["execution"]
    arguments = job_arguments(execution["job"])
    matches = [
        value
        for value in fixed_queries(
            control["athena_database"], arguments.run_id, arguments.attempt_id
        )
        if value.family == family
    ]
    if len(matches) != 1:
        raise ControlRejected("fixed Athena query is missing")
    query = matches[0]
    expected = {
        "sql": query.sql,
        "sql_sha256": query.sha256,
        "client_request_token": sha256(
            canonical_bytes(
                {
                    "identity": control["execution_input_sha256"],
                    "family": family,
                }
            )
        ).hexdigest(),
        "output_location": control["queries"][family]["output_location"],
    }
    if control["queries"].get(family) != expected:
        raise ControlRejected("fixed Athena query state differs")
    return query


def _result_reference(
    objects: VersionedObjects,
    output_prefix: str,
    query_execution_id: str,
    output_location: str,
) -> dict[str, Any]:
    expected_uri = output_prefix + query_execution_id + ".csv"
    if not output_prefix.endswith("/") or output_location != expected_uri:
        raise ControlRejected("Athena result object address differs")
    before = snapshot(objects, output_prefix[:-1])
    if (
        len(before) != 1
        or before[0].uri != expected_uri
        or before[0].delete_marker
        or not before[0].is_latest
        or not 1 <= before[0].size_bytes <= MAX_RESULT_BYTES
    ):
        raise ControlRejected("Athena result object history differs")
    version = before[0]
    digest = sha256()
    size = 0
    for chunk in objects.chunks(version.uri, version.version_id):
        if type(chunk) is not bytes:
            raise ControlRejected("Athena result object returned non-bytes")
        size += len(chunk)
        if size > version.size_bytes:
            raise ControlRejected("Athena result object exceeds declared size")
        digest.update(chunk)
    if size != version.size_bytes:
        raise ControlRejected("Athena result object is truncated")
    assert_unchanged(objects, output_prefix[:-1], before)
    return {
        "uri": version.uri,
        "version_id": version.version_id,
        "sha256": digest.hexdigest(),
        "size_bytes": size,
    }


def _state(
    event: Any,
    config: HandlerConfig,
    objects: VersionedObjects,
    family: str,
) -> tuple[str, dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    owner, state = _invocation(event, f"validate-{family}-query")
    if set(state) != {"control", "managed"}:
        raise ControlRejected("Athena validation state shape differs")
    control = state.get("control")
    managed = state.get("managed")
    if type(control) is not dict or type(managed) is not dict:
        raise ControlRejected("Athena validation state differs")

    initial = validate_execution(
        {
            "action": "validate-execution",
            "execution_arn": owner,
            "state": {"execution_input_sha256": config.execution_input["sha256"]},
        },
        config,
        objects,
    )["control"]
    position = FAMILIES.index(family)
    previous = FAMILIES[:position]
    allowed = set(initial) | {
        "namespace",
        "predecessor",
        "attempt",
        "validation_receipt",
    }
    if previous or "query_proofs" in control:
        allowed.add("query_proofs")
    if set(control) != allowed or any(
        control.get(name) != value for name, value in initial.items()
    ):
        raise ControlRejected("Athena control state was substituted")

    execution = control["execution"]
    attempt = _attempt(control, execution, owner)
    if (
        control.get("namespace") != execution.get("namespace")
        or control.get("predecessor") != execution.get("predecessor")
    ):
        raise ControlRejected("Athena registration boundary differs")
    receipt = _document(objects, control["validation_receipt"], "validation-receipt")
    identity_names = (
        "run_id",
        "attempt_id",
        "control_record_identity",
        "policy_sha256",
        "manifest_sha256",
        "source_bundle_sha256",
    )
    expected_receipt = {
        **{name: execution["job"][name] for name in identity_names},
        "execution_arn": owner,
        "fence": attempt["fence"],
        "predecessor": execution["predecessor"],
        "expected_results_sha256": execution["expected_results"]["sha256"],
    }
    if any(receipt.get(name) != value for name, value in expected_receipt.items()):
        raise ControlRejected("candidate validation receipt identity differs")
    glue = managed.get("glue")
    if (
        type(glue) is not dict
        or set(glue) != {"JobRunId"}
        or glue["JobRunId"] != receipt["glue_job_run_id"]
    ):
        raise ControlRejected("terminal Glue state differs")
    inventory = _document(objects, receipt["physical_inventory"], "physical-inventory")
    if (
        inventory["run_id"] != execution["job"]["run_id"]
        or inventory["attempt_id"] != execution["job"]["attempt_id"]
        or inventory["version_inventory_sha256"] != receipt["version_inventory_sha256"]
        or inventory["financial_comparison"]["expected_sha256"]
        != execution["expected_results"]["sha256"]
    ):
        raise ControlRejected("candidate physical inventory identity differs")

    athena = managed.get("athena")
    completed = (*previous, family)
    if type(athena) is not dict or set(athena) != set(completed):
        raise ControlRejected("managed Athena query order differs")
    for name in completed:
        value = athena.get(name)
        if (
            type(value) is not dict
            or set(value) != {"QueryExecutionId"}
            or type(value["QueryExecutionId"]) is not str
        ):
            raise ControlRejected("managed Athena query result differs")
    if len({athena[name]["QueryExecutionId"] for name in completed}) != len(completed):
        raise ControlRejected("managed Athena query identities are not unique")

    proofs = control.get("query_proofs")
    if previous:
        if type(proofs) is not dict or set(proofs) != set(previous):
            raise ControlRejected("retained Athena proof order differs")
        for name in previous:
            proof = _document(objects, proofs[name], "query-proof")
            if (
                proof["family"] != name
                or any(proof[key] != execution["job"][key] for key in identity_names)
                or proof["query_execution_id"] != athena[name]["QueryExecutionId"]
                or proof["version_inventory_before_sha256"]
                != receipt["version_inventory_sha256"]
                or proof["version_inventory_after_sha256"]
                != receipt["version_inventory_sha256"]
            ):
                raise ControlRejected("retained Athena proof identity differs")
    elif proofs is not None:
        raise ControlRejected("unexpected retained Athena proof")
    return owner, state, control, execution, receipt


def validate_query(
    event: Any,
    config: HandlerConfig,
    objects: VersionedObjects,
    athena: AthenaReads,
    immutable: ImmutableObjects,
    workspace_parent: Path | None = None,
) -> dict[str, Any]:
    """Verify and retain exactly one query in the workflow-defined order."""
    if type(event) is not dict or type(event.get("action")) is not str:
        raise ControlRejected("unsupported Athena validation action")
    action = event["action"]
    matches = [name for name in FAMILIES if action == f"validate-{name}-query"]
    if len(matches) != 1:
        raise ControlRejected("unsupported Athena validation action")
    family = matches[0]
    _owner, state, control, execution, receipt = _state(event, config, objects, family)
    query = _query(control, family)
    query_execution_id = state["managed"]["athena"][family]["QueryExecutionId"]

    candidate_prefix = execution["job"]["candidate_output_prefix"]
    candidate_before = snapshot(objects, candidate_prefix)
    inventory_digest = snapshot_digest(candidate_before)
    if inventory_digest != receipt["version_inventory_sha256"]:
        raise ControlRejected("candidate versions changed before Athena validation")

    observed, pages = observe_query(athena, query_execution_id)
    output_prefix = control["queries"][family]["output_location"]
    result_reference = _result_reference(
        objects, output_prefix, query_execution_id, observed.output_location
    )
    with tempfile.TemporaryDirectory(prefix="ledgerguard-athena-", dir=workspace_parent) as raw:
        expected_path = Path(raw) / "expected-results.jsonl"
        _materialize(
            objects,
            execution["expected_results"],
            expected_path,
            MAX_EXPECTED_BYTES,
        )
        expected = summarize_expected_rows(
            expected_path, execution["expected_results"]["sha256"], query
        )
    verification = verify_query(
        query,
        observed,
        pages,
        expected,
        workgroup=control["athena_workgroup"],
        output_location=result_reference["uri"],
        account_id=ACCOUNT_ID,
    )
    assert_unchanged(objects, candidate_prefix, candidate_before)
    after_digest = snapshot_digest(snapshot(objects, candidate_prefix))
    if after_digest != inventory_digest:
        raise ControlRejected("candidate versions changed during Athena validation")

    identity = {
        name: execution["job"][name]
        for name in (
            "run_id",
            "attempt_id",
            "control_record_identity",
            "policy_sha256",
            "manifest_sha256",
            "source_bundle_sha256",
        )
    }
    proof = persist_query_proof(
        immutable,
        bucket=config.bucket,
        account_id=ACCOUNT_ID,
        family=family,
        identity=identity,
        query=query,
        execution=observed,
        verification=verification,
        result_reference=result_reference,
        version_inventory_before_sha256=inventory_digest,
        version_inventory_after_sha256=after_digest,
    )
    proofs = control.setdefault("query_proofs", {})
    proofs[family] = proof
    return state
