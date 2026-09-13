"""Prepare an immutable financial snapshot from independently pinned source truth.

This module is the financial half of ``PreparePublication``.  It re-admits the
actual Part 2 source bundle, independently compares every resulting candidate to
the already admitted financial evidence, advances the accepted
``FinalizationStore`` and seals its complete history.  It does not publish the
namespace metadata root.
"""

from __future__ import annotations

import base64
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

from ledgerguard.reconciliation import (
    FinalizationReceipt,
    FinalizationStore,
    admit_bundle,
    reconcile_settlements,
    reconcile_transactions,
)
from ledgerguard.reconciliation.admission import object_locator
from ledgerguard.stage3.canonical import canonical_bytes, canonical_digest
from ledgerguard.stage3.paths import parse_s3_uri

from .candidate_validation import _attempt, _put_document
from .contracts import MAX_DOCUMENT_BYTES, ControlRejected, job_arguments, strict_json, validate
from .execution import HandlerConfig, _invocation, read_reference
from .financial_rows import SHAPES, validate_row
from .objects import VersionedObjects
from .publication import FinancialSnapshots, ImmutableObjects
from .query_validation import FAMILIES, _document
from .query_validation import _state as query_state

MAX_SOURCE_OBJECT_BYTES = 64 * 1024 * 1024
MAX_SOURCE_BUNDLE_BYTES = 256 * 1024 * 1024
MAX_EXPECTED_ROWS = 1_000_000


@dataclass(frozen=True)
class AdmittedInputs:
    policy: dict[str, Any]
    manifest: dict[str, Any]
    objects: dict[str, bytes]
    correction: dict[str, Any] | None
    inventory_sha256: str


@dataclass(frozen=True)
class PreparedSnapshot:
    snapshot_sha256: str
    financial_head: str
    finalization_receipt: FinalizationReceipt
    input_inventory_sha256: str
    expected_results_sha256: str


