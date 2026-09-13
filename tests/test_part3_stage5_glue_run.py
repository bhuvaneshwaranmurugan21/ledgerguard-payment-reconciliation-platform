from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta, tzinfo
from types import MappingProxyType
from typing import Any, cast

import pytest
from test_part3_stage5_admission import fixture

from ledgerguard_control.contracts import ControlRejected, job_arguments
from ledgerguard_control.glue_run import (
    GlueReads,
    bind_candidate_job_run,
    observe_terminal,
    recover_ambiguous_start,
    start_request,
)

JOB = "ledgerguard-p3-operation-01-reconciliation"
RUN = "jr_" + "a" * 64
STARTED = datetime(2026, 9, 11, 8, 0, tzinfo=UTC)


def request() -> dict[str, Any]:
    value, _, _, _ = fixture()
    return start_request(JOB, job_arguments(value["job"]))


def run_document(run_id: str = RUN) -> dict[str, Any]:
    return {
        "Id": run_id,
        "JobName": JOB,
        "JobRunState": "SUCCEEDED",
        "Attempt": 0,
        "Arguments": request()["Arguments"],
        "StartedOn": STARTED,
        "CompletedOn": STARTED + timedelta(seconds=61),
        "ExecutionTime": 60,
        "DPUSeconds": 120.5,
        "GlueVersion": "5.1",
        "WorkerType": "G.1X",
        "NumberOfWorkers": 2,
        "Timeout": 15,
        "ExecutionClass": "STANDARD",
        "JobRunQueuingEnabled": False,
    }


class Reads:
    def __init__(self, pages: list[dict[str, Any]] | None = None):
        self.run = run_document()
        self.pages = list(pages or [])
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def get_job_run(self, **query: Any) -> dict[str, Any]:
        self.calls.append(("get_job_run", query))
        return {"JobRun": self.run}

    def get_job_runs(self, **query: Any) -> dict[str, Any]:
        self.calls.append(("get_job_runs", query))
        return self.pages.pop(0)


def test_terminal_receipt_binds_exact_read_and_start_arguments() -> None:
    client = Reads()
    receipt = observe_terminal(client, request(), RUN)
    assert receipt.job_run_id == RUN
    assert receipt.execution_seconds == 60
    assert receipt.dpu_seconds == "120.5"
    assert len(receipt.arguments_sha256) == len(receipt.observation_sha256) == 64
    assert client.calls == [
        (
            "get_job_run",
            {"JobName": JOB, "RunId": RUN, "PredecessorsIncluded": False},
        )
    ]
    bind_candidate_job_run({"glue_job_run_id": RUN}, receipt)
    with pytest.raises(ControlRejected, match="does not bind"):
        bind_candidate_job_run({"glue_job_run_id": "jr_" + "b" * 64}, receipt)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("Id", "jr_" + "b" * 64),
        ("JobName", "ledgerguard-p3-operation-02-reconciliation"),
        ("JobRunState", "FAILED"),
        ("ErrorMessage", "failed"),
        ("Attempt", 1),
        ("PreviousRunId", "jr_" + "b" * 64),
        ("Arguments", {"--run-id": "run-other"}),
        ("GlueVersion", "5.0"),
        ("WorkerType", "G.2X"),
        ("NumberOfWorkers", 3),
        ("Timeout", 16),
        ("ExecutionClass", "FLEX"),
        ("JobRunQueuingEnabled", True),
        ("ExecutionTime", 901),
        ("DPUSeconds", 1800.1),
    ],
)
def test_terminal_mismatch_matrix(field: str, value: Any) -> None:
    client = Reads()
    client.run[field] = value
    with pytest.raises(ControlRejected):
        observe_terminal(client, request(), RUN)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("StartedOn", "2026-09-11T08:00:00Z"),
        ("StartedOn", datetime(2026, 9, 11, 8, 0)),
        ("CompletedOn", STARTED - timedelta(seconds=1)),
        ("CompletedOn", STARTED + timedelta(seconds=961)),
    ],
)
def test_terminal_timestamp_bounds(field: str, value: Any) -> None:
    client = Reads()
    client.run[field] = value
    with pytest.raises(ControlRejected):
        observe_terminal(client, request(), RUN)


