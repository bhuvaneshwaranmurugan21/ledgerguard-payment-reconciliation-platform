"""Concrete execution admission and registration use durable local backends."""

from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from typing import Any

import pytest

from ledgerguard.stage3.canonical import canonical_bytes
from ledgerguard_control.authority import LocalAuthority
from ledgerguard_control.contracts import ControlRejected
from ledgerguard_control.execution import (
    admit_attempt,
    parse_config,
    read_reference,
    register_run,
    validate_execution,
)
from ledgerguard_control.objects import LocalVersionedObjects

OPERATION = "operation-stage5"
BUCKET = f"ledgerguard-p3-857229544428-{OPERATION}"
OWNER = (
    "arn:aws:states:ap-southeast-2:857229544428:execution:ledgerguard-test:execution-one"
)


def fixture(tmp_path: Path) -> tuple[dict[str, Any], bytes, LocalVersionedObjects]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    objects = LocalVersionedObjects(tmp_path / "objects.sqlite")
    runtime = {
        "source_commit": "a" * 40,
        "source_tree": "b" * 40,
        "runtime_package_sha256": "c" * 64,
        "script_sha256": "d" * 64,
        "wheels_sha256": "e" * 64,
    }
    prefix = f"s3://{BUCKET}/runs/run-test1/inputs"
    job = {
        "run_id": "run-test1",
        "attempt_id": "attempt-1",
        "control_record_identity": "control-1",
        "policy_sha256": "1" * 64,
        "manifest_sha256": "2" * 64,
        "source_bundle_sha256": "3" * 64,
        "source_commit": "f" * 40,
        "source_tree": runtime["source_tree"],
        "runtime_package_sha256": runtime["runtime_package_sha256"],
        "workload_bucket": BUCKET,
        "input_prefix": prefix,
        "candidate_output_prefix": (
            f"s3://{BUCKET}/runs/run-test1/attempts/attempt-1/candidates"
        ),
        "evidence_prefix": f"s3://{BUCKET}/runs/run-test1/attempts/attempt-1/evidence",
    }

    def ref(name: str) -> dict[str, Any]:
        raw = (name + "\n").encode()
        uri = f"{prefix}/{name}.json"
        version = objects.put(uri, raw)
        return {
            "uri": uri,
            "version_id": version,
            "sha256": sha256(raw).hexdigest(),
            "size_bytes": len(raw),
        }

    execution = {
        "schema_version": "ledgerguard.execution-input.v1",
        "job": job,
        "runtime": runtime,
        "release_manifest_sha256": "9" * 64,
        "expected_results": ref("expected"),
        "input_inventory": ref("inventory"),
        "namespace": "namespace-1",
        "predecessor": None,
    }
    execution_raw = canonical_bytes(execution)
    uri = f"{prefix}/execution-input.json"
    version = objects.put(uri, execution_raw)
    reference = {
        "uri": uri,
        "version_id": version,
        "sha256": sha256(execution_raw).hexdigest(),
        "size_bytes": len(execution_raw),
    }
    config_value = {
        "schema_version": "ledgerguard.handler-config.v1",
        "operation_id": OPERATION,
        "execution_input": reference,
        "release_manifest_sha256": "9" * 64,
        "runtime": runtime,
    }
    config_raw = canonical_bytes(config_value)
    return config_value, config_raw, objects


def admitted(tmp_path: Path) -> tuple[dict[str, Any], Any, LocalVersionedObjects]:
    value, raw, objects = fixture(tmp_path)
    config = parse_config(raw, sha256(raw).hexdigest())
    event = {
        "action": "validate-execution",
        "execution_arn": OWNER,
        "state": {"execution_input_sha256": value["execution_input"]["sha256"]},
    }
    return validate_execution(event, config, objects), config, objects


def test_exact_execution_is_admitted_and_renders_managed_requests(tmp_path: Path) -> None:
    state, config, _ = admitted(tmp_path)
    control = state["control"]
    assert control["execution_input_sha256"] == config.execution_input["sha256"]
    assert config.table == "ledgerguard-p3-operation-stage5-control"
    assert control["glue_start"]["ExecutionClass"] == "STANDARD"
    assert set(control["queries"]) == {
        "transactions",
        "settlements",
        "bank_allocations",
    }
    assert all("run_id = 'run-test1'" in row["sql"] for row in control["queries"].values())
    assert all(
        "attempt_id = 'attempt-1'" in row["sql"] for row in control["queries"].values()
    )
    assert len({row["client_request_token"] for row in control["queries"].values()}) == 3
    assert state["managed"] == {"athena": {}}


