from __future__ import annotations

from base64 import b64decode
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from typing import Any

import pytest
from test_part2_stage3_admission import build_bundle

from ledgerguard.reconciliation import (
    AdmissionRejected,
    admit_bundle,
    reconcile_settlements,
    reconcile_transactions,
)
from ledgerguard.stage3.canonical import canonical_bytes, canonical_digest
from ledgerguard_control.authority import LocalAuthority
from ledgerguard_control.candidate_validation import _put_document
from ledgerguard_control.contracts import ControlRejected, strict_json
from ledgerguard_control.execution import (
    admit_attempt,
    parse_config,
    register_run,
    validate_execution,
)
from ledgerguard_control.objects import LocalVersionedObjects
from ledgerguard_control.preparation import (
    AdmittedInputs,
    _derived_rows,
    _expected_rows,
    _successful_state,
    admit_inputs,
    prepare_financial_snapshot,
    prepare_publication,
    publish_authority,
)
from ledgerguard_control.publication import FinancialSnapshots

ROOT = Path(__file__).resolve().parents[1]
BUCKET = "ledgerguard-p3-857229544428-operation-stage5"
PREFIX = f"s3://{BUCKET}/runs/run-0001/inputs"
OWNER = (
    "arn:aws:states:ap-southeast-2:857229544428:execution:ledgerguard-test:execution-one"
)


def _put(objects: LocalVersionedObjects, uri: str, raw: bytes) -> dict[str, Any]:
    version = objects.put(uri, raw)
    return {
        "uri": uri,
        "version_id": version,
        "sha256": sha256(raw).hexdigest(),
        "size_bytes": len(raw),
    }


def fixture(
    tmp_path: Path,
    *,
    run_id: str = "run-0001",
    objects: LocalVersionedObjects | None = None,
) -> tuple[Any, ...]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    objects = objects or LocalVersionedObjects(tmp_path / "objects.sqlite")
    policy_raw, manifest_raw, source_objects, manifest = build_bundle(run_id=run_id)
    prefix = f"s3://{BUCKET}/runs/{run_id}/inputs"
    policy_ref = _put(objects, prefix + "/policy.json", policy_raw + b"\n")
    manifest_ref = _put(objects, prefix + "/run-manifest.json", manifest_raw + b"\n")
    rows = []
    for descriptor in manifest["objects"]:
        locator = "local:" + descriptor["relative_path"]
        rows.append(
            {
                "locator": locator,
                "reference": _put(
                    objects,
                    prefix + "/" + descriptor["relative_path"],
                    source_objects[locator],
                ),
            }
        )
    inventory = {
        "schema_version": "ledgerguard.input-inventory.v1",
        "policy": policy_ref,
        "manifest": manifest_ref,
        "objects": rows,
        "correction": None,
    }
    inventory_raw = canonical_bytes(inventory) + b"\n"
    inventory_ref = _put(objects, prefix + "/input-inventory.json", inventory_raw)
    admitted = admit_bundle(ROOT, policy_raw, manifest_raw, source_objects)
    transactions = reconcile_transactions(admitted)
    settlements = reconcile_settlements(admitted)
    expected_rows = [
        *[("transactions", row.value()) for row in transactions.candidates],
        *[("settlements", row.value()) for row in settlements.candidates],
        *[("bank-allocations", row.value()) for row in settlements.bank_allocations],
    ]
    expected = b"".join(
        canonical_bytes({"family": family, "row": row}) + b"\n"
        for family, row in expected_rows
    )
    inputs = admit_inputs(
        objects,
        inventory_ref,
        input_prefix=prefix,
        run_id=run_id,
        source_commit=manifest["source_commit"],
        policy_sha256=admitted.policy_sha256,
        manifest_sha256=admitted.manifest_sha256,
    )
    return objects, inputs, expected, manifest, inventory_ref, prefix


def test_source_truth_is_finalized_and_sealed_without_metadata_authority(tmp_path: Path) -> None:
    objects, inputs, expected, _manifest, _inventory, _prefix = fixture(tmp_path)
    snapshots = FinancialSnapshots(objects, BUCKET, "namespace-1")
    authority = LocalAuthority(tmp_path / "authority.sqlite")
    prepared = prepare_financial_snapshot(
        repository=ROOT,
        objects=objects,
        snapshots=snapshots,
        authority=authority,
        namespace="namespace-1",
        predecessor=None,
        attempt_id="attempt-1",
        created_at="2026-09-12T08:01:01Z",
        inputs=inputs,
        expected_raw=expected,
        expected_sha256=sha256(expected).hexdigest(),
        workspace=tmp_path / "prepare",
    )
    assert authority.read_root("namespace-1") is None
    root = strict_json(snapshots._get(prepared.snapshot_sha256))
    assert root["financial_head"] == prepared.financial_head
    assert prepared.finalization_receipt.commit_sha256 == prepared.financial_head
    assert prepared.input_inventory_sha256 == inputs.inventory_sha256


