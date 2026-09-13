"""Terminal failure evidence remains immutable, fenced and replay-safe."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from ledgerguard.stage3.canonical import canonical_bytes
from ledgerguard_control import controller
from ledgerguard_control.authority import Attempt, LocalAuthority
from ledgerguard_control.contracts import ControlRejected, strict_json
from ledgerguard_control.execution import admit_attempt, register_run
from ledgerguard_control.failure import _managed_identity, record_failure
from tests.test_part3_stage5_execution import OWNER, admitted


def failed_start(
    tmp_path: Path,
) -> tuple[dict[str, Any], Any, Any, LocalAuthority]:
    state, config, objects = admitted(tmp_path / "admitted")
    authority = LocalAuthority(tmp_path / "authority.sqlite")
    state = register_run(
        {"action": "register-run", "execution_arn": OWNER, "state": state}, authority
    )
    state = admit_attempt(
        {"action": "admit-attempt", "execution_arn": OWNER, "state": state}, authority
    )
    state["failure"] = {"Error": "Glue.ServiceException", "Cause": "bounded failure"}
    event = {
        "action": "record-failure",
        "execution_arn": OWNER,
        "state": {
            "failed_state": "StartGlue",
            "error": "Glue.ServiceException",
            "cause": "bounded failure",
            "state": state,
        },
    }
    return event, config, objects, authority


def test_failure_record_is_immutable_fenced_and_exactly_replayable(tmp_path: Path) -> None:
    event, config, objects, authority = failed_start(tmp_path)
    first = record_failure(event, config, objects, objects, authority)
    reference = first["control"]["failure_record"]
    document = strict_json(objects.read(reference["uri"], reference["version_id"]))
    assert canonical_bytes(document) + b"\n" == objects.read(
        reference["uri"], reference["version_id"]
    )
    assert document["failed_state"] == "StartGlue"
    assert document["execution_arn"] == OWNER
    assert document["fence"] == first["control"]["attempt"]["fence"]
    assert document["glue_job_run_id"] is None
    assert document["query_execution_ids"] == []
    assert document["candidate_prefix"].endswith("/attempt-1/candidates")
    assert document["recovery_required"] is True

    replay = record_failure(event, config, objects, objects, authority)
    assert replay["control"]["failure_record"] == reference
    second = authority.admit(
        "namespace-1", "run-test1", config.execution_input["sha256"], "attempt-two", OWNER
    )
    assert second.fence == 2


def test_controller_dispatches_failure_with_real_durable_dependencies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    event, config, objects, authority = failed_start(tmp_path)
    monkeypatch.setattr(controller, "load_config", lambda: config)
    monkeypatch.setattr(
        controller,
        "_failure_dependencies",
        lambda actual: (objects, authority) if actual == config else (None, None),
    )
    result = controller.handler(event, None)
    assert result["control"]["failure_record"]["uri"].startswith(
        f"s3://{config.bucket}/publications/failure-records/"
    )


@pytest.mark.parametrize(
    ("change", "match"),
    [
        (lambda event: event["state"].update(failed_state="ValidateExecution"), "attempt-owned"),
        (lambda event: event["state"].update(error=""), "error differs"),
        (lambda event: event["state"].update(cause="x" * 1025), "cause differs"),
        (
            lambda event: event["state"]["state"]["failure"].update(Cause="changed"),
            "failure identity",
        ),
        (
            lambda event: event["state"]["state"]["managed"].update(
                athena={"settlements": {"QueryExecutionId": "query-one"}}
            ),
            "Athena order",
        ),
        (
            lambda event: event["state"]["state"]["control"].update(
                execution_input_sha256="0" * 64
            ),
            "substituted",
        ),
    ],
)
def test_failure_record_rejects_unowned_or_substituted_state(
    tmp_path: Path, change: Any, match: str
) -> None:
    event, config, objects, authority = failed_start(tmp_path)
    change(event)
    with pytest.raises(ControlRejected, match=match):
        record_failure(event, config, objects, objects, authority)


def test_post_glue_failure_requires_exact_managed_identity(tmp_path: Path) -> None:
    event, config, objects, authority = failed_start(tmp_path)
    event = deepcopy(event)
    event["state"]["failed_state"] = "ValidateCandidate"
    with pytest.raises(ControlRejected, match="missing its run"):
        record_failure(event, config, objects, objects, authority)
    event["state"]["state"]["managed"]["glue"] = {"JobRunId": "jr_" + "1" * 64}
    result = record_failure(event, config, objects, objects, authority)
    reference = result["control"]["failure_record"]
    document = strict_json(objects.read(reference["uri"], reference["version_id"]))
    assert document["glue_job_run_id"] == "jr_" + "1" * 64


@pytest.mark.parametrize(
    ("managed", "state", "match"),
    [
        ({"athena": {}, "extra": True}, "StartGlue", "managed state"),
        ({"athena": {}, "glue": []}, "ValidateCandidate", "Glue state"),
        (
            {"athena": {}, "glue": {"JobRunId": "jr_" + "1" * 64}},
            "StartGlue",
            "cannot claim",
        ),
        (
            {
                "athena": {"transactions": []},
                "glue": {"JobRunId": "jr_" + "1" * 64},
            },
            "SettlementsQuery",
            "Athena result",
        ),
        (
            {
                "athena": {
                    "transactions": {"QueryExecutionId": "query-one"},
                    "settlements": {"QueryExecutionId": "query-one"},
                    "bank_allocations": {"QueryExecutionId": "query-one"},
                },
                "glue": {"JobRunId": "jr_" + "1" * 64},
            },
            "PreparePublication",
            "not unique",
        ),
    ],
)
def test_failure_managed_identity_is_closed(
    managed: dict[str, Any], state: str, match: str
) -> None:
    with pytest.raises(ControlRejected, match=match):
        _managed_identity(managed, state)


def test_failure_query_ids_follow_workflow_order_not_json_key_order() -> None:
    managed = {
        "glue": {"JobRunId": "jr_" + "1" * 64},
        "athena": {
            "settlements": {"QueryExecutionId": "query-two"},
            "transactions": {"QueryExecutionId": "query-one"},
        },
    }
    glue, queries = _managed_identity(managed, "BankAllocationsQuery")
    assert glue == "jr_" + "1" * 64
    assert queries == ["query-one", "query-two"]


@pytest.mark.parametrize(
    ("change", "match"),
    [
        (lambda event: event["state"].update(extra=True), "envelope shape"),
        (lambda event: event["state"].update(state=[]), "captured failure state"),
        (
            lambda event: event["state"]["state"].update(control=[]),
            "captured control state",
        ),
        (
            lambda event: event["state"]["state"]["control"].update(
                namespace="namespace-other"
            ),
            "registration boundary",
        ),
    ],
)
def test_failure_envelope_and_registration_are_closed(
    tmp_path: Path, change: Any, match: str
) -> None:
    event, config, objects, authority = failed_start(tmp_path)
    change(event)
    with pytest.raises(ControlRejected, match=match):
        record_failure(event, config, objects, objects, authority)


def test_failure_rejects_attempt_that_is_no_longer_active(tmp_path: Path) -> None:
    event, config, objects, authority = failed_start(tmp_path)
    authority.fail(Attempt(**event["state"]["state"]["control"]["attempt"]))
    changed = deepcopy(event)
    changed["state"]["state"]["control"]["attempt"]["fence"] += 1
    with pytest.raises(ControlRejected, match="stale attempt"):
        record_failure(changed, config, objects, objects, authority)