def _successful_state(
    event: Any,
    config: HandlerConfig,
    objects: VersionedObjects,
    action: str,
    *,
    prepared: bool,
) -> tuple[str, dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    owner, incoming = _invocation(event, action)
    control = incoming.get("control")
    if type(control) is not dict:
        raise ControlRejected("successful publication control state differs")
    preparation = control.pop("preparation", None)
    if prepared != (preparation is not None):
        raise ControlRejected("publication preparation state differs")
    proofs = control.get("query_proofs")
    if type(proofs) is not dict or set(proofs) != set(FAMILIES):
        raise ControlRejected("completed query proof inventory differs")
    final_reference = proofs.pop("bank_allocations")
    _query_owner, state, admitted_control, execution, receipt = query_state(
        {
            "action": "validate-bank_allocations-query",
            "execution_arn": owner,
            "state": incoming,
        },
        config,
        objects,
        "bank_allocations",
    )
    final_proof = _document(objects, final_reference, "query-proof")
    identity_names = (
        "run_id",
        "attempt_id",
        "control_record_identity",
        "policy_sha256",
        "manifest_sha256",
        "source_bundle_sha256",
    )
    if (
        final_proof["family"] != "bank_allocations"
        or final_proof["query_execution_id"]
        != state["managed"]["athena"]["bank_allocations"]["QueryExecutionId"]
        or final_proof["version_inventory_before_sha256"]
        != receipt["version_inventory_sha256"]
        or final_proof["version_inventory_after_sha256"]
        != receipt["version_inventory_sha256"]
        or any(final_proof[name] != execution["job"][name] for name in identity_names)
    ):
        raise ControlRejected("final Athena proof identity differs")
    admitted_control["query_proofs"]["bank_allocations"] = final_reference
    if prepared:
        admitted_control["preparation"] = preparation
    return owner, state, admitted_control, execution, receipt


def _canonical_document(raw: bytes, name: str) -> dict[str, Any]:
    value = strict_json(raw)
    if raw != canonical_bytes(value) + b"\n":
        raise ControlRejected(f"{name} bytes are not canonical")
    return value


def _confined(reference: Mapping[str, Any], prefix: str, suffix: str) -> None:
    location = parse_s3_uri(str(reference.get("uri")))
    parent = parse_s3_uri(prefix)
    expected = (*parent.segments, *suffix.split("/"))
    if location.bucket != parent.bucket or location.segments != expected:
        raise ControlRejected("input inventory object is outside the admitted prefix")


def admit_inputs(
    objects: VersionedObjects,
    inventory_reference: Mapping[str, Any],
    *,
    input_prefix: str,
    run_id: str,
    source_commit: str,
    policy_sha256: str,
    manifest_sha256: str,
) -> AdmittedInputs:
    """Read the exact inventory and all versioned Part 2 source bytes once."""
    inventory_raw = read_reference(
        objects, inventory_reference, maximum_bytes=MAX_DOCUMENT_BYTES
    )
    inventory = validate(
        "input-inventory", _canonical_document(inventory_raw, "input inventory")
    )
    _confined(inventory["policy"], input_prefix, "policy.json")
    _confined(inventory["manifest"], input_prefix, "run-manifest.json")
    policy_raw = read_reference(objects, inventory["policy"], maximum_bytes=MAX_DOCUMENT_BYTES)
    manifest_raw = read_reference(
        objects, inventory["manifest"], maximum_bytes=MAX_DOCUMENT_BYTES
    )
    policy = _canonical_document(policy_raw, "policy")
    manifest = _canonical_document(manifest_raw, "run manifest")
    if (
        policy.get("policy_sha256") != policy_sha256
        or manifest.get("manifest_sha256") != manifest_sha256
        or manifest.get("policy_sha256") != policy_sha256
        or manifest.get("run_id") != run_id
        or manifest.get("source_commit") != source_commit
    ):
        raise ControlRejected("input documents differ from the admitted run")

    declared = manifest.get("objects")
    if type(declared) is not list:
        raise ControlRejected("run manifest objects are unavailable")
    expected: dict[str, Mapping[str, Any]] = {}
    suffixes: dict[str, str] = {}
    for item in declared:
        if type(item) is not dict:
            raise ControlRejected("run manifest object shape differs")
        locator = object_locator(item)
        if locator in expected:
            raise ControlRejected("duplicate run manifest locator")
        expected[locator] = item
        if item.get("locator_type") == "LOCAL_FILE":
            suffixes[locator] = str(item.get("relative_path"))
        else:
            suffixes[locator] = ""

    rows = inventory["objects"]
    if len(rows) != len(expected):
        raise ControlRejected("input inventory object set differs")
    supplied: dict[str, bytes] = {}
    total = 0
    for row in rows:
        locator = row["locator"]
        reference = row["reference"]
        if locator not in expected or locator in supplied:
            raise ControlRejected("input inventory locator differs")
        descriptor = expected[locator]
        if descriptor.get("locator_type") == "LOCAL_FILE":
            relative = suffixes[locator]
            if (
                not relative
                or relative.startswith("/")
                or ".." in relative.split("/")
            ):
                raise ControlRejected("unsafe input inventory relative path")
            _confined(reference, input_prefix, relative)
        elif (
            reference.get("uri") != descriptor.get("s3_uri")
            or reference.get("version_id") != descriptor.get("version_id")
        ):
            raise ControlRejected("S3 manifest locator differs from its exact reference")
        size = reference["size_bytes"]
        if size != descriptor.get("size_bytes") or reference["sha256"] != descriptor.get(
            "sha256"
        ):
            raise ControlRejected("input inventory physical identity differs")
        total += size
        if total > MAX_SOURCE_BUNDLE_BYTES:
            raise ControlRejected("input source bundle exceeds byte bound")
        supplied[locator] = read_reference(
            objects, reference, maximum_bytes=MAX_SOURCE_OBJECT_BYTES
        )
    correction_reference = inventory["correction"]
    correction = None
    if correction_reference is not None:
        _confined(correction_reference, input_prefix, "correction.json")
        correction = _canonical_document(
            read_reference(
                objects, correction_reference, maximum_bytes=MAX_DOCUMENT_BYTES
            ),
            "correction",
        )
    return AdmittedInputs(
        policy,
        manifest,
        supplied,
        correction,
        sha256(inventory_raw).hexdigest(),
    )


def _expected_rows(raw: bytes, trusted_sha256: str) -> dict[str, dict[str, Any]]:
    digest = sha256()
    rows: dict[str, dict[str, Any]] = {}
    count = 0
    for framed in raw.splitlines(keepends=True):
        if not framed.endswith(b"\n"):
            raise ControlRejected("expected financial row framing differs")
        value = strict_json(framed)
        if set(value) != {"family", "row"} or framed != canonical_bytes(value) + b"\n":
            raise ControlRejected("expected financial row shape differs")
        family = value["family"]
        row = value["row"]
        identity = validate_row(family, row)
        key = f"{family}:{identity}"
        if key in rows:
            raise ControlRejected("duplicate expected financial identity")
        rows[key] = row
        digest.update(framed)
        count += 1
        if count > MAX_EXPECTED_ROWS:
            raise ControlRejected("expected financial row count exceeds bound")
    if digest.hexdigest() != trusted_sha256:
        raise ControlRejected("expected financial evidence digest differs")
    if not rows or {key.split(":", 1)[0] for key in rows} != set(SHAPES):
        raise ControlRejected("expected financial family inventory differs")
    return rows


def _derived_rows(transaction: Any, settlement: Any) -> dict[str, dict[str, Any]]:
    values: list[tuple[str, dict[str, Any]]] = [
        *[("transactions", row.value()) for row in transaction.candidates],
        *[("settlements", row.value()) for row in settlement.candidates],
        *[("bank-allocations", row.value()) for row in settlement.bank_allocations],
    ]
    result: dict[str, dict[str, Any]] = {}
    for family, row in values:
        identity = validate_row(family, row)
        key = f"{family}:{identity}"
        if key in result:
            raise ControlRejected("duplicate derived financial identity")
        result[key] = row
    return result


def _correction_inputs(inputs: AdmittedInputs) -> dict[str, Any]:
    return {
        "policy": inputs.policy,
        "manifest": inputs.manifest,
        "object_encoding": "base64",
        "objects": {
            key: base64.b64encode(raw).decode("ascii")
            for key, raw in sorted(inputs.objects.items())
        },
    }


def prepare_financial_snapshot(
    *,
    repository: Path,
    objects: VersionedObjects,
    snapshots: FinancialSnapshots,
    authority: Any,
    namespace: str,
    predecessor: str | None,
    attempt_id: str,
    created_at: str,
    inputs: AdmittedInputs,
    expected_raw: bytes,
    expected_sha256: str,
    workspace: Path,
) -> PreparedSnapshot:
    """Build, finalize, verify and seal one unreachable financial candidate."""
    current = authority.read_root(namespace)
    current_digest = None if current is None else canonical_digest(current)
    if current_digest != predecessor:
        raise ControlRejected("financial predecessor is no longer authoritative")
    if predecessor is None:
        store = FinalizationStore(repository, workspace / "financial-store")
    else:
        store = snapshots.open_committed(
            authority, repository, workspace / "financial-store"
        )
        # Close a root race between the initial CAS observation and snapshot restore.
        observed = authority.read_root(namespace)
        if observed is None or canonical_digest(observed) != predecessor:
            raise ControlRejected("financial predecessor changed during restore")

    prior_admission, prior_transactions, prior_settlements = store.load_states()
    admitted = admit_bundle(
        repository,
        canonical_bytes(inputs.policy),
        canonical_bytes(inputs.manifest),
        inputs.objects,
        prior_state=prior_admission,
    )
    transaction = reconcile_transactions(admitted, prior_transactions)
    settlement = reconcile_settlements(admitted, prior_settlements)
    if _derived_rows(transaction, settlement) != _expected_rows(
        expected_raw, expected_sha256
    ):
        raise ControlRejected("derived financial authority differs from admitted evidence")
    receipt = store.finalize(
        attempt_id=attempt_id,
        expected_head=store.read_head(),
        created_at=created_at,
        transaction_batch=transaction,
        settlement_batch=settlement,
        correction=inputs.correction,
        correction_inputs=(
            _correction_inputs(inputs) if inputs.correction is not None else None
        ),
    )
    store.verify_history()
    snapshot_sha256 = snapshots.seal(store)
    if receipt.commit_sha256 != store.read_head():
        raise ControlRejected("prepared financial head differs from finalization outcome")
    return PreparedSnapshot(
        snapshot_sha256,
        receipt.commit_sha256,
        receipt,
        inputs.inventory_sha256,
        expected_sha256,
    )


def prepare_publication(
    event: Any,
    config: HandlerConfig,
    objects: VersionedObjects,
    immutable: ImmutableObjects,
    authority: Any,
    repository: Path,
    workspace_parent: Path | None = None,
) -> dict[str, Any]:
    """Execute the production preparation transition without publishing authority."""
    owner, state, control, execution, receipt = _successful_state(
        event, config, objects, "prepare-publication", prepared=False
    )
    job = execution["job"]
    arguments = job_arguments(job)
    inputs = admit_inputs(
        objects,
        execution["input_inventory"],
        input_prefix=arguments.input_prefix,
        run_id=arguments.run_id,
        source_commit=arguments.source_commit,
        policy_sha256=arguments.policy_sha256,
        manifest_sha256=arguments.manifest_sha256,
    )
    expected_raw = read_reference(
        objects,
        execution["expected_results"],
        maximum_bytes=MAX_SOURCE_BUNDLE_BYTES,
    )
    snapshots = FinancialSnapshots(immutable, config.bucket, execution["namespace"])
    with tempfile.TemporaryDirectory(
        prefix="ledgerguard-prepare-", dir=workspace_parent
    ) as raw:
        prepared = prepare_financial_snapshot(
            repository=repository,
            objects=objects,
            snapshots=snapshots,
            authority=authority,
            namespace=execution["namespace"],
            predecessor=execution["predecessor"],
            attempt_id=arguments.attempt_id,
            created_at=receipt["glue_completed_at"],
            inputs=inputs,
            expected_raw=expected_raw,
            expected_sha256=execution["expected_results"]["sha256"],
            workspace=Path(raw),
        )
    attempt = _attempt(control, execution, owner)
    query_references = [control["query_proofs"][family] for family in FAMILIES]
    reference = _put_document(
        immutable,
        config.bucket,
        f"{arguments.run_id}/{arguments.attempt_id}",
        "preparation-receipt",
        {
            "schema_version": "ledgerguard.preparation-receipt.v1",
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
            "fence": attempt["fence"],
            "predecessor": execution["predecessor"],
            "namespace": execution["namespace"],
            "validation_receipt": control["validation_receipt"],
            "query_proofs": query_references,
            "input_inventory_sha256": prepared.input_inventory_sha256,
            "expected_results_sha256": prepared.expected_results_sha256,
            "financial_snapshot_sha256": prepared.snapshot_sha256,
            "financial_head": prepared.financial_head,
            "proof_count": len(prepared.finalization_receipt.proofs),
            "case_count": len(prepared.finalization_receipt.cases),
        },
    )
    control["preparation"] = reference
    return state


def publish_authority(
    event: Any,
    config: HandlerConfig,
    objects: VersionedObjects,
    immutable: ImmutableObjects,
    authority: Any,
    repository: Path,
    workspace_parent: Path | None = None,
) -> dict[str, Any]:
    """Verify one preparation, publish its fixed-size root, then reopen it."""
    owner, state, control, execution, _receipt = _successful_state(
        event, config, objects, "publish-authority", prepared=True
    )
    preparation_reference = control["preparation"]
    preparation = _document(objects, preparation_reference, "preparation-receipt")
    job = execution["job"]
    attempt_value = _attempt(control, execution, owner)
    expected = {
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
        "fence": attempt_value["fence"],
        "predecessor": execution["predecessor"],
        "namespace": execution["namespace"],
        "validation_receipt": control["validation_receipt"],
        "query_proofs": [control["query_proofs"][family] for family in FAMILIES],
        "expected_results_sha256": execution["expected_results"]["sha256"],
    }
    if any(preparation.get(name) != value for name, value in expected.items()):
        raise ControlRejected("publication preparation identity differs")
    arguments = job_arguments(job)
    admitted_inputs = admit_inputs(
        objects,
        execution["input_inventory"],
        input_prefix=arguments.input_prefix,
        run_id=arguments.run_id,
        source_commit=arguments.source_commit,
        policy_sha256=arguments.policy_sha256,
        manifest_sha256=arguments.manifest_sha256,
    )
    if admitted_inputs.inventory_sha256 != preparation["input_inventory_sha256"]:
        raise ControlRejected("publication input inventory identity differs")
    snapshots = FinancialSnapshots(immutable, config.bucket, execution["namespace"])
    with tempfile.TemporaryDirectory(
        prefix="ledgerguard-verify-preparation-", dir=workspace_parent
    ) as raw:
        prepared_reader = snapshots.open_snapshot(
            preparation["financial_snapshot_sha256"],
            repository,
            Path(raw) / "financial",
        )
        outcome = prepared_reader._read_outcome(
            prepared_reader.root
            / "attempts"
            / arguments.attempt_id
            / "outcome.json"
        )
        if (
            prepared_reader.read_head() != preparation["financial_head"]
            or outcome.commit_sha256 != preparation["financial_head"]
            or len(outcome.proofs) != preparation["proof_count"]
            or len(outcome.cases) != preparation["case_count"]
        ):
            raise ControlRejected("prepared financial snapshot identity differs")
    from .authority import Attempt

    commit_sha256 = authority.publish(
        Attempt(**attempt_value),
        execution["predecessor"],
        preparation["financial_snapshot_sha256"],
    )
    committed = authority.read_root(execution["namespace"])
    if (
        committed is None
        or canonical_digest(committed) != commit_sha256
        or committed.get("preparation_sha256")
        != preparation["financial_snapshot_sha256"]
    ):
        raise ControlRejected("published metadata root differs")
    with tempfile.TemporaryDirectory(
        prefix="ledgerguard-verify-publication-", dir=workspace_parent
    ) as raw:
        reader = snapshots.open_committed(authority, repository, Path(raw) / "financial")
        if reader.read_head() != preparation["financial_head"]:
            raise ControlRejected("published financial head differs")
        reader.verify_history()
    publication = _put_document(
        immutable,
        config.bucket,
        f"{job['run_id']}/{job['attempt_id']}/publication",
        "publication",
        {
            "schema_version": "ledgerguard.publication.v1",
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
            "fence": attempt_value["fence"],
            "predecessor": execution["predecessor"],
            "namespace": execution["namespace"],
            "commit_sha256": commit_sha256,
            "candidate_index": preparation_reference,
            "registration_sha256": control["execution_input_sha256"],
            "validated_inventory_sha256": preparation["input_inventory_sha256"],
        },
    )
    control["committed_sha256"] = commit_sha256
    control["publication"] = publication
    return state