def test_prepared_snapshot_replay_and_predecessor_restore_preserve_history(tmp_path: Path) -> None:
    objects, inputs, expected, _manifest, _inventory, _prefix = fixture(tmp_path / "first")
    snapshots = FinancialSnapshots(objects, BUCKET, "namespace-1")
    authority = LocalAuthority(tmp_path / "authority.sqlite")
    first = prepare_financial_snapshot(
        repository=ROOT,
        objects=objects,
        snapshots=snapshots,
        authority=authority,
        namespace="namespace-1",
        predecessor=None,
        attempt_id="attempt-1",
        created_at="2026-09-12T08:01:01Z",
        inputs=inputs,
        expected_raw=expected,
        expected_sha256=sha256(expected).hexdigest(),
        workspace=tmp_path / "prepared-first",
    )
    authority.register("namespace-1", "run-0001", "a" * 64)
    token = authority.admit("namespace-1", "run-0001", "a" * 64, "attempt-1", OWNER)
    predecessor = authority.publish(token, None, first.snapshot_sha256)

    # A fresh run with the same immutable business facts exercises prior-state replay.
    _second_objects, second_inputs, second_expected, _, _, _ = fixture(
        tmp_path / "second", run_id="run-0002", objects=objects
    )
    second = prepare_financial_snapshot(
        repository=ROOT,
        objects=objects,
        snapshots=snapshots,
        authority=authority,
        namespace="namespace-1",
        predecessor=predecessor,
        attempt_id="attempt-2",
        created_at="2026-09-12T09:01:01Z",
        inputs=second_inputs,
        expected_raw=second_expected,
        expected_sha256=sha256(second_expected).hexdigest(),
        workspace=tmp_path / "prepared-second",
    )
    assert second.financial_head != first.financial_head
    assert authority.read_root("namespace-1")["preparation_sha256"] == first.snapshot_sha256


@pytest.mark.parametrize("fault", ["expected", "source", "inventory", "predecessor"])
def test_substitution_never_seals_authority(tmp_path: Path, fault: str) -> None:
    objects, inputs, expected, _manifest, inventory_ref, prefix = fixture(tmp_path)
    authority = LocalAuthority(tmp_path / "authority.sqlite")
    snapshots = FinancialSnapshots(objects, BUCKET, "namespace-1")
    if fault == "expected":
        value = strict_json(expected.splitlines()[0])
        value["row"]["totals"]["processor_minor"] += 1
        expected = canonical_bytes(value) + b"\n" + b"\n".join(expected.splitlines()[1:]) + b"\n"
    elif fault == "source":
        inputs.objects[next(iter(inputs.objects))] += b" "
    elif fault == "inventory":
        inventory = strict_json(objects.read(inventory_ref["uri"], inventory_ref["version_id"]))
        inventory["objects"][0]["locator"] = "local:other.jsonl"
        raw = canonical_bytes(inventory) + b"\n"
        changed = _put(objects, prefix + "/changed-inventory.json", raw)
        with pytest.raises(ControlRejected):
            admit_inputs(
                objects,
                changed,
                input_prefix=prefix,
                run_id="run-0001",
                source_commit="a" * 40,
                policy_sha256=inputs.policy["policy_sha256"],
                manifest_sha256=inputs.manifest["manifest_sha256"],
            )
        return
    else:
        authority.register("namespace-1", "run-other", "b" * 64)
        token = authority.admit(
            "namespace-1", "run-other", "b" * 64, "attempt-other", OWNER
        )
        authority.publish(token, None, "f" * 64)
    with pytest.raises((ControlRejected, AdmissionRejected)):
        prepare_financial_snapshot(
            repository=ROOT,
            objects=objects,
            snapshots=snapshots,
            authority=authority,
            namespace="namespace-1",
            predecessor=None,
            attempt_id="attempt-1",
            created_at="2026-09-12T08:01:01Z",
            inputs=inputs,
            expected_raw=expected,
            expected_sha256=sha256(expected).hexdigest(),
            workspace=tmp_path / "prepare",
        )
    if fault != "predecessor":
        assert authority.read_root("namespace-1") is None


def test_inventory_documents_and_physical_identities_are_exact(tmp_path: Path) -> None:
    objects, inputs, _expected, _manifest, inventory_ref, prefix = fixture(tmp_path)
    inventory = strict_json(objects.read(inventory_ref["uri"], inventory_ref["version_id"]))
    for change, match in (
        (lambda value: value["policy"].update(uri=prefix + "/other.json"), "outside"),
        (lambda value: value["objects"][0]["reference"].update(size_bytes=1), "identity"),
        (lambda value: value["objects"].pop(), "set differs"),
    ):
        candidate = deepcopy(inventory)
        change(candidate)
        raw = canonical_bytes(candidate) + b"\n"
        reference = _put(objects, prefix + "/changed-" + sha256(raw).hexdigest(), raw)
        with pytest.raises(ControlRejected, match=match):
            admit_inputs(
                objects,
                reference,
                input_prefix=prefix,
                run_id="run-0001",
                source_commit="a" * 40,
                policy_sha256=inputs.policy["policy_sha256"],
                manifest_sha256=inputs.manifest["manifest_sha256"],
            )


