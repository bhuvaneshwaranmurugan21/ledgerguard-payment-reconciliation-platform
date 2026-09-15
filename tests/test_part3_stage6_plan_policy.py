from __future__ import annotations

import copy
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from tools.part3_stage6.plan_policy import (
    AWS_PROVIDER,
    COMPUTED_UNKNOWN_PATHS,
    _list,
    _object,
    _unknown_paths,
    expected_addresses,
    validate_saved_plan,
)

ROOT = Path(__file__).resolve().parents[1]
ADDRESSES = expected_addresses(ROOT)


def valid_plan() -> dict[str, Any]:
    return {
        "format_version": "1.2",
        "terraform_version": "1.13.1",
        "resource_drift": [],
        "output_changes": {},
        "checks": [{"status": "pass"}],
        "resource_changes": [
            {
                "address": address,
                "mode": "managed",
                "type": address.split(".", 1)[0],
                "name": address.split(".", 1)[1].split("[", 1)[0],
                "provider_name": AWS_PROVIDER,
                "change": {
                    "actions": ["create"],
                    "before": None,
                    "after": {"id": None},
                    "after_unknown": {"id": True},
                    "replace_paths": [],
                },
            }
            for address in ADDRESSES
        ],
        "prior_state": {"values": {"root_module": {}}},
        "configuration": {
            "provider_config": {"aws": {"full_name": AWS_PROVIDER}},
            "root_module": {
                "resources": [
                    {
                        "address": address,
                        "mode": "managed",
                        "provider_config_key": "aws",
                    }
                    for address in ADDRESSES
                ]
            },
        },
    }


def test_valid_syntactic_vector_passes_without_claiming_property_or_stage_gate() -> None:
    result = validate_saved_plan(valid_plan(), ADDRESSES)
    assert result["resource_changes"] == result["create_actions"] == 33
    assert result["other_actions"] == result["aws_calls"] == 0
    assert result["benign_computed_unknown_count"] == 33
    assert result["property_policy_required"] is True
    assert result["stage6_complete"] is False


def first(plan: dict[str, Any]) -> dict[str, Any]:
    return plan["resource_changes"][0]


def set_action(action: list[str]) -> Callable[[dict[str, Any]], None]:
    return lambda plan: first(plan)["change"].__setitem__("actions", action)


@pytest.mark.parametrize(
    ("name", "mutate"),
    [
        ("update", set_action(["update"])),
        ("delete", set_action(["delete"])),
        ("replacement", set_action(["delete", "create"])),
        ("no-op", set_action(["no-op"])),
        ("read", set_action(["read"])),
        ("import", lambda p: first(p)["change"].__setitem__("importing", {"id": "x"})),
        ("generated", lambda p: first(p)["change"].__setitem__("generated_config", "x")),
        ("replace-path", lambda p: first(p)["change"].__setitem__("replace_paths", [["id"]])),
        ("prior", lambda p: first(p)["change"].__setitem__("before", {"id": "old"})),
        ("data", lambda p: first(p).__setitem__("mode", "data")),
        ("provider", lambda p: first(p).__setitem__("provider_name", "other/aws")),
        ("type", lambda p: first(p).__setitem__("type", "aws_sqs_queue")),
        ("move", lambda p: first(p).__setitem__("previous_address", "old.address")),
        ("deposed", lambda p: first(p).__setitem__("deposed", "x")),
        ("module", lambda p: first(p).__setitem__("module_address", "module.x")),
        (
            "critical-unknown",
            lambda p: first(p)["change"].__setitem__("after_unknown", {"policy": True}),
        ),
        ("extra", lambda p: p["resource_changes"].append(copy.deepcopy(first(p)))),
        ("missing", lambda p: p["resource_changes"].pop()),
        ("duplicate", lambda p: p["resource_changes"].__setitem__(1, copy.deepcopy(first(p)))),
        ("drift", lambda p: p["resource_drift"].append({})),
        ("output", lambda p: p["output_changes"].update(x={})),
        ("check", lambda p: p["checks"][0].update(status="fail")),
        ("prior-state", lambda p: p["prior_state"]["values"]["root_module"].update(resources=[{}])),
        (
            "child-state",
            lambda p: p["prior_state"]["values"]["root_module"].update(child_modules=[{}]),
        ),
        ("module-call", lambda p: p["configuration"]["root_module"].update(module_calls={"x": {}})),
        (
            "provider-config",
            lambda p: p["configuration"]["provider_config"]["aws"].update(full_name="other/aws"),
        ),
        (
            "data-source",
            lambda p: p["configuration"]["root_module"]["resources"][0].update(mode="data"),
        ),
        (
            "configuration-provider",
            lambda p: p["configuration"]["root_module"]["resources"][0].update(
                provider_config_key="other"
            ),
        ),
        (
            "provisioner",
            lambda p: p["configuration"]["root_module"]["resources"][0].update(
                provisioners=[{"type": "local-exec"}]
            ),
        ),
    ],
)
def test_forbidden_saved_plan_shapes_fail_closed(
    name: str, mutate: Callable[[dict[str, Any]], None]
) -> None:
    plan = valid_plan()
    mutate(plan)
    with pytest.raises(ValueError):
        validate_saved_plan(plan, ADDRESSES)