def test_start_request_is_fixed_and_rejects_wrong_job() -> None:
    value = request()
    assert value["ExecutionClass"] == "STANDARD"
    assert value["JobRunQueuingEnabled"] is False
    assert "--attempt-id" in value["Arguments"]
    assert "--JOB_RUN_ID" not in value["Arguments"]
    with pytest.raises(ControlRejected, match="job name"):
        start_request("other", job_arguments(fixture()[0]["job"]))
    with pytest.raises(ControlRejected, match="job name"):
        start_request(cast(Any, None), job_arguments(fixture()[0]["job"]))
    invalid = replace(job_arguments(fixture()[0]["job"]), run_id="")
    with pytest.raises(ControlRejected, match="start argument"):
        start_request(JOB, invalid)


def test_glue_read_protocol_defaults_do_not_fabricate_responses() -> None:
    client = cast(GlueReads, object())
    with pytest.raises(NotImplementedError):
        GlueReads.get_job_run(client)
    with pytest.raises(NotImplementedError):
        GlueReads.get_job_runs(client)


class NoOffset(tzinfo):
    def utcoffset(self, dt: datetime | None) -> None:
        return None

    def dst(self, dt: datetime | None) -> None:
        return None


@pytest.mark.parametrize(
    ("request_value", "run_id"),
    [
        (MappingProxyType(request()), RUN),
        (request(), "invalid"),
        ({**request(), "JobName": None}, RUN),
        ({**request(), "Arguments": []}, RUN),
        ({**request(), "Arguments": {1: "value"}}, RUN),
    ],
)
def test_terminal_request_and_identity_rejections(request_value: Any, run_id: str) -> None:
    with pytest.raises(ControlRejected):
        observe_terminal(Reads(), request_value, run_id)


@pytest.mark.parametrize("response", [None, {}, {"JobRun": []}])
def test_terminal_response_shape_rejections(response: Any) -> None:
    class Broken(Reads):
        def get_job_run(self, **query: Any) -> Any:
            return response

    with pytest.raises(ControlRejected):
        observe_terminal(Broken(), request(), RUN)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("Arguments", {"--run-id": 1}),
        ("ExecutionTime", True),
        ("ExecutionTime", -1),
        ("DPUSeconds", True),
        ("DPUSeconds", -1),
        ("DPUSeconds", float("nan")),
    ],
)
def test_terminal_rejects_inexact_or_nonfinite_values(field: str, value: Any) -> None:
    client = Reads()
    client.run[field] = value
    with pytest.raises(ControlRejected):
        observe_terminal(client, request(), RUN)


def test_terminal_rejects_timezone_with_no_offset() -> None:
    client = Reads()
    client.run["StartedOn"] = datetime(2026, 9, 11, 8, 0, tzinfo=NoOffset())
    with pytest.raises(ControlRejected, match="no UTC offset"):
        observe_terminal(client, request(), RUN)


def test_ambiguous_start_recovery_reads_every_page_and_selects_one_exact_run() -> None:
    other = run_document("jr_" + "b" * 64)
    other["Arguments"] = {**other["Arguments"], "--attempt-id": "attempt-other"}
    exact = run_document()
    client = Reads(
        [
            {"JobRuns": [other], "NextToken": "page-2"},
            {"JobRuns": [exact]},
        ]
    )
    assert recover_ambiguous_start(
        client, request(), STARTED - timedelta(seconds=1), STARTED + timedelta(seconds=1)
    ) == RUN
    assert client.calls == [
        ("get_job_runs", {"JobName": JOB, "MaxResults": 100}),
        (
            "get_job_runs",
            {"JobName": JOB, "MaxResults": 100, "NextToken": "page-2"},
        ),
    ]


