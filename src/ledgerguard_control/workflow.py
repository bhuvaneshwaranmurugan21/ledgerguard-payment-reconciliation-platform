"""Exact production Step Functions definition and static control-flow admission.

The renderer emits only control pointers and digests.  It cannot start a workflow;
AWS definition validation and deployment remain separate, explicitly gated stages.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping
from itertools import pairwise
from typing import Any

from ledgerguard.stage3.canonical import canonical_bytes

from .contracts import ControlRejected

ACCOUNT_ID = "857229544428"
REGION = "ap-southeast-2"
TRANSIENT_LAMBDA = [
    "Lambda.ServiceException",
    "Lambda.AWSLambdaException",
    "Lambda.SdkClientException",
    "Lambda.TooManyRequestsException",
]
TRANSIENT_ATHENA = [
    "Athena.InternalServerException",
    "Athena.TooManyRequestsException",
]
FAMILIES = ("transactions", "settlements", "bank_allocations")


def _lambda_task(function_arn: str, action: str, failed_state: str) -> dict[str, Any]:
    return {
        "Type": "Task",
        # A direct exact-function resource returns only the handler result.  This
        # avoids carrying the optimized integration's SDK envelope and preserves
        # the original state on Catch via its own ResultPath.
        "Resource": function_arn,
        "Parameters": {
            "action": action,
            "execution_arn.$": "$$.Execution.Id",
            "state.$": "$",
        },
        "Retry": [
            {
                "ErrorEquals": TRANSIENT_LAMBDA,
                "IntervalSeconds": 2,
                "MaxAttempts": 3,
                "BackoffRate": 2,
            }
        ],
        "Catch": [
            {
                "ErrorEquals": ["States.ALL"],
                "ResultPath": "$.failure",
                "Next": failed_state,
            }
        ],
    }


def _failure_pass(failed_state: str) -> dict[str, Any]:
    # Only Error, Cause and the original state are universally present.  Optional
    # Glue/query/candidate fields are recovered by RecordFailure from that state;
    # JSONPath selection here would itself fail when an early phase lacks them.
    parameters: dict[str, Any] = {
        "failed_state": failed_state,
        "error.$": "$.failure.Error",
        "cause.$": "$.failure.Cause",
        "state.$": "$",
    }
    return {"Type": "Pass", "Parameters": parameters, "Next": "RecordFailure"}


def _athena_task(family: str, failed_state: str) -> dict[str, Any]:
    return {
        "Type": "Task",
        "Resource": "arn:aws:states:::athena:startQueryExecution.sync",
        "Parameters": {
            "QueryString.$": f"$.control.queries.{family}.sql",
            "ClientRequestToken.$": f"$.control.queries.{family}.client_request_token",
            "WorkGroup.$": "$.control.athena_workgroup",
            "QueryExecutionContext": {
                "Database.$": "$.control.athena_database",
                "Catalog": "AwsDataCatalog",
            },
            "ResultConfiguration": {
                "OutputLocation.$": f"$.control.queries.{family}.output_location",
                "ExpectedBucketOwner": ACCOUNT_ID,
                "EncryptionConfiguration": {"EncryptionOption": "SSE_S3"},
            },
        },
        "ResultPath": f"$.managed.athena.{family}",
        "Retry": [
            {
                "ErrorEquals": TRANSIENT_ATHENA,
                "IntervalSeconds": 2,
                "MaxAttempts": 2,
                "BackoffRate": 2,
            }
        ],
        "Catch": [
            {
                "ErrorEquals": ["States.ALL"],
                "ResultPath": "$.failure",
                "Next": failed_state,
            }
        ],
    }


def render_definition(operation_id: str) -> dict[str, Any]:
    """Render a closed exact-account definition for one admitted operation."""
    if type(operation_id) is not str or re.fullmatch(
        r"[a-z0-9][a-z0-9-]{7,31}", operation_id
    ) is None:
        raise ControlRejected("invalid workflow operation identity")
    prefix = f"arn:aws:lambda:{REGION}:{ACCOUNT_ID}:function:ledgerguard-p3-{operation_id}"
    validator = prefix + "-validator"
    controller = prefix + "-controller"
    states: dict[str, Any] = {}

    states["ValidateExecution"] = _lambda_task(
        validator, "validate-execution", "CaptureValidateExecutionFailure"
    )
    states["ValidateExecution"]["Next"] = "RegisterRun"
    states["RegisterRun"] = _lambda_task(controller, "register-run", "CaptureRegisterFailure")
    states["RegisterRun"]["Next"] = "RegistrationOutcome"
    states["RegistrationOutcome"] = {
        "Type": "Choice",
        "Choices": [
            {
                "Variable": "$.control.replay_committed",
                "BooleanEquals": True,
                "Next": "ReplaySucceeded",
            }
        ],
        "Default": "AdmitAttempt",
    }
    states["ReplaySucceeded"] = {"Type": "Succeed"}
    states["AdmitAttempt"] = _lambda_task(
        controller, "admit-attempt", "CaptureAdmitAttemptFailure"
    )
    states["AdmitAttempt"]["Next"] = "StartGlue"
    states["StartGlue"] = {
        "Type": "Task",
        "Resource": "arn:aws:states:::glue:startJobRun.sync",
        "Parameters": {
            "JobName.$": "$.control.glue_start.JobName",
            "Arguments.$": "$.control.glue_start.Arguments",
            "ExecutionClass": "STANDARD",
            "JobRunQueuingEnabled": False,
        },
        "ResultPath": "$.managed.glue",
        # StartJobRun has no idempotency token.  Retrying an ambiguous response here
        # could create two runs, so recovery is explicit and never a blind retry.
        "Catch": [
            {
                "ErrorEquals": ["States.ALL"],
                "ResultPath": "$.failure",
                "Next": "CaptureGlueFailure",
            }
        ],
        "Next": "ValidateCandidate",
    }
    states["ValidateCandidate"] = _lambda_task(
        validator, "validate-candidate", "CaptureValidateCandidateFailure"
    )
    states["ValidateCandidate"]["Next"] = "RunTransactionsQuery"

    prior = "ValidateCandidate"
    for family in FAMILIES:
        title = "".join(part.title() for part in family.split("_"))
        run = f"Run{title}Query"
        check = f"Validate{title}Query"
        capture = f"Capture{title}QueryFailure"
        if prior != "ValidateCandidate":
            states[prior]["Next"] = run
        states[run] = _athena_task(family, capture)
        states[run]["Next"] = check
        states[check] = _lambda_task(validator, f"validate-{family}-query", capture)
        prior = check
    states[prior]["Next"] = "PreparePublication"

    states["PreparePublication"] = _lambda_task(
        controller, "prepare-publication", "CapturePreparePublicationFailure"
    )
    states["PreparePublication"]["Next"] = "PublishAuthority"
    states["PublishAuthority"] = _lambda_task(
        controller, "publish-authority", "CapturePublishFailure"
    )
    states["PublishAuthority"]["Next"] = "WorkflowSucceeded"
    states["WorkflowSucceeded"] = {"Type": "Succeed"}

    failure_sources = {
        "CaptureValidateExecutionFailure": "ValidateExecution",
        "CaptureRegisterFailure": "RegisterRun",
        "CaptureAdmitAttemptFailure": "AdmitAttempt",
        "CaptureGlueFailure": "StartGlue",
        "CaptureValidateCandidateFailure": "ValidateCandidate",
        "CaptureTransactionsQueryFailure": "TransactionsQuery",
        "CaptureSettlementsQueryFailure": "SettlementsQuery",
        "CaptureBankAllocationsQueryFailure": "BankAllocationsQuery",
        "CapturePreparePublicationFailure": "PreparePublication",
        "CapturePublishFailure": "PublishAuthority",
    }
    for name, failed in failure_sources.items():
        states[name] = _failure_pass(failed)
    states["RecordFailure"] = _lambda_task(
        controller, "record-failure", "FailureEvidenceUnavailable"
    )
    states["RecordFailure"].pop("Next", None)
    states["RecordFailure"]["Next"] = "WorkflowFailed"
    states["FailureEvidenceUnavailable"] = {
        "Type": "Fail",
        "Error": "LedgerGuardFailureEvidenceUnavailable",
        "Cause": "The original failure could not be durably recorded",
    }
    states["WorkflowFailed"] = {
        "Type": "Fail",
        "Error": "LedgerGuardRunFailed",
        "Cause": "Terminal failure ownership was durably recorded",
    }
    definition = {
        "Comment": "LedgerGuard Part 3 fail-closed reconciliation orchestration",
        "StartAt": "ValidateExecution",
        "TimeoutSeconds": 1800,
        "States": states,
    }
    validate_definition(definition, operation_id)
    return definition


def definition_bytes(operation_id: str) -> bytes:
    """Return the exact compact JSON submitted to definition validation/deployment."""
    return canonical_bytes(render_definition(operation_id))


def _edges(name: str, state: Mapping[str, Any]) -> Iterator[str]:
    if "Next" in state:
        yield state["Next"]
    if state.get("Type") == "Choice":
        for choice in state.get("Choices", []):
            yield choice["Next"]
        yield state["Default"]
    for catcher in state.get("Catch", []):
        yield catcher["Next"]


def validate_definition(definition: Mapping[str, Any], operation_id: str) -> None:
    """Fail closed on structural shortcuts before AWS performs syntax validation."""
    if set(definition) != {"Comment", "StartAt", "TimeoutSeconds", "States"}:
        raise ControlRejected("workflow top-level shape differs")
    if definition.get("TimeoutSeconds") != 1800:
        raise ControlRejected("workflow timeout differs")
    states = definition.get("States")
    if type(states) is not dict or definition.get("StartAt") not in states:
        raise ControlRejected("workflow has no valid start")
    expected_prefix = (
        f"arn:aws:lambda:{REGION}:{ACCOUNT_ID}:function:ledgerguard-p3-{operation_id}-"
    )
    for name, raw in states.items():
        if type(name) is not str or type(raw) is not dict:
            raise ControlRejected("workflow state shape differs")
        state = raw
        for edge_target in _edges(name, state):
            if edge_target not in states:
                raise ControlRejected("workflow edge targets a missing state")
        if state.get("Type") == "Task":
            resource = state.get("Resource")
            if type(resource) is str and resource.startswith("arn:aws:lambda:"):
                if not resource.startswith(expected_prefix) or resource not in {
                    expected_prefix + "validator",
                    expected_prefix + "controller",
                }:
                    raise ControlRejected("workflow Lambda target differs")
            elif resource not in {
                "arn:aws:states:::glue:startJobRun.sync",
                "arn:aws:states:::athena:startQueryExecution.sync",
            }:
                raise ControlRejected("workflow task resource differs")
            if not state.get("Catch") or state["Catch"][-1] != {
                "ErrorEquals": ["States.ALL"],
                "ResultPath": "$.failure",
                "Next": state["Catch"][-1]["Next"],
            }:
                raise ControlRejected("workflow task does not preserve a terminal failure")
            for retry in state.get("Retry", []):
                if (
                    type(retry.get("MaxAttempts")) is not int
                    or not 1 <= retry["MaxAttempts"] <= 3
                    or retry.get("ErrorEquals") in (["States.ALL"], ["States.TaskFailed"])
                ):
                    raise ControlRejected("workflow retry is unbounded or indiscriminate")
        if name == "StartGlue" and "Retry" in state:
            raise ControlRejected("ambiguous Glue start must not be blindly retried")

    required_success_chain = [
        "ValidateExecution",
        "RegisterRun",
        "AdmitAttempt",
        "StartGlue",
        "ValidateCandidate",
        "RunTransactionsQuery",
        "ValidateTransactionsQuery",
        "RunSettlementsQuery",
        "ValidateSettlementsQuery",
        "RunBankAllocationsQuery",
        "ValidateBankAllocationsQuery",
        "PreparePublication",
        "PublishAuthority",
        "WorkflowSucceeded",
    ]
    for left, right in pairwise(required_success_chain):
        state = states[left]
        if left == "RegisterRun":
            outcome = states.get(state.get("Next"), {})
            target: Any = outcome.get("Default")
        else:
            target = state.get("Next")
        if target != right:
            raise ControlRejected("workflow success chain can bypass required authority")
    if states.get("ReplaySucceeded") != {"Type": "Succeed"}:
        raise ControlRejected("workflow replay terminal differs")
    if states.get("WorkflowSucceeded") != {"Type": "Succeed"}:
        raise ControlRejected("workflow success terminal differs")
    reachable: set[str] = set()
    pending = [definition["StartAt"]]
    while pending:
        name = pending.pop()
        if name in reachable:
            continue
        reachable.add(name)
        pending.extend(_edges(name, states[name]))
    if reachable != set(states):
        raise ControlRejected("workflow contains unreachable states")
