#!/usr/bin/env python3
"""Independently inspect a Stage 3 runtime bundle without executing its code."""

from __future__ import annotations

import argparse
import base64
import csv
import io
import json
import stat
import zipfile
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import Any


def _safe_members(archive: zipfile.ZipFile) -> dict[str, bytes]:
    rows = archive.infolist()
    names = [row.filename for row in rows]
    if len(names) != len(set(names)):
        raise ValueError("duplicate archive member")
    members: dict[str, bytes] = {}
    for row in rows:
        path = PurePosixPath(row.filename)
        mode = row.external_attr >> 16
        if (
            path.is_absolute()
            or not path.parts
            or ".." in path.parts
            or row.filename.endswith("/")
            or stat.S_ISLNK(mode)
            or stat.S_ISDIR(mode)
        ):
            raise ValueError(f"unsafe archive member: {row.filename}")
        if mode and stat.S_IMODE(mode) != 0o644:
            raise ValueError(f"unexpected archive mode: {row.filename}")
        members[row.filename] = archive.read(row)
    return members


def _json(members: dict[str, bytes], name: str) -> dict[str, Any]:
    try:
        value = json.loads(members[name])
    except (KeyError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid required JSON member: {name}") from error
    if not isinstance(value, dict):
        raise ValueError(f"JSON member is not an object: {name}")
    return value


def _inspect_record(wheel: bytes) -> dict[str, Any]:
    with zipfile.ZipFile(io.BytesIO(wheel)) as archive:
        members = _safe_members(archive)
    records = [name for name in members if name.endswith(".dist-info/RECORD")]
    if len(records) != 1:
        raise ValueError("wheel must contain exactly one RECORD")
    seen: set[str] = set()
    for row in csv.reader(members[records[0]].decode().splitlines()):
        if len(row) != 3 or row[0] in seen:
            raise ValueError("invalid or duplicate RECORD row")
        seen.add(row[0])
        if row[0] == records[0]:
            if row[1:] != ["", ""]:
                raise ValueError("RECORD self-row is not empty")
            continue
        raw = members.get(row[0])
        if raw is None or row[2] != str(len(raw)):
            raise ValueError(f"RECORD member or size mismatch: {row[0]}")
        expected = "sha256=" + base64.urlsafe_b64encode(sha256(raw).digest()).decode().rstrip("=")
        if row[1] != expected:
            raise ValueError(f"RECORD digest mismatch: {row[0]}")
    if seen != set(members):
        raise ValueError("RECORD coverage differs from wheel members")
    return {"member_count": len(members), "record_sha256": sha256(members[records[0]]).hexdigest()}


def inspect_runtime_bundle(path: Path) -> dict[str, Any]:
    with zipfile.ZipFile(path) as archive:
        members = _safe_members(archive)
        timestamps = sorted({row.date_time for row in archive.infolist()})
    required = {
        "glue/ledgerguard_stage3_job.py",
        "requirements/runtime-wheels.json",
        "requirements/runtime.lock",
        "SBOM.spdx.json",
        "LICENSES.json",
        "PROVENANCE.json",
        "package-manifest.json",
    }
    if not required.issubset(members):
        raise ValueError("required runtime bundle members unavailable")
    manifest = _json(members, "package-manifest.json")
    declared = manifest.get("members")
    if not isinstance(declared, list):
        raise ValueError("package member inventory unavailable")
    expected_names = set(members).difference({"package-manifest.json"})
    declared_names: set[str] = set()
    for row in declared:
        if not isinstance(row, dict) or not isinstance(row.get("path"), str):
            raise ValueError("invalid package inventory row")
        name = row["path"]
        if name in declared_names or name not in expected_names:
            raise ValueError("duplicate or unexpected package inventory path")
        declared_names.add(name)
        raw = members[name]
        if row.get("size_bytes") != len(raw) or row.get("sha256") != sha256(raw).hexdigest():
            raise ValueError(f"package inventory identity mismatch: {name}")
    if declared_names != expected_names:
        raise ValueError("package inventory set differs")
    sbom = _json(members, "SBOM.spdx.json")
    if sbom.get("spdxVersion") != "SPDX-2.3" or sbom.get("dataLicense") != "CC0-1.0":
        raise ValueError("SBOM standard identity differs")
    if manifest.get("sbom_sha256") != sha256(members["SBOM.spdx.json"]).hexdigest():
        raise ValueError("SBOM digest mismatch")
    wheels = sorted(
        name for name in members if name.startswith("wheelhouse/") and name.endswith(".whl")
    )
    if len(wheels) != 7:
        raise ValueError("offline wheel closure count differs")
    runtime = [name for name in wheels if "/ledgerguard_runtime-" in name]
    if len(runtime) != 1:
        raise ValueError("runtime wheel identity differs")
    if manifest.get("runtime_wheel_sha256") != sha256(members[runtime[0]]).hexdigest():
        raise ValueError("runtime wheel digest mismatch")
    wheel_evidence = {name: _inspect_record(members[name]) for name in wheels}
    with zipfile.ZipFile(io.BytesIO(members[runtime[0]])) as archive:
        runtime_names = set(archive.namelist())
    forbidden = ("generator.py", "expectations.py", "campaign.py", "ledgerguard_reference_oracle")
    if any(any(token in name for token in forbidden) for name in runtime_names):
        raise ValueError("production runtime contains an excluded oracle/tooling path")
    bundle_sha256 = sha256(path.read_bytes()).hexdigest()
    return {
        "bundle_sha256": bundle_sha256,
        "bundle_member_count": len(members),
        "wheel_count": len(wheels),
        "timestamps": [list(value) for value in timestamps],
        "runtime_member_count": wheel_evidence[runtime[0]]["member_count"],
        "oracle_excluded": True,
        "generator_excluded": True,
        "sbom_valid": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("bundle", type=Path)
    arguments = parser.parse_args()
    print(json.dumps(inspect_runtime_bundle(arguments.bundle), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
