#!/usr/bin/env python3
"""Build and inspect the reproducible, offline-installable Stage 5 release.

The release manifest is external to the executable archives so it can bind their
actual bytes without a self-reference.  Glue receives AWS Glue 5.x's documented
``.gluewheels.zip`` format.  Lambda receives one root-layout ZIP containing the
same application source plus the exact manylinux NumPy/PyArrow runtime needed by
the candidate validator.  No AWS API is called by this module.
"""

from __future__ import annotations

import argparse
import base64
import csv
import email.parser
import json
import re
import sys
import zipfile
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import Any

from ledgerguard.stage3.canonical import canonical_bytes
from ledgerguard_control.admission import verify_release
from ledgerguard_control.execution import parse_config
from ledgerguard_control.workflow import definition_bytes
from tools.build_part3_stage3_runtime import (
    DEPENDENCIES,
    _distribution_members,
    _record_line,
    _runtime_members,
    _site_packages,
    _zip,
)

NATIVE_DEPENDENCIES = {"numpy": "2.1.3", "pyarrow": "17.0.0"}
NATIVE_WHEEL_SHA256 = {
    "numpy": "bc6f24b3d1ecc1eebfbf5d6051faa49af40b03be1aaa781ebdadcbc090b4539b",
    "pyarrow": "0b72e87fe3e1db343995562f7fff8aee354b55ee83d13afba65400c178ab2597",
}
LAMBDA_ZIPPED_LIMIT = 50 * 1024 * 1024
LAMBDA_UNZIPPED_LIMIT = 250 * 1024 * 1024
MAX_MEMBERS = 4096
PROJECT_WHEEL = "ledgerguard_stage5_runtime-0.1.0-py3-none-any.whl"
_OBJECT = re.compile(r"[0-9a-f]{40}")
_INSTALLER_METADATA = frozenset(
    {"INSTALLER", "REQUESTED", "direct_url.json", "uv_cache.json"}
)


def _digest(raw: bytes) -> str:
    return sha256(raw).hexdigest()


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False).encode() + b"\n"


def _inventory(members: dict[str, bytes]) -> list[dict[str, Any]]:
    return [
        {"path": name, "sha256": _digest(raw), "size_bytes": len(raw)}
        for name, raw in sorted(members.items())
    ]


def _distribution(root: Path, name: str, version: str) -> Path:
    normalized = name.replace("-", "_")
    matches = sorted(root.glob(f"{normalized}-{version}.dist-info"))
    if len(matches) != 1:
        raise ValueError(f"installed distribution differs: {name}=={version}")
    return matches[0]


def _verify_installed_distribution(site: Path, name: str, version: str) -> None:
    """Verify pip's installed RECORD before repackaging any distribution bytes."""
    info = _distribution(site, name, version)
    environment = site.parents[2].resolve()
    rows = list(csv.reader((info / "RECORD").read_text(encoding="utf-8").splitlines()))
    if not rows:
        raise ValueError(f"installed RECORD is empty: {name}")
    for row in rows:
        if len(row) != 3 or not row[0]:
            raise ValueError(f"installed RECORD shape differs: {name}")
        relative, encoded, size = row
        path = PurePosixPath(relative)
        if path.is_absolute():
            raise ValueError(f"unsafe installed RECORD path: {name}")
        if "__pycache__" in path.parts and path.suffix == ".pyc":
            if bool(encoded) != bool(size):
                raise ValueError(f"partial installed RECORD digest: {name}")
            # Bytecode may be regenerated after install, even when a wheel's
            # RECORD happened to hash it. It is never repackaged below.
            continue
        if not encoded or not size:
            if encoded or size:
                raise ValueError(f"partial installed RECORD digest: {name}")
            if path.name == "RECORD":
                continue
            raise ValueError(f"unverified installed RECORD member: {name}")
        source = site.joinpath(*path.parts)
        target = source.resolve()
        if not target.is_relative_to(environment):
            raise ValueError(f"installed RECORD escapes environment: {name}")
        if not target.is_file() or source.is_symlink():
            raise ValueError(f"installed distribution member unavailable: {name}")
        raw = target.read_bytes()
        expected = "sha256=" + base64.urlsafe_b64encode(sha256(raw).digest()).decode().rstrip("=")
        if encoded != expected or size != str(len(raw)):
            raise ValueError(f"installed distribution member differs: {name}")