def _replace_inventory_document(
    objects: LocalVersionedObjects,
    inventory_ref: dict[str, Any],
    inventory: dict[str, Any],
    prefix: str,
) -> dict[str, Any]:
    raw = canonical_bytes(inventory) + b"\n"
    return _put(objects, prefix + "/changed-" + sha256(raw).hexdigest() + ".json", raw)


def test_noncanonical_inventory_and_documents_reject(tmp_path: Path) -> None:
    objects, inputs, _expected, _manifest, inventory_ref, prefix = fixture(tmp_path)
    inventory = strict_json(objects.read(inventory_ref["uri"], inventory_ref["version_id"]))
    raw = canonical_bytes(inventory)
    unframed = _put(objects, prefix + "/unframed.json", raw)
    with pytest.raises(ControlRejected, match="not canonical"):
        admit_inputs(
            objects,
            unframed,
            input_prefix=prefix,
            run_id="run-0001",
            source_commit="a" * 40,
            policy_sha256=inputs.policy["policy_sha256"],
            manifest_sha256=inputs.manifest["manifest_sha256"],
        )


@pytest.mark.parametrize(
    "field",
    ["policy", "manifest", "manifest-policy", "run", "source-commit"],
)
def test_every_input_document_identity_is_bound(
    tmp_path: Path, field: str
) -> None:
    objects, inputs, _expected, _manifest, inventory_ref, prefix = fixture(tmp_path)
    kwargs = {
        "input_prefix": prefix,
        "run_id": "run-0001",
        "source_commit": "a" * 40,
        "policy_sha256": inputs.policy["policy_sha256"],
        "manifest_sha256": inputs.manifest["manifest_sha256"],
    }
    if field == "policy":
        kwargs["policy_sha256"] = "0" * 64
    elif field == "manifest":
        kwargs["manifest_sha256"] = "0" * 64
    elif field == "run":
        kwargs["run_id"] = "run-other"
    elif field == "source-commit":
        kwargs["source_commit"] = "0" * 40
    else:
        inventory = strict_json(
            objects.read(inventory_ref["uri"], inventory_ref["version_id"])
        )
        manifest_ref = inventory["manifest"]
        manifest = strict_json(objects.read(manifest_ref["uri"], manifest_ref["version_id"]))
        manifest["policy_sha256"] = "0" * 64
        manifest["manifest_sha256"] = canonical_digest(
            {key: value for key, value in manifest.items() if key != "manifest_sha256"}
        )
        inventory["manifest"] = _put(
            objects, prefix + "/run-manifest.json", canonical_bytes(manifest) + b"\n"
        )
        inventory_ref = _replace_inventory_document(objects, inventory_ref, inventory, prefix)
        kwargs["manifest_sha256"] = manifest["manifest_sha256"]
    with pytest.raises(ControlRejected, match="documents differ"):
        admit_inputs(objects, inventory_ref, **kwargs)


