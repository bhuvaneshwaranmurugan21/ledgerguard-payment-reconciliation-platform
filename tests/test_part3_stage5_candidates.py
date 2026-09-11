"""Candidate integrity through a real persistent local version store, not AWS proof."""

from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from typing import Any

import pytest
from test_part3_stage5_admission import fixture

from ledgerguard.stage3.canonical import canonical_bytes
from ledgerguard_control.candidates import verify_physical_candidate
from ledgerguard_control.contracts import ControlRejected, job_arguments, strict_json
from ledgerguard_control.objects import (
    LocalVersionedObjects,
    ObjectVersion,
    VersionedObjects,
    assert_unchanged,
    snapshot,
    snapshot_digest,
)

PART = "part-00000-12345678-1234-1234-1234-123456789012-c000"


def candidate_bytes(arguments: Any) -> dict[str, bytes]:
    # These are intentionally opaque byte-integrity vectors, not Parquet or
    # reconciliation evidence. Financial/schema validation is a separate gate.
    values = {
        f"{family}/{PART}.snappy.parquet": family.encode()
        for family in ("transactions", "settlements", "bank-allocations")
    }
    manifest = {
        "schema_version": "2.0",
        "run_id": arguments.run_id,
        "attempt_id": arguments.attempt_id,
        "control_record_identity": "control-1",
        "glue_job_run_id": "jr_" + "d" * 64,
        "transaction_count": 1,
        "settlement_count": 1,
        "allocation_count": 1,
        "logical_sha256": "a" * 64,
        "authoritative_proof": False,
        "physical_files": [
            {"path": path, "size_bytes": len(raw), "sha256": sha256(raw).hexdigest()}
            for path, raw in sorted(values.items())
        ],
    }
    raw = canonical_bytes(manifest) + b"\n"
    values[f"candidate-manifest/{PART}.txt"] = raw
    values[f"completion/{PART}.txt"] = (
        canonical_bytes(
            {
                "schema_version": "2.0",
                "glue_job_run_id": "jr_" + "d" * 64,
                "candidate_manifest_file_sha256": sha256(raw).hexdigest(),
                "logical_sha256": "a" * 64,
                "authoritative_proof": False,
                "state": "COMPLETE_NON_AUTHORITATIVE_CANDIDATE",
            }
        )
        + b"\n"
    )
    for family in (
        "transactions",
        "settlements",
        "bank-allocations",
        "candidate-manifest",
        "completion",
    ):
        values[f"{family}/_SUCCESS"] = b""
    return values


def persist(tmp_path: Path, values: dict[str, bytes]) -> tuple[LocalVersionedObjects, Any]:
    document, _, _, _ = fixture()
    arguments = job_arguments(document["job"])
    store = LocalVersionedObjects(tmp_path / "objects.sqlite")
    for path, raw in values.items():
        store.put(f"{arguments.candidate_output_prefix}/{path}", raw)
    return store, arguments


def inputs() -> tuple[Any, dict[str, bytes]]:
    document, _, _, _ = fixture()
    arguments = job_arguments(document["job"])
    return arguments, candidate_bytes(arguments)


def rewrite_marker(values: dict[str, bytes], marker: str, edit: Any) -> None:
    path = f"{marker}/{PART}.txt"
    document = strict_json(values[path])
    edit(document)
    values[path] = canonical_bytes(document) + b"\n"
    if marker == "candidate-manifest":
        digest = sha256(values[path]).hexdigest()
        rewrite_marker(
            values, "completion", lambda v: v.update(candidate_manifest_file_sha256=digest)
        )


def test_physical_identity_reopens_and_binds_exact_versions(tmp_path: Path) -> None:
    _, values = inputs()
    store, arguments = persist(tmp_path, values)
    first = verify_physical_candidate(store, arguments)
    reopened = LocalVersionedObjects(store.path)
    second = verify_physical_candidate(reopened, arguments)
    assert first == second
    assert len(first.physical_references) == 3
    assert first.version_inventory_sha256 == snapshot_digest(
        snapshot(store, arguments.candidate_output_prefix)
    )
    ref = first.physical_references[0]
    original = reopened.read(ref["uri"], ref["version_id"])
    reopened.put(ref["uri"], b"new latest")
    assert reopened.read(ref["uri"], ref["version_id"]) == original
    with pytest.raises(ControlRejected, match="changed"):
        assert_unchanged(reopened, arguments.candidate_output_prefix, first.versions)
    with pytest.raises(ControlRejected, match="overwrite"):
        verify_physical_candidate(reopened, arguments)


