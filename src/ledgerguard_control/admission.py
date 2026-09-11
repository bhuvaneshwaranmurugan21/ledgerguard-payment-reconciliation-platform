"""Bind an execution to independently qualified release and input identities.

The trusted release digest and input arguments come from the deployment/control
authority, never from the untrusted execution request. This module performs no I/O.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
from typing import Any

from ledgerguard.stage3.arguments import JobArguments
from ledgerguard.stage3.paths import parse_s3_uri

from .contracts import RUNTIME, ControlRejected, closed, job_arguments, strict_json, validate


@dataclass(frozen=True)
class Release:
    manifest_sha256: str
    source_commit: str
    source_tree: str
    runtime_package_sha256: str
    script_sha256: str
    wheels_sha256: str

    def runtime(self) -> dict[str, str]:
        return {key: value for key, value in asdict(self).items() if key != "manifest_sha256"}


def verify_release(raw: bytes, trusted_sha256: str, artifacts: dict[str, bytes]) -> Release:
    """Verify actual release bytes; hash-shape checks alone never admit a release.

    The independently reviewed manifest lives outside its runtime archive, avoiding
    any self-referential package hash. Exact artifact names reject silent extras.
    """
    from jsonschema import Draft202012Validator

    if sha256(raw).hexdigest() != trusted_sha256:
        raise ControlRejected("release manifest digest mismatch")
    value = strict_json(raw)
    schema = closed(
        {
            "schema_version": {"const": "ledgerguard.release.v1"},
            "runtime": RUNTIME,
        }
    )
    if not Draft202012Validator(schema).is_valid(value):
        raise ControlRejected("invalid release manifest")
    fields = {
        "runtime.zip": "runtime_package_sha256",
        "ledgerguard_stage3_job.py": "script_sha256",
        "ledgerguard.gluewheels.zip": "wheels_sha256",
    }
    if set(artifacts) != set(fields):
        raise ControlRejected("release artifact inventory mismatch")
    for name, field in fields.items():
        if sha256(artifacts[name]).hexdigest() != value["runtime"][field]:
            raise ControlRejected(f"release artifact digest mismatch: {name}")
    return Release(manifest_sha256=trusted_sha256, **value["runtime"])


def admit_execution(
    raw: bytes,
    release: Release,
    registered_input: JobArguments,
    trusted_expected: dict[str, Any],
    trusted_inventory: dict[str, Any],
) -> dict[str, Any]:
    value = validate("execution-input", strict_json(raw))
    arguments = job_arguments(value["job"])
    if arguments != registered_input:
        raise ControlRejected("job identity differs from independently admitted input")
    if value["release_manifest_sha256"] != release.manifest_sha256:
        raise ControlRejected("unqualified release manifest")
    if value["runtime"] != release.runtime():
        raise ControlRejected("runtime differs from qualified release")
    if (
        arguments.source_tree != release.source_tree
        or arguments.runtime_package_sha256 != release.runtime_package_sha256
    ):
        raise ControlRejected("job runtime arguments differ from qualified release")
    # source_commit is the accepted input manifest's provenance; runtime.source_commit
    # is the release provenance. They intentionally need not be the same commit.
    bindings = (("expected_results", trusted_expected), ("input_inventory", trusted_inventory))
    for key, expected in bindings:
        if value[key] != expected:
            raise ControlRejected(f"untrusted {key} reference")
        location = parse_s3_uri(value[key]["uri"])
        parent = parse_s3_uri(arguments.input_prefix)
        if location.bucket != parent.bucket or location.segments[:-1] != parent.segments:
            raise ControlRejected(f"{key} must be a direct member of this run's inputs")
        if value[key]["version_id"] == "null":
            raise ControlRejected("versioned input required")
    if value["expected_results"]["uri"] == value["input_inventory"]["uri"]:
        raise ControlRejected("expected results and inventory must be distinct")
    return value
