"""Complete candidate-validation Lambda transition.

This boundary re-admits the immutable execution, proves the terminal Glue run,
reopens every exact S3 object version, compares real Parquet rows with the
independently supplied financial evidence, and retains canonical proof objects
outside the transient runs namespace. It never starts a Glue job.
"""

from __future__ import annotations

import tempfile
from collections.abc import Mapping
from hashlib import sha256
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from ledgerguard.stage3.canonical import canonical_bytes

from .athena import MAX_EXPECTED_BYTES
from .candidates import MAX_CANDIDATE_BYTES, PhysicalCandidate, verify_physical_candidate
from .contracts import OBJECT, ControlRejected, job_arguments, validate
from .execution import HandlerConfig, _invocation, validate_execution
from .financial_rows import ParquetMember, compare_parquet
from .glue_run import GlueReads, bind_candidate_job_run, observe_terminal
from .objects import VersionedObjects, assert_unchanged
from .publication import ImmutableObjects


def _attempt(
    control: Mapping[str, Any], execution: Mapping[str, Any], owner: str
) -> dict[str, Any]:
    value = control.get("attempt")
    if type(value) is not dict or set(value) != {
        "namespace",
        "run_id",
        "identity_sha256",
        "attempt_id",
        "owner",
        "fence",
    }:
        raise ControlRejected("admitted attempt shape differs")
    arguments = job_arguments(execution.get("job", {}))
    expected = {
        "namespace": execution.get("namespace"),
        "run_id": arguments.run_id,
        "identity_sha256": control.get("execution_input_sha256"),
        "attempt_id": arguments.attempt_id,
        "owner": owner,
    }
    if any(value.get(name) != item for name, item in expected.items()):
        raise ControlRejected("admitted attempt identity differs")
    if type(value.get("fence")) is not int or not 1 <= value["fence"] <= 2**63 - 1:
        raise ControlRejected("admitted attempt fence differs")
    return dict(value)


def _state(
    event: Any, config: HandlerConfig, objects: VersionedObjects
) -> tuple[str, dict[str, Any], dict[str, Any], dict[str, Any], str]:
    owner, state = _invocation(event, "validate-candidate")
    if set(state) != {"control", "managed"}:
        raise ControlRejected("candidate validation state shape differs")
    managed = state.get("managed")
    if type(managed) is not dict or set(managed) != {"athena", "glue"}:
        raise ControlRejected("managed candidate state shape differs")
    glue = managed.get("glue")
    if managed.get("athena") != {} or type(glue) is not dict or set(glue) != {"JobRunId"}:
        raise ControlRejected("managed Glue result shape differs")
    job_run_id = glue.get("JobRunId")
    if type(job_run_id) is not str:
        raise ControlRejected("managed Glue run identity differs")

    initial = validate_execution(
        {
            "action": "validate-execution",
            "execution_arn": owner,
            "state": {"execution_input_sha256": config.execution_input["sha256"]},
        },
        config,
        objects,
    )["control"]
    control = state.get("control")
    if type(control) is not dict or set(control) != set(initial) | {
        "namespace",
        "predecessor",
        "attempt",
    }:
        raise ControlRejected("candidate control state shape differs")
    if any(control.get(name) != item for name, item in initial.items()):
        raise ControlRejected("candidate control state was substituted")
    execution = control["execution"]
    if (
        control.get("namespace") != execution.get("namespace")
        or control.get("predecessor") != execution.get("predecessor")
    ):
        raise ControlRejected("candidate registration boundary differs")
    _attempt(control, execution, owner)
    return owner, state, control, execution, job_run_id


def _materialize(
    objects: VersionedObjects,
    reference: Mapping[str, Any],
    destination: Path,
    maximum_bytes: int,
) -> None:
    if not Draft202012Validator(OBJECT).is_valid(reference):
        raise ControlRejected("invalid materialized object reference")
    expected_size = reference["size_bytes"]
    if (
        reference["version_id"] == "null"
        or not 1 <= expected_size <= maximum_bytes
    ):
        raise ControlRejected("materialized object exceeds byte bound")
    digest = sha256()
    size = 0
    with destination.open("xb") as output:
        for chunk in objects.chunks(reference["uri"], reference["version_id"]):
            if type(chunk) is not bytes:
                raise ControlRejected("materialized object returned non-bytes")
            size += len(chunk)
            if size > expected_size:
                raise ControlRejected("materialized object exceeds declared size")
            digest.update(chunk)
            output.write(chunk)
    if size != expected_size or digest.hexdigest() != reference["sha256"]:
        raise ControlRejected("materialized object bytes differ")


