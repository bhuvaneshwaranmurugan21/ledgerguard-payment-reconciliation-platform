"""Athena AWS transport is strict, bounded, and retains immutable proof bytes."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from ledgerguard.stage3.canonical import canonical_bytes
from ledgerguard_control.athena import ENGINE, QueryExecution, fixed_queries
from ledgerguard_control.athena_aws import (
    AthenaReads,
    normalize_execution,
    observe_query,
    persist_query_proof,
    read_result_pages,
)
from ledgerguard_control.contracts import ControlRejected, strict_json
from ledgerguard_control.objects import LocalVersionedObjects

QUERY_ID = "12345678-abcd"


def execution_response() -> dict[str, Any]:
    query = fixed_queries("ledgerguard_p3_reconciliation", "run-test1", "attempt-1")[0]
    return {
        "QueryExecution": {
            "QueryExecutionId": QUERY_ID,
            "Query": query.sql,
            "WorkGroup": "ledgerguard-p3-operation-1-checks",
            "Status": {"State": "SUCCEEDED"},
            "ResultConfiguration": {
                "OutputLocation": "s3://ledgerguard-bucket/query-results/result.csv",
                "ExpectedBucketOwner": "857229544428",
                "EncryptionConfiguration": {"EncryptionOption": "SSE_S3"},
            },
            "EngineVersion": {"SelectedEngineVersion": ENGINE},
            "Statistics": {"DataScannedInBytes": 100, "EngineExecutionTimeInMillis": 20},
        }
    }


def result_page(token: str | None = None) -> dict[str, Any]:
    query = fixed_queries("ledgerguard_p3_reconciliation", "run-test1", "attempt-1")[0]
    response: dict[str, Any] = {
        "ResultSet": {
            "ResultSetMetadata": {"ColumnInfo": [{"Name": name} for name in query.columns]},
            "Rows": [{"Data": [{"VarCharValue": name} for name in query.columns]}],
        }
    }
    if token is not None:
        response["NextToken"] = token
    return response


class Athena:
    def __init__(self, execution: Any, pages: list[Any]):
        self.execution = execution
        self.pages = iter(pages)
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def get_query_execution(self, **request: Any) -> Any:
        self.calls.append(("get_query_execution", request))
        return self.execution

    def get_query_results(self, **request: Any) -> Any:
        self.calls.append(("get_query_results", request))
        return next(self.pages)


def test_protocol_methods_are_abstract_transport_boundaries() -> None:
    class MissingTransport(AthenaReads):
        pass

    transport = MissingTransport()
    with pytest.raises(NotImplementedError):
        transport.get_query_execution()
    with pytest.raises(NotImplementedError):
        transport.get_query_results()


def test_observe_normalizes_exact_execution_and_complete_pages() -> None:
    first = result_page("next-1")
    second = result_page()
    second["ResultSet"]["Rows"] = [{"Data": [{}, {"VarCharValue": "EXCEPTION"}]}]
    client = Athena(execution_response(), [first, second])
    execution, pages = observe_query(client, QUERY_ID)
    assert execution.scanned_bytes == 100 and execution.execution_ms == 20
    assert pages[0].request_token is None and pages[0].next_token == "next-1"
    assert pages[1].request_token == "next-1" and pages[1].rows == ((None, "EXCEPTION"),)
    assert client.calls == [
        ("get_query_execution", {"QueryExecutionId": QUERY_ID}),
        ("get_query_results", {"QueryExecutionId": QUERY_ID, "MaxResults": 1000}),
        (
            "get_query_results",
            {"QueryExecutionId": QUERY_ID, "MaxResults": 1000, "NextToken": "next-1"},
        ),
    ]


@pytest.mark.parametrize(
    "path,value",
    [
        (("QueryExecutionId",), "different-1"),
        (("Query",), None),
        (("WorkGroup",), 1),
        (("Status",), None),
        (("Status", "State"), ""),
        (("ResultConfiguration",), []),
        (("ResultConfiguration", "ExpectedBucketOwner"), None),
        (("ResultConfiguration", "EncryptionConfiguration"), None),
        (("EngineVersion",), None),
        (("Statistics", "DataScannedInBytes"), True),
        (("Statistics", "EngineExecutionTimeInMillis"), -1),
    ],
)
def test_execution_normalization_rejects_missing_wrong_or_inexact_fields(
    path: tuple[str, ...], value: Any
) -> None:
    response = execution_response()
    target = response["QueryExecution"]
    for name in path[:-1]:
        target = target[name]
    target[path[-1]] = value
    with pytest.raises(ControlRejected):
        normalize_execution(response, QUERY_ID)


@pytest.mark.parametrize("query_id", ["bad", 1])
def test_invalid_query_identity_rejected_before_transport(query_id: Any) -> None:
    with pytest.raises(ControlRejected, match="identity"):
        normalize_execution(execution_response(), query_id)
    client = Athena({}, [])
    with pytest.raises(ControlRejected, match="identity"):
        read_result_pages(client, query_id)
    assert client.calls == []


@pytest.mark.parametrize(
    "page",
    [
        {},
        {"ResultSet": None},
        {"ResultSet": {"ResultSetMetadata": None, "Rows": []}},
        {"ResultSet": {"ResultSetMetadata": {"ColumnInfo": []}, "Rows": []}},
        {
            "ResultSet": {
                "ResultSetMetadata": {"ColumnInfo": [{"Name": 1}]},
                "Rows": [],
            }
        },
        {
            "ResultSet": {
                "ResultSetMetadata": {"ColumnInfo": [{"Name": "x"}]},
                "Rows": {},
            }
        },
        {
            "ResultSet": {
                "ResultSetMetadata": {"ColumnInfo": [{"Name": "x"}]},
                "Rows": [{}],
            }
        },
        {
            "ResultSet": {
                "ResultSetMetadata": {"ColumnInfo": [{"Name": "x"}]},
                "Rows": [None],
            }
        },
        {
            "ResultSet": {
                "ResultSetMetadata": {"ColumnInfo": [{"Name": "x"}]},
                "Rows": [{"Data": [None]}],
            }
        },
        {
            "ResultSet": {
                "ResultSetMetadata": {"ColumnInfo": [{"Name": "x"}]},
                "Rows": [{"Data": [{"VarCharValue": 1}]}],
            }
        },
        {
            "ResultSet": {
                "ResultSetMetadata": {"ColumnInfo": [{"Name": "x"}]},
                "Rows": [{"Data": [{"Other": "x"}]}],
            }
        },
    ],
)
def test_result_normalization_rejects_incomplete_or_unknown_shapes(page: dict[str, Any]) -> None:
    with pytest.raises(ControlRejected):
        read_result_pages(Athena({}, [page]), QUERY_ID)


@pytest.mark.parametrize("token", ["", 1])
def test_invalid_pagination_token_rejected(token: Any) -> None:
    page = result_page()
    page["NextToken"] = token
    with pytest.raises(ControlRejected, match="pagination token"):
        read_result_pages(Athena({}, [page]), QUERY_ID)


def test_repeated_pagination_token_rejected() -> None:
    with pytest.raises(ControlRejected, match="pagination token"):
        read_result_pages(Athena({}, [result_page("same"), result_page("same")]), QUERY_ID)


def test_pagination_page_bound_is_enforced() -> None:
    class Endless(Athena):
        def __init__(self) -> None:
            super().__init__({}, [])
            self.count = 0

        def get_query_results(self, **request: Any) -> dict[str, Any]:
            self.count += 1
            return result_page(f"token-{self.count}")

    client = Endless()
    with pytest.raises(ControlRejected, match="exceeds bound"):
        read_result_pages(client, QUERY_ID)
    assert client.count == 128


def proof_values() -> tuple[Any, Any, dict[str, str], dict[str, Any], dict[str, Any]]:
    query = fixed_queries("ledgerguard_p3_reconciliation", "run-test1", "attempt-1")[0]
    execution = normalize_execution(execution_response(), QUERY_ID)
    identity = {
        "run_id": "run-test1",
        "attempt_id": "attempt-1",
        "control_record_identity": "control-1",
        "policy_sha256": "a" * 64,
        "manifest_sha256": "b" * 64,
        "source_bundle_sha256": "c" * 64,
    }
    verification = {
        "query_execution_id": QUERY_ID,
        "sql_sha256": query.sha256,
        "rows_sha256": "d" * 64,
        "row_count": 1,
        "scanned_bytes": 100,
        "execution_ms": 20,
    }
    result = {
        "uri": "s3://ledgerguard-bucket/query-results/result.csv",
        "version_id": "version-1",
        "sha256": "e" * 64,
        "size_bytes": 123,
    }
    return query, execution, identity, verification, result


def test_query_proof_is_canonical_content_addressed_and_idempotent(tmp_path: Path) -> None:
    query, execution, identity, verification, result = proof_values()
    objects = LocalVersionedObjects(tmp_path / "objects.sqlite")
    arguments = dict(
        bucket="ledgerguard-bucket",
        account_id="857229544428",
        family="transactions",
        identity=identity,
        query=query,
        execution=execution,
        verification=verification,
        result_reference=result,
        version_inventory_before_sha256="f" * 64,
        version_inventory_after_sha256="f" * 64,
    )
    reference = persist_query_proof(objects, **arguments)
    assert persist_query_proof(objects, **arguments) == reference
    raw = objects.read(reference["uri"], reference["version_id"])
    document = strict_json(raw)
    assert raw == canonical_bytes(document) + b"\n"
    assert document["query_execution_id"] == QUERY_ID
    assert document["family"] == "transactions"
    assert document["execution_ms"] == execution.execution_ms
    assert document["workgroup"] == execution.workgroup
    assert "/publications/query-proofs/run-test1/attempt-1/transactions/" in reference["uri"]


@pytest.mark.parametrize(
    "change",
    [
        {"family": "settlements"},
        {"bucket": "bad/bucket"},
        {"account_id": "bad"},
        {"identity": {"run_id": "run-test1"}},
        {"version_inventory_before_sha256": "bad"},
        {"verification": {"query_execution_id": QUERY_ID}},
    ],
)
def test_query_proof_rejects_unbound_inputs(tmp_path: Path, change: dict[str, Any]) -> None:
    query, execution, identity, verification, result = proof_values()
    arguments = dict(
        bucket="ledgerguard-bucket",
        account_id="857229544428",
        family="transactions",
        identity=identity,
        query=query,
        execution=execution,
        verification=verification,
        result_reference=result,
        version_inventory_before_sha256="f" * 64,
        version_inventory_after_sha256="f" * 64,
    )
    arguments.update(change)
    with pytest.raises(ControlRejected):
        persist_query_proof(LocalVersionedObjects(tmp_path / "objects.sqlite"), **arguments)


def test_query_proof_rejects_execution_or_result_contract_drift(tmp_path: Path) -> None:
    query, execution, identity, verification, result = proof_values()
    changed_execution = QueryExecution(**{**execution.__dict__, "status": "FAILED"})
    with pytest.raises(ControlRejected, match="verification binding"):
        persist_query_proof(
            LocalVersionedObjects(tmp_path / "first.sqlite"),
            bucket="ledgerguard-bucket",
            account_id="857229544428",
            family="transactions",
            identity=identity,
            query=query,
            execution=changed_execution,
            verification=verification,
            result_reference=result,
            version_inventory_before_sha256="f" * 64,
            version_inventory_after_sha256="f" * 64,
        )
    changed_result = deepcopy(result)
    changed_result["extra"] = "x"
    with pytest.raises(ControlRejected, match="query-proof"):
        persist_query_proof(
            LocalVersionedObjects(tmp_path / "second.sqlite"),
            bucket="ledgerguard-bucket",
            account_id="857229544428",
            family="transactions",
            identity=identity,
            query=query,
            execution=execution,
            verification=verification,
            result_reference=changed_result,
            version_inventory_before_sha256="f" * 64,
            version_inventory_after_sha256="f" * 64,
        )


@pytest.mark.parametrize(
    "field,value",
    [("sql_sha256", "0" * 64), ("scanned_bytes", 99), ("execution_ms", 19)],
)
def test_query_proof_rejects_exact_verification_drift(
    tmp_path: Path, field: str, value: Any
) -> None:
    query, execution, identity, verification, result = proof_values()
    verification[field] = value
    with pytest.raises(ControlRejected, match="verification binding"):
        persist_query_proof(
            LocalVersionedObjects(tmp_path / "objects.sqlite"),
            bucket="ledgerguard-bucket",
            account_id="857229544428",
            family="transactions",
            identity=identity,
            query=query,
            execution=execution,
            verification=verification,
            result_reference=result,
            version_inventory_before_sha256="f" * 64,
            version_inventory_after_sha256="f" * 64,
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("sql", "SELECT 1"),
        ("engine_version", "Athena engine version 2"),
        ("output_location", "s3://ledgerguard-bucket/query-results/other.csv"),
        ("expected_bucket_owner", "000000000000"),
        ("encryption_option", "SSE_KMS"),
    ],
)
def test_query_proof_rejects_execution_ownership_drift(
    tmp_path: Path, field: str, value: Any
) -> None:
    query, execution, identity, verification, result = proof_values()
    changed = QueryExecution(**{**execution.__dict__, field: value})
    with pytest.raises(ControlRejected, match="verification binding"):
        persist_query_proof(
            LocalVersionedObjects(tmp_path / "objects.sqlite"),
            bucket="ledgerguard-bucket",
            account_id="857229544428",
            family="transactions",
            identity=identity,
            query=query,
            execution=changed,
            verification=verification,
            result_reference=result,
            version_inventory_before_sha256="f" * 64,
            version_inventory_after_sha256="f" * 64,
        )
