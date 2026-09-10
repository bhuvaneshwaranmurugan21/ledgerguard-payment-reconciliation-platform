"""Streaming manifest-bound local admission used before Spark starts."""

from __future__ import annotations

import csv
import json
from collections.abc import Iterator
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import Any

from ledgerguard.reconciliation.contracts import MANIFEST_FAMILY_CONTRACTS, ContractRegistry

from .canonical import canonical_bytes, canonical_digest
from .errors import Stage3Rejected
from .formats import CSV_FIELDS, FAMILIES, SOURCE_DIGEST_EXCLUSIONS

_INTEGER_FIELDS = frozenset(
    {
        "amount_minor",
        "gross_minor",
        "fee_minor",
        "refund_minor",
        "chargeback_minor",
        "reserve_minor",
        "reported_net_minor",
    }
)


@dataclass(frozen=True)
class RuntimeInputs:
    root: Path
    policy: dict[str, Any]
    manifest: dict[str, Any]
    source_bundle: dict[str, Any]
    raw_paths: dict[str, tuple[Path | str, ...]]


def _document(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
        value = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise Stage3Rejected("ADMISSION_FAILURE", f"invalid document: {path.name}") from error
    if not isinstance(value, dict) or raw != canonical_bytes(value) + b"\n":
        raise Stage3Rejected("ADMISSION_FAILURE", f"noncanonical document: {path.name}")
    return value


def _relative(root: Path, value: object) -> Path:
    if not isinstance(value, str):
        raise Stage3Rejected("ADMISSION_FAILURE", "relative path is not text")
    pure = PurePosixPath(value)
    if pure.is_absolute() or not pure.parts or any(part in {"", ".", ".."} for part in pure.parts):
        raise Stage3Rejected("ADMISSION_FAILURE", "unsafe relative path")
    path = root.joinpath(*pure.parts)
    if not path.is_file() or root not in path.resolve().parents:
        raise Stage3Rejected("ADMISSION_FAILURE", "source object unavailable")
    return path


def _identity(path: Path) -> tuple[int, str]:
    size = 0
    digest = sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            size += len(chunk)
            digest.update(chunk)
    return size, digest.hexdigest()


def _json_records(path: Path) -> Iterator[dict[str, Any]]:
    with path.open("rb") as handle:
        for raw in handle:
            if raw == b"\n" or not raw.endswith(b"\n") or b"\r" in raw:
                raise Stage3Rejected("FORMAT_VIOLATION", f"invalid JSONL framing: {path}")
            try:
                value = json.loads(raw)
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise Stage3Rejected("FORMAT_VIOLATION", f"invalid JSON: {path}") from error
            if not isinstance(value, dict) or raw != canonical_bytes(value) + b"\n":
                raise Stage3Rejected("FORMAT_VIOLATION", f"noncanonical JSONL: {path}")
            yield value


def _csv_records(path: Path, family: str) -> Iterator[dict[str, Any]]:
    fields = CSV_FIELDS[family]
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != fields:
            raise Stage3Rejected("FORMAT_VIOLATION", f"CSV header mismatch: {path}")
        for row in reader:
            if None in row or any(value is None for value in row.values()):
                raise Stage3Rejected("FORMAT_VIOLATION", f"CSV row width mismatch: {path}")
            yield {
                key: int(value) if key in _INTEGER_FIELDS else value
                for key, value in row.items()
                if value != ""
            }


def _validate_records(
    registry: ContractRegistry, family: str, physical_format: str, path: Path
) -> int:
    contract_family = MANIFEST_FAMILY_CONTRACTS[family]
    expected = "CSV_RFC4180_LF" if family in CSV_FIELDS else "JSONL_CANONICAL_LF"
    if physical_format != expected:
        raise Stage3Rejected("FORMAT_VIOLATION", f"wrong format for {family}")
    records = _csv_records(path, family) if family in CSV_FIELDS else _json_records(path)
    count = 0
    for value in records:
        if canonical_digest(
            {key: item for key, item in value.items() if key not in SOURCE_DIGEST_EXCLUSIONS}
        ) != value.get("payload_sha256"):
            raise Stage3Rejected("SOURCE_IDENTITY_MISMATCH", f"payload digest: {path}")
        try:
            registry.validate(contract_family, value)
        except ValueError as error:
            raise Stage3Rejected("SCHEMA_VIOLATION", f"{family}:{count}") from error
        count += 1
    return count


def admit_runtime_bundle(repository: Path, root: Path) -> RuntimeInputs:
    repository = repository.resolve()
    root = root.resolve()
    registry = ContractRegistry.load(repository)
    policy = _document(root / "policy.json")
    manifest = _document(root / "run-manifest.json")
    source = _document(root / "source-bundle.json")
    try:
        registry.validate("RECONCILIATION_POLICY", policy)
        registry.validate("RUN_MANIFEST", manifest)
    except ValueError as error:
        raise Stage3Rejected("SCHEMA_VIOLATION", "policy or manifest") from error
    if canonical_digest(
        {key: value for key, value in policy.items() if key != "policy_sha256"}
    ) != policy.get("policy_sha256"):
        raise Stage3Rejected("POLICY_MISMATCH", "policy digest")
    if canonical_digest(
        {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    ) != manifest.get("manifest_sha256"):
        raise Stage3Rejected("SOURCE_IDENTITY_MISMATCH", "manifest digest")
    if canonical_digest(
        {key: value for key, value in source.items() if key != "source_bundle_sha256"}
    ) != source.get("source_bundle_sha256"):
        raise Stage3Rejected("SOURCE_IDENTITY_MISMATCH", "source-bundle digest")
    if source.get("policy_sha256") != policy.get("policy_sha256") or source.get(
        "manifest_sha256"
    ) != manifest.get("manifest_sha256"):
        raise Stage3Rejected("SOURCE_IDENTITY_MISMATCH", "document binding")
    rows = source.get("objects")
    if not isinstance(rows, list):
        raise Stage3Rejected("ADMISSION_FAILURE", "source objects unavailable")
    grouped: dict[str, list[Path]] = {family: [] for family in FAMILIES}
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict) or row.get("family") not in grouped:
            raise Stage3Rejected("ADMISSION_FAILURE", "invalid source object")
        family = str(row["family"])
        relative = row.get("relative_path")
        if not isinstance(relative, str) or relative in seen:
            raise Stage3Rejected("ADMISSION_FAILURE", "duplicate source path")
        seen.add(relative)
        path = _relative(root, relative)
        size, digest = _identity(path)
        if size != row.get("size_bytes") or digest != row.get("sha256"):
            raise Stage3Rejected("SOURCE_IDENTITY_MISMATCH", f"object identity: {relative}")
        count = _validate_records(registry, family, str(row.get("physical_format")), path)
        if count != row.get("record_count"):
            raise Stage3Rejected("SOURCE_IDENTITY_MISMATCH", f"object count: {relative}")
        grouped[family].append(path)
    if any(not paths for paths in grouped.values()):
        raise Stage3Rejected("ADMISSION_FAILURE", "source family set incomplete")
    return RuntimeInputs(
        root, policy, manifest, source, {key: tuple(value) for key, value in grouped.items()}
    )