def test_registration_is_durable_fenced_and_committed_replay_is_terminal(tmp_path: Path) -> None:
    state, _, _ = admitted(tmp_path)
    authority = LocalAuthority(tmp_path / "authority.sqlite")
    event = {"action": "register-run", "execution_arn": OWNER, "state": state}
    registered = register_run(event, authority)
    assert "attempt" not in registered["control"]
    assert registered["control"]["namespace"] == "namespace-1"
    admitted_state = admit_attempt(
        {"action": "admit-attempt", "execution_arn": OWNER, "state": registered}, authority
    )
    attempt = admitted_state["control"]["attempt"]
    assert attempt["owner"] == OWNER and attempt["fence"] == 1
    from ledgerguard_control.authority import Attempt

    commit = authority.publish(Attempt(**attempt), None, "a" * 64)
    replay_state, _, _ = admitted(tmp_path / "replay")
    replay = register_run(
        {"action": "register-run", "execution_arn": OWNER, "state": replay_state}, authority
    )
    assert replay["control"]["replay_committed"] is True
    assert replay["control"]["committed_sha256"] == commit
    with pytest.raises(ControlRejected, match="committed replay"):
        admit_attempt(
            {"action": "admit-attempt", "execution_arn": OWNER, "state": replay}, authority
        )


@pytest.mark.parametrize(
    "edit,match",
    [
        (lambda value: value.update(operation_id="operation-other"), "deployed run"),
        (
            lambda value: value["execution_input"].update(
                uri=f"s3://{BUCKET}/runs/run-test1/inputs/extra/execution-input.json"
            ),
            "deployed run",
        ),
        (
            lambda value: value["execution_input"].update(
                uri=f"s3://{BUCKET}/notruns/run-test1/inputs/execution-input.json"
            ),
            "deployed run",
        ),
        (
            lambda value: value["execution_input"].update(
                uri=f"s3://{BUCKET}/runs/run-test1/inputs/other.json"
            ),
            "deployed run",
        ),
        (lambda value: value["execution_input"].update(version_id="null"), "configuration"),
        (lambda value: value.update(extra=True), "configuration"),
    ],
)
def test_configuration_rejects_wrong_scope_or_shape(
    tmp_path: Path, edit: Any, match: str
) -> None:
    value, _raw, _ = fixture(tmp_path)
    edit(value)
    raw = canonical_bytes(value)
    with pytest.raises(ControlRejected, match=match):
        parse_config(raw, sha256(raw).hexdigest())


def test_configuration_and_object_digests_are_mandatory(tmp_path: Path) -> None:
    _value, raw, objects = fixture(tmp_path)
    with pytest.raises(ControlRejected, match="digest differs"):
        parse_config(raw, "0" * 64)
    with pytest.raises(ControlRejected, match="invalid handler"):
        parse_config(raw, "invalid")
    config = parse_config(raw, sha256(raw).hexdigest())
    config.execution_input["sha256"] = "0" * 64
    with pytest.raises(ControlRejected, match="bytes differ"):
        read_reference(objects, config.execution_input, maximum_bytes=131072)


@pytest.mark.parametrize(
    "event",
    [
        {},
        {"action": "wrong", "execution_arn": OWNER, "state": {}},
        {"action": "validate-execution", "execution_arn": "wrong", "state": {}},
        {"action": "validate-execution", "execution_arn": OWNER, "state": []},
    ],
)
def test_invocation_fails_closed_before_read(tmp_path: Path, event: Any) -> None:
    _value, raw, objects = fixture(tmp_path)
    config = parse_config(raw, sha256(raw).hexdigest())
    with pytest.raises(ControlRejected, match=r"invocation|owner|state"):
        validate_execution(event, config, objects)


