#!/usr/bin/env python3
"""Build the dedicated reproducible Stage 3 Glue runtime and offline wheelhouse."""

from __future__ import annotations

import argparse
import base64
import csv
import email.parser
import json
import os
import sys
import zipfile
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import Any

RUNTIME_STAGE3 = (
    "__init__.py",
    "arguments.py",
    "canonical.py",
    "errors.py",
    "formats.py",
    "job.py",
    "paths.py",
    "runtime_admission.py",
    "spark_pipeline.py",
)
DEPENDENCIES = {
    "attrs": "26.1.0",
    "jsonschema": "4.26.0",
    "jsonschema_specifications": "2025.9.1",
    "referencing": "0.37.0",
    "rpds_py": "2026.6.3",
    "typing_extensions": "4.16.0",
}


def _timestamp(epoch: int) -> tuple[int, int, int, int, int, int]:
    value = datetime.fromtimestamp(max(epoch, 315532800), UTC)
    return value.year, value.month, value.day, value.hour, value.minute, value.second


def _zip(path: Path, members: dict[str, bytes], epoch: int) -> None:
    with zipfile.ZipFile(path, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name in sorted(members):
            pure = PurePosixPath(name)
            if pure.is_absolute() or ".." in pure.parts or name.endswith("/"):
                raise SystemExit(f"unsafe archive member: {name}")
            info = zipfile.ZipInfo(name, _timestamp(epoch))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, members[name])


def _record_line(name: str, raw: bytes) -> str:
    encoded = base64.urlsafe_b64encode(sha256(raw).digest()).decode().rstrip("=")
    return f"{name},sha256={encoded},{len(raw)}"


def _runtime_members(repository: Path) -> dict[str, bytes]:
    members: dict[str, bytes] = {}
    members["ledgerguard/__init__.py"] = b'"""LedgerGuard production runtime."""\n'
    for path in sorted((repository / "src/ledgerguard/reconciliation").glob("*.py")):
        members[f"ledgerguard/reconciliation/{path.name}"] = path.read_bytes()
    for name in RUNTIME_STAGE3:
        members[f"ledgerguard/stage3/{name}"] = (
            repository / "src/ledgerguard/stage3" / name
        ).read_bytes()
    members["ledgerguard/contract_data/__init__.py"] = (
        repository / "src/ledgerguard/contract_data/__init__.py"
    ).read_bytes()
    registry = repository / "contracts/active-contract-set-v1.json"
    members["ledgerguard/contract_data/contracts/active-contract-set-v1.json"] = (
        registry.read_bytes()
    )
    authority = json.loads(registry.read_text(encoding="utf-8"))
    for row in authority["contracts"]:
        relative = str(row["path"])
        source = repository / relative
        raw = source.read_bytes()
        if sha256(raw).hexdigest() != row["sha256"]:
            raise SystemExit(f"contract digest mismatch: {relative}")
        members[f"ledgerguard/contract_data/{relative}"] = raw
    return members


def build_runtime_wheel(repository: Path, destination: Path, epoch: int) -> dict[str, Any]:
    members = _runtime_members(repository)
    dist = "ledgerguard_runtime-0.1.0.dist-info"
    members[f"{dist}/METADATA"] = (
        b"Metadata-Version: 2.4\n"
        b"Name: ledgerguard-runtime\n"
        b"Version: 0.1.0\n"
        b"Summary: LedgerGuard Stage 3 production-only Glue runtime\n"
        b"Requires-Python: >=3.11,<3.12\n"
        b"Requires-Dist: jsonschema==4.26.0\n\n"
    )
    members[f"{dist}/WHEEL"] = (
        b"Wheel-Version: 1.0\n"
        b"Generator: ledgerguard-stage3\n"
        b"Root-Is-Purelib: true\n"
        b"Tag: py3-none-any\n"
    )
    record_name = f"{dist}/RECORD"
    record = [_record_line(name, raw) for name, raw in sorted(members.items())]
    record.append(f"{record_name},,")
    members[record_name] = ("\n".join(record) + "\n").encode()
    _zip(destination, members, epoch)
    return {
        "filename": destination.name,
        "sha256": sha256(destination.read_bytes()).hexdigest(),
        "size_bytes": destination.stat().st_size,
        "member_count": len(members),
    }


def _site_packages(environment: Path) -> Path:
    candidates = (
        [environment / "Lib/site-packages"]
        if os.name == "nt"
        else sorted((environment / "lib").glob("python3.11/site-packages"))
    )
    if len(candidates) != 1 or not candidates[0].is_dir():
        raise SystemExit("exact CPython 3.11 environment site-packages unavailable")
    return candidates[0]


