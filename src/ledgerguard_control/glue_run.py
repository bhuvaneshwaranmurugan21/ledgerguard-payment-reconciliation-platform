"""Bounded Glue start, terminal observation, and ambiguous-start recovery.

The functions in this module issue only Glue control-plane reads.  They never run
the reconciliation workload.  A successful receipt is useful only when the
candidate manifest carries the same Glue job-run identity.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any, Protocol

from ledgerguard.stage3.arguments import JobArguments
from ledgerguard.stage3.canonical import canonical_bytes

from .contracts import ControlRejected

_JOB = re.compile(r"ledgerguard-p3-[a-z0-9][a-z0-9-]{7,31}-reconciliation")
_JOB_RUN = re.compile(r"jr_[0-9a-f]{64}")
_MAX_PAGES = 16
_MAX_RUNS = 1600


class GlueReads(Protocol):
    def get_job_run(self, **request: Any) -> Mapping[str, Any]:
        raise NotImplementedError

    def get_job_runs(self, **request: Any) -> Mapping[str, Any]:
        raise NotImplementedError


@dataclass(frozen=True)
class GlueTerminalReceipt:
    job_name: str
    job_run_id: str
    arguments_sha256: str
    started_at: str
    completed_at: str
    execution_seconds: int
    dpu_seconds: str
    observation_sha256: str


def _job_name(value: Any) -> str:
    if type(value) is not str or _JOB.fullmatch(value) is None:
        raise ControlRejected("invalid Glue job name")
    return value


def _job_run_id(value: Any) -> str:
    if type(value) is not str or _JOB_RUN.fullmatch(value) is None:
        raise ControlRejected("invalid Glue job run identity")
    return value


def start_arguments(arguments: JobArguments) -> dict[str, str]:
    """Render only immutable per-run overrides; job defaults stay in Terraform."""
    values = asdict(arguments)
    rendered = {f"--{name.replace('_', '-')}": value for name, value in values.items()}
    if any(type(value) is not str or not value for value in rendered.values()):
        raise ControlRejected("invalid Glue start argument")
    return dict(sorted(rendered.items()))


def start_request(job_name: str, arguments: JobArguments) -> dict[str, Any]:
    _job_name(job_name)
    return {
        "JobName": job_name,
        "Arguments": start_arguments(arguments),
        "ExecutionClass": "STANDARD",
        "JobRunQueuingEnabled": False,
    }


def _utc(value: Any, name: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None:
        raise ControlRejected(f"Glue {name} timestamp is not timezone-aware")
    if value.utcoffset() is None:
        raise ControlRejected(f"Glue {name} timestamp has no UTC offset")
    result = value.astimezone(UTC)
    return result


def _arguments(value: Any) -> dict[str, str]:
    if type(value) is not dict or any(
        type(key) is not str or type(item) is not str for key, item in value.items()
    ):
        raise ControlRejected("invalid Glue observed arguments")
    return dict(sorted(value.items()))


def _number(value: Any, name: str, maximum: float) -> float:
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= maximum:
        raise ControlRejected(f"invalid Glue {name}")
    return float(value)


def _run(document: Any) -> dict[str, Any]:
    if type(document) is not dict:
        raise ControlRejected("Glue response has no job run")
    return document


def observe_terminal(
    client: GlueReads,
    request: Mapping[str, Any],
    job_run_id: str,
) -> GlueTerminalReceipt:
    """Read and verify one exact terminal run.  No retry can create another run."""
    if type(request) is not dict:
        raise ControlRejected("invalid retained Glue start request")
    job_name = _job_name(request.get("JobName"))
    job_run_id = _job_run_id(job_run_id)
    expected_arguments = _arguments(request.get("Arguments"))
    response = client.get_job_run(
        JobName=job_name,
        RunId=job_run_id,
        PredecessorsIncluded=False,
    )
    if type(response) is not dict:
        raise ControlRejected("invalid Glue get-job-run response")
    run = _run(response.get("JobRun"))
    if run.get("Id") != job_run_id or run.get("JobName") != job_name:
        raise ControlRejected("Glue terminal identity differs")
    if run.get("JobRunState") != "SUCCEEDED" or run.get("ErrorMessage") not in (None, ""):
        raise ControlRejected("Glue run is not successful")
    if run.get("Attempt") != 0 or run.get("PreviousRunId") not in (None, ""):
        raise ControlRejected("Glue run is a retry or predecessor continuation")
    if _arguments(run.get("Arguments")) != expected_arguments:
        raise ControlRejected("Glue run arguments differ from retained start")
    exact = {
        "GlueVersion": "5.1",
        "WorkerType": "G.1X",
        "NumberOfWorkers": 2,
        "Timeout": 15,
        "ExecutionClass": "STANDARD",
        "JobRunQueuingEnabled": False,
    }
    for name, expected in exact.items():
        if run.get(name) != expected:
            raise ControlRejected(f"Glue effective configuration differs: {name}")
    started = _utc(run.get("StartedOn"), "start")
    completed = _utc(run.get("CompletedOn"), "completion")
    if completed < started or (completed - started).total_seconds() > 960:
        raise ControlRejected("Glue observed wall time exceeds bound")
    execution = run.get("ExecutionTime")
    if type(execution) is not int or not 0 <= execution <= 900:
        raise ControlRejected("invalid Glue execution time")
    dpu = _number(run.get("DPUSeconds"), "DPU seconds", 1800)
    started_text = started.isoformat().replace("+00:00", "Z")
    completed_text = completed.isoformat().replace("+00:00", "Z")
    dpu_text = format(dpu, ".6f").rstrip("0").rstrip(".")
    observation = {
        "job_name": job_name,
        "job_run_id": job_run_id,
        "arguments": expected_arguments,
        "state": "SUCCEEDED",
        "started_at": started_text,
        "completed_at": completed_text,
        "execution_seconds": execution,
        "dpu_seconds": dpu_text,
        **exact,
    }
    return GlueTerminalReceipt(
        job_name,
        job_run_id,
        sha256(canonical_bytes(expected_arguments)).hexdigest(),
        started_text,
        completed_text,
        execution,
        dpu_text,
        sha256(canonical_bytes(observation)).hexdigest(),
    )


def recover_ambiguous_start(
    client: GlueReads,
    request: Mapping[str, Any],
    started_after: datetime,
    started_before: datetime,
) -> str:
    """Discover one already-created run; never infer that a second start is safe."""
    if type(request) is not dict:
        raise ControlRejected("invalid retained Glue start request")
    job_name = _job_name(request.get("JobName"))
    expected_arguments = _arguments(request.get("Arguments"))
    lower = _utc(started_after, "recovery lower")
    upper = _utc(started_before, "recovery upper")
    if upper < lower or (upper - lower).total_seconds() > 300:
        raise ControlRejected("ambiguous-start recovery window exceeds bound")
    token: str | None = None
    seen_tokens: set[str] = set()
    matches: list[str] = []
    count = 0
    for _page in range(_MAX_PAGES):
        query: dict[str, Any] = {"JobName": job_name, "MaxResults": 100}
        if token is not None:
            query["NextToken"] = token
        response = client.get_job_runs(**query)
        if type(response) is not dict or type(response.get("JobRuns")) is not list:
            raise ControlRejected("invalid Glue get-job-runs page")
        for raw in response["JobRuns"]:
            count += 1
            if count > _MAX_RUNS:
                raise ControlRejected("Glue recovery inventory exceeds bound")
            run = _run(raw)
            started = _utc(run.get("StartedOn"), "listed start")
            if (
                run.get("JobName") == job_name
                and run.get("Attempt") == 0
                and run.get("PreviousRunId") in (None, "")
                and lower <= started <= upper
                and _arguments(run.get("Arguments")) == expected_arguments
            ):
                matches.append(_job_run_id(run.get("Id")))
        next_token = response.get("NextToken")
        if next_token is None:
            break
        if type(next_token) is not str or not next_token or next_token in seen_tokens:
            raise ControlRejected("invalid Glue recovery pagination token")
        seen_tokens.add(next_token)
        token = next_token
    else:
        raise ControlRejected("Glue recovery pagination exceeds bound")
    if len(matches) != 1:
        raise ControlRejected("ambiguous Glue start has no unique owned run")
    return matches[0]


def bind_candidate_job_run(manifest: Mapping[str, Any], receipt: GlueTerminalReceipt) -> None:
    if type(manifest) is not dict or manifest.get("glue_job_run_id") != receipt.job_run_id:
        raise ControlRejected("candidate does not bind terminal Glue run")
