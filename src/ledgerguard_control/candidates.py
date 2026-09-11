"""Independent physical candidate verification of the frozen managed writer.

This proves byte/version/marker identity only. Independent financial comparison,
actual terminal Glue ownership and Athena proof remain separate required gates.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from hashlib import sha256
from typing import Any

from jsonschema import Draft202012Validator

from ledgerguard.stage3.arguments import JobArguments
from ledgerguard.stage3.canonical import canonical_bytes

from .contracts import ID, MAX_DOCUMENT_BYTES, SHA256, UINT, ControlRejected, closed, strict_json
from .objects import ObjectVersion, VersionedObjects, assert_unchanged, snapshot, snapshot_digest

_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
_PART = rf"part-[0-9]{{5}}-{_UUID}"
_PARQUET = re.compile(
    rf"(transactions|settlements|bank-allocations)/{_PART}-c[0-9]{{3}}\.snappy\.parquet"
)
_MARKER = re.compile(rf"(candidate-manifest|completion)/{_PART}-c[0-9]{{3}}\.txt")
_FAMILIES = {"transactions", "settlements", "bank-allocations"}
_DIRECTORIES = _FAMILIES | {"candidate-manifest", "completion"}
_PHYSICAL = closed(
    {"path": {"type": "string"}, "size_bytes": {**UINT, "minimum": 1}, "sha256": SHA256}
)
_MANIFEST = closed(
    {
        "schema_version": {"const": "1.0"},
        "run_id": ID,
        "attempt_id": ID,
        "control_record_identity": ID,
        "transaction_count": UINT,
        "settlement_count": UINT,
        "allocation_count": UINT,
        "logical_sha256": SHA256,
        "physical_files": {"type": "array", "items": _PHYSICAL, "minItems": 3},
        "authoritative_proof": {"const": False},
    }
)
_COMPLETION = closed(
    {
        "schema_version": {"const": "1.0"},
        "candidate_manifest_file_sha256": SHA256,
        "logical_sha256": SHA256,
        "authoritative_proof": {"const": False},
        "state": {"const": "COMPLETE_NON_AUTHORITATIVE_CANDIDATE"},
    }
)


@dataclass(frozen=True)
class PhysicalCandidate:
    manifest: dict[str, Any]
    manifest_reference: dict[str, Any]
    completion_reference: dict[str, Any]
    physical_references: tuple[dict[str, Any], ...]
    versions: tuple[ObjectVersion, ...]
    version_inventory_sha256: str


def _read(store: VersionedObjects, version: ObjectVersion) -> tuple[bytes, dict[str, Any]]:
    if version.size_bytes > MAX_DOCUMENT_BYTES:
        raise ControlRejected("candidate marker exceeds byte bound")
    parts = []
    size = 0
    for chunk in store.chunks(version.uri, version.version_id):
        size += len(chunk)
        if size > version.size_bytes:
            raise ControlRejected("object size differs from listed version")
        parts.append(chunk)
    raw = b"".join(parts)
    if len(raw) != version.size_bytes:
        raise ControlRejected("object size differs from listed version")
    return raw, {
        "uri": version.uri,
        "version_id": version.version_id,
        "size_bytes": len(raw),
        "sha256": sha256(raw).hexdigest(),
    }


def _fingerprint(store: VersionedObjects, version: ObjectVersion) -> dict[str, Any]:
    size = 0
    digest = sha256()
    for chunk in store.chunks(version.uri, version.version_id):
        size += len(chunk)
        if size > version.size_bytes:
            raise ControlRejected("candidate stream exceeds listed size")
        digest.update(chunk)
    if size != version.size_bytes:
        raise ControlRejected("candidate stream is truncated")
    return {
        "uri": version.uri,
        "version_id": version.version_id,
        "size_bytes": size,
        "sha256": digest.hexdigest(),
    }


def _marker_document(raw: bytes, schema: dict[str, Any]) -> dict[str, Any]:
    value = strict_json(raw)
    if raw != canonical_bytes(value) + b"\n":
        raise ControlRejected("marker must be exactly one canonical JSON line")
    if not Draft202012Validator(schema).is_valid(value):
        raise ControlRejected("marker schema mismatch")
    return value


def verify_physical_candidate(
    store: VersionedObjects,
    arguments: JobArguments,
) -> PhysicalCandidate:
    prefix = arguments.candidate_output_prefix
    before = snapshot(store, prefix)
    latest = {value.uri[len(prefix) + 1 :]: value for value in before if value.is_latest}
    if any(value.delete_marker for value in before):
        raise ControlRejected("candidate prefix contains a deletion history")
    # A managed attempt is single-writer and write-once. Versioning records an
    # overwrite; it cannot make one acceptable even if its bytes were restored.
    if len(latest) != len(before):
        raise ControlRejected("candidate prefix contains an overwrite history")
    markers: dict[str, list[str]] = {"candidate-manifest": [], "completion": []}
    physical: dict[str, ObjectVersion] = {}
    for path, version in latest.items():
        if _PARQUET.fullmatch(path):
            physical[path] = version
        elif _MARKER.fullmatch(path):
            markers[path.split("/")[0]].append(path)
        elif path in {f"{directory}/_SUCCESS" for directory in _DIRECTORIES}:
            raw, _ = _read(store, version)
            if raw:
                raise ControlRejected("unexpected nonempty Spark success marker")
        else:
            raise ControlRejected(f"unexpected candidate object: {path}")
    if any(len(paths) != 1 for paths in markers.values()):
        raise ControlRejected("exactly one data object required in each marker directory")
    manifest_raw, manifest_ref = _read(store, latest[markers["candidate-manifest"][0]])
    completion_raw, completion_ref = _read(store, latest[markers["completion"][0]])
    manifest = _marker_document(manifest_raw, _MANIFEST)
    completion = _marker_document(completion_raw, _COMPLETION)
    for name in ("run_id", "attempt_id", "control_record_identity"):
        if manifest[name] != asdict(arguments)[name]:
            raise ControlRejected("candidate identity differs from admitted attempt")
    if (
        completion["candidate_manifest_file_sha256"] != manifest_ref["sha256"]
        or completion["logical_sha256"] != manifest["logical_sha256"]
    ):
        raise ControlRejected("completion does not bind candidate manifest")
    rows = manifest["physical_files"]
    paths = [row["path"] for row in rows]
    if paths != sorted(set(paths)) or set(paths) != set(physical):
        raise ControlRejected("manifest and actual physical inventory differ")
    if {path.split("/")[0] for path in paths} != _FAMILIES:
        raise ControlRejected("candidate table family missing")
    references = []
    for row in rows:
        reference = _fingerprint(store, physical[row["path"]])
        if reference["sha256"] != row["sha256"] or reference["size_bytes"] != row["size_bytes"]:
            raise ControlRejected("candidate bytes differ from manifest")
        references.append(reference)
    assert_unchanged(store, prefix, before)
    return PhysicalCandidate(
        manifest,
        manifest_ref,
        completion_ref,
        tuple(references),
        before,
        snapshot_digest(before),
    )
