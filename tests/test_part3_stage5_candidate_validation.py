"""The candidate Lambda boundary uses real Parquet and durable local transports."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ledgerguard.stage3.canonical import canonical_bytes
from ledgerguard_control import validator
from ledgerguard_control.authority import LocalAuthority
from ledgerguard_control.candidate_validation import (
    _materialize,
    _parquet_members,
    validate_candidate,
)
from ledgerguard_control.candidates import PhysicalCandidate
from ledgerguard_control.contracts import ControlRejected, job_arguments, strict_json
from ledgerguard_control.execution import (
    admit_attempt,
    parse_config,
    register_run,
    validate_execution,
)
from ledgerguard_control.objects import LocalVersionedObjects
from tests.test_part3_stage5_execution import OWNER, fixture
from tests.test_part3_stage5_financial_rows import bank, settlement, transaction

RUN = "jr_" + "d" * 64
PART = "part-00000-12345678-1234-1234-1234-123456789012-c000"


class Glue:
    def __init__(self, request: dict[str, Any]):
        started = datetime(2026, 9, 12, 8, 0, tzinfo=UTC)
        self.calls: list[dict[str, Any]] = []
        self.run = {
            "Id": RUN,
            "JobName": request["JobName"],
            "JobRunState": "SUCCEEDED",
            "Attempt": 0,
            "Arguments": request["Arguments"],
            "StartedOn": started,
            "CompletedOn": started + timedelta(seconds=61),
            "ExecutionTime": 60,
            "DPUSeconds": 120.5,
            "GlueVersion": "5.1",
            "WorkerType": "G.1X",
            "NumberOfWorkers": 2,
            "Timeout": 15,
            "ExecutionClass": "STANDARD",
            "JobRunQueuingEnabled": False,
        }

    def get_job_run(self, **request: Any) -> dict[str, Any]:
        self.calls.append(request)
        return {"JobRun": self.run}

    def get_job_runs(self, **_request: Any) -> dict[str, Any]:
        raise AssertionError("candidate validation never performs ambiguous-start recovery")


def _reference(objects: LocalVersionedObjects, uri: str, raw: bytes) -> dict[str, Any]:
    version = objects.put(uri, raw)
    return {
        "uri": uri,
        "version_id": version,
        "sha256": sha256(raw).hexdigest(),
        "size_bytes": len(raw),
    }


def _parquet(tmp_path: Path, rows: list[dict[str, Any]]) -> bytes:
    path = tmp_path / (str(len(list(tmp_path.glob("*.parquet")))) + ".parquet")
    pq.write_table(pa.Table.from_pylist(rows), path, row_group_size=1)
    return path.read_bytes()


def candidate_fixture(
    tmp_path: Path,
) -> tuple[dict[str, Any], Any, LocalVersionedObjects, Glue]:
    value, _raw, objects = fixture(tmp_path / "base")
    original = strict_json(
        objects.read(value["execution_input"]["uri"], value["execution_input"]["version_id"])
    )
    rows = [
        ("transactions", transaction(amount=2**53 + 19)),
        ("settlements", settlement()),
        ("bank-allocations", bank()),
    ]
    expected = b"".join(
        canonical_bytes({"family": family, "row": row}) + b"\n" for family, row in rows
    )
    original["expected_results"] = _reference(
        objects, original["expected_results"]["uri"], expected
    )
    execution_raw = canonical_bytes(original)
    value["execution_input"] = _reference(
        objects, value["execution_input"]["uri"], execution_raw
    )
    config_raw = canonical_bytes(value)
    config = parse_config(config_raw, sha256(config_raw).hexdigest())
    state = validate_execution(
        {
            "action": "validate-execution",
            "execution_arn": OWNER,
            "state": {"execution_input_sha256": config.execution_input["sha256"]},
        },
        config,
        objects,
    )
    authority = LocalAuthority(tmp_path / "authority.sqlite")
    state = register_run(
        {"action": "register-run", "execution_arn": OWNER, "state": state}, authority
    )
    state = admit_attempt(
        {"action": "admit-attempt", "execution_arn": OWNER, "state": state}, authority
    )
    arguments = job_arguments(original["job"])
    files = {
        f"{family}/{PART}.snappy.parquet": _parquet(tmp_path, [row])
        for family, row in rows
    }
    manifest = {
        "schema_version": "2.0",
        "run_id": arguments.run_id,
        "attempt_id": arguments.attempt_id,
        "control_record_identity": arguments.control_record_identity,
        "glue_job_run_id": RUN,
        "transaction_count": 1,
        "settlement_count": 1,
        "allocation_count": 1,
        "logical_sha256": "a" * 64,
        "physical_files": [
            {"path": name, "size_bytes": len(raw), "sha256": sha256(raw).hexdigest()}
            for name, raw in sorted(files.items())
        ],
        "authoritative_proof": False,
    }
    manifest_raw = canonical_bytes(manifest) + b"\n"
    files[f"candidate-manifest/{PART}.txt"] = manifest_raw
    files[f"completion/{PART}.txt"] = (
        canonical_bytes(
            {
                "schema_version": "2.0",
                "glue_job_run_id": RUN,
                "candidate_manifest_file_sha256": sha256(manifest_raw).hexdigest(),
                "logical_sha256": "a" * 64,
                "authoritative_proof": False,
                "state": "COMPLETE_NON_AUTHORITATIVE_CANDIDATE",
            }
        )
        + b"\n"
    )
    for family in (
        "transactions",
        "settlements",
        "bank-allocations",
        "candidate-manifest",
        "completion",
    ):
        files[f"{family}/_SUCCESS"] = b""
    for name, raw in files.items():
        objects.put(f"{arguments.candidate_output_prefix}/{name}", raw)
    state["managed"]["glue"] = {"JobRunId": RUN}
    return state, config, objects, Glue(state["control"]["glue_start"])


def test_candidate_transition_binds_glue_parquet_versions_and_retained_receipt(
    tmp_path: Path,
) -> None:
    state, config, objects, glue = candidate_fixture(tmp_path)
    before = deepcopy(state)
    result = validate_candidate(
        {"action": "validate-candidate", "execution_arn": OWNER, "state": state},
        config,
        objects,
        glue,
        objects,
        tmp_path,
    )
    reference = result["control"]["validation_receipt"]
    assert "/publications/validation-receipts/run-test1/attempt-1/receipt/" in reference["uri"]
    receipt = strict_json(objects.read(reference["uri"], reference["version_id"]))
    assert receipt["glue_job_run_id"] == RUN
    assert receipt["glue_dpu_seconds"] == "120.5"
    assert receipt["expected_results_sha256"] == state["control"]["execution"][
        "expected_results"
    ]["sha256"]
    inventory_ref = receipt["physical_inventory"]
    inventory = strict_json(objects.read(inventory_ref["uri"], inventory_ref["version_id"]))
    assert inventory["financial_comparison"]["counts"] == {
        "transactions": 1,
        "settlements": 1,
        "bank-allocations": 1,
    }
    assert len(inventory["objects"]) == 3
    assert glue.calls == [
        {
            "JobName": state["control"]["glue_start"]["JobName"],
            "RunId": RUN,
            "PredecessorsIncluded": False,
        }
    ]
    replay = validate_candidate(
        {"action": "validate-candidate", "execution_arn": OWNER, "state": before},
        config,
        objects,
        Glue(before["control"]["glue_start"]),
        objects,
        tmp_path,
    )
    assert replay["control"]["validation_receipt"] == reference


@pytest.mark.parametrize(
    "change,match",
    [
        (lambda state: state.update(extra=True), "state shape"),
        (lambda state: state["managed"].update(extra=True), "managed candidate"),
        (lambda state: state["managed"].update(athena=[]), "managed Glue"),
        (lambda state: state["managed"].update(glue={"JobRunId": RUN, "extra": 1}), "managed Glue"),
        (lambda state: state["managed"].update(glue={"JobRunId": 1}), "run identity"),
        (lambda state: state["control"].update(extra=True), "control state shape"),
        (lambda state: state["control"].update(attempt={}), "attempt shape"),
        (
            lambda state: state["control"]["queries"]["transactions"].update(sql="changed"),
            "substituted",
        ),
        (lambda state: state["control"].update(namespace="namespace-2"), "registration"),
        (lambda state: state["control"]["attempt"].update(owner=OWNER + "x"), "attempt identity"),
        (lambda state: state["control"]["attempt"].update(fence=True), "attempt fence"),
    ],
)
def test_candidate_state_rejects_substitution_before_glue(
    tmp_path: Path, change: Any, match: str
) -> None:
    state, config, objects, glue = candidate_fixture(tmp_path)
    change(state)
    with pytest.raises(ControlRejected, match=match):
        validate_candidate(
            {"action": "validate-candidate", "execution_arn": OWNER, "state": state},
            config,
            objects,
            glue,
            objects,
            tmp_path,
        )
    assert glue.calls == []


def test_candidate_rejects_terminal_or_financial_substitution(tmp_path: Path) -> None:
    state, config, objects, glue = candidate_fixture(tmp_path / "glue")
    glue.run["Id"] = "jr_" + "e" * 64
    with pytest.raises(ControlRejected, match="identity differs"):
        validate_candidate(
            {"action": "validate-candidate", "execution_arn": OWNER, "state": state},
            config,
            objects,
            glue,
            objects,
            tmp_path / "glue-work",
        )

    state, config, objects, glue = candidate_fixture(tmp_path / "financial")
    prefix = state["control"]["execution"]["job"]["candidate_output_prefix"]
    parquet = next(v for v in objects.versions(prefix) if "/transactions/part-" in v.uri)
    objects.put(parquet.uri, b"substituted")
    with pytest.raises(ControlRejected, match="overwrite"):
        validate_candidate(
            {"action": "validate-candidate", "execution_arn": OWNER, "state": state},
            config,
            objects,
            glue,
            objects,
            tmp_path / "financial-work",
        )


def test_candidate_versions_cannot_change_during_financial_comparison(tmp_path: Path) -> None:
    state, config, objects, glue = candidate_fixture(tmp_path)
    expected_uri = state["control"]["execution"]["expected_results"]["uri"]
    candidate_prefix = state["control"]["execution"]["job"]["candidate_output_prefix"]

    class RacingObjects(LocalVersionedObjects):
        changed = False

        def chunks(self, uri: str, version_id: str) -> Any:
            yield from super().chunks(uri, version_id)
            if uri == expected_uri and not self.changed:
                self.changed = True
                self.put(candidate_prefix + "/late-object", b"changed")

    racing = RacingObjects(objects.path)
    with pytest.raises(ControlRejected, match="changed during validation"):
        validate_candidate(
            {"action": "validate-candidate", "execution_arn": OWNER, "state": state},
            config,
            racing,
            glue,
            objects,
            tmp_path,
        )


def test_candidate_handler_uses_only_candidate_dependencies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state, config, objects, glue = candidate_fixture(tmp_path)
    monkeypatch.setattr(validator, "load_config", lambda: config)
    monkeypatch.setattr(validator, "_candidate_dependencies", lambda actual: (objects, glue))
    result = validator.handler(
        {"action": "validate-candidate", "execution_arn": OWNER, "state": state}, None
    )
    assert result["control"]["validation_receipt"]["version_id"]


def test_parquet_member_address_is_confined_to_candidate_prefix(tmp_path: Path) -> None:
    reference = {
        "uri": "s3://bucket-one/outside/member.parquet",
        "version_id": "v1",
        "sha256": "0" * 64,
        "size_bytes": 1,
    }
    candidate = PhysicalCandidate({}, {}, {}, (reference,), (), "0" * 64)
    with pytest.raises(ControlRejected, match="address"):
        _parquet_members(object(), candidate, tmp_path)  # type: ignore[arg-type]


@pytest.mark.parametrize("fault", ["shape", "null", "zero", "nonbytes", "long", "short", "digest"])
def test_materialization_rejects_unbounded_or_changed_streams(tmp_path: Path, fault: str) -> None:
    raw = b"expected"
    reference: dict[str, Any] = {
        "uri": "s3://bucket-one/path/data",
        "version_id": "v1",
        "sha256": sha256(raw).hexdigest(),
        "size_bytes": len(raw),
    }

    class Objects:
        def chunks(self, _uri: str, _version: str) -> Any:
            if fault == "nonbytes":
                yield "wrong"
            elif fault == "long":
                yield raw + b"x"
            elif fault == "short":
                yield raw[:-1]
            elif fault == "digest":
                yield b"x" * len(raw)
            else:
                yield raw

    if fault == "shape":
        reference = {}
    elif fault == "null":
        reference["version_id"] = "null"
    elif fault == "zero":
        reference["size_bytes"] = 0
    with pytest.raises(ControlRejected):
        _materialize(Objects(), reference, tmp_path / "value", 1024)  # type: ignore[arg-type]