def _distribution_members(site: Path, dist_info: Path) -> dict[str, bytes]:
    rows = csv.reader((dist_info / "RECORD").read_text(encoding="utf-8").splitlines())
    members: dict[str, bytes] = {}
    for row in rows:
        if not row:
            continue
        pure = PurePosixPath(row[0])
        if pure.is_absolute() or ".." in pure.parts or pure.name == "RECORD":
            continue
        if pure.parent == PurePosixPath(dist_info.name) and pure.name in {
            "INSTALLER",
            "REQUESTED",
            "direct_url.json",
            "uv_cache.json",
        }:
            # These describe the local installation tool or source, not the
            # locked wheel payload, and would make a rebuilt wheel depend on
            # whether pip or uv created the build environment.
            continue
        source = site.joinpath(*pure.parts)
        if source.is_symlink() or not source.is_file() or "__pycache__" in pure.parts:
            continue
        members[pure.as_posix()] = source.read_bytes()
    return members


def build_dependency_wheel(
    site: Path, distribution: str, version: str, destination: Path, epoch: int
) -> dict[str, Any]:
    matches = sorted(site.glob(f"{distribution}-{version}.dist-info"))
    if len(matches) != 1:
        raise SystemExit(f"locked distribution unavailable: {distribution}=={version}")
    dist_info = matches[0]
    metadata = email.parser.Parser().parsestr((dist_info / "METADATA").read_text(encoding="utf-8"))
    if metadata["Version"] != version:
        raise SystemExit(f"distribution version mismatch: {distribution}")
    wheel_lines = (dist_info / "WHEEL").read_text(encoding="utf-8").splitlines()
    tags = [line.split(":", 1)[1].strip() for line in wheel_lines if line.startswith("Tag:")]
    if not tags:
        raise SystemExit(f"wheel tag unavailable: {distribution}")
    tag = tags[0]
    normalized_name = str(metadata["Name"]).lower().replace("-", "_")
    filename = f"{normalized_name}-{version}-{tag}.whl"
    members = _distribution_members(site, dist_info)
    record_name = f"{dist_info.name}/RECORD"
    record = [_record_line(name, raw) for name, raw in sorted(members.items())]
    record.append(f"{record_name},,")
    members[record_name] = ("\n".join(record) + "\n").encode()
    target = destination / filename
    _zip(target, members, epoch)
    if tag == "py3-none-any" and any(name.endswith((".so", ".dll", ".dylib")) for name in members):
        raise SystemExit(f"native member in pure wheel: {distribution}")
    if distribution == "rpds_py" and "cp311-cp311-manylinux" not in tag:
        raise SystemExit("rpds-py wheel is not CPython 3.11 manylinux compatible")
    return {
        "distribution": str(metadata["Name"]),
        "version": version,
        "filename": filename,
        "tag": tag,
        "sha256": sha256(target.read_bytes()).hexdigest(),
        "size_bytes": target.stat().st_size,
        "license_expression": metadata.get("License-Expression", "NOASSERTION"),
        "member_count": len(members),
    }


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False).encode() + b"\n"


def _inventory(members: dict[str, bytes]) -> list[dict[str, Any]]:
    return [
        {"path": name, "size_bytes": len(raw), "sha256": sha256(raw).hexdigest()}
        for name, raw in sorted(members.items())
    ]


def _sbom(
    source_commit: str,
    runtime: dict[str, Any],
    dependencies: list[dict[str, Any]],
) -> dict[str, Any]:
    packages = [
        {
            "SPDXID": "SPDXRef-Package-LedgerGuardRuntime",
            "name": "ledgerguard-runtime",
            "versionInfo": "0.1.0",
            "downloadLocation": "NOASSERTION",
            "filesAnalyzed": False,
            "checksums": [{"algorithm": "SHA256", "checksumValue": runtime["sha256"]}],
            "licenseConcluded": "MIT",
            "licenseDeclared": "MIT",
        }
    ]
    relationships = [
        {
            "spdxElementId": "SPDXRef-DOCUMENT",
            "relationshipType": "DESCRIBES",
            "relatedSpdxElement": "SPDXRef-Package-LedgerGuardRuntime",
        }
    ]
    for index, row in enumerate(dependencies):
        identifier = f"SPDXRef-Package-Dependency-{index}"
        packages.append(
            {
                "SPDXID": identifier,
                "name": row["distribution"],
                "versionInfo": row["version"],
                "downloadLocation": "NOASSERTION",
                "filesAnalyzed": False,
                "checksums": [{"algorithm": "SHA256", "checksumValue": row["sha256"]}],
                "licenseConcluded": "NOASSERTION",
                "licenseDeclared": row["license_expression"],
            }
        )
        relationships.append(
            {
                "spdxElementId": "SPDXRef-Package-LedgerGuardRuntime",
                "relationshipType": "DEPENDS_ON",
                "relatedSpdxElement": identifier,
            }
        )
    return {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": f"ledgerguard-stage3-{source_commit}",
        "documentNamespace": f"https://ledgerguard.local/spdx/{source_commit}",
        "creationInfo": {
            "created": "2026-09-09T00:00:00Z",
            "creators": ["Tool: ledgerguard-stage3-runtime-builder/1.0"],
        },
        "packages": packages,
        "relationships": relationships,
    }


