"""Strict Glue job arguments bound to immutable Stage 3 identities."""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass

from .errors import Stage3Rejected
from .paths import validate_job_paths

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9-]{7,63}$")
_REQUIRED = (
    "run-id",
    "attempt-id",
    "policy-sha256",
    "source-bundle-sha256",
    "manifest-sha256",
    "input-prefix",
    "candidate-output-prefix",
    "evidence-prefix",
    "control-record-identity",
    "source-commit",
    "source-tree",
    "runtime-package-sha256",
    "workload-bucket",
)
_GLUE = frozenset({"JOB_NAME", "JOB_RUN_ID", "TempDir"})


@dataclass(frozen=True)
class JobArguments:
    run_id: str
    attempt_id: str
    policy_sha256: str
    source_bundle_sha256: str
    manifest_sha256: str
    input_prefix: str
    candidate_output_prefix: str
    evidence_prefix: str
    control_record_identity: str
    source_commit: str
    source_tree: str
    runtime_package_sha256: str
    workload_bucket: str


def _pairs(argv: list[str]) -> dict[str, str]:
    if len(argv) % 2:
        raise Stage3Rejected("ARGUMENT_VIOLATION", "every flag requires one value")
    result: dict[str, str] = {}
    for index in range(0, len(argv), 2):
        flag, value = argv[index : index + 2]
        if not flag.startswith("--") or not value or value.startswith("--"):
            raise Stage3Rejected("ARGUMENT_VIOLATION", "malformed flag/value pair")
        name = flag[2:]
        if name in result:
            raise Stage3Rejected("ARGUMENT_VIOLATION", f"duplicate flag: {name}")
        if name not in _REQUIRED and name not in _GLUE:
            raise Stage3Rejected("ARGUMENT_VIOLATION", f"unknown flag: {name}")
        result[name] = value
    missing = sorted(set(_REQUIRED).difference(result))
    if missing:
        raise Stage3Rejected("ARGUMENT_VIOLATION", f"missing flags: {','.join(missing)}")
    return result


def parse_job_arguments(argv: list[str]) -> JobArguments:
    values = _pairs(argv)
    for name in ("run-id", "attempt-id", "control-record-identity"):
        if not _IDENTIFIER.fullmatch(values[name]):
            raise Stage3Rejected("ARGUMENT_VIOLATION", f"invalid {name}")
    for name in (
        "policy-sha256",
        "source-bundle-sha256",
        "manifest-sha256",
        "runtime-package-sha256",
    ):
        if not _HEX64.fullmatch(values[name]):
            raise Stage3Rejected("ARGUMENT_VIOLATION", f"invalid {name}")
    if not _HEX40.fullmatch(values["source-commit"]):
        raise Stage3Rejected("ARGUMENT_VIOLATION", "invalid source-commit")
    if not _HEX40.fullmatch(values["source-tree"]):
        raise Stage3Rejected("ARGUMENT_VIOLATION", "invalid source-tree")
    arguments = JobArguments(
        run_id=values["run-id"],
        attempt_id=values["attempt-id"],
        policy_sha256=values["policy-sha256"],
        source_bundle_sha256=values["source-bundle-sha256"],
        manifest_sha256=values["manifest-sha256"],
        input_prefix=values["input-prefix"],
        candidate_output_prefix=values["candidate-output-prefix"],
        evidence_prefix=values["evidence-prefix"],
        control_record_identity=values["control-record-identity"],
        source_commit=values["source-commit"],
        source_tree=values["source-tree"],
        runtime_package_sha256=values["runtime-package-sha256"],
        workload_bucket=values["workload-bucket"],
    )
    validate_job_paths(
        arguments.workload_bucket,
        arguments.run_id,
        arguments.attempt_id,
        arguments.input_prefix,
        arguments.candidate_output_prefix,
        arguments.evidence_prefix,
    )
    return arguments


def parser_contract() -> argparse.ArgumentParser:
    """Expose help text without using argparse for security-critical parsing."""
    parser = argparse.ArgumentParser(add_help=True)
    for name in _REQUIRED:
        parser.add_argument(f"--{name}", required=True)
    return parser
