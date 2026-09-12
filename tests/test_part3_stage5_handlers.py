"""Concrete Lambda entrypoints remain deployment-bound and fail closed."""

from __future__ import annotations

import sys
from hashlib import sha256
from types import SimpleNamespace
from typing import Any

import pytest

from ledgerguard.stage3.canonical import canonical_bytes
from ledgerguard_control import controller, runtime, validator
from ledgerguard_control.authority import LocalAuthority
from ledgerguard_control.contracts import ControlRejected
from ledgerguard_control.objects import LocalVersionedObjects
from tests.test_part3_stage5_execution import OWNER, admitted, fixture


def environment(tmp_path: Any) -> tuple[dict[str, str], LocalVersionedObjects]:
    value, raw, objects = fixture(tmp_path)
    return (
        {
            "HANDLER_CONFIG_JSON": raw.decode(),
            "HANDLER_CONFIG_SHA256": sha256(raw).hexdigest(),
            "WORKLOAD_BUCKET": f"ledgerguard-p3-857229544428-{value['operation_id']}",
            "CONTROL_TABLE": f"ledgerguard-p3-{value['operation_id']}-control",
        },
        objects,
    )


def test_runtime_configuration_and_aws_client_are_exact(tmp_path: Any) -> None:
    values, _ = environment(tmp_path)
    config = runtime.load_config(values)
    assert config.bucket == values["WORKLOAD_BUCKET"]
    calls = []
    sys.modules["boto3"] = SimpleNamespace(
        client=lambda service, **kwargs: calls.append((service, kwargs)) or service
    )
    try:
        assert runtime.aws_client("s3") == "s3"
    finally:
        del sys.modules["boto3"]
    assert calls == [("s3", {"region_name": "ap-southeast-2"})]
    with pytest.raises(ControlRejected, match="unsupported"):
        runtime.aws_client("glue")


@pytest.mark.parametrize(
    "change,match",
    [
        (lambda value: value.pop("HANDLER_CONFIG_JSON"), "incomplete"),
        (lambda value: value.update(HANDLER_CONFIG_JSON=object()), "incomplete"),
        (lambda value: value.update(HANDLER_CONFIG_SHA256=object()), "incomplete"),
        (lambda value: value.update(HANDLER_CONFIG_JSON="\ud800"), "invalid"),
        (lambda value: value.update(WORKLOAD_BUCKET="wrong"), "workload bucket"),
        (lambda value: value.update(CONTROL_TABLE="wrong"), "control table"),
    ],
)
def test_runtime_configuration_rejects_missing_or_substituted_values(
    tmp_path: Any, change: Any, match: str
) -> None:
    values, _ = environment(tmp_path)
    change(values)
    with pytest.raises(ControlRejected, match=match):
        runtime.load_config(values)


def test_validator_handler_executes_real_admission(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    values, objects = environment(tmp_path)
    config = runtime.load_config(values)
    monkeypatch.setattr(validator, "load_config", lambda: config)
    monkeypatch.setattr(validator, "_objects", lambda actual: objects if actual == config else None)
    event = {
        "action": "validate-execution",
        "execution_arn": OWNER,
        "state": {"execution_input_sha256": config.execution_input["sha256"]},
    }
    result = validator.handler(event, object())
    assert result["control"]["execution_input_sha256"] == config.execution_input["sha256"]


def test_controller_handler_executes_durable_registration(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    state, config, _ = admitted(tmp_path / "admitted")
    authority = LocalAuthority(tmp_path / "authority.sqlite")
    monkeypatch.setattr(controller, "load_config", lambda: config)
    monkeypatch.setattr(
        controller, "_authority", lambda actual: authority if actual == config else None
    )
    event = {"action": "register-run", "execution_arn": OWNER, "state": state}
    result = controller.handler(event, None)
    assert "attempt" not in result["control"]
    result = controller.handler(
        {"action": "admit-attempt", "execution_arn": OWNER, "state": result}, None
    )
    assert result["control"]["attempt"]["owner"] == OWNER


@pytest.mark.parametrize("entrypoint", [validator.handler, controller.handler])
@pytest.mark.parametrize("event", [None, {}, {"action": "wrong"}])
def test_handlers_reject_unknown_actions_before_runtime_access(
    entrypoint: Any, event: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        validator if entrypoint is validator.handler else controller,
        "load_config",
        lambda: (_ for _ in ()).throw(AssertionError("runtime must not be loaded")),
    )
    with pytest.raises(ControlRejected, match="unsupported"):
        entrypoint(event, None)


def test_default_environment_and_transport_factories(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    values, _ = environment(tmp_path)
    monkeypatch.setattr(runtime.os, "environ", values)
    config = runtime.load_config()
    monkeypatch.setattr(validator, "aws_client", lambda service: ("client", service))
    monkeypatch.setattr(controller, "aws_client", lambda service: ("client", service))
    s3 = validator._objects(config)
    authority = controller._authority(config)
    assert s3.client == ("client", "s3")
    assert authority.client == ("client", "dynamodb")
    assert authority.table == config.table


def test_handler_configuration_is_canonical_json(tmp_path: Any) -> None:
    values, _ = environment(tmp_path)
    assert canonical_bytes(runtime.load_config(values).execution_input).startswith(b"{")
