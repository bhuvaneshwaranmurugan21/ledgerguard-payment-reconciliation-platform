"""Enumerated Glue service adapter; frozen business parser remains authoritative."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from ledgerguard.stage3.arguments import JobArguments, parse_job_arguments

from .admission import Release
from .contracts import ControlRejected

_JOB_RUN = re.compile(r"jr_[0-9a-f]{64}")


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
        }


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
    business = {key.replace("_", "-") for key in asdict(admitted)}
    allowed = business | set(configured) | {"JOB_RUN_ID"}
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
            # AWS documents this as presence-based. Map-style empty values and
            # the standalone argv flag are equivalent; true/false are not accepted.
            value = ""
            if offset < len(argv) and argv[offset] == "":
                offset += 1
        else:
            if offset == len(argv) or not argv[offset]:
                raise ControlRejected("each valued Glue argument requires one value")
            value = argv[offset]
            offset += 1
        values[name] = value
    if set(values) != allowed:
        raise ControlRejected("missing Glue arguments")
    for name, expected in configured.items():
        if values[name] != expected:
            raise ControlRejected(f"Glue configuration mismatch: {name}")
    if _JOB_RUN.fullmatch(values["JOB_RUN_ID"]) is None:
        raise ControlRejected("invalid Glue job run identity")
    parsed = parse_job_arguments(
        [item for name in sorted(business) for item in (f"--{name}", values[name])]
    )
    if parsed != admitted:
        raise ControlRejected("Glue arguments differ from admitted execution")
    if (
        parsed.workload_bucket != contract.workload_bucket
        or parsed.source_tree != contract.release.source_tree
        or parsed.runtime_package_sha256 != contract.release.runtime_package_sha256
    ):
        raise ControlRejected("Glue runtime provenance mismatch")
    return parsed, values["JOB_RUN_ID"]