def _stage5_distribution_members(site: Path, info: Path) -> dict[str, bytes]:
    """Return payload bytes while excluding local installer provenance."""
    members = _distribution_members(site, info)
    return {
        name: raw
        for name, raw in members.items()
        if not (
            PurePosixPath(name).parent == PurePosixPath(info.name)
            and PurePosixPath(name).name in _INSTALLER_METADATA
        )
    }


def _build_stage5_dependency_wheel(
    site: Path, distribution: str, version: str, destination: Path, epoch: int
) -> dict[str, Any]:
    """Rebuild one Stage 5 wheel without installation-tool metadata."""
    info = _distribution(site, distribution, version)
    metadata = email.parser.Parser().parsestr((info / "METADATA").read_text(encoding="utf-8"))
    if metadata["Version"] != version:
        raise ValueError(f"distribution version mismatch: {distribution}")
    tags = [
        line.split(":", 1)[1].strip()
        for line in (info / "WHEEL").read_text(encoding="utf-8").splitlines()
        if line.startswith("Tag:")
    ]
    if not tags:
        raise ValueError(f"wheel tag unavailable: {distribution}")
    tag = tags[0]
    normalized = str(metadata["Name"]).lower().replace("-", "_")
    filename = f"{normalized}-{version}-{tag}.whl"
    members = _stage5_distribution_members(site, info)
    record_name = f"{info.name}/RECORD"
    record = [_record_line(name, raw) for name, raw in sorted(members.items())]
    record.append(f"{record_name},,")
    members[record_name] = ("\n".join(record) + "\n").encode()
    target = destination / filename
    _zip(target, members, epoch)
    if tag == "py3-none-any" and any(
        name.endswith((".so", ".dll", ".dylib")) for name in members
    ):
        raise ValueError(f"native member in pure wheel: {distribution}")
    if distribution == "rpds_py" and "cp311-cp311-manylinux" not in tag:
        raise ValueError("rpds-py wheel is not CPython 3.11 manylinux compatible")
    return {
        "distribution": str(metadata["Name"]),
        "version": version,
        "filename": filename,
        "tag": tag,
        "sha256": _digest(target.read_bytes()),
        "size_bytes": target.stat().st_size,
        "license_expression": metadata.get("License-Expression", "NOASSERTION"),
        "member_count": len(members),
    }


def _application_members(repository: Path) -> dict[str, bytes]:
    members = _runtime_members(repository)
    for path in sorted((repository / "src/ledgerguard_control").glob("*.py")):
        members[f"ledgerguard_control/{path.name}"] = path.read_bytes()
    if not members or any("ledgerguard_reference_oracle" in name for name in members):
        raise ValueError("production application allowlist differs")
    if any(name.endswith(("generator.py", "expectations.py")) for name in members):
        raise ValueError("production release contains an expectation generator")
    return members


def _project_wheel_members(repository: Path) -> dict[str, bytes]:
    members = _application_members(repository)
    dist = "ledgerguard_stage5_runtime-0.1.0.dist-info"
    members[f"{dist}/METADATA"] = (
        b"Metadata-Version: 2.4\n"
        b"Name: ledgerguard-stage5-runtime\n"
        b"Version: 0.1.0\n"
        b"Summary: LedgerGuard Stage 5 production runtime\n"
        b"Requires-Python: >=3.11,<3.12\n"
        b"Requires-Dist: jsonschema==4.26.0\n\n"
    )
    members[f"{dist}/WHEEL"] = (
        b"Wheel-Version: 1.0\n"
        b"Generator: ledgerguard-stage5-release/1.0\n"
        b"Root-Is-Purelib: true\n"
        b"Tag: py3-none-any\n"
    )
    record = f"{dist}/RECORD"
    members[record] = (
        "\n".join(
            [*[_record_line(name, raw) for name, raw in sorted(members.items())], f"{record},,"]
        )
        + "\n"
    ).encode()
    return members


def _lambda_member_allowed(name: str) -> bool:
    path = PurePosixPath(name)
    if "__pycache__" in path.parts or "tests" in path.parts or "testing" in path.parts:
        return False
    if len(path.parts) >= 2 and path.parts[:2] in {
        ("pyarrow", "include"),
        ("pyarrow", "src"),
    }:
        return False
    if name in {
        "pyarrow/_flight.cpython-311-x86_64-linux-gnu.so",
        "pyarrow/flight.py",
        "pyarrow/libarrow_flight.so.1700",
        "pyarrow/libarrow_python_flight.so",
    }:
        return False
    return path.suffix not in {".pyc", ".pyo", ".pyi", ".pyx", ".pxd", ".pxi"}


