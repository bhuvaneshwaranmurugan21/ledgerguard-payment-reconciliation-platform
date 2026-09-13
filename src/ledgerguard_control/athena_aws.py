"""Strict Athena response normalization and immutable proof publication.

This adapter only observes an already-started query.  Starting queries remains an
explicit Step Functions task, while this module converts the complete AWS response
chain into the closed types consumed by :mod:`ledgerguard_control.athena`.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from hashlib import sha256
from typing import Any, Protocol

from ledgerguard.stage3.canonical import canonical_bytes
from ledgerguard.stage3.paths import parse_s3_uri

from .athena import ENGINE, MAX_RESULT_PAGES, FixedQuery, QueryExecution, ResultPage
from .contracts import ControlRejected, validate
from .publication import ImmutableObjects

_QUERY_ID = re.compile(r"[0-9a-f-]{8,128}")
_DIGEST = re.compile(r"[0-9a-f]{64}")


class AthenaReads(Protocol):
    def get_query_execution(self, **request: Any) -> Mapping[str, Any]:
        raise NotImplementedError

    def get_query_results(self, **request: Any) -> Mapping[str, Any]:
        raise NotImplementedError


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ControlRejected(f"invalid Athena {label}")
    return value


def _text(value: Any, label: str) -> str:
    if type(value) is not str or not value:
        raise ControlRejected(f"invalid Athena {label}")
    return value


def _uint(value: Any, label: str) -> int:
    if type(value) is not int or not 0 <= value <= 2**63 - 1:
        raise ControlRejected(f"invalid Athena {label}")
    return value


def normalize_execution(response: Mapping[str, Any], query_execution_id: str) -> QueryExecution:
    """Normalize one exact terminal-query observation without permissive defaults."""
    if type(query_execution_id) is not str or _QUERY_ID.fullmatch(query_execution_id) is None:
        raise ControlRejected("invalid Athena query execution identity")
    outer = _mapping(response, "get-query-execution response")
    raw = _mapping(outer.get("QueryExecution"), "query execution")
    if raw.get("QueryExecutionId") != query_execution_id:
        raise ControlRejected("Athena query execution identity differs")
    status = _mapping(raw.get("Status"), "status")
    result = _mapping(raw.get("ResultConfiguration"), "result configuration")
    encryption = _mapping(result.get("EncryptionConfiguration"), "encryption")
    engine = _mapping(raw.get("EngineVersion"), "engine version")
    statistics = _mapping(raw.get("Statistics"), "statistics")
    return QueryExecution(
        query_execution_id=query_execution_id,
        sql=_text(raw.get("Query"), "query text"),
        workgroup=_text(raw.get("WorkGroup"), "workgroup"),
        engine_version=_text(engine.get("SelectedEngineVersion"), "engine version"),
        output_location=_text(result.get("OutputLocation"), "output location"),
        expected_bucket_owner=_text(result.get("ExpectedBucketOwner"), "bucket owner"),
        encryption_option=_text(encryption.get("EncryptionOption"), "encryption option"),
        status=_text(status.get("State"), "status state"),
        scanned_bytes=_uint(statistics.get("DataScannedInBytes"), "scanned bytes"),
        execution_ms=_uint(statistics.get("EngineExecutionTimeInMillis"), "execution time"),
    )


def _rows(value: Any) -> tuple[tuple[str | None, ...], ...]:
    if type(value) is not list:
        raise ControlRejected("invalid Athena result rows")
    result = []
    for row in value:
        cells = _mapping(row, "result row").get("Data")
        if type(cells) is not list:
            raise ControlRejected("invalid Athena result row data")
        values = []
        for cell in cells:
            item = _mapping(cell, "result cell")
            if set(item) - {"VarCharValue"}:
                raise ControlRejected("unknown Athena result cell field")
            raw = item.get("VarCharValue")
            if raw is not None and type(raw) is not str:
                raise ControlRejected("invalid Athena result cell value")
            values.append(raw)
        result.append(tuple(values))
    return tuple(result)


def read_result_pages(client: AthenaReads, query_execution_id: str) -> tuple[ResultPage, ...]:
    """Consume the entire bounded token chain for one exact query execution."""
    if type(query_execution_id) is not str or _QUERY_ID.fullmatch(query_execution_id) is None:
        raise ControlRejected("invalid Athena query execution identity")
    request_token: str | None = None
    seen: set[str] = set()
    pages = []
    for _ in range(MAX_RESULT_PAGES):
        request: dict[str, Any] = {"QueryExecutionId": query_execution_id, "MaxResults": 1000}
        if request_token is not None:
            request["NextToken"] = request_token
        response = _mapping(client.get_query_results(**request), "get-query-results response")
        result_set = _mapping(response.get("ResultSet"), "result set")
        metadata = _mapping(result_set.get("ResultSetMetadata"), "result metadata")
        columns = metadata.get("ColumnInfo")
        if type(columns) is not list or not columns:
            raise ControlRejected("invalid Athena result columns")
        for column in columns:
            if type(_mapping(column, "result column").get("Name")) is not str:
                raise ControlRejected("invalid Athena result column name")
        next_token = response.get("NextToken")
        if next_token is not None:
            if type(next_token) is not str or not next_token or next_token in seen:
                raise ControlRejected("invalid Athena result pagination token")
            seen.add(next_token)
        pages.append(ResultPage(request_token, next_token, _rows(result_set.get("Rows"))))
        if next_token is None:
            return tuple(pages)
        request_token = next_token
    raise ControlRejected("Athena result pagination exceeds bound")


def observe_query(
    client: AthenaReads, query_execution_id: str
) -> tuple[QueryExecution, tuple[ResultPage, ...]]:
    execution = normalize_execution(
        client.get_query_execution(QueryExecutionId=query_execution_id), query_execution_id
    )
    return execution, read_result_pages(client, query_execution_id)


def persist_query_proof(
    objects: ImmutableObjects,
    *,
    bucket: str,
    account_id: str,
    family: str,
    identity: Mapping[str, str],
    query: FixedQuery,
    execution: QueryExecution,
    verification: Mapping[str, Any],
    result_reference: Mapping[str, Any],
    version_inventory_before_sha256: str,
    version_inventory_after_sha256: str,
) -> dict[str, Any]:
    """Persist a canonical, content-addressed proof outside transient run lifecycle."""
    if family != query.family or family not in {"transactions", "settlements", "bank_allocations"}:
        raise ControlRejected("Athena proof family differs")
    if type(bucket) is not str or parse_s3_uri(f"s3://{bucket}/publications").bucket != bucket:
        raise ControlRejected("invalid Athena proof bucket")
    if type(account_id) is not str or re.fullmatch(r"[0-9]{12}", account_id) is None:
        raise ControlRejected("invalid Athena proof account")
    required_identity = {
        "run_id",
        "attempt_id",
        "control_record_identity",
        "policy_sha256",
        "manifest_sha256",
        "source_bundle_sha256",
    }
    if set(identity) != required_identity or any(
        type(value) is not str for value in identity.values()
    ):
        raise ControlRejected("invalid Athena proof identity")
    if any(
        type(value) is not str or _DIGEST.fullmatch(value) is None
        for value in (version_inventory_before_sha256, version_inventory_after_sha256)
    ):
        raise ControlRejected("invalid Athena proof version inventory")
    expected_verification = {
        "query_execution_id",
        "sql_sha256",
        "rows_sha256",
        "row_count",
        "scanned_bytes",
        "execution_ms",
    }
    result = _mapping(result_reference, "result reference")
    if (
        set(verification) != expected_verification
        or verification.get("sql_sha256") != query.sha256
        or verification.get("query_execution_id") != execution.query_execution_id
        or verification.get("scanned_bytes") != execution.scanned_bytes
        or verification.get("execution_ms") != execution.execution_ms
        or sha256(execution.sql.encode()).hexdigest() != query.sha256
        or execution.engine_version != ENGINE
        or execution.output_location != result.get("uri")
        or execution.expected_bucket_owner != account_id
        or execution.encryption_option != "SSE_S3"
        or execution.status != "SUCCEEDED"
        or re.fullmatch(r"ledgerguard-p3-[a-z0-9][a-z0-9-]{7,31}-checks", execution.workgroup)
        is None
    ):
        raise ControlRejected("invalid Athena verification binding")
    value = validate(
        "query-proof",
        {
            "schema_version": "ledgerguard.query-proof.v1",
            **dict(identity),
            "family": family,
            "query_execution_id": verification["query_execution_id"],
            "sql_sha256": query.sha256,
            "workgroup": execution.workgroup,
            "engine_version": execution.engine_version,
            "status": execution.status,
            "scanned_bytes": verification["scanned_bytes"],
            "execution_ms": verification["execution_ms"],
            "result": dict(result),
            "rows_sha256": verification["rows_sha256"],
            "row_count": verification["row_count"],
            "version_inventory_before_sha256": version_inventory_before_sha256,
            "version_inventory_after_sha256": version_inventory_after_sha256,
        },
    )
    raw = canonical_bytes(value) + b"\n"
    digest = sha256(raw).hexdigest()
    uri = (
        f"s3://{bucket}/publications/query-proofs/{identity['run_id']}/"
        f"{identity['attempt_id']}/{family}/{digest}.json"
    )
    version_id = objects.put_immutable(uri, raw)
    return {"uri": uri, "version_id": version_id, "sha256": digest, "size_bytes": len(raw)}