@pytest.mark.parametrize("change", ["overwrite-restore", "delete-restore", "new-hidden"])
def test_transient_substitution_cannot_disappear_from_history(tmp_path: Path, change: str) -> None:
    _, values = inputs()
    store, arguments = persist(tmp_path, values)
    before = snapshot(store, arguments.candidate_output_prefix)
    path, original = next(iter(values.items()))
    uri = f"{arguments.candidate_output_prefix}/{path}"
    if change == "overwrite-restore":
        store.put(uri, b"substituted")
        store.put(uri, original)
    elif change == "delete-restore":
        tombstone = store.delete(uri)
        with pytest.raises(ControlRejected):
            store.read(uri, tombstone)
        store.put(uri, original)
    else:
        store.put(f"{arguments.candidate_output_prefix}/_unexpected", b"hidden")
    with pytest.raises(ControlRejected, match="changed"):
        assert_unchanged(store, arguments.candidate_output_prefix, before)
    with pytest.raises(ControlRejected):
        verify_physical_candidate(store, arguments)


@pytest.mark.parametrize(
    "path",
    [
        "_hidden",
        ".hidden",
        "transactions/_hidden",
        "transactions/nested/part.parquet",
        "transactions/extra.parquet",
        "completion/unexpected.txt",
        "unknown/_SUCCESS",
    ],
)
def test_no_blanket_housekeeping_exclusions(tmp_path: Path, path: str) -> None:
    _, values = inputs()
    values[path] = b"unexpected"
    store, arguments = persist(tmp_path, values)
    with pytest.raises(ControlRejected, match="unexpected candidate object"):
        verify_physical_candidate(store, arguments)


@pytest.mark.parametrize(
    "edit",
    [
        lambda v: v.pop(f"completion/{PART}.txt"),
        lambda v: v.update(
            {f"completion/{PART.replace('00000', '00001')}.txt": v[f"completion/{PART}.txt"]}
        ),
    ],
)
def test_marker_must_be_singular(tmp_path: Path, edit: Any) -> None:
    _, values = inputs()
    edit(values)
    store, arguments = persist(tmp_path, values)
    with pytest.raises(ControlRejected, match="exactly one"):
        verify_physical_candidate(store, arguments)


@pytest.mark.parametrize("raw", [b"{}", b"{}\n\n", b"{ }\n", b"{}\n", b"[]\n"])
def test_marker_canonical_line_and_schema(tmp_path: Path, raw: bytes) -> None:
    _, values = inputs()
    values[f"completion/{PART}.txt"] = raw
    store, arguments = persist(tmp_path, values)
    with pytest.raises(ControlRejected):
        verify_physical_candidate(store, arguments)


@pytest.mark.parametrize(
    "field,value",
    [
        ("run_id", "run-else"),
        ("attempt_id", "attempt-other"),
        ("control_record_identity", "control-other"),
        ("authoritative_proof", True),
        ("transaction_count", True),
    ],
)
def test_candidate_identity_and_authority_rejections(
    tmp_path: Path, field: str, value: Any
) -> None:
    _, values = inputs()
    rewrite_marker(values, "candidate-manifest", lambda v: v.update({field: value}))
    store, arguments = persist(tmp_path, values)
    with pytest.raises(ControlRejected):
        verify_physical_candidate(store, arguments)


@pytest.mark.parametrize("field", ["logical_sha256", "candidate_manifest_file_sha256"])
def test_completion_link_rejections(tmp_path: Path, field: str) -> None:
    _, values = inputs()
    rewrite_marker(values, "completion", lambda v: v.update({field: "b" * 64}))
    store, arguments = persist(tmp_path, values)
    with pytest.raises(ControlRejected, match="does not bind"):
        verify_physical_candidate(store, arguments)


def test_completion_must_bind_same_valid_glue_job_run(tmp_path: Path) -> None:
    _, values = inputs()
    rewrite_marker(
        values, "completion", lambda v: v.update(glue_job_run_id="jr_" + "e" * 64)
    )
    store, arguments = persist(tmp_path, values)
    with pytest.raises(ControlRejected, match="does not bind"):
        verify_physical_candidate(store, arguments)


@pytest.mark.parametrize(
    "fault", ["changed", "missing", "duplicate", "unsorted", "size", "success"]
)
def test_inventory_and_bytes_rejections(tmp_path: Path, fault: str) -> None:
    _, values = inputs()
    if fault == "changed":
        path = f"transactions/{PART}.snappy.parquet"
        values[path] = b"X" * len(values[path])
    elif fault == "missing":
        del values[f"transactions/{PART}.snappy.parquet"]
    elif fault == "success":
        values["transactions/_SUCCESS"] = b"unexpected"
    else:

        def edit(v: dict[str, Any]) -> None:
            if fault == "duplicate":
                v["physical_files"].append(v["physical_files"][0])
            elif fault == "unsorted":
                v["physical_files"].reverse()
            else:
                v["physical_files"][0]["size_bytes"] += 1

        rewrite_marker(values, "candidate-manifest", edit)
    store, arguments = persist(tmp_path, values)
    with pytest.raises(ControlRejected):
        verify_physical_candidate(store, arguments)