def _merge(target: dict[str, bytes], source: dict[str, bytes]) -> None:
    for name, raw in source.items():
        if not _lambda_member_allowed(name):
            continue
        if name in target and target[name] != raw:
            raise ValueError(f"release member collision: {name}")
        target[name] = raw


def _spdx(
    source_commit: str,
    runtime_sha256: str,
    components: list[dict[str, Any]],
) -> dict[str, Any]:
    packages = [
        {
            "SPDXID": "SPDXRef-Package-LedgerGuardStage5",
            "name": "ledgerguard-stage5-runtime",
            "versionInfo": "0.1.0",
            "downloadLocation": "NOASSERTION",
            "filesAnalyzed": False,
            "checksums": [{"algorithm": "SHA256", "checksumValue": runtime_sha256}],
            "licenseConcluded": "MIT",
            "licenseDeclared": "MIT",
        }
    ]
    relationships = [
        {
            "spdxElementId": "SPDXRef-DOCUMENT",
            "relationshipType": "DESCRIBES",
            "relatedSpdxElement": "SPDXRef-Package-LedgerGuardStage5",
        }
    ]
    for index, component in enumerate(components):
        identifier = f"SPDXRef-Package-Dependency-{index}"
        packages.append(
            {
                "SPDXID": identifier,
                "name": component["distribution"],
                "versionInfo": component["version"],
                "downloadLocation": "NOASSERTION",
                "filesAnalyzed": False,
                "checksums": [
                    {"algorithm": "SHA256", "checksumValue": component["sha256"]}
                ],
                "licenseConcluded": "NOASSERTION",
                "licenseDeclared": component["license_expression"],
            }
        )
        relationships.append(
            {
                "spdxElementId": "SPDXRef-Package-LedgerGuardStage5",
                "relationshipType": "DEPENDS_ON",
                "relatedSpdxElement": identifier,
            }
        )
    return {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": f"ledgerguard-stage5-{source_commit}",
        "documentNamespace": f"https://ledgerguard.local/spdx/stage5/{source_commit}",
        "creationInfo": {
            "created": "2026-09-13T00:00:00Z",
            "creators": ["Tool: ledgerguard-stage5-release/1.0"],
        },
        "packages": packages,
        "relationships": relationships,
    }


