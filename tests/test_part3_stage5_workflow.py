"""Production ASL rendering, reachability, retry and authority-order checks."""

from __future__ import annotations

from copy import deepcopy

import pytest

from ledgerguard.stage3.canonical import canonical_bytes
from ledgerguard_control.contracts import ControlRejected, strict_json
from ledgerguard_control.workflow import (
    FAMILIES,
    TRANSIENT_ATHENA,
    TRANSIENT_LAMBDA,
    definition_bytes,
    render_definition,
    validate_definition,
)

OPERATION = "operation-stage5"


def definition() -> dict[str, object]:
    return render_definition(OPERATION)


def test_definition_is_exact_canonical_standard_workflow() -> None:
    value = definition()
    raw = definition_bytes(OPERATION)
    assert strict_json(raw) == value
    assert canonical_bytes(value) == raw
    assert value["StartAt"] == "ValidateExecution"
    assert value["TimeoutSeconds"] == 1800
    assert b"857229544428" in raw and b"857229544429" not in raw
    states = value["States"]
    assert isinstance(states, dict)
    assert states["ReplaySucceeded"] == {"Type": "Succeed"}
    assert states["WorkflowSucceeded"] == {"Type": "Succeed"}
    assert states["WorkflowFailed"]["Type"] == "Fail"


def test_success_path_is_complete_and_ordered() -> None:
    states = definition()["States"]
    assert isinstance(states, dict)
    assert states["ValidateExecution"]["Next"] == "RegisterRun"
    assert states["RegisterRun"]["Next"] == "RegistrationOutcome"
    assert states["RegistrationOutcome"]["Default"] == "StartGlue"
    assert states["StartGlue"]["Next"] == "ValidateCandidate"
    current = "ValidateCandidate"
    for family in FAMILIES:
        title = "".join(part.title() for part in family.split("_"))
        run = f"Run{title}Query"
        check = f"Validate{title}Query"
        assert states[current]["Next"] == run
        assert states[run]["Next"] == check
        current = check
    assert states[current]["Next"] == "PreparePublication"
    assert states["PreparePublication"]["Next"] == "PublishAuthority"
    assert states["PublishAuthority"]["Next"] == "WorkflowSucceeded"


def test_managed_tasks_use_exact_integrations_and_pointer_inputs() -> None:
    states = definition()["States"]
    assert isinstance(states, dict)
    glue = states["StartGlue"]
    assert glue["Resource"] == "arn:aws:states:::glue:startJobRun.sync"
    assert "Retry" not in glue
    assert glue["Parameters"] == {
        "JobName.$": "$.control.glue_start.JobName",
        "Arguments.$": "$.control.glue_start.Arguments",
        "ExecutionClass": "STANDARD",
        "JobRunQueuingEnabled": False,
    }
    for family in FAMILIES:
        title = "".join(part.title() for part in family.split("_"))
        task = states[f"Run{title}Query"]
        assert task["Resource"] == "arn:aws:states:::athena:startQueryExecution.sync"
        assert task["Parameters"]["ClientRequestToken.$"] == (
            f"$.control.queries.{family}.client_request_token"
        )
        assert task["Retry"][0]["ErrorEquals"] == TRANSIENT_ATHENA
        assert task["Retry"][0]["MaxAttempts"] == 2
    assert b"transactions" in definition_bytes(OPERATION)
    assert b"raw financial" not in definition_bytes(OPERATION).lower()


def test_lambda_retries_are_named_bounded_and_semantic_errors_are_not_retried() -> None:
    states = definition()["States"]
    assert isinstance(states, dict)
    for state in states.values():
        if not str(state.get("Resource", "")).startswith("arn:aws:lambda:"):
            continue
        retry = state["Retry"]
        assert state["Parameters"]["execution_arn.$"] == "$$.Execution.Id"
        assert retry == [
            {
                "ErrorEquals": TRANSIENT_LAMBDA,
                "IntervalSeconds": 2,
                "MaxAttempts": 3,
                "BackoffRate": 2,
            }
        ]
        assert "States.ALL" not in retry[0]["ErrorEquals"]
        assert state["Catch"][0]["ResultPath"] == "$.failure"


