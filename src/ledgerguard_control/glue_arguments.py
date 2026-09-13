"""Enumerated Glue service adapter; frozen business parser remains authoritative."""

from __future__ import annotations

import re
from dataclasses import dataclass

from ledgerguard.stage3.arguments import JobArguments, parse_job_arguments

from .admission import Release
from .contracts import ControlRejected

_JOB_RUN = re.compile(r"jr_[0-9a-f]{64}")
_SHA1 = re.compile(r"[0-9a-f]{40}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_CONFIGURED_NAMES = frozenset(
    {
        "additional-python-modules",
        "python-modules-installer-option",
        "enable-observability-metrics",
        "enable-metrics",
        "enable-s3-parquet-optimized-committer",
        "custom-logGroup-prefix",
        "job-bookmark-option",
        "TempDir",
        "JOB_NAME",
        "runtime-source-commit",
        "runtime-source-tree",
        "runtime-package-sha256",
        "runtime-script-sha256",
        "runtime-wheels-sha256",
        "release-manifest-sha256",
    }
)


@dataclass(frozen=True)
class GlueServiceContract:
    job_name: str
    workload_bucket: str
    log_group_prefix: str
    release: Release

    def configured(self) -> dict[str, str]:
        return {
            "additional-python-modules": (
                f"s3://{self.workload_bucket}/deployment/"
                f"{self.release.wheels_sha256}/ledgerguard.gluewheels.zip"
            ),
            "python-modules-installer-option": "--no-index",
            "enable-observability-metrics": "true",
            "enable-metrics": "",
            "enable-s3-parquet-optimized-committer": "true",
            "custom-logGroup-prefix": self.log_group_prefix,
            "job-bookmark-option": "job-bookmark-disable",
            "TempDir": f"s3://{self.workload_bucket}/temporary/glue/",
            "JOB_NAME": self.job_name,
            "runtime-source-commit": self.release.source_commit,
            "runtime-source-tree": self.release.source_tree,
            "runtime-package-sha256": self.release.runtime_package_sha256,
            "runtime-script-sha256": self.release.script_sha256,
            "runtime-wheels-sha256": self.release.wheels_sha256,
            "release-manifest-sha256": self.release.manifest_sha256,
        }


def _business_names() -> set[str]:
    return {key.replace("_", "-") for key in JobArguments.__dataclass_fields__}


def _values(argv: list[str]) -> dict[str, str]:
    business = _business_names()
    allowed = business | _CONFIGURED_NAMES | {"JOB_RUN_ID"}
    values: dict[str, str] = {}
    offset = 0
    while offset < len(argv):
        flag = argv[offset]
        offset += 1
        if not flag.startswith("--"):
            raise ControlRejected("malformed Glue argument")
        name = flag[2:]
        if name not in allowed or name in values:
            raise ControlRejected("unknown or duplicate Glue argument")
        if name == "enable-metrics":
            value = ""
            if offset < len(argv) and argv[offset] == "":
                offset += 1
        else:
            if offset == len(argv) or not argv[offset]:
                raise ControlRejected("each valued Glue argument requires one value")
            value = argv[offset]
            offset += 1
        values[name] = value
    return values


def release_from_glue_arguments(argv: list[str]) -> Release:
    """Read release values that Terraform makes non-overridable for the job."""
    values = _values(argv)
    fields = (
        ("release-manifest-sha256", _SHA256),
        ("runtime-source-commit", _SHA1),
        ("runtime-source-tree", _SHA1),
        ("runtime-package-sha256", _SHA256),
        ("runtime-script-sha256", _SHA256),
        ("runtime-wheels-sha256", _SHA256),
    )
    release: list[str] = []
    for name, pattern in fields:
        value = values.get(name)
        if type(value) is not str or pattern.fullmatch(value) is None:
            raise ControlRejected(f"invalid Glue release identity: {name}")
        release.append(value)
    return Release(*release)


def admitted_from_glue_arguments(argv: list[str]) -> JobArguments:
    values = _values(argv)
    business = _business_names()
    if not business.issubset(values):
        raise ControlRejected("missing Glue business arguments")
    return parse_job_arguments(
        [item for name in sorted(business) for item in (f"--{name}", values[name])]
    )


def adapt_glue_arguments(
    argv: list[str],
    contract: GlueServiceContract,
    admitted: JobArguments,
) -> tuple[JobArguments, str]:
    """Validate before Spark creation; return original business arguments plus job ID.

    Only the installer flag can have a flag-shaped value, and only the exact
    qualified value is accepted. No catch-all or ignored argument path exists.
    """
    configured = contract.configured()
    business = _business_names()
    allowed = business | set(configured) | {"JOB_RUN_ID"}
    values = _values(argv)
    if set(values) != allowed:
        raise ControlRejected("missing Glue arguments")
    for name, expected in configured.items():
        if values[name] != expected:
            raise ControlRejected(f"Glue configuration mismatch: {name}")
    if _JOB_RUN.fullmatch(values["JOB_RUN_ID"]) is None:
        raise ControlRejected("invalid Glue job run identity")
    parsed = admitted_from_glue_arguments(argv)
    if parsed != admitted:
        raise ControlRejected("Glue arguments differ from admitted execution")
    if (
        parsed.workload_bucket != contract.workload_bucket
        or parsed.source_tree != contract.release.source_tree
        or parsed.runtime_package_sha256 != contract.release.runtime_package_sha256
    ):
        raise ControlRejected("Glue runtime provenance mismatch")
    return parsed, values["JOB_RUN_ID"]
