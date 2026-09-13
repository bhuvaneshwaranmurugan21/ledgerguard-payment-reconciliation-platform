"""Ordered query handlers bind real expected rows, AWS reads and immutable proofs."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Any

import pytest

from ledgerguard.stage3.canonical import canonical_bytes
from ledgerguard_control import validator
from ledgerguard_control.athena import ENGINE, fixed_queries, summarize_expected_rows
from ledgerguard_control.candidate_validation import validate_candidate
from ledgerguard_control.contracts import ControlRejected, strict_json
from ledgerguard_control.objects import LocalVersionedObjects, ObjectVersion
from ledgerguard_control.query_validation import (
    FAMILIES,
    _document,
    _query,
    _result_reference,
    validate_query,
)
from tests.test_part3_stage5_candidate_validation import candidate_fixture
from tests.test_part3_stage5_execution import OWNER


class Athena:
    def __init__(
        self,
        query_id: str,
        query: Any,
        workgroup: str,
        output: str,
        expected: tuple[dict[str, str], ...],
    ):
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.execution = {
            "QueryExecution": {
                "QueryExecutionId": query_id,
                "Query": query.sql,
                "WorkGroup": workgroup,
                "Status": {"State": "SUCCEEDED"},
                "ResultConfiguration": {
                    "OutputLocation": output,
                    "ExpectedBucketOwner": "857229544428",
                    "EncryptionConfiguration": {"EncryptionOption": "SSE_S3"},
                },
                "EngineVersion": {"SelectedEngineVersion": ENGINE},
                "Statistics": {
                    "DataScannedInBytes": 100,
                    "EngineExecutionTimeInMillis": 20,
                },
            }
        }
        rows = [tuple(query.columns)] + [
            tuple(row[name] for name in query.columns) for row in expected
        ]
        self.page = {
            "ResultSet": {
                "ResultSetMetadata": {
                    "ColumnInfo": [{"Name": name} for name in query.columns]
                },
                "Rows": [
                    {"Data": [{"VarCharValue": value} for value in row]} for row in rows
                ],
            }
        }

    def get_query_execution(self, **request: Any) -> dict[str, Any]:
        self.calls.append(("get_query_execution", request))
        return self.execution

    def get_query_results(self, **request: Any) -> dict[str, Any]:
        self.calls.append(("get_query_results", request))
        return self.page


def candidate_state(tmp_path: Path) -> tuple[dict[str, Any], Any, Any]:
    state, config, objects, glue = candidate_fixture(tmp_path)
    result = validate_candidate(
        {"action": "validate-candidate", "execution_arn": OWNER, "state": state},
        config,
        objects,
        glue,
        objects,
        tmp_path,
    )
    return result, config, objects


def query_transport(
    tmp_path: Path,
    state: dict[str, Any],
    objects: Any,
    family: str,
    ordinal: int,
) -> Athena:
    control = state["control"]
    arguments = control["execution"]["job"]
    query = next(
        item
        for item in fixed_queries(
            control["athena_database"], arguments["run_id"], arguments["attempt_id"]
        )
        if item.family == family
    )
    expected_path = tmp_path / f"expected-{family}.jsonl"
    reference = control["execution"]["expected_results"]
    expected_path.write_bytes(objects.read(reference["uri"], reference["version_id"]))
    expected = summarize_expected_rows(expected_path, reference["sha256"], query)
    query_id = f"12345678-0000-0000-0000-{ordinal:012d}"
    output = control["queries"][family]["output_location"] + query_id + ".csv"
    objects.put(output, (family + "\n").encode())
    state["managed"]["athena"][family] = {"QueryExecutionId": query_id}
    return Athena(query_id, query, control["athena_workgroup"], output, expected)


def replace_document(
    objects: LocalVersionedObjects,
    reference: dict[str, Any],
    change: Any,
    suffix: str,
) -> dict[str, Any]:
    value = strict_json(objects.read(reference["uri"], reference["version_id"]))
    change(value)
    raw = canonical_bytes(value) + b"\n"
    uri = f"s3://ledgerguard-bucket/publications/test/{suffix}.json"
    version = objects.put(uri, raw)
    return {
        "uri": uri,
        "version_id": version,
        "sha256": sha256(raw).hexdigest(),
        "size_bytes": len(raw),
    }


def test_all_three_queries_are_verified_in_order_and_retained(tmp_path: Path) -> None:
    state, config, objects = candidate_state(tmp_path)
    for ordinal, family in enumerate(FAMILIES, start=1):
        athena = query_transport(tmp_path, state, objects, family, ordinal)
        state = validate_query(
            {
                "action": f"validate-{family}-query",
                "execution_arn": OWNER,
                "state": state,
            },
            config,
            objects,
            athena,
            objects,
            tmp_path,
        )
        reference = state["control"]["query_proofs"][family]
        proof = strict_json(objects.read(reference["uri"], reference["version_id"]))
        assert proof["family"] == family
        assert proof["query_execution_id"] == state["managed"]["athena"][family][
            "QueryExecutionId"
        ]
        receipt_reference = state["control"]["validation_receipt"]
        receipt = strict_json(
            objects.read(receipt_reference["uri"], receipt_reference["version_id"])
        )
        assert proof["version_inventory_before_sha256"] == receipt[
            "version_inventory_sha256"
        ]
        assert proof["version_inventory_after_sha256"] == receipt[
            "version_inventory_sha256"
        ]


def test_query_rejects_state_substitution_before_athena_reads(tmp_path: Path) -> None:
    state, config, objects = candidate_state(tmp_path)
    athena = query_transport(tmp_path, state, objects, "transactions", 1)
    state["control"]["athena_workgroup"] = "ledgerguard-p3-other-checks"
    with pytest.raises(ControlRejected, match="substituted"):
        validate_query(
            {"action": "validate-transactions-query", "execution_arn": OWNER, "state": state},
            config,
            objects,
            athena,
            objects,
            tmp_path,
        )
    assert athena.calls == []


def test_query_rejects_candidate_or_result_version_history(tmp_path: Path) -> None:
    state, config, objects = candidate_state(tmp_path / "candidate")
    athena = query_transport(tmp_path, state, objects, "transactions", 1)
    prefix = state["control"]["execution"]["job"]["candidate_output_prefix"]
    candidate = next(value for value in objects.versions(prefix) if value.size_bytes)
    objects.put(candidate.uri, objects.read(candidate.uri, candidate.version_id))
    with pytest.raises(ControlRejected, match="changed before"):
        validate_query(
            {"action": "validate-transactions-query", "execution_arn": OWNER, "state": state},
            config,
            objects,
            athena,
            objects,
            tmp_path,
        )
    assert athena.calls == []

    state, config, objects = candidate_state(tmp_path / "result")
    athena = query_transport(tmp_path, state, objects, "transactions", 1)
    output = athena.execution["QueryExecution"]["ResultConfiguration"]["OutputLocation"]
    objects.put(output, b"overwritten\n")
    with pytest.raises(ControlRejected, match="result object history"):
        validate_query(
            {"action": "validate-transactions-query", "execution_arn": OWNER, "state": state},
            config,
            objects,
            athena,
            objects,
            tmp_path,
        )


def test_query_rejects_wrong_order_duplicate_ids_and_wrong_rows(tmp_path: Path) -> None:
    state, config, objects = candidate_state(tmp_path / "order")
    athena = query_transport(tmp_path, state, objects, "settlements", 2)
    with pytest.raises(ControlRejected, match=r"substituted|query order"):
        validate_query(
            {"action": "validate-settlements-query", "execution_arn": OWNER, "state": state},
            config,
            objects,
            athena,
            objects,
            tmp_path,
        )

    state, config, objects = candidate_state(tmp_path / "rows")
    athena = query_transport(tmp_path, state, objects, "transactions", 1)
    athena.page["ResultSet"]["Rows"][-1]["Data"][-1]["VarCharValue"] = "999"
    with pytest.raises(ControlRejected, match=r"rows disagree|formula|delta|amount"):
        validate_query(
            {"action": "validate-transactions-query", "execution_arn": OWNER, "state": state},
            config,
            objects,
            athena,
            objects,
            tmp_path,
        )

    state, config, objects = candidate_state(tmp_path / "duplicate")
    first = query_transport(tmp_path, state, objects, "transactions", 1)
    state = validate_query(
        {"action": "validate-transactions-query", "execution_arn": OWNER, "state": state},
        config,
        objects,
        first,
        objects,
        tmp_path,
    )
    second = query_transport(tmp_path, state, objects, "settlements", 1)
    with pytest.raises(ControlRejected, match="not unique"):
        validate_query(
            {"action": "validate-settlements-query", "execution_arn": OWNER, "state": state},
            config,
            objects,
            second,
            objects,
            tmp_path,
        )


def test_query_handler_uses_only_query_dependencies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state, config, objects = candidate_state(tmp_path)
    athena = query_transport(tmp_path, state, objects, "transactions", 1)
    monkeypatch.setattr(validator, "load_config", lambda: config)
    monkeypatch.setattr(
        validator,
        "_query_dependencies",
        lambda actual: (objects, athena) if actual == config else None,
    )
    result = validator.handler(
        {"action": "validate-transactions-query", "execution_arn": OWNER, "state": state},
        None,
    )
    assert result["control"]["query_proofs"]["transactions"]["version_id"]


def test_document_and_fixed_query_reject_noncanonical_or_changed_state(tmp_path: Path) -> None:
    state, _config, objects = candidate_state(tmp_path)
    reference = state["control"]["validation_receipt"]
    raw = objects.read(reference["uri"], reference["version_id"]).rstrip(b"\n")
    changed = {
        "uri": "s3://ledgerguard-bucket/publications/test/noncanonical.json",
        "version_id": objects.put(
            "s3://ledgerguard-bucket/publications/test/noncanonical.json", raw
        ),
        "sha256": sha256(raw).hexdigest(),
        "size_bytes": len(raw),
    }
    with pytest.raises(ControlRejected, match="not canonical"):
        _document(objects, changed, "validation-receipt")
    with pytest.raises(ControlRejected, match="query is missing"):
        _query(state["control"], "wrong")
    state["control"]["queries"]["transactions"]["sql_sha256"] = "0" * 64
    with pytest.raises(ControlRejected, match="query state"):
        _query(state["control"], "transactions")


def test_result_reference_rejects_address_and_stream_faults() -> None:
    prefix = "s3://ledgerguard-bucket/query-results/run/attempt/transactions/"
    query_id = "12345678-abcd"
    uri = prefix + query_id + ".csv"

    class ResultObjects:
        def __init__(self, fault: str):
            self.fault = fault

        def versions(self, _prefix: str) -> tuple[ObjectVersion, ...]:
            size = 4
            return (ObjectVersion(uri, "v1", True, False, size),)

        def chunks(self, _uri: str, _version: str) -> Any:
            if self.fault == "nonbytes":
                yield "bad"
            elif self.fault == "long":
                yield b"12345"
            elif self.fault == "short":
                yield b"123"
            else:
                yield b"1234"

    with pytest.raises(ControlRejected, match="address"):
        _result_reference(ResultObjects("ok"), prefix[:-1], query_id, uri)
    with pytest.raises(ControlRejected, match="address"):
        _result_reference(ResultObjects("ok"), prefix, query_id, uri + "x")
    for fault, match in (
        ("nonbytes", "non-bytes"),
        ("long", "exceeds"),
        ("short", "truncated"),
    ):
        with pytest.raises(ControlRejected, match=match):
            _result_reference(ResultObjects(fault), prefix, query_id, uri)


@pytest.mark.parametrize(
    "change,match",
    [
        (lambda state: state.update(extra=True), "state shape"),
        (lambda state: state.update(control=[]), "state differs"),
        (lambda state: state["control"].update(namespace="namespace-2"), "registration"),
        (lambda state: state["managed"].update(glue={"JobRunId": "wrong"}), "Glue state"),
        (
            lambda state: state["managed"]["athena"].update(
                extra={"QueryExecutionId": "x"}
            ),
            "query order",
        ),
        (lambda state: state["managed"]["athena"].update(transactions={}), "query result"),
        (lambda state: state["control"].update(query_proofs={}), "unexpected retained"),
    ],
)
def test_query_state_boundaries_fail_before_reads(
    tmp_path: Path, change: Any, match: str
) -> None:
    state, config, objects = candidate_state(tmp_path)
    athena = query_transport(tmp_path, state, objects, "transactions", 1)
    change(state)
    with pytest.raises(ControlRejected, match=match):
        validate_query(
            {"action": "validate-transactions-query", "execution_arn": OWNER, "state": state},
            config,
            objects,
            athena,
            objects,
            tmp_path,
        )
    assert athena.calls == []


def test_query_receipt_and_inventory_identity_are_reverified(tmp_path: Path) -> None:
    state, config, objects = candidate_state(tmp_path / "receipt")
    athena = query_transport(tmp_path, state, objects, "transactions", 1)
    state["control"]["validation_receipt"] = replace_document(
        objects,
        state["control"]["validation_receipt"],
        lambda value: value.update(fence=value["fence"] + 1),
        "receipt-fence",
    )
    with pytest.raises(ControlRejected, match="receipt identity"):
        validate_query(
            {"action": "validate-transactions-query", "execution_arn": OWNER, "state": state},
            config,
            objects,
            athena,
            objects,
            tmp_path,
        )

    state, config, objects = candidate_state(tmp_path / "inventory")
    athena = query_transport(tmp_path, state, objects, "transactions", 1)
    receipt_ref = state["control"]["validation_receipt"]
    receipt = strict_json(objects.read(receipt_ref["uri"], receipt_ref["version_id"]))
    receipt["physical_inventory"] = replace_document(
        objects,
        receipt["physical_inventory"],
        lambda value: value.update(run_id="run-other1"),
        "wrong-inventory",
    )
    raw = canonical_bytes(receipt) + b"\n"
    uri = "s3://ledgerguard-bucket/publications/test/receipt-inventory.json"
    state["control"]["validation_receipt"] = {
        "uri": uri,
        "version_id": objects.put(uri, raw),
        "sha256": sha256(raw).hexdigest(),
        "size_bytes": len(raw),
    }
    with pytest.raises(ControlRejected, match="physical inventory identity"):
        validate_query(
            {"action": "validate-transactions-query", "execution_arn": OWNER, "state": state},
            config,
            objects,
            athena,
            objects,
            tmp_path,
        )


def test_retained_query_proof_order_and_identity_are_reverified(tmp_path: Path) -> None:
    state, config, objects = candidate_state(tmp_path)
    first = query_transport(tmp_path, state, objects, "transactions", 1)
    state = validate_query(
        {"action": "validate-transactions-query", "execution_arn": OWNER, "state": state},
        config,
        objects,
        first,
        objects,
        tmp_path,
    )
    second = query_transport(tmp_path, state, objects, "settlements", 2)
    missing = deepcopy_state(state)
    missing["control"]["query_proofs"] = {}
    with pytest.raises(ControlRejected, match="proof order"):
        validate_query(
            {"action": "validate-settlements-query", "execution_arn": OWNER, "state": missing},
            config,
            objects,
            second,
            objects,
            tmp_path,
        )
    changed = deepcopy_state(state)
    proof_ref = changed["control"]["query_proofs"]["transactions"]
    changed["control"]["query_proofs"]["transactions"] = replace_document(
        objects,
        proof_ref,
        lambda value: value.update(query_execution_id="87654321-abcd"),
        "wrong-proof",
    )
    with pytest.raises(ControlRejected, match="proof identity"):
        validate_query(
            {"action": "validate-settlements-query", "execution_arn": OWNER, "state": changed},
            config,
            objects,
            second,
            objects,
            tmp_path,
        )


def deepcopy_state(state: dict[str, Any]) -> dict[str, Any]:
    return strict_json(canonical_bytes(state))


def test_query_action_shape_and_post_check_race_are_rejected(tmp_path: Path) -> None:
    state, config, objects = candidate_state(tmp_path)
    athena = query_transport(tmp_path, state, objects, "transactions", 1)
    with pytest.raises(ControlRejected, match="unsupported"):
        validate_query(None, config, objects, athena, objects, tmp_path)
    with pytest.raises(ControlRejected, match="unsupported"):
        validate_query({"action": "wrong"}, config, objects, athena, objects, tmp_path)

    candidate_prefix = state["control"]["execution"]["job"]["candidate_output_prefix"]

    class RacingObjects(LocalVersionedObjects):
        candidate_calls = 0

        def versions(self, prefix: str) -> tuple[ObjectVersion, ...]:
            if prefix == candidate_prefix:
                self.candidate_calls += 1
                if self.candidate_calls == 3:
                    self.put(candidate_prefix + "/late-after-check", b"changed")
            return super().versions(prefix)

    racing = RacingObjects(objects.path)
    with pytest.raises(ControlRejected, match="changed during"):
        validate_query(
            {"action": "validate-transactions-query", "execution_arn": OWNER, "state": state},
            config,
            racing,
            athena,
            objects,
            tmp_path,
        )