def _put_document(
    objects: ImmutableObjects,
    bucket: str,
    suffix: str,
    kind: str,
    value: dict[str, Any],
) -> dict[str, Any]:
    document = validate(kind, value)
    raw = canonical_bytes(document) + b"\n"
    digest = sha256(raw).hexdigest()
    uri = f"s3://{bucket}/publications/validation-receipts/{suffix}/{digest}.json"
    version_id = objects.put_immutable(uri, raw)
    return {"uri": uri, "version_id": version_id, "sha256": digest, "size_bytes": len(raw)}


def _parquet_members(
    objects: VersionedObjects, candidate: PhysicalCandidate, root: Path
) -> tuple[ParquetMember, ...]:
    members = []
    for index, reference in enumerate(candidate.physical_references):
        relative = reference["uri"].rsplit("/candidates/", 1)
        if len(relative) != 2:
            raise ControlRejected("candidate object address differs")
        family = relative[1].split("/", 1)[0]
        destination = root / f"candidate-{index:04d}.parquet"
        _materialize(objects, reference, destination, MAX_CANDIDATE_BYTES)
        members.append(
            ParquetMember(family, destination, reference["sha256"], reference["size_bytes"])
        )
    return tuple(members)


def validate_candidate(
    event: Any,
    config: HandlerConfig,
    objects: VersionedObjects,
    glue: GlueReads,
    immutable: ImmutableObjects,
    workspace_parent: Path | None = None,
) -> dict[str, Any]:
    """Prove and retain one candidate without starting managed work."""
    owner, state, control, execution, job_run_id = _state(event, config, objects)
    arguments = job_arguments(execution["job"])
    terminal = observe_terminal(glue, control["glue_start"], job_run_id)
    candidate = verify_physical_candidate(objects, arguments)
    bind_candidate_job_run(candidate.manifest, terminal)

    with tempfile.TemporaryDirectory(prefix="ledgerguard-candidate-", dir=workspace_parent) as raw:
        root = Path(raw)
        expected = root / "expected-results.jsonl"
        _materialize(objects, execution["expected_results"], expected, MAX_EXPECTED_BYTES)
        comparison = compare_parquet(
            expected,
            execution["expected_results"]["sha256"],
            _parquet_members(objects, candidate, root),
            root / "comparison",
        )
    assert_unchanged(objects, arguments.candidate_output_prefix, candidate.versions)

    inventory = _put_document(
        immutable,
        config.bucket,
        f"{arguments.run_id}/{arguments.attempt_id}/physical-inventory",
        "physical-inventory",
        {
            "schema_version": "ledgerguard.physical-inventory.v1",
            "run_id": arguments.run_id,
            "attempt_id": arguments.attempt_id,
            "version_inventory_sha256": candidate.version_inventory_sha256,
            "objects": list(candidate.physical_references),
            "financial_comparison": comparison,
        },
    )
    attempt = _attempt(control, execution, owner)
    receipt = _put_document(
        immutable,
        config.bucket,
        f"{arguments.run_id}/{arguments.attempt_id}/receipt",
        "validation-receipt",
        {
            "schema_version": "ledgerguard.validation-receipt.v1",
            **{
                name: execution["job"][name]
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
            "fence": attempt["fence"],
            "predecessor": execution["predecessor"],
            "glue_job_name": terminal.job_name,
            "glue_job_run_id": terminal.job_run_id,
            "glue_arguments_sha256": terminal.arguments_sha256,
            "glue_observation_sha256": terminal.observation_sha256,
            "glue_started_at": terminal.started_at,
            "glue_completed_at": terminal.completed_at,
            "glue_execution_seconds": terminal.execution_seconds,
            "glue_dpu_seconds": terminal.dpu_seconds,
            "completion": candidate.completion_reference,
            "candidate_manifest": candidate.manifest_reference,
            "physical_inventory": inventory,
            "version_inventory_sha256": candidate.version_inventory_sha256,
            "logical_sha256": candidate.manifest["logical_sha256"],
            "expected_results_sha256": comparison["expected_sha256"],
        },
    )
    control["validation_receipt"] = receipt
    return state