def test_workflow_input_and_registration_state_cannot_be_substituted(tmp_path: Path) -> None:
    _value, raw, objects = fixture(tmp_path)
    config = parse_config(raw, sha256(raw).hexdigest())
    event = {
        "action": "validate-execution",
        "execution_arn": OWNER,
        "state": {"execution_input_sha256": "0" * 64},
    }
    with pytest.raises(ControlRejected, match="deployed execution"):
        validate_execution(event, config, objects)
    valid_event = {
        "action": "validate-execution",
        "execution_arn": OWNER,
        "state": {"execution_input_sha256": config.execution_input["sha256"]},
    }
    with pytest.raises(ControlRejected, match="job bucket"):
        validate_execution(valid_event, replace(config, operation_id="operation-other"), objects)
    state, _, _ = admitted(tmp_path / "registration")
    state["managed"] = {}
    with pytest.raises(ControlRejected, match="state shape"):
        register_run({"action": "register-run", "execution_arn": OWNER, "state": state}, object())
    state, _, _ = admitted(tmp_path / "control")
    state["control"]["schema_version"] = "wrong"
    with pytest.raises(ControlRejected, match="control state"):
        register_run({"action": "register-run", "execution_arn": OWNER, "state": state}, object())
    state, _, _ = admitted(tmp_path / "execution")
    state["control"].pop("execution")
    with pytest.raises(ControlRejected, match="execution is missing"):
        register_run({"action": "register-run", "execution_arn": OWNER, "state": state}, object())


def test_attempt_admission_requires_exact_registered_boundary(tmp_path: Path) -> None:
    authority = LocalAuthority(tmp_path / "authority.sqlite")
    state, _, _ = admitted(tmp_path / "registered")
    registered = register_run(
        {"action": "register-run", "execution_arn": OWNER, "state": state}, authority
    )
    replay = admit_attempt(
        {"action": "admit-attempt", "execution_arn": OWNER, "state": registered}, authority
    )
    assert replay["control"]["attempt"]["owner"] == OWNER
    fresh = dict(replay)
    fresh["control"] = dict(replay["control"])
    fresh["control"].pop("attempt")
    repeated = admit_attempt(
        {"action": "admit-attempt", "execution_arn": OWNER, "state": fresh}, authority
    )
    assert repeated["control"]["attempt"] == replay["control"]["attempt"]
    for field, value in (("namespace", "other-space"), ("predecessor", "0" * 64)):
        changed = dict(fresh)
        changed["control"] = dict(fresh["control"])
        changed["control"][field] = value
        with pytest.raises(ControlRejected, match=f"registered {field}"):
            admit_attempt(
                {"action": "admit-attempt", "execution_arn": OWNER, "state": changed}, authority
            )
    with pytest.raises(ControlRejected, match="must be admitted"):
        admit_attempt(
            {"action": "admit-attempt", "execution_arn": OWNER, "state": replay}, authority
        )


def test_reference_rejects_nonbytes_oversize_and_truncation(tmp_path: Path) -> None:
    value, _raw, objects = fixture(tmp_path)
    reference = value["execution_input"]

    class Chunks:
        def chunks(self, _uri: str, _version: str) -> Any:
            yield "not-bytes"

    with pytest.raises(ControlRejected, match="non-bytes"):
        read_reference(Chunks(), reference, maximum_bytes=131072)  # type: ignore[arg-type]
    with pytest.raises(ControlRejected, match="invalid object"):
        read_reference(objects, {}, maximum_bytes=131072)
    with pytest.raises(ControlRejected, match="byte bound"):
        read_reference(objects, dict(reference, size_bytes=0), maximum_bytes=131072)
    with pytest.raises(ControlRejected, match="byte bound"):
        read_reference(objects, reference, maximum_bytes=1)
    changed = dict(reference, size_bytes=1)
    with pytest.raises(ControlRejected, match="exceeds"):
        read_reference(objects, changed, maximum_bytes=131072)
    changed = dict(reference, size_bytes=reference["size_bytes"] + 1)
    with pytest.raises(ControlRejected, match="bytes differ"):
        read_reference(objects, changed, maximum_bytes=131072)
    with pytest.raises(ControlRejected, match="unversioned"):
        read_reference(objects, dict(reference, version_id="null"), maximum_bytes=131072)
