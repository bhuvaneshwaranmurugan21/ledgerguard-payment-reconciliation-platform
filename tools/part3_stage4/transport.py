"""Materialize the accepted runtime into Glue's actual offline delivery format."""

from __future__ import annotations

import json
import zipfile
from hashlib import sha256
from pathlib import Path
from typing import Any

from tools.inspect_part3_stage3_artifact import inspect_runtime_bundle

ACCEPTED = {
    "source_commit": "3370898d83539fe41594c7cb7ad15e920dcb5674",
    "source_tree": "32e66b9d97cc63cd588eca14ecaf6602b9ff7f0a",
    "runtime_bundle_sha256": "12a263615abeeea33a6202ecc49d9fe27606fe1c2b37650f25ba9adebcb7b7f7",
    "runtime_wheel_sha256": "dbc78cb26fdceca4aac805826b572381c837505276ebf8297ef6304a17783476",
    "sbom_sha256": "09199428f39f781275c734e1036d20b3894fdf35451af64f58b2c2088fcbecd3",
}


def verify_identity(manifest: dict[str, Any]) -> None:
    for name in ("source_commit", "source_tree", "runtime_wheel_sha256", "sbom_sha256"):
        if manifest.get(name) != ACCEPTED[name]:
            raise ValueError("accepted runtime identity differs: " + name)


def verify_wheels(transport: Path, wheels: dict[str, bytes]) -> None:
    with zipfile.ZipFile(transport) as archive:
        if (
            len(archive.namelist()) != len(wheels)
            or {name: archive.read(name) for name in archive.namelist()} != wheels
        ):
            raise ValueError("wheel transport round-trip differs")


def materialize(bundle: Path, destination: Path) -> dict[str, Any]:
    """Copy only admitted bytes; never rebuild, download or upload dependencies."""
    if sha256(bundle.read_bytes()).hexdigest() != ACCEPTED["runtime_bundle_sha256"]:
        raise ValueError("unaccepted Stage 3 runtime bundle")
    inspection = inspect_runtime_bundle(bundle)
    with zipfile.ZipFile(bundle) as archive:
        members = {name: archive.read(name) for name in archive.namelist()}
    manifest = json.loads(members["package-manifest.json"])
    verify_identity(manifest)
    destination.mkdir(parents=True, exist_ok=False)
    wheels = {Path(name).name: raw for name, raw in members.items() if name.endswith(".whl")}
    transport = destination / "ledgerguard.gluewheels.zip"
    with zipfile.ZipFile(transport, "x", compression=zipfile.ZIP_DEFLATED) as output:
        for name, raw in sorted(wheels.items()):
            info = zipfile.ZipInfo(name, (2026, 9, 9, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            output.writestr(info, raw)
    verify_wheels(transport, wheels)
    script = destination / "ledgerguard_stage3_job.py"
    script.write_bytes(members["glue/ledgerguard_stage3_job.py"])
    for name in ("SBOM.spdx.json", "LICENSES.json", "PROVENANCE.json"):
        (destination / name).write_bytes(members[name])
    (destination / "runtime.lock").write_bytes(members["requirements/runtime.lock"])
    inventory = [
        {
            "path": path.name,
            "sha256": sha256(path.read_bytes()).hexdigest(),
            "size_bytes": path.stat().st_size,
        }
        for path in sorted(destination.iterdir())
    ]
    result = {
        "schema_version": "1.0",
        "accepted_runtime": ACCEPTED,
        "inspection": inspection,
        "objects": {
            "script_key": f"deployment/{sha256(script.read_bytes()).hexdigest()}/{script.name}",
            "wheels_key": (
                f"deployment/{sha256(transport.read_bytes()).hexdigest()}/{transport.name}"
            ),
        },
        "members": inventory,
        "wheels": [
            {"name": name, "sha256": sha256(raw).hexdigest()}
            for name, raw in sorted(wheels.items())
        ],
        "runtime_installation": "REQUIRES_OFFLINE_INSTALL_QUALIFICATION",
        "service_argument_adapter": "REQUIRED_STAGE5_SUCCESSOR_WITH_EXPLICIT_PROVENANCE",
        "aws_execution": False,
        "deployment_ready": False,
    }
    (destination / "transport-manifest.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n"
    )
    return result