class BrokenListing(LocalVersionedObjects):
    """Deliberately invalid adapter metadata for fail-closed contract negatives."""

    listing: tuple[ObjectVersion, ...] = ()

    def versions(self, prefix: str) -> tuple[ObjectVersion, ...]:
        return self.listing


@pytest.mark.parametrize("fault", ["outside", "null", "duplicate", "size", "latest", "bool"])
def test_adapter_listing_rejections(tmp_path: Path, fault: str) -> None:
    store = BrokenListing(tmp_path / "objects.sqlite")
    version = ObjectVersion("s3://bucket-one/attempt/data", "v1", True, False, 1)
    if fault == "outside":
        version = replace(version, uri="s3://bucket-one/other/data")
    elif fault == "null":
        version = replace(version, version_id="null")
    elif fault == "size":
        version = replace(version, size_bytes=-1)
    elif fault == "latest":
        version = replace(version, is_latest=False)
    elif fault == "bool":
        version = replace(version, size_bytes=True)
    store.listing = (version, version) if fault == "duplicate" else (version,)
    with pytest.raises(ControlRejected):
        snapshot(store, "s3://bucket-one/attempt")


def test_local_prefix_boundaries_and_missing_version(tmp_path: Path) -> None:
    store = LocalVersionedObjects(tmp_path / "objects.sqlite")
    version = store.put("s3://bucket-one/attempt2/data", b"other")
    assert snapshot(store, "s3://bucket-one/attempt") == ()
    with pytest.raises(ControlRejected):
        store.read("s3://bucket-one/attempt/data", version)


@pytest.mark.parametrize(
    "target,delta",
    [
        ("completion", 131072),
        ("completion", -1),
        ("completion", 1),
        ("transactions", -1),
        ("transactions", 1),
    ],
)
def test_listing_size_must_match_actual_stream(
    tmp_path: Path,
    target: str,
    delta: int,
) -> None:
    _, values = inputs()
    original, arguments = persist(tmp_path, values)
    store = BrokenListing(original.path)
    store.listing = tuple(
        replace(v, size_bytes=v.size_bytes + delta) if f"/{target}/part-" in v.uri else v
        for v in original.versions(arguments.candidate_output_prefix)
    )
    with pytest.raises(ControlRejected):
        verify_physical_candidate(store, arguments)


def test_complete_inventory_still_requires_all_three_families(tmp_path: Path) -> None:
    _, values = inputs()
    del values[f"bank-allocations/{PART}.snappy.parquet"]
    extra = f"transactions/{PART.replace('00000', '00001')}.snappy.parquet"
    values[extra] = b"extra transaction partition"

    def edit(document: dict[str, Any]) -> None:
        document["physical_files"] = [
            {"path": path, "size_bytes": len(raw), "sha256": sha256(raw).hexdigest()}
            for path, raw in sorted(values.items())
            if path.endswith(".parquet")
        ]

    rewrite_marker(values, "candidate-manifest", edit)
    store, arguments = persist(tmp_path, values)
    with pytest.raises(ControlRejected, match="table family missing"):
        verify_physical_candidate(store, arguments)


def test_unimplemented_object_backend_cannot_silently_admit_data(tmp_path: Path) -> None:
    class Incomplete(VersionedObjects):
        pass

    with pytest.raises(TypeError, match="abstract"):
        Incomplete()
    store = LocalVersionedObjects(tmp_path / "objects.sqlite")
    for method, args in (
        (VersionedObjects.versions, ("s3://bucket-one/attempt",)),
        (VersionedObjects.read, ("s3://bucket-one/attempt/data", "v1")),
        (VersionedObjects.chunks, ("s3://bucket-one/attempt/data", "v1")),
    ):
        with pytest.raises(NotImplementedError):
            method(store, *args)


@pytest.mark.parametrize("suffix", [b"", b"\n\n", b" \n"])
def test_valid_marker_content_requires_exact_line_bytes(tmp_path: Path, suffix: bytes) -> None:
    _, values = inputs()
    path = f"completion/{PART}.txt"
    values[path] = values[path].rstrip(b"\n") + suffix
    store, arguments = persist(tmp_path, values)
    with pytest.raises(ControlRejected, match="canonical JSON line"):
        verify_physical_candidate(store, arguments)