@pytest.mark.parametrize("term", ["assume_role_policy", "kms_key_id", "public_access", "tags"])
def test_nested_security_critical_unknowns_fail(term: str) -> None:
    plan = valid_plan()
    first(plan)["change"]["after_unknown"] = {"nested": [{term: True}]}
    with pytest.raises(ValueError, match="security-critical"):
        validate_saved_plan(plan, ADDRESSES)


def test_only_exact_provider_computed_identity_unknowns_are_admitted() -> None:
    plan = valid_plan()
    row = next(item for item in plan["resource_changes"] if item["type"] == "aws_lambda_function")
    admitted = sorted(COMPUTED_UNKNOWN_PATHS["aws_lambda_function"])
    row["change"]["after_unknown"] = {key: True for key in admitted}
    result = validate_saved_plan(plan, ADDRESSES)
    assert result["benign_computed_unknown_count"] == 32 + len(admitted)
    row["change"]["after_unknown"] = {"runtime": True}
    with pytest.raises(ValueError, match="security-critical"):
        validate_saved_plan(plan, ADDRESSES)


@pytest.mark.parametrize(
    ("resource_type", "path"),
    [
        ("aws_s3_bucket_policy", ("policy",)),
        ("aws_iam_role_policy", ("role",)),
        ("aws_glue_job", ("role_arn",)),
        ("aws_lambda_function", ("role",)),
        ("aws_sfn_state_machine", ("role_arn",)),
        ("aws_glue_catalog_table", ("database_name",)),
        (
            "aws_sfn_state_machine",
            ("logging_configuration", "0", "log_destination"),
        ),
        ("aws_cloudwatch_metric_alarm", ("dimensions", "StateMachineArn")),
    ],
)
def test_exact_source_derived_computed_unknowns_are_admitted(
    resource_type: str, path: tuple[str, ...]
) -> None:
    plan = valid_plan()
    row = next(item for item in plan["resource_changes"] if item["type"] == resource_type)
    unknown: dict[str, Any] = {}
    cursor = unknown
    for token in path[:-1]:
        child: Any = [] if token == "logging_configuration" else {}
        cursor[token] = child
        if isinstance(child, list):
            child.append({})
            cursor = child[0]
        else:
            cursor = child
    cursor[path[-1]] = True
    row["change"]["after_unknown"] = unknown
    validate_saved_plan(plan, ADDRESSES)


def test_adjacent_nested_critical_unknown_is_not_admitted() -> None:
    plan = valid_plan()
    row = next(item for item in plan["resource_changes"] if item["type"] == "aws_sfn_state_machine")
    row["change"]["after_unknown"] = {"logging_configuration": [{"kms_key_arn": True}]}
    with pytest.raises(ValueError, match="security-critical"):
        validate_saved_plan(plan, ADDRESSES)


def test_invalid_unknown_leaf_and_address_authority_fail() -> None:
    plan = valid_plan()
    first(plan)["change"]["after_unknown"] = {"id": "yes"}
    with pytest.raises(ValueError, match="unknown-value"):
        validate_saved_plan(plan, ADDRESSES)
    with pytest.raises(ValueError, match="expected address"):
        validate_saved_plan(valid_plan(), ADDRESSES[:-1])


def test_configuration_resources_are_required_and_addressed() -> None:
    plan = valid_plan()
    plan["configuration"]["root_module"]["resources"] = []
    with pytest.raises(ValueError, match="resources missing"):
        validate_saved_plan(plan, ADDRESSES)
    plan = valid_plan()
    plan["configuration"]["root_module"]["resources"][0]["address"] = None
    with pytest.raises(ValueError, match="address missing"):
        validate_saved_plan(plan, ADDRESSES)


@pytest.mark.parametrize(
    ("value", "helper"),
    [
        ([], lambda value: _object(value, "object")),
        ({}, lambda value: _list(value, "list")),
    ],
)
def test_container_helpers_reject_wrong_types(
    value: object, helper: Callable[[object], object]
) -> None:
    with pytest.raises(ValueError):
        helper(value)


def test_unknown_tree_accepts_false_and_none_but_rejects_non_string_keys() -> None:
    assert _unknown_paths(False) == []
    assert _unknown_paths(None) == []
    with pytest.raises(ValueError, match="key"):
        _unknown_paths({1: True})


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("format_version", "1.1", "format"),
        ("terraform_version", "1.12.0", "version"),
    ],
)
def test_plan_version_identity_is_exact(field: str, value: str, message: str) -> None:
    plan = valid_plan()
    plan[field] = value
    with pytest.raises(ValueError, match=message):
        validate_saved_plan(plan, ADDRESSES)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("address", None, "address missing"),
        ("address", "invalid", "invalid managed address"),
        ("after", None, "after object"),
    ],
)
def test_required_change_identity_and_after_object(field: str, value: object, message: str) -> None:
    plan = valid_plan()
    if field == "after":
        first(plan)["change"][field] = value
    else:
        first(plan)[field] = value
    with pytest.raises(ValueError, match=message):
        validate_saved_plan(plan, ADDRESSES)


def test_equal_count_substituted_address_is_rejected() -> None:
    plan = valid_plan()
    row = first(plan)
    row["address"] = "aws_sqs_queue.unapproved"
    row["type"] = "aws_sqs_queue"
    with pytest.raises(ValueError, match="inventory differs"):
        validate_saved_plan(plan, ADDRESSES)