def build_bundle(
    repository: Path,
    environment: Path,
    output: Path,
    source_commit: str,
    source_tree: str,
    epoch: int,
) -> dict[str, Any]:
    if output.exists() and any(output.iterdir()):
        raise SystemExit("runtime output directory must be empty")
    output.mkdir(parents=True, exist_ok=True)
    wheelhouse = output / "wheelhouse"
    wheelhouse.mkdir()
    runtime_path = wheelhouse / "ledgerguard_runtime-0.1.0-py3-none-any.whl"
    runtime = build_runtime_wheel(repository, runtime_path, epoch)
    site = _site_packages(environment)
    dependencies = [
        build_dependency_wheel(site, name, version, wheelhouse, epoch)
        for name, version in DEPENDENCIES.items()
    ]
    lock = {
        "schema_version": "1.0",
        "python": "3.11.13",
        "platform": "manylinux2014_x86_64",
        "runtime": runtime,
        "dependencies": dependencies,
        "platform_provided": {
            "aws_glue": "5.1",
            "python": "3.11",
            "spark": "3.5.6",
            "java": "17",
        },
        "network_required_at_runtime": False,
    }
    sbom = _sbom(source_commit, runtime, dependencies)
    licenses = {
        "schema_version": "1.0",
        "project": {"name": "ledgerguard-runtime", "license": "MIT"},
        "dependencies": [
            {
                "name": row["distribution"],
                "version": row["version"],
                "license_expression": row["license_expression"],
            }
            for row in dependencies
        ],
    }
    provenance = {
        "schema_version": "1.0",
        "source_commit": source_commit,
        "source_tree": source_tree,
        "builder": "tools/build_part3_stage3_runtime.py",
        "source_date_epoch": epoch,
        "production_allowlist": list(RUNTIME_STAGE3),
        "excluded": [
            "ledgerguard_reference_oracle",
            "ledgerguard.stage3.generator",
            "ledgerguard.stage3.expectations",
            "tests",
            "evidence tools",
            "AWS Stage 2 control-plane code",
        ],
    }
    bundle_members: dict[str, bytes] = {
        "glue/ledgerguard_stage3_job.py": (
            repository / "glue/ledgerguard_stage3_job.py"
        ).read_bytes(),
        "requirements/runtime-wheels.json": _json_bytes(lock),
        "SBOM.spdx.json": _json_bytes(sbom),
        "LICENSES.json": _json_bytes(licenses),
        "PROVENANCE.json": _json_bytes(provenance),
    }
    requirement_rows = [
        f"ledgerguard-runtime==0.1.0 --hash=sha256:{runtime['sha256']}"
    ]
    requirement_rows.extend(
        f"{row['distribution']}=={row['version']} --hash=sha256:{row['sha256']}"
        for row in dependencies
    )
    bundle_members["requirements/runtime.lock"] = (
        "\n".join(requirement_rows) + "\n"
    ).encode()
    for wheel in sorted(wheelhouse.glob("*.whl")):
        bundle_members[f"wheelhouse/{wheel.name}"] = wheel.read_bytes()
    sbom_sha = sha256(bundle_members["SBOM.spdx.json"]).hexdigest()
    manifest = {
        "schema_version": "1.0",
        "source_commit": source_commit,
        "source_tree": source_tree,
        "python": "3.11.13",
        "spark": "3.5.6",
        "java": "17",
        "members": _inventory(bundle_members),
        "runtime_wheel_sha256": runtime["sha256"],
        "sbom_sha256": sbom_sha,
        "oracle_excluded": True,
        "generator_excluded": True,
    }
    bundle_members["package-manifest.json"] = _json_bytes(manifest)
    bundle_path = output / "ledgerguard-stage3-glue-runtime.zip"
    _zip(bundle_path, bundle_members, epoch)
    result = {
        "schema_version": "1.0",
        "bundle": {
            "path": bundle_path.name,
            "size_bytes": bundle_path.stat().st_size,
            "sha256": sha256(bundle_path.read_bytes()).hexdigest(),
            "member_count": len(bundle_members),
        },
        "runtime": runtime,
        "dependencies": dependencies,
        "sbom_sha256": sbom_sha,
        "source_commit": source_commit,
        "source_tree": source_tree,
    }
    (output / "build-result.json").write_bytes(_json_bytes(result))
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument("--environment", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--source-tree", required=True)
    parser.add_argument("--source-date-epoch", type=int, required=True)
    arguments = parser.parse_args()
    if sys.version_info[:3] != (3, 11, 13):
        raise SystemExit("runtime build requires exact CPython 3.11.13")
    if len(arguments.source_commit) != 40 or len(arguments.source_tree) not in {40, 64}:
        raise SystemExit("invalid source identity")
    result = build_bundle(
        arguments.repository.resolve(),
        arguments.environment.resolve(),
        arguments.output.resolve(),
        arguments.source_commit,
        arguments.source_tree,
        arguments.source_date_epoch,
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