@pytest.mark.parametrize("fault", ["missing", "non-object", "duplicate", "unsafe"])
def test_manifest_object_inventory_fails_closed(tmp_path: Path, fault: str) -> None:
    objects, inputs, _expected, _manifest, inventory_ref, prefix = fixture(tmp_path)
    inventory = strict_json(objects.read(inventory_ref["uri"], inventory_ref["version_id"]))
    manifest_ref = inventory["manifest"]
    manifest = strict_json(objects.read(manifest_ref["uri"], manifest_ref["version_id"]))
    if fault == "missing":
        manifest["objects"] = None
    elif fault == "non-object":
        manifest["objects"][0] = None
    elif fault == "duplicate":
        manifest["objects"].append(deepcopy(manifest["objects"][0]))
    else:
        old = "local:" + manifest["objects"][0]["relative_path"]
        manifest["objects"][0]["relative_path"] = "../escape.jsonl"
        inventory["objects"][0]["locator"] = "local:../escape.jsonl"
        assert inventory["objects"][0]["locator"] != old
    manifest["manifest_sha256"] = canonical_digest(
        {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    )
    inventory["manifest"] = _put(
        objects, prefix + "/run-manifest.json", canonical_bytes(manifest) + b"\n"
    )
    changed = _replace_inventory_document(objects, inventory_ref, inventory, prefix)
    with pytest.raises((ControlRejected, AdmissionRejected)):
        admit_inputs(
            objects,
            changed,
            input_prefix=prefix,
            run_id="run-0001",
            source_commit="a" * 40,
            policy_sha256=inputs.policy["policy_sha256"],
            manifest_sha256=manifest["manifest_sha256"],
        )


def test_s3_manifest_locator_is_exact(tmp_path: Path) -> None:
    objects, inputs, _expected, _manifest, inventory_ref, prefix = fixture(tmp_path)
    inventory = strict_json(objects.read(inventory_ref["uri"], inventory_ref["version_id"]))
    manifest_ref = inventory["manifest"]
    manifest = strict_json(objects.read(manifest_ref["uri"], manifest_ref["version_id"]))
    row = inventory["objects"][0]
    descriptor = manifest["objects"][0]
    descriptor.update(
        locator_type="S3_OBJECT",
        s3_uri=row["reference"]["uri"],
        version_id=row["reference"]["version_id"],
    )
    descriptor.pop("relative_path")
    row["locator"] = f's3:{descriptor["s3_uri"]}#{descriptor["version_id"]}'
    manifest["manifest_sha256"] = canonical_digest(
        {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    )
    inventory["manifest"] = _put(
        objects, prefix + "/run-manifest.json", canonical_bytes(manifest) + b"\n"
    )
    changed = _replace_inventory_document(objects, inventory_ref, inventory, prefix)
    admitted = admit_inputs(
        objects,
        changed,
        input_prefix=prefix,
        run_id="run-0001",
        source_commit="a" * 40,
        policy_sha256=inputs.policy["policy_sha256"],
        manifest_sha256=manifest["manifest_sha256"],
    )
    assert row["locator"] in admitted.objects
    descriptor["s3_uri"] += "-changed"
    row["locator"] = f's3:{descriptor["s3_uri"]}#{descriptor["version_id"]}'
    manifest["manifest_sha256"] = canonical_digest(
        {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    )
    inventory["manifest"] = _put(
        objects, prefix + "/run-manifest.json", canonical_bytes(manifest) + b"\n"
    )
    changed = _replace_inventory_document(objects, inventory_ref, inventory, prefix)
    with pytest.raises(ControlRejected, match="S3 manifest locator"):
        admit_inputs(
            objects,
            changed,
            input_prefix=prefix,
            run_id="run-0001",
            source_commit="a" * 40,
            policy_sha256=inputs.policy["policy_sha256"],
            manifest_sha256=manifest["manifest_sha256"],
        )


def test_source_bundle_byte_bound_is_enforced(tmp_path: Path, monkeypatch: Any) -> None:
    import ledgerguard_control.preparation as module

    objects, inputs, _expected, _manifest, inventory_ref, prefix = fixture(tmp_path)
    monkeypatch.setattr(module, "MAX_SOURCE_BUNDLE_BYTES", 1)
    with pytest.raises(ControlRejected, match="byte bound"):
        admit_inputs(
            objects,
            inventory_ref,
            input_prefix=prefix,
            run_id="run-0001",
            source_commit="a" * 40,
            policy_sha256=inputs.policy["policy_sha256"],
            manifest_sha256=inputs.manifest["manifest_sha256"],
        )


def test_correction_reference_is_retained(tmp_path: Path) -> None:
    objects, inputs, _expected, _manifest, inventory_ref, prefix = fixture(tmp_path)
    inventory = strict_json(objects.read(inventory_ref["uri"], inventory_ref["version_id"]))
    correction = {"schema_version": "test-only", "identity": "correction-one"}
    inventory["correction"] = _put(
        objects, prefix + "/correction.json", canonical_bytes(correction) + b"\n"
    )
    changed = _replace_inventory_document(objects, inventory_ref, inventory, prefix)
    admitted = admit_inputs(
        objects,
        changed,
        input_prefix=prefix,
        run_id="run-0001",
        source_commit="a" * 40,
        policy_sha256=inputs.policy["policy_sha256"],
        manifest_sha256=inputs.manifest["manifest_sha256"],
    )
    assert admitted.correction == correction


@pytest.mark.parametrize(
    "raw,match",
    [
        (b'{}', "framing"),
        (b'{"family":"transactions"}\n', "shape"),
        (b"", "family inventory"),
    ],
)
def test_expected_financial_document_boundaries(raw: bytes, match: str) -> None:
    with pytest.raises(ControlRejected, match=match):
        _expected_rows(raw, sha256(raw).hexdigest())


def test_expected_duplicate_and_row_count_bound(tmp_path: Path, monkeypatch: Any) -> None:
    import ledgerguard_control.preparation as module

    _objects, _inputs, expected, _manifest, _inventory, _prefix = fixture(tmp_path)
    with pytest.raises(ControlRejected, match="digest"):
        _expected_rows(expected, "0" * 64)
    first = expected.splitlines(keepends=True)[0]
    duplicate = first + first
    with pytest.raises(ControlRejected, match="duplicate"):
        _expected_rows(duplicate, sha256(duplicate).hexdigest())
    monkeypatch.setattr(module, "MAX_EXPECTED_ROWS", 0)
    with pytest.raises(ControlRejected, match="count exceeds"):
        _expected_rows(expected, sha256(expected).hexdigest())


def test_valid_but_different_expected_rows_do_not_prepare(tmp_path: Path) -> None:
    objects, inputs, expected, _manifest, _inventory, _prefix = fixture(tmp_path)
    rows = [strict_json(line) for line in expected.splitlines()]
    transaction = next(value["row"] for value in rows if value["family"] == "transactions")
    transaction["totals"].update(
        ledger_minor=99, processor_ledger_delta_minor=1, difference_minor=1
    )
    transaction.update(status="EXCEPTION", reason_codes=["PROCESSOR_LEDGER_MISMATCH"])
    changed = b"".join(canonical_bytes(value) + b"\n" for value in rows)
    with pytest.raises(ControlRejected, match="derived financial authority"):
        prepare_financial_snapshot(
            repository=ROOT,
            objects=objects,
            snapshots=FinancialSnapshots(objects, BUCKET, "namespace-1"),
            authority=LocalAuthority(tmp_path / "authority.sqlite"),
            namespace="namespace-1",
            predecessor=None,
            attempt_id="attempt-1",
            created_at="2026-09-12T08:01:01Z",
            inputs=inputs,
            expected_raw=changed,
            expected_sha256=sha256(changed).hexdigest(),
            workspace=tmp_path / "prepare",
        )


def test_duplicate_derived_identity_rejects() -> None:
    class Row:
        def value(self) -> dict[str, Any]:
            from tests.test_part3_stage5_financial_rows import transaction

            return transaction()

    class Transactions:
        candidates = (Row(), Row())

    class Settlements:
        candidates: tuple[Any, ...] = ()
        bank_allocations: tuple[Any, ...] = ()

    with pytest.raises(ControlRejected, match="duplicate derived"):
        _derived_rows(Transactions(), Settlements())


def test_predecessor_race_and_post_seal_head_change_reject(
    tmp_path: Path, monkeypatch: Any
) -> None:
    objects, inputs, expected, _manifest, _inventory, _prefix = fixture(tmp_path)
    snapshots = FinancialSnapshots(objects, BUCKET, "namespace-1")
    authority = LocalAuthority(tmp_path / "authority.sqlite")
    first = prepare_financial_snapshot(
        repository=ROOT,
        objects=objects,
        snapshots=snapshots,
        authority=authority,
        namespace="namespace-1",
        predecessor=None,
        attempt_id="attempt-1",
        created_at="2026-09-12T08:01:01Z",
        inputs=inputs,
        expected_raw=expected,
        expected_sha256=sha256(expected).hexdigest(),
        workspace=tmp_path / "first",
    )
    authority.register("namespace-1", "run-0001", "a" * 64)
    token = authority.admit("namespace-1", "run-0001", "a" * 64, "attempt-1", OWNER)
    predecessor = authority.publish(token, None, first.snapshot_sha256)

    original_read = authority.read_root
    calls = 0

    def raced(namespace: str) -> dict[str, Any] | None:
        nonlocal calls
        calls += 1
        return original_read(namespace) if calls < 3 else None

    monkeypatch.setattr(authority, "read_root", raced)
    with pytest.raises(ControlRejected, match="changed during restore"):
        prepare_financial_snapshot(
            repository=ROOT,
            objects=objects,
            snapshots=snapshots,
            authority=authority,
            namespace="namespace-1",
            predecessor=predecessor,
            attempt_id="attempt-2",
            created_at="2026-09-12T09:01:01Z",
            inputs=inputs,
            expected_raw=expected,
            expected_sha256=sha256(expected).hexdigest(),
            workspace=tmp_path / "raced",
        )

    monkeypatch.setattr(authority, "read_root", original_read)

    class ChangedHead(FinancialSnapshots):
        def seal(self, store: Any) -> str:
            digest = super().seal(store)
            (store.root / "control/HEAD").write_text(first.financial_head + "\n")
            return digest

    with pytest.raises(ControlRejected, match="prepared financial head"):
        prepare_financial_snapshot(
            repository=ROOT,
            objects=objects,
            snapshots=ChangedHead(objects, BUCKET, "namespace-1"),
            authority=authority,
            namespace="namespace-1",
            predecessor=predecessor,
            attempt_id="attempt-2",
            created_at="2026-09-12T09:01:01Z",
            inputs=inputs,
            expected_raw=expected,
            expected_sha256=sha256(expected).hexdigest(),
            workspace=tmp_path / "changed-head",
        )


def test_real_accepted_correction_is_preserved_end_to_end(tmp_path: Path) -> None:
    from test_part3_stage1_correction import scenario

    case = scenario(tmp_path / "case")
    source = case["store"]
    correction_args = case["args"]
    objects = LocalVersionedObjects(tmp_path / "objects.sqlite")
    snapshots = FinancialSnapshots(objects, BUCKET, "namespace-1")
    authority = LocalAuthority(tmp_path / "authority.sqlite")
    authority.register("namespace-1", "run-first", "a" * 64)
    token = authority.admit("namespace-1", "run-first", "a" * 64, "attempt-1", OWNER)
    predecessor = authority.publish(token, None, snapshots.seal(source))
    encoded = correction_args["correction_inputs"]
    inputs = AdmittedInputs(
        policy=dict(encoded["policy"]),
        manifest=dict(encoded["manifest"]),
        objects={key: b64decode(value) for key, value in encoded["objects"].items()},
        correction=dict(correction_args["correction"]),
        inventory_sha256="b" * 64,
    )
    transaction = correction_args["transaction_batch"]
    settlement = correction_args["settlement_batch"]
    values = [
        *[("transactions", row.value()) for row in transaction.candidates],
        *[("settlements", row.value()) for row in settlement.candidates],
        *[("bank-allocations", row.value()) for row in settlement.bank_allocations],
    ]
    expected = b"".join(
        canonical_bytes({"family": family, "row": row}) + b"\n"
        for family, row in values
    )
    prepared = prepare_financial_snapshot(
        repository=ROOT,
        objects=objects,
        snapshots=snapshots,
        authority=authority,
        namespace="namespace-1",
        predecessor=predecessor,
        attempt_id=correction_args["attempt_id"],
        created_at=correction_args["created_at"],
        inputs=inputs,
        expected_raw=expected,
        expected_sha256=sha256(expected).hexdigest(),
        workspace=tmp_path / "correction",
    )
    authority.register("namespace-1", "run-correction", "c" * 64)
    correction_token = authority.admit(
        "namespace-1", "run-correction", "c" * 64, "attempt-correction", OWNER
    )
    authority.publish(correction_token, predecessor, prepared.snapshot_sha256)
    reader = snapshots.open_committed(authority, ROOT, tmp_path / "reader")
    statuses = [
        reader.read_case_revision(reference.object_sha256)["status"]
        for reference in prepared.finalization_receipt.cases
    ]
    assert statuses and set(statuses) == {"RESOLVED_BY_CORRECTION"}


def successful_state(tmp_path: Path) -> tuple[Any, ...]:
    objects, inputs, expected, manifest, inventory_ref, prefix = fixture(tmp_path / "input")
    runtime = {
        "source_commit": "a" * 40,
        "source_tree": "b" * 40,
        "runtime_package_sha256": "c" * 64,
        "script_sha256": "d" * 64,
        "wheels_sha256": "e" * 64,
    }
    expected_ref = _put(objects, prefix + "/expected-results.jsonl", expected)
    job = {
        "run_id": "run-0001",
        "attempt_id": "attempt-1",
        "control_record_identity": "control-1",
        "policy_sha256": inputs.policy["policy_sha256"],
        "manifest_sha256": inputs.manifest["manifest_sha256"],
        "source_bundle_sha256": "3" * 64,
        "source_commit": manifest["source_commit"],
        "source_tree": runtime["source_tree"],
        "runtime_package_sha256": runtime["runtime_package_sha256"],
        "workload_bucket": BUCKET,
        "input_prefix": prefix,
        "candidate_output_prefix": (
            f"s3://{BUCKET}/runs/run-0001/attempts/attempt-1/candidates"
        ),
        "evidence_prefix": f"s3://{BUCKET}/runs/run-0001/attempts/attempt-1/evidence",
    }
    execution = {
        "schema_version": "ledgerguard.execution-input.v1",
        "job": job,
        "runtime": runtime,
        "release_manifest_sha256": "9" * 64,
        "expected_results": expected_ref,
        "input_inventory": inventory_ref,
        "namespace": "namespace-1",
        "predecessor": None,
    }
    execution_raw = canonical_bytes(execution)
    execution_ref = _put(objects, prefix + "/execution-input.json", execution_raw)
    config_value = {
        "schema_version": "ledgerguard.handler-config.v1",
        "operation_id": "operation-stage5",
        "execution_input": execution_ref,
        "release_manifest_sha256": "9" * 64,
        "runtime": runtime,
    }
    config_raw = canonical_bytes(config_value)
    config = parse_config(config_raw, sha256(config_raw).hexdigest())
    state = validate_execution(
        {
            "action": "validate-execution",
            "execution_arn": OWNER,
            "state": {"execution_input_sha256": execution_ref["sha256"]},
        },
        config,
        objects,
    )
    authority = LocalAuthority(tmp_path / "authority.sqlite")
    state = register_run(
        {"action": "register-run", "execution_arn": OWNER, "state": state}, authority
    )
    state = admit_attempt(
        {"action": "admit-attempt", "execution_arn": OWNER, "state": state}, authority
    )
    version_inventory = "4" * 64
    physical = _put_document(
        objects,
        BUCKET,
        "run-0001/attempt-1/test-physical",
        "physical-inventory",
        {
            "schema_version": "ledgerguard.physical-inventory.v1",
            "run_id": "run-0001",
            "attempt_id": "attempt-1",
            "version_inventory_sha256": version_inventory,
            "objects": [inventory_ref, expected_ref, execution_ref],
            "financial_comparison": {
                "expected_sha256": expected_ref["sha256"],
                "rows_sha256": "5" * 64,
                "counts": {
                    "transactions": 1,
                    "settlements": 1,
                    "bank-allocations": 1,
                },
            },
        },
    )
    identity = {
        name: job[name]
        for name in (
            "run_id",
            "attempt_id",
            "control_record_identity",
            "policy_sha256",
            "manifest_sha256",
            "source_bundle_sha256",
        )
    }
    attempt = state["control"]["attempt"]
    receipt = _put_document(
        objects,
        BUCKET,
        "run-0001/attempt-1/test-receipt",
        "validation-receipt",
        {
            "schema_version": "ledgerguard.validation-receipt.v1",
            **identity,
            "execution_arn": OWNER,
            "fence": attempt["fence"],
            "predecessor": None,
            "glue_job_name": "ledgerguard-p3-operation-stage5-reconciliation",
            "glue_job_run_id": "jr_" + "6" * 64,
            "glue_arguments_sha256": "7" * 64,
            "glue_observation_sha256": "8" * 64,
            "glue_started_at": "2026-09-12T08:00:00Z",
            "glue_completed_at": "2026-09-12T08:01:01Z",
            "glue_execution_seconds": 60,
            "glue_dpu_seconds": "120.5",
            "completion": inventory_ref,
            "candidate_manifest": inventory_ref,
            "physical_inventory": physical,
            "version_inventory_sha256": version_inventory,
            "logical_sha256": "a" * 64,
            "expected_results_sha256": expected_ref["sha256"],
        },
    )
    state["control"]["validation_receipt"] = receipt
    state["managed"]["glue"] = {"JobRunId": "jr_" + "6" * 64}
    state["control"]["query_proofs"] = {}
    for ordinal, family in enumerate(("transactions", "settlements", "bank_allocations"), 1):
        query_id = f"12345678-0000-0000-0000-{ordinal:012d}"
        state["managed"]["athena"][family] = {"QueryExecutionId": query_id}
        proof = _put_document(
            objects,
            BUCKET,
            f"run-0001/attempt-1/test-{family}",
            "query-proof",
            {
                "schema_version": "ledgerguard.query-proof.v1",
                **identity,
                "family": family,
                "query_execution_id": query_id,
                "sql_sha256": state["control"]["queries"][family]["sql_sha256"],
                "workgroup": state["control"]["athena_workgroup"],
                "engine_version": "Athena engine version 3",
                "status": "SUCCEEDED",
                "scanned_bytes": 100,
                "execution_ms": 20,
                "result": inventory_ref,
                "rows_sha256": "b" * 64,
                "row_count": 1,
                "version_inventory_before_sha256": version_inventory,
                "version_inventory_after_sha256": version_inventory,
            },
        )
        state["control"]["query_proofs"][family] = proof
    return state, config, objects, authority


def test_success_handlers_prepare_then_atomically_publish_exact_financial_history(
    tmp_path: Path,
) -> None:
    state, config, objects, authority = successful_state(tmp_path)
    prepared = prepare_publication(
        {"action": "prepare-publication", "execution_arn": OWNER, "state": state},
        config,
        objects,
        objects,
        authority,
        ROOT,
        tmp_path,
    )
    assert authority.read_root("namespace-1") is None
    preparation_ref = prepared["control"]["preparation"]
    preparation = strict_json(
        objects.read(preparation_ref["uri"], preparation_ref["version_id"])
    )
    assert preparation["input_inventory_sha256"]
    assert preparation["expected_results_sha256"] == prepared["control"]["execution"][
        "expected_results"
    ]["sha256"]

    before_publish = deepcopy(prepared)
    published = publish_authority(
        {
            "action": "publish-authority",
            "execution_arn": OWNER,
            "state": prepared,
        },
        config,
        objects,
        objects,
        authority,
        ROOT,
        tmp_path,
    )
    assert published["control"]["committed_sha256"] == canonical_digest(
        authority.read_root("namespace-1")
    )
    publication_ref = published["control"]["publication"]
    publication = strict_json(
        objects.read(publication_ref["uri"], publication_ref["version_id"])
    )
    assert publication["candidate_index"] == preparation_ref
    assert publication["validated_inventory_sha256"] == preparation[
        "input_inventory_sha256"
    ]

    replay = publish_authority(
        {
            "action": "publish-authority",
            "execution_arn": OWNER,
            "state": before_publish,
        },
        config,
        objects,
        objects,
        authority,
        ROOT,
        tmp_path,
    )
    assert replay["control"]["committed_sha256"] == published["control"][
        "committed_sha256"
    ]
    assert replay["control"]["publication"] == publication_ref


def _replace_preparation(
    objects: LocalVersionedObjects,
    state: dict[str, Any],
    change: Any,
) -> dict[str, Any]:
    result = deepcopy(state)
    reference = result["control"]["preparation"]
    value = strict_json(objects.read(reference["uri"], reference["version_id"]))
    change(value)
    result["control"]["preparation"] = _put_document(
        objects,
        BUCKET,
        "run-0001/attempt-1/changed-preparation",
        "preparation-receipt",
        value,
    )
    return result


@pytest.mark.parametrize(
    ("change", "match"),
    [
        (
            lambda state: state.update(control=[]),
            "control state",
        ),
        (
            lambda state: state["control"].update(
                preparation=state["control"]["validation_receipt"]
            ),
            "preparation state",
        ),
        (
            lambda state: state["control"]["query_proofs"].pop("transactions"),
            "proof inventory",
        ),
    ],
)
def test_success_state_rejects_incomplete_or_wrong_phase(
    tmp_path: Path, change: Any, match: str
) -> None:
    state, config, objects, _authority = successful_state(tmp_path)
    change(state)
    with pytest.raises(ControlRejected, match=match):
        _successful_state(
            {"action": "prepare-publication", "execution_arn": OWNER, "state": state},
            config,
            objects,
            "prepare-publication",
            prepared=False,
        )


@pytest.mark.parametrize(
    "field",
    [
        "family",
        "query_execution_id",
        "version_inventory_before_sha256",
        "version_inventory_after_sha256",
        "run_id",
    ],
)
def test_final_query_proof_is_fully_readmitted(
    tmp_path: Path, field: str
) -> None:
    state, config, objects, _authority = successful_state(tmp_path)
    reference = state["control"]["query_proofs"]["bank_allocations"]
    proof = strict_json(objects.read(reference["uri"], reference["version_id"]))
    if field == "family":
        proof[field] = "transactions"
    elif field == "query_execution_id":
        proof[field] = "different-query"
    elif field == "run_id":
        proof[field] = "run-other"
    else:
        proof[field] = "0" * 64
    state["control"]["query_proofs"]["bank_allocations"] = _put_document(
        objects,
        BUCKET,
        f"run-0001/attempt-1/changed-{field}",
        "query-proof",
        proof,
    )
    with pytest.raises(ControlRejected, match="final Athena proof identity"):
        _successful_state(
            {"action": "prepare-publication", "execution_arn": OWNER, "state": state},
            config,
            objects,
            "prepare-publication",
            prepared=False,
        )


@pytest.mark.parametrize(
    ("change", "match"),
    [
        (lambda value: value.update(namespace="namespace-other"), "preparation identity"),
        (
            lambda value: value.update(input_inventory_sha256="0" * 64),
            "input inventory identity",
        ),
        (lambda value: value.update(proof_count=value["proof_count"] + 1), "snapshot identity"),
    ],
)
def test_publication_rejects_substituted_preparation_before_authority(
    tmp_path: Path, change: Any, match: str
) -> None:
    state, config, objects, authority = successful_state(tmp_path)
    prepared = prepare_publication(
        {"action": "prepare-publication", "execution_arn": OWNER, "state": state},
        config,
        objects,
        objects,
        authority,
        ROOT,
        tmp_path,
    )
    changed = _replace_preparation(objects, prepared, change)
    with pytest.raises(ControlRejected, match=match):
        publish_authority(
            {
                "action": "publish-authority",
                "execution_arn": OWNER,
                "state": changed,
            },
            config,
            objects,
            objects,
            authority,
            ROOT,
            tmp_path,
        )
    assert authority.read_root("namespace-1") is None


def test_publication_checks_exact_postconditions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state, config, objects, authority = successful_state(tmp_path)
    prepared = prepare_publication(
        {"action": "prepare-publication", "execution_arn": OWNER, "state": state},
        config,
        objects,
        objects,
        authority,
        ROOT,
        tmp_path,
    )
    monkeypatch.setattr(authority, "read_root", lambda _namespace: None)
    with pytest.raises(ControlRejected, match="published metadata root"):
        publish_authority(
            {
                "action": "publish-authority",
                "execution_arn": OWNER,
                "state": prepared,
            },
            config,
            objects,
            objects,
            authority,
            ROOT,
            tmp_path,
        )

    state, config, objects, authority = successful_state(tmp_path / "head")
    prepared = prepare_publication(
        {"action": "prepare-publication", "execution_arn": OWNER, "state": state},
        config,
        objects,
        objects,
        authority,
        ROOT,
        tmp_path,
    )

    class Reader:
        def read_head(self) -> str:
            return "0" * 64

        def verify_history(self) -> None:
            raise AssertionError("wrong head must reject first")

    monkeypatch.setattr(FinancialSnapshots, "open_committed", lambda *_args: Reader())
    with pytest.raises(ControlRejected, match="published financial head"):
        publish_authority(
            {
                "action": "publish-authority",
                "execution_arn": OWNER,
                "state": prepared,
            },
            config,
            objects,
            objects,
            authority,
            ROOT,
            tmp_path,
        )
