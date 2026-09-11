"""Fixed, bounded Athena summaries and complete result-page verification.

This module never starts a query.  It renders three pre-authored SELECT statements
and verifies normalized read-only observations against independently admitted rows.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, cast

from ledgerguard.stage3.canonical import canonical_bytes

from .contracts import MAX_DOCUMENT_BYTES, ControlRejected, exact_amount, strict_json

SCAN_LIMIT_BYTES = 100 * 1024 * 1024
EXECUTION_LIMIT_MS = 5 * 60 * 1000
ENGINE = "Athena engine version 3"
MAX_RESULT_PAGES = 128
MAX_RESULT_ROWS = 4096

GROUPS = {
    "transactions": ("currency", "status", "reason_codes"),
    "settlements": ("currency", "status", "reason_codes"),
    "bank_allocations": ("currency", "disposition", "reason_codes"),
}
AMOUNTS = {
    "transactions": (
        "processor_minor",
        "ledger_minor",
        "processor_ledger_delta_minor",
        "difference_minor",
        "processor_record_count",
        "ledger_journal_count",
    ),
    "settlements": (
        "processor_net_minor",
        "ledger_clearing_minor",
        "bank_minor",
        "processor_ledger_delta_minor",
        "processor_bank_delta_minor",
        "ledger_bank_delta_minor",
        "difference_minor",
        "processor_settlement_count",
        "ledger_journal_count",
        "allocated_bank_entry_count",
    ),
    "bank_allocations": ("signed_minor",),
}
REASONS = {
    "transactions": frozenset(
        {
            "INVALID_ACCOUNT_ROLE",
            "UNRESOLVED_REFERENCE",
            "OVER_APPLIED_REFERENCE",
            "MISSING_LEDGER_MOVEMENT",
            "MISSING_PROCESSOR_ACTIVITY",
            "PROCESSOR_LEDGER_MISMATCH",
            "TOLERATED_DIFFERENCE",
        }
    ),
    "settlements": frozenset(
        {
            "INVALID_ACCOUNT_ROLE",
            "MISSING_LEDGER_MOVEMENT",
            "MISSING_PROCESSOR_ACTIVITY",
            "MISSING_BANK_SETTLEMENT",
            "UNALLOCATED_BANK_MOVEMENT",
            "INVALID_BANK_ACCOUNT",
            "DUPLICATE_BANK_MOVEMENT",
            "SETTLEMENT_FORMULA_MISMATCH",
            "PROCESSOR_LEDGER_MISMATCH",
            "PROCESSOR_BANK_MISMATCH",
            "LEDGER_BANK_MISMATCH",
            "TOLERATED_DIFFERENCE",
        }
    ),
    "bank_allocations": frozenset(
        {"UNALLOCATED_BANK_MOVEMENT", "INVALID_BANK_ACCOUNT", "DUPLICATE_BANK_MOVEMENT"}
    ),
}


@dataclass(frozen=True)
class FixedQuery:
    family: str
    sql: str
    sha256: str
    columns: tuple[str, ...]


@dataclass(frozen=True)
class QueryExecution:
    query_execution_id: str
    sql: str
    workgroup: str
    engine_version: str
    output_location: str
    expected_bucket_owner: str
    encryption_option: str
    status: str
    scanned_bytes: int
    execution_ms: int


@dataclass(frozen=True)
class ResultPage:
    request_token: str | None
    next_token: str | None
    rows: tuple[tuple[str | None, ...], ...]


def _identifier(value: str, pattern: str, label: str) -> str:
    if type(value) is not str or re.fullmatch(pattern, value) is None:
        raise ControlRejected(f"invalid Athena {label}")
    return value


def fixed_queries(database: str, run_id: str, attempt_id: str) -> tuple[FixedQuery, ...]:
    """Render only partition-confined aggregate SQL from closed identifiers."""
    database = _identifier(database, r"[a-z0-9_]{8,255}", "database")
    run_id = _identifier(run_id, r"[a-z0-9][a-z0-9-]{7,63}", "run identity")
    attempt_id = _identifier(attempt_id, r"[a-z0-9][a-z0-9-]{7,63}", "attempt identity")
    result = []
    for family in GROUPS:
        groups = GROUPS[family]
        group_sql = []
        for name in groups:
            if name == "currency" and family != "bank_allocations":
                expression = "key_components.currency"
            elif name == "reason_codes":
                expression = "array_join(reason_codes, '|')"
            else:
                expression = name
            group_sql.append(f"{expression} AS {name}")
        amount_sql = []
        for name in AMOUNTS[family]:
            expression = name if family == "bank_allocations" else f"totals.{name}"
            amount_sql.append(
                f"CAST(SUM(CAST({expression} AS DECIMAL(38,0))) AS VARCHAR) AS {name}"
            )
        columns = (*groups, "row_count", *AMOUNTS[family])
        sql = (
            "SELECT "
            + ", ".join((*group_sql, "CAST(COUNT(*) AS VARCHAR) AS row_count", *amount_sql))
            + f' FROM "{database}"."{family}"'
            + f" WHERE run_id = '{run_id}' AND attempt_id = '{attempt_id}'"
            + " GROUP BY "
            + ", ".join(
                "key_components.currency"
                if name == "currency" and family != "bank_allocations"
                else "array_join(reason_codes, '|')"
                if name == "reason_codes"
                else name
                for name in groups
            )
            + " ORDER BY "
            + ", ".join(groups)
        )
        result.append(FixedQuery(family, sql, sha256(sql.encode()).hexdigest(), columns))
    return tuple(result)


def _validate_summary_row(query: FixedQuery, row: dict[str, str]) -> None:
    if re.fullmatch(r"[A-Z]{3}", row["currency"]) is None:
        raise ControlRejected("Athena summary currency differs")
    reasons = row["reason_codes"].split("|") if row["reason_codes"] else []
    if len(reasons) != len(set(reasons)) or not set(reasons) <= REASONS[query.family]:
        raise ControlRejected("Athena summary reasons differ")
    if query.family == "bank_allocations":
        if row["disposition"] not in {
            "ALLOCATED",
            "UNALLOCATED_MISSING_REFERENCE",
            "UNALLOCATED_UNKNOWN_REFERENCE",
        }:
            raise ControlRejected("Athena summary disposition differs")
    else:
        status = row["status"]
        if status not in {"MATCHED", "WITHIN_TOLERANCE", "EXCEPTION"}:
            raise ControlRejected("Athena summary status differs")
        if (status == "MATCHED" and reasons) or (
            status == "WITHIN_TOLERANCE" and reasons != ["TOLERATED_DIFFERENCE"]
        ):
            raise ControlRejected("Athena summary status and reasons disagree")
    for name in ("row_count", *AMOUNTS[query.family]):
        amount = exact_amount(row[name])
        if (name == "row_count" and amount < 1) or (name.endswith("_count") and amount < 0):
            raise ControlRejected("Athena summary count differs")


def read_expected(path: Path, trusted_sha256: str, query: FixedQuery) -> tuple[dict[str, str], ...]:
    if re.fullmatch(r"[0-9a-f]{64}", trusted_sha256) is None:
        raise ControlRejected("invalid Athena expectation digest")
    digest = sha256()
    rows: list[dict[str, str]] = []
    size = 0
    with path.open("rb") as stream:
        while raw := stream.readline(MAX_DOCUMENT_BYTES + 1):
            size += len(raw)
            if size > MAX_DOCUMENT_BYTES or len(rows) == MAX_RESULT_ROWS:
                raise ControlRejected("Athena expectation exceeds bound")
            value = strict_json(raw)
            if raw != canonical_bytes(value) + b"\n" or set(value) != set(query.columns):
                raise ControlRejected("Athena expectation framing or columns differ")
            row = {}
            for name in query.columns:
                item = value[name]
                if type(item) is not str or (not item and name != "reason_codes"):
                    raise ControlRejected("Athena expectation value differs")
                row[name] = item
            _validate_summary_row(query, row)
            rows.append(row)
            digest.update(raw)
    if digest.hexdigest() != trusted_sha256:
        raise ControlRejected("Athena expectation digest differs")
    if rows != sorted(rows, key=lambda row: tuple(row[name] for name in GROUPS[query.family])):
        raise ControlRejected("Athena expectation order differs")
    return tuple(rows)


def verify_query(
    query: FixedQuery,
    execution: QueryExecution,
    pages: tuple[ResultPage, ...],
    expected: tuple[dict[str, str], ...],
    *,
    workgroup: str,
    output_location: str,
    account_id: str,
) -> dict[str, Any]:
    """Verify terminal ownership, every page, exact values and bounded scan/time."""
    if (
        execution.sql != query.sql
        or sha256(execution.sql.encode()).hexdigest() != query.sha256
        or execution.workgroup != workgroup
        or execution.engine_version != ENGINE
        or execution.output_location != output_location
        or execution.expected_bucket_owner != account_id
        or execution.encryption_option != "SSE_S3"
    ):
        raise ControlRejected("Athena query ownership differs")
    if execution.status != "SUCCEEDED":
        raise ControlRejected("Athena query did not succeed")
    if (
        type(execution.scanned_bytes) is not int
        or not 0 <= execution.scanned_bytes <= SCAN_LIMIT_BYTES
        or type(execution.execution_ms) is not int
        or not 0 <= execution.execution_ms <= EXECUTION_LIMIT_MS
    ):
        raise ControlRejected("Athena query resource bound differs")
    if re.fullmatch(r"[0-9a-f-]{8,128}", execution.query_execution_id) is None:
        raise ControlRejected("Athena query execution identity differs")
    if not pages or len(pages) > MAX_RESULT_PAGES or pages[0].request_token is not None:
        raise ControlRejected("Athena result pagination start differs")
    rows: list[dict[str, str]] = []
    seen_tokens: set[str] = set()
    expected_token: str | None = None
    for index, page in enumerate(pages):
        if page.request_token != expected_token:
            raise ControlRejected("Athena result pagination chain differs")
        if page.next_token is not None:
            if not page.next_token or page.next_token in seen_tokens:
                raise ControlRejected("Athena result pagination token differs")
            seen_tokens.add(page.next_token)
        expected_token = page.next_token
        for row_index, values in enumerate(page.rows):
            if index == 0 and row_index == 0:
                if values != query.columns:
                    raise ControlRejected("Athena result header differs")
                continue
            if len(values) != len(query.columns) or any(value is None for value in values):
                raise ControlRejected("Athena result row shape differs")
            row = {
                name: cast(str, value) for name, value in zip(query.columns, values, strict=True)
            }
            _validate_summary_row(query, row)
            rows.append(row)
            if len(rows) > MAX_RESULT_ROWS:
                raise ControlRejected("Athena result exceeds row bound")
    if expected_token is not None:
        raise ControlRejected("Athena result pagination is incomplete")
    if rows != list(expected):
        raise ControlRejected("Athena aggregate rows disagree")
    raw = b"".join(canonical_bytes(row) + b"\n" for row in rows)
    return {
        "query_execution_id": execution.query_execution_id,
        "sql_sha256": query.sha256,
        "rows_sha256": sha256(raw).hexdigest(),
        "row_count": len(rows),
        "scanned_bytes": execution.scanned_bytes,
        "execution_ms": execution.execution_ms,
    }