def build_release(
    repository: Path,
    environment: Path,
    output: Path,
    *,
    source_commit: str,
    source_tree: str,
    source_date_epoch: int,
    operation_id: str,
    execution_input: dict[str, Any],
) -> dict[str, Any]:
    """Build one deterministic release from verified installed dependencies."""
    if sys.version_info[:3] != (3, 11, 13):
        raise ValueError("release build requires exact CPython 3.11.13")
    if _OBJECT.fullmatch(source_commit) is None or _OBJECT.fullmatch(source_tree) is None:
        raise ValueError("release source identity differs")
    if output.exists() and any(output.iterdir()):
        raise ValueError("release output directory must be empty")
    output.mkdir(parents=True, exist_ok=True)
    site = _site_packages(environment)
    versions = {**DEPENDENCIES, **NATIVE_DEPENDENCIES}
    for name, version in versions.items():
        _verify_installed_distribution(site, name, version)

    project_members = _project_wheel_members(repository)
    wheelhouse = output / "wheelhouse"
    wheelhouse.mkdir()
    project_wheel = wheelhouse / PROJECT_WHEEL
    _zip(project_wheel, project_members, source_date_epoch)
    components = [
        {
            "distribution": "ledgerguard-stage5-runtime",
            "version": "0.1.0",
            "filename": PROJECT_WHEEL,
            "sha256": _digest(project_wheel.read_bytes()),
            "size_bytes": project_wheel.stat().st_size,
            "license_expression": "MIT",
        }
    ]
    components.extend(
        _build_stage5_dependency_wheel(site, name, version, wheelhouse, source_date_epoch)
        for name, version in DEPENDENCIES.items()
    )
    native_components = [
        {
            "distribution": name,
            "version": version,
            "filename": _distribution(site, name, version).name,
            "sha256": NATIVE_WHEEL_SHA256[name],
            "license_expression": "NOASSERTION",
        }
        for name, version in NATIVE_DEPENDENCIES.items()
    ]
    glue_members = {path.name: path.read_bytes() for path in sorted(wheelhouse.glob("*.whl"))}
    glue_path = output / "ledgerguard.gluewheels.zip"
    _zip(glue_path, glue_members, source_date_epoch)

    lambda_members = dict(project_members)
    for name, version in versions.items():
        info = _distribution(site, name, version)
        _merge(lambda_members, _stage5_distribution_members(site, info))
    if len(lambda_members) > MAX_MEMBERS:
        raise ValueError("Lambda release member count exceeds bound")
    runtime_path = output / "runtime.zip"
    _zip(runtime_path, lambda_members, source_date_epoch)
    runtime_size = runtime_path.stat().st_size
    uncompressed = sum(len(raw) for raw in lambda_members.values())
    if runtime_size > LAMBDA_ZIPPED_LIMIT or uncompressed > LAMBDA_UNZIPPED_LIMIT:
        raise ValueError("Lambda release exceeds a deployment-package limit")

    script_path = output / "ledgerguard_stage5_job.py"
    script_path.write_bytes((repository / "glue/ledgerguard_stage5_job.py").read_bytes())
    release = {
        "schema_version": "ledgerguard.release.v1",
        "runtime": {
            "source_commit": source_commit,
            "source_tree": source_tree,
            "runtime_package_sha256": _digest(runtime_path.read_bytes()),
            "script_sha256": _digest(script_path.read_bytes()),
            "wheels_sha256": _digest(glue_path.read_bytes()),
        },
    }
    release_raw = canonical_bytes(release) + b"\n"
    release_path = output / "release-manifest.json"
    release_path.write_bytes(release_raw)
    release_sha256 = _digest(release_raw)
    qualified = verify_release(
        release_raw,
        release_sha256,
        {
            "runtime.zip": runtime_path.read_bytes(),
            "ledgerguard_stage5_job.py": script_path.read_bytes(),
            "ledgerguard.gluewheels.zip": glue_path.read_bytes(),
        },
    )
    config = {
        "schema_version": "ledgerguard.handler-config.v1",
        "operation_id": operation_id,
        "execution_input": execution_input,
        "release_manifest_sha256": release_sha256,
        "runtime": qualified.runtime(),
    }
    config_raw = canonical_bytes(config)
    parse_config(config_raw, _digest(config_raw))
    definition = definition_bytes(operation_id)
    runtime_sha256_base64 = base64.b64encode(sha256(runtime_path.read_bytes()).digest()).decode()
    terraform_release = _json_bytes(
        {
            "schema_version": "ledgerguard.stage5-terraform-release.v1",
            "definition": definition.decode(),
            "definition_sha256": _digest(definition),
            "validator_zip": "runtime.zip",
            "validator_sha256_base64": runtime_sha256_base64,
            "controller_zip": "runtime.zip",
            "controller_sha256_base64": runtime_sha256_base64,
            "script_key": (
                f"deployment/{qualified.script_sha256}/ledgerguard_stage5_job.py"
            ),
            "wheels_key": (
                f"deployment/{qualified.wheels_sha256}/ledgerguard.gluewheels.zip"
            ),
            "manifest_sha256": release_sha256,
            "source_commit": source_commit,
            "source_tree": source_tree,
            "runtime_package_sha256": qualified.runtime_package_sha256,
            "script_sha256": qualified.script_sha256,
            "wheels_sha256": qualified.wheels_sha256,
            "handler_config": config_raw.decode(),
            "handler_config_sha256": _digest(config_raw),
        }
    )

    payloads = {
        "runtime.zip": runtime_path.read_bytes(),
        "ledgerguard.gluewheels.zip": glue_path.read_bytes(),
        "ledgerguard_stage5_job.py": script_path.read_bytes(),
        "release-manifest.json": release_raw,
        "handler-config.json": config_raw,
        "state-machine.json": definition,
        "terraform-stage5-release.json": terraform_release,
    }
    sbom_dependencies = [*components[1:], *native_components]
    sbom = _json_bytes(
        _spdx(source_commit, qualified.runtime_package_sha256, sbom_dependencies)
    )
    licenses = _json_bytes(
        {
            "schema_version": "1.0",
            "project": {"name": "ledgerguard-stage5-runtime", "license": "MIT"},
            "dependencies": [
                {
                    "name": row["distribution"],
                    "version": row["version"],
                    "license_expression": row["license_expression"],
                }
                for row in sbom_dependencies
            ],
        }
    )
    provenance = _json_bytes(
        {
            "schema_version": "ledgerguard.stage5-provenance.v1",
            "source_commit": source_commit,
            "source_tree": source_tree,
            "source_date_epoch": source_date_epoch,
            "python": "3.11.13",
            "lambda_architecture": "x86_64",
            "lambda_native_platform": "manylinux2014_x86_64",
            "glue": "5.1",
            "spark": "3.5.6",
            "runtime_boto3": "AWS_LAMBDA_PYTHON_3_11_PLATFORM_PROVIDED",
            "oracle_excluded": True,
            "generator_excluded": True,
            "aws_calls": 0,
        }
    )
    payloads.update(
        {"SBOM.spdx.json": sbom, "LICENSES.json": licenses, "PROVENANCE.json": provenance}
    )
    package_manifest = {
        "schema_version": "ledgerguard.stage5-package-manifest.v1",
        "source_commit": source_commit,
        "source_tree": source_tree,
        "release_manifest_sha256": release_sha256,
        "lambda": {
            "member_count": len(lambda_members),
            "zipped_bytes": runtime_size,
            "unzipped_bytes": uncompressed,
            "zipped_limit": LAMBDA_ZIPPED_LIMIT,
            "unzipped_limit": LAMBDA_UNZIPPED_LIMIT,
        },
        "glue_wheels": [
            {key: value for key, value in row.items() if key != "license_expression"}
            for row in components
        ],
        "lambda_native_wheels": native_components,
        "members": _inventory(payloads),
    }
    payloads["package-manifest.json"] = _json_bytes(package_manifest)
    for name, raw in payloads.items():
        (output / name).write_bytes(raw)
    bundle_path = output / "ledgerguard-stage5-release.zip"
    _zip(bundle_path, payloads, source_date_epoch)
    result = {
        "schema_version": "ledgerguard.stage5-build-result.v1",
        "source_commit": source_commit,
        "source_tree": source_tree,
        "release_manifest_sha256": release_sha256,
        "runtime_package_sha256": qualified.runtime_package_sha256,
        "script_sha256": qualified.script_sha256,
        "wheels_sha256": qualified.wheels_sha256,
        "handler_config_sha256": _digest(config_raw),
        "definition_sha256": _digest(definition),
        "sbom_sha256": _digest(sbom),
        "provenance_sha256": _digest(provenance),
        "bundle_sha256": _digest(bundle_path.read_bytes()),
        "bundle_size_bytes": bundle_path.stat().st_size,
        "aws_calls": 0,
    }
    (output / "build-result.json").write_bytes(_json_bytes(result))
    return result


