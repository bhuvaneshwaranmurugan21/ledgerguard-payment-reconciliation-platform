"""Strict Glue 5.1 entrypoint for the Stage 5 qualified successor release."""

from __future__ import annotations

import re
import sys

from ledgerguard.stage3.errors import Stage3Rejected

from .glue_arguments import (
    GlueServiceContract,
    adapt_glue_arguments,
    admitted_from_glue_arguments,
    release_from_glue_arguments,
)
from .successor_writer import materialize_candidates_uri

_BUCKET = re.compile(r"ledgerguard-p3-857229544428-([a-z0-9][a-z0-9-]{7,31})")


def _service_contract(argv: list[str]) -> GlueServiceContract:
    admitted = admitted_from_glue_arguments(argv)
    match = _BUCKET.fullmatch(admitted.workload_bucket)
    if match is None:
        raise Stage3Rejected("ARGUMENT_VIOLATION", "workload bucket is not deployment-bound")
    operation = match.group(1)
    release = release_from_glue_arguments(argv)
    return GlueServiceContract(
        f"ledgerguard-p3-{operation}-reconciliation",
        admitted.workload_bucket,
        f"/ledgerguard-p3-{operation}/glue",
        release,
    )


def main(argv: list[str] | None = None) -> int:
    from ledgerguard.stage3.job import _managed_inputs, _spark
    from ledgerguard.stage3.spark_pipeline import reconcile_sources

    raw = list(sys.argv[1:] if argv is None else argv)
    contract = _service_contract(raw)
    admitted = admitted_from_glue_arguments(raw)
    arguments, job_run_id = adapt_glue_arguments(raw, contract, admitted)
    spark = _spark()
    try:
        inputs = _managed_inputs(spark, arguments)
        candidates = reconcile_sources(spark, inputs)
        materialize_candidates_uri(
            candidates,
            arguments.candidate_output_prefix,
            arguments.run_id,
            arguments.attempt_id,
            arguments.control_record_identity,
            job_run_id,
        )
    finally:
        spark.stop()
    return 0