def test_failure_paths_preserve_original_error_and_end_in_fail() -> None:
    states = definition()["States"]
    assert isinstance(states, dict)
    captures = [name for name in states if name.startswith("Capture")]
    assert len(captures) == 9
    for name in captures:
        state = states[name]
        assert state["Type"] == "Pass"
        assert state["Parameters"]["error.$"] == "$.failure.Error"
        assert state["Parameters"]["cause.$"] == "$.failure.Cause"
        assert state["Parameters"]["state.$"] == "$"
        assert state["Next"] == "RecordFailure"
    assert states["RecordFailure"]["Next"] == "WorkflowFailed"
    assert states["RecordFailure"]["Catch"][0]["Next"] == "FailureEvidenceUnavailable"


@pytest.mark.parametrize(
    "operation",
    ["short", "Uppercase-operation", "operation/escape", "a" * 33, 1],
)
def test_invalid_operation_identity_is_rejected(operation: object) -> None:
    with pytest.raises(ControlRejected, match="operation"):
        render_definition(operation)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "mutate,match",
    [
        (lambda d: d.update(TimeoutSeconds=1), "timeout"),
        (lambda d: d.update(Version="1.0"), "top-level"),
        (lambda d: d.update(StartAt="Missing"), "valid start"),
        (lambda d: d["States"]["StartGlue"].update(Next="Missing"), "missing state"),
        (lambda d: d["States"]["StartGlue"].update(Retry=[]), "blindly"),
        (
            lambda d: d["States"]["ValidateExecution"].update(
                Resource="arn:aws:lambda:us-east-1:000000000000:function:other"
            ),
            "Lambda target",
        ),
        (
            lambda d: d["States"]["StartGlue"].update(Resource="arn:aws:states:::sqs:sendMessage"),
            "resource",
        ),
        (lambda d: d["States"]["ValidateCandidate"].pop("Catch"), "terminal failure"),
        (
            lambda d: d["States"]["ValidateExecution"]["Retry"][0].update(
                ErrorEquals=["States.ALL"]
            ),
            "indiscriminate",
        ),
        (
            lambda d: d["States"]["ValidateExecution"]["Retry"][0].update(MaxAttempts=4),
            "unbounded",
        ),
        (lambda d: d["States"].update(Dead={"Type": "Fail"}), "unreachable"),
        (
            lambda d: d["States"]["ValidateCandidate"].update(Next="PreparePublication"),
            "bypass",
        ),
        (lambda d: d["States"]["ReplaySucceeded"].update(Type="Fail"), "replay"),
        (lambda d: d["States"]["WorkflowSucceeded"].update(Type="Fail"), "success terminal"),
    ],
)
def test_static_admission_rejects_definition_shortcuts(mutate: object, match: str) -> None:
    value = definition()
    mutate(value)  # type: ignore[operator]
    with pytest.raises(ControlRejected, match=match):
        validate_definition(value, OPERATION)


def test_static_admission_rejects_malformed_state_and_retry_types() -> None:
    value = definition()
    value["States"]["WorkflowFailed"] = []
    with pytest.raises(ControlRejected, match="state shape"):
        validate_definition(value, OPERATION)
    value = definition()
    value["States"]["ValidateExecution"]["Retry"][0]["MaxAttempts"] = True
    with pytest.raises(ControlRejected, match="unbounded"):
        validate_definition(value, OPERATION)


def test_renderer_returns_detached_definition() -> None:
    first = definition()
    second = deepcopy(definition())
    first["States"]["StartGlue"]["Parameters"]["ExecutionClass"] = "FLEX"
    assert second == definition()