def _safe_members(path: Path) -> dict[str, bytes]:
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        if not infos or len(infos) != len({item.filename for item in infos}):
            raise ValueError("release archive member inventory differs")
        rows: dict[str, bytes] = {}
        for item in infos:
            name = PurePosixPath(item.filename)
            if name.is_absolute() or ".." in name.parts or item.is_dir():
                raise ValueError("release archive contains an unsafe member")
            if (item.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError("release archive contains a symbolic link")
            rows[item.filename] = archive.read(item)
        return rows


def inspect_release(output: Path) -> dict[str, Any]:
    """Independently re-open every artifact and its complete digest inventory."""
    result = json.loads((output / "build-result.json").read_text(encoding="utf-8"))
    if set(result) != {
        "schema_version",
        "source_commit",
        "source_tree",
        "release_manifest_sha256",
        "runtime_package_sha256",
        "script_sha256",
        "wheels_sha256",
        "handler_config_sha256",
        "definition_sha256",
        "sbom_sha256",
        "provenance_sha256",
        "bundle_sha256",
        "bundle_size_bytes",
        "aws_calls",
    } or result.get("schema_version") != "ledgerguard.stage5-build-result.v1":
        raise ValueError("release build result shape differs")
    bundle = _safe_members(output / "ledgerguard-stage5-release.zip")
    manifest = json.loads(bundle["package-manifest.json"])
    if manifest.get("schema_version") != "ledgerguard.stage5-package-manifest.v1":
        raise ValueError("release package manifest shape differs")
    if set(bundle) != {row["path"] for row in manifest["members"]} | {"package-manifest.json"}:
        raise ValueError("release bundle inventory differs")
    for row in manifest["members"]:
        raw = bundle[row["path"]]
        if len(raw) != row["size_bytes"] or _digest(raw) != row["sha256"]:
            raise ValueError("release bundle member differs")
    for name, raw in bundle.items():
        if (output / name).read_bytes() != raw:
            raise ValueError("release output and bundle member differ")
    bundle_path = output / "ledgerguard-stage5-release.zip"
    if (
        bundle_path.stat().st_size != result["bundle_size_bytes"]
        or _digest(bundle_path.read_bytes()) != result["bundle_sha256"]
        or manifest.get("source_commit") != result["source_commit"]
        or manifest.get("source_tree") != result["source_tree"]
        or manifest.get("release_manifest_sha256") != result["release_manifest_sha256"]
    ):
        raise ValueError("release result identity differs")
    runtime = _safe_members(output / "runtime.zip")
    if len(runtime) != manifest["lambda"]["member_count"]:
        raise ValueError("Lambda member count differs")
    if sum(len(raw) for raw in runtime.values()) != manifest["lambda"]["unzipped_bytes"]:
        raise ValueError("Lambda expanded size differs")
    if (
        bundle["runtime.zip"] != (output / "runtime.zip").read_bytes()
        or len(bundle["runtime.zip"]) != manifest["lambda"]["zipped_bytes"]
        or len(bundle["runtime.zip"]) > LAMBDA_ZIPPED_LIMIT
        or manifest["lambda"]["unzipped_bytes"] > LAMBDA_UNZIPPED_LIMIT
        or manifest["lambda"]["zipped_limit"] != LAMBDA_ZIPPED_LIMIT
        or manifest["lambda"]["unzipped_limit"] != LAMBDA_UNZIPPED_LIMIT
    ):
        raise ValueError("Lambda release size identity differs")
    if any("tests" in PurePosixPath(name).parts for name in runtime):
        raise ValueError("Lambda release contains test source")
    if any(
        PurePosixPath(name).parent.name.endswith(".dist-info")
        and PurePosixPath(name).name
        in {"INSTALLER", "REQUESTED", "direct_url.json", "uv_cache.json"}
        for name in runtime
    ):
        raise ValueError("Lambda release contains installation-specific metadata")
    if any(
        "ledgerguard_reference_oracle" in name
        or name.endswith(("generator.py", "expectations.py"))
        or PurePosixPath(name).name
        in {
            "_flight.cpython-311-x86_64-linux-gnu.so",
            "flight.py",
            "libarrow_flight.so.1700",
            "libarrow_python_flight.so",
        }
        for name in runtime
    ):
        raise ValueError("Lambda release contains a forbidden member")
    for required in (
        "ledgerguard_control/controller.py",
        "ledgerguard_control/validator.py",
        "numpy/__init__.py",
        "pyarrow/__init__.py",
        "pyarrow/_parquet.cpython-311-x86_64-linux-gnu.so",
    ):
        if required not in runtime:
            raise ValueError("Lambda release is missing a runtime member")
    wheels = _safe_members(output / "ledgerguard.gluewheels.zip")
    expected_wheels = {row["filename"]: row["sha256"] for row in manifest["glue_wheels"]}
    if set(wheels) != set(expected_wheels):
        raise ValueError("Glue wheel inventory differs")
    if any(_digest(raw) != expected_wheels[name] for name, raw in wheels.items()):
        raise ValueError("Glue wheel digest differs")
    release_raw = bundle["release-manifest.json"]
    verified = verify_release(
        release_raw,
        result["release_manifest_sha256"],
        {
            "runtime.zip": bundle["runtime.zip"],
            "ledgerguard_stage5_job.py": bundle["ledgerguard_stage5_job.py"],
            "ledgerguard.gluewheels.zip": bundle["ledgerguard.gluewheels.zip"],
        },
    )
    config_raw = bundle["handler-config.json"]
    config = parse_config(config_raw, result["handler_config_sha256"])
    if (
        config.release != verified
        or verified.runtime_package_sha256 != result["runtime_package_sha256"]
        or verified.script_sha256 != result["script_sha256"]
        or verified.wheels_sha256 != result["wheels_sha256"]
    ):
        raise ValueError("handler release identity differs")
    if (
        _digest(bundle["state-machine.json"]) != result["definition_sha256"]
        or bundle["state-machine.json"] != definition_bytes(config.operation_id)
    ):
        raise ValueError("workflow definition digest differs")
    terraform = json.loads(bundle["terraform-stage5-release.json"])
    runtime_sha256_base64 = base64.b64encode(
        sha256(bundle["runtime.zip"]).digest()
    ).decode()
    if (
        terraform.get("schema_version") != "ledgerguard.stage5-terraform-release.v1"
        or terraform.get("definition") != bundle["state-machine.json"].decode()
        or terraform.get("handler_config") != config_raw.decode()
        or terraform.get("handler_config_sha256") != result["handler_config_sha256"]
        or terraform.get("manifest_sha256") != result["release_manifest_sha256"]
        or terraform.get("runtime_package_sha256") != result["runtime_package_sha256"]
        or terraform.get("script_sha256") != result["script_sha256"]
        or terraform.get("wheels_sha256") != result["wheels_sha256"]
        or terraform.get("source_commit") != result["source_commit"]
        or terraform.get("source_tree") != result["source_tree"]
        or terraform.get("definition_sha256") != result["definition_sha256"]
        or terraform.get("validator_zip") != "runtime.zip"
        or terraform.get("controller_zip") != "runtime.zip"
        or terraform.get("validator_sha256_base64") != runtime_sha256_base64
        or terraform.get("controller_sha256_base64") != runtime_sha256_base64
        or terraform.get("script_key")
        != f"deployment/{result['script_sha256']}/ledgerguard_stage5_job.py"
        or terraform.get("wheels_key")
        != f"deployment/{result['wheels_sha256']}/ledgerguard.gluewheels.zip"
    ):
        raise ValueError("Terraform release input differs")
    sbom = json.loads(bundle["SBOM.spdx.json"])
    if (
        sbom.get("spdxVersion") != "SPDX-2.3"
        or len(sbom.get("packages", []))
        != len(wheels) + len(manifest["lambda_native_wheels"])
    ):
        raise ValueError("release SBOM inventory differs")
    provenance = json.loads(bundle["PROVENANCE.json"])
    if (
        _digest(bundle["SBOM.spdx.json"]) != result["sbom_sha256"]
        or _digest(bundle["PROVENANCE.json"]) != result["provenance_sha256"]
        or provenance.get("source_commit") != result["source_commit"]
        or provenance.get("source_tree") != result["source_tree"]
        or provenance.get("aws_calls") != 0
        or provenance.get("oracle_excluded") is not True
        or provenance.get("generator_excluded") is not True
    ):
        raise ValueError("release provenance differs")
    if result.get("aws_calls") != 0:
        raise ValueError("release falsely reports an AWS call")
    return {
        "bundle_sha256": _digest((output / "ledgerguard-stage5-release.zip").read_bytes()),
        "runtime_sha256": _digest((output / "runtime.zip").read_bytes()),
        "runtime_members": len(runtime),
        "runtime_zipped_bytes": (output / "runtime.zip").stat().st_size,
        "runtime_unzipped_bytes": sum(len(raw) for raw in runtime.values()),
        "glue_wheel_count": len(wheels),
        "release_manifest_sha256": result["release_manifest_sha256"],
        "handler_config_sha256": result["handler_config_sha256"],
        "definition_sha256": result["definition_sha256"],
        "sbom_sha256": _digest(bundle["SBOM.spdx.json"]),
        "source_commit": result["source_commit"],
        "source_tree": result["source_tree"],
        "aws_calls": 0,
    }


def _parse_reference(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if type(value) is not dict:
        raise ValueError("execution input reference is not an object")
    return value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument("--environment", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--source-tree", required=True)
    parser.add_argument("--source-date-epoch", type=int, required=True)
    parser.add_argument("--operation-id", required=True)
    parser.add_argument("--execution-input-reference", type=Path, required=True)
    arguments = parser.parse_args()
    result = build_release(
        arguments.repository.resolve(),
        arguments.environment.resolve(),
        arguments.output.resolve(),
        source_commit=arguments.source_commit,
        source_tree=arguments.source_tree,
        source_date_epoch=arguments.source_date_epoch,
        operation_id=arguments.operation_id,
        execution_input=_parse_reference(arguments.execution_input_reference),
    )
    inspection = inspect_release(arguments.output.resolve())
    print(json.dumps({"build": result, "inspection": inspection}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