@pytest.mark.parametrize("fault", ["missing", "duplicate", "token", "window", "arguments"])
def test_ambiguous_start_recovery_fails_closed(fault: str) -> None:
    exact = run_document()
    pages: list[dict[str, Any]] = [{"JobRuns": [exact]}]
    lower = STARTED - timedelta(seconds=1)
    upper = STARTED + timedelta(seconds=1)
    if fault == "missing":
        pages = [{"JobRuns": []}]
    elif fault == "duplicate":
        pages = [{"JobRuns": [exact, deepcopy(exact)]}]
    elif fault == "token":
        pages = [
            {"JobRuns": [], "NextToken": "repeat"},
            {"JobRuns": [], "NextToken": "repeat"},
        ]
    elif fault == "window":
        upper = lower + timedelta(seconds=301)
    else:
        exact["Arguments"] = {"--attempt-id": "attempt-other"}
    client = Reads(pages)
    with pytest.raises(ControlRejected):
        recover_ambiguous_start(client, request(), lower, upper)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("JobName", "ledgerguard-p3-operation-02-reconciliation"),
        ("Attempt", 1),
        ("PreviousRunId", "jr_" + "b" * 64),
        ("StartedOn", STARTED - timedelta(seconds=2)),
        ("Arguments", {"--attempt-id": "attempt-other"}),
    ],
)
def test_recovery_match_requires_every_ownership_field(field: str, value: Any) -> None:
    listed = run_document()
    listed[field] = value
    client = Reads([{"JobRuns": [listed]}])
    with pytest.raises(ControlRejected, match="no unique"):
        recover_ambiguous_start(
            client, request(), STARTED - timedelta(seconds=1), STARTED + timedelta(seconds=1)
        )


@pytest.mark.parametrize("page", [None, {}, {"JobRuns": None}])
def test_recovery_page_shape_rejections(page: Any) -> None:
    client = Reads(cast(Any, [page]))
    with pytest.raises(ControlRejected, match="page"):
        recover_ambiguous_start(
            client, request(), STARTED - timedelta(seconds=1), STARTED + timedelta(seconds=1)
        )


@pytest.mark.parametrize("token", [1, ""])
def test_recovery_token_type_and_empty_rejections(token: Any) -> None:
    client = Reads([{"JobRuns": [], "NextToken": token}])
    with pytest.raises(ControlRejected, match="pagination token"):
        recover_ambiguous_start(
            client, request(), STARTED - timedelta(seconds=1), STARTED + timedelta(seconds=1)
        )


def test_recovery_rejects_invalid_listed_run_and_identity() -> None:
    for listed in (None, {**run_document(), "Id": "invalid"}):
        client = Reads([{"JobRuns": [listed]}])
        with pytest.raises(ControlRejected):
            recover_ambiguous_start(
                client,
                request(),
                STARTED - timedelta(seconds=1),
                STARTED + timedelta(seconds=1),
            )


def test_recovery_inventory_and_page_count_are_bounded() -> None:
    outside = run_document()
    outside["StartedOn"] = STARTED - timedelta(seconds=2)
    client = Reads([{"JobRuns": [outside] * 1601}])
    with pytest.raises(ControlRejected, match="inventory"):
        recover_ambiguous_start(
            client, request(), STARTED - timedelta(seconds=1), STARTED + timedelta(seconds=1)
        )
    pages = [{"JobRuns": [], "NextToken": f"page-{number}"} for number in range(16)]
    client = Reads(pages)
    with pytest.raises(ControlRejected, match="pagination exceeds"):
        recover_ambiguous_start(
            client, request(), STARTED - timedelta(seconds=1), STARTED + timedelta(seconds=1)
        )


def test_recovery_request_shape_and_candidate_shape_rejections() -> None:
    with pytest.raises(ControlRejected, match="retained"):
        recover_ambiguous_start(
            Reads(),
            cast(Any, MappingProxyType(request())),
            STARTED,
            STARTED,
        )
    receipt = observe_terminal(Reads(), request(), RUN)
    with pytest.raises(ControlRejected, match="does not bind"):
        bind_candidate_job_run(cast(Any, MappingProxyType({"glue_job_run_id": RUN})), receipt)
