"""Fixed SQL and complete Athena observation validation."""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256

import pytest

from ledgerguard.stage3.canonical import canonical_bytes
from ledgerguard_control.athena import (
    AMOUNTS,
    ENGINE,
    MAX_RESULT_PAGES,
    MAX_RESULT_ROWS,
    QueryExecution,
    ResultPage,
    _validate_summary_row,
    fixed_queries,
    read_expected,
    verify_query,
)
from ledgerguard_control.contracts import MAX_DOCUMENT_BYTES, ControlRejected


def query():
    return fixed_queries("ledgerguard_p3_reconciliation", "run-test1", "attempt-1")[0]


def expected_row(q=None):
    q = q or query()
    row = {name: "0" for name in q.columns}
    row.update(currency="INR", status="EXCEPTION", reason_codes="PROCESSOR_LEDGER_MISMATCH")
    row["row_count"] = "2"
    return row


def execution(q=None):
    q = q or query()
    return QueryExecution(
        "12345678-abcd",
        q.sql,
        "ledgerguard-checks",
        ENGINE,
        "s3://ledgerguard-bucket/query-results/id.csv",
        "857229544428",
        "SSE_S3",
        "SUCCEEDED",
        1024,
        200,
    )


def test_three_fixed_partition_confined_queries():
    queries = fixed_queries("ledgerguard_p3_reconciliation", "run-test1", "attempt-1")
    assert tuple(q.family for q in queries) == (
        "transactions",
        "settlements",
        "bank_allocations",
    )
    for q in queries:
        assert "SELECT " in q.sql and " GROUP BY " in q.sql and " ORDER BY " in q.sql
        assert " WHERE run_id = 'run-test1' AND attempt_id = 'attempt-1'" in q.sql
        assert "DECIMAL(38,0)" in q.sql and q.sha256 == sha256(q.sql.encode()).hexdigest()


@pytest.mark.parametrize("field", ["database", "run", "attempt"])
def test_sql_identifiers_reject_injection(field):
    values = ["ledgerguard_p3_reconciliation", "run-test1", "attempt-1"]
    values[{"database": 0, "run": 1, "attempt": 2}[field]] = "bad'; DROP TABLE x;--"
    with pytest.raises(ControlRejected):
        fixed_queries(*values)


def test_expected_rows_are_canonical_pinned_exact_and_ordered(tmp_path):
    q = query()
    row = expected_row(q)
    raw = canonical_bytes(row) + b"\n"
    path = tmp_path / "expected.jsonl"
    path.write_bytes(raw)
    assert read_expected(path, sha256(raw).hexdigest(), q) == (row,)
    for changed, match in [
        (raw + b" ", "strict JSON"),
        (raw, "digest"),
    ]:
        path.write_bytes(changed)
        with pytest.raises(ControlRejected, match=match):
            read_expected(path, "0" * 64 if match == "digest" else sha256(changed).hexdigest(), q)


def test_expected_rejects_columns_types_currency_and_order(tmp_path):
    q = query()
    cases = []
    row = expected_row(q)
    changed = deepcopy(row)
    changed["extra"] = "x"
    cases.append([changed])
    changed = deepcopy(row)
    changed["row_count"] = "01"
    cases.append([changed])
    changed = deepcopy(row)
    changed["currency"] = "inr"
    cases.append([changed])
    changed = deepcopy(row)
    changed["status"] = 1
    cases.append([changed])
    changed = deepcopy(row)
    changed["currency"] = "USD"
    cases.append([changed, row])
    for number, rows in enumerate(cases):
        raw = b"".join(canonical_bytes(value) + b"\n" for value in rows)
        path = tmp_path / f"expected-{number}.jsonl"
        path.write_bytes(raw)
        with pytest.raises(ControlRejected):
            read_expected(path, sha256(raw).hexdigest(), q)
    with pytest.raises(ControlRejected, match="digest"):
        read_expected(path, "bad", q)


@pytest.mark.parametrize(
    "family,change",
    [
        ("transactions", {"reason_codes": "UNKNOWN"}),
        (
            "transactions",
            {"reason_codes": "PROCESSOR_LEDGER_MISMATCH|PROCESSOR_LEDGER_MISMATCH"},
        ),
        ("transactions", {"status": "UNKNOWN"}),
        ("transactions", {"status": "MATCHED"}),
        ("transactions", {"status": "WITHIN_TOLERANCE"}),
        ("transactions", {"row_count": "0"}),
        ("transactions", {"processor_record_count": "-1"}),
        ("bank_allocations", {"disposition": "UNKNOWN"}),
    ],
)
def test_summary_semantics_reject_invalid_groups(family, change):
    q = next(
        value
        for value in fixed_queries("ledgerguard_p3_reconciliation", "run-test1", "attempt-1")
        if value.family == family
    )
    row = {name: "0" for name in q.columns}
    row.update(currency="INR", reason_codes="PROCESSOR_LEDGER_MISMATCH", row_count="1")
    if family == "transactions":
        row["status"] = "EXCEPTION"
    else:
        row.update(disposition="ALLOCATED", reason_codes="")
    row.update(change)
    with pytest.raises(ControlRejected):
        _validate_summary_row(q, row)


def test_valid_matched_and_tolerated_groups():
    q = query()
    row = expected_row(q)
    row.update(status="MATCHED", reason_codes="")
    _validate_summary_row(q, row)
    row.update(status="WITHIN_TOLERANCE", reason_codes="TOLERATED_DIFFERENCE")
    _validate_summary_row(q, row)
    bank_query = fixed_queries("ledgerguard_p3_reconciliation", "run-test1", "attempt-1")[2]
    bank_row = {name: "0" for name in bank_query.columns}
    bank_row.update(currency="INR", disposition="ALLOCATED", reason_codes="", row_count="1")
    _validate_summary_row(bank_query, bank_row)


def test_expected_total_size_bound(tmp_path):
    path = tmp_path / "oversized.jsonl"
    raw = b"x" * (MAX_DOCUMENT_BYTES + 1)
    path.write_bytes(raw)
    with pytest.raises(ControlRejected, match="exceeds bound"):
        read_expected(path, sha256(raw).hexdigest(), query())


def test_verify_complete_two_page_result():
    q = query()
    row = expected_row(q)
    values = tuple(row[name] for name in q.columns)
    pages = (
        ResultPage(None, "token-1", (q.columns,)),
        ResultPage("token-1", None, (values,)),
    )
    result = verify_query(
        q,
        execution(q),
        pages,
        (row,),
        workgroup="ledgerguard-checks",
        output_location="s3://ledgerguard-bucket/query-results/id.csv",
        account_id="857229544428",
    )
    assert result["row_count"] == 1 and result["scanned_bytes"] == 1024


@pytest.mark.parametrize(
    "field,value,match",
    [
        ("sql", "SELECT 1", "ownership"),
        ("workgroup", "other", "ownership"),
        ("engine_version", "other", "ownership"),
        ("output_location", "s3://other", "ownership"),
        ("expected_bucket_owner", "000000000000", "ownership"),
        ("encryption_option", "NONE", "ownership"),
        ("status", "FAILED", "succeed"),
        ("scanned_bytes", 104857601, "resource"),
        ("execution_ms", 300001, "resource"),
        ("query_execution_id", "bad", "identity"),
    ],
)
def test_query_execution_rejections(field, value, match):
    q = query()
    observed = execution(q)
    observed = QueryExecution(**{**observed.__dict__, field: value})
    with pytest.raises(ControlRejected, match=match):
        verify_query(
            q,
            observed,
            (ResultPage(None, None, (q.columns,)),),
            (),
            workgroup="ledgerguard-checks",
            output_location="s3://ledgerguard-bucket/query-results/id.csv",
            account_id="857229544428",
        )


@pytest.mark.parametrize(
    "fault",
    [
        "empty",
        "page-bound",
        "start",
        "chain",
        "repeat",
        "header",
        "null",
        "width",
        "number",
        "row-bound",
        "incomplete",
        "value",
    ],
)
def test_result_page_rejections(fault):
    q = query()
    row = expected_row(q)
    values = tuple(row[name] for name in q.columns)
    pages = [ResultPage(None, None, (q.columns, values))]
    expected = (row,)
    if fault == "empty":
        pages = []
    if fault == "page-bound":
        pages = [ResultPage(None, None, (q.columns,))] * (MAX_RESULT_PAGES + 1)
    if fault == "start":
        pages[0] = ResultPage("token", None, pages[0].rows)
    if fault == "chain":
        pages = [ResultPage(None, "one", (q.columns,)), ResultPage("two", None, (values,))]
    if fault == "repeat":
        pages = [ResultPage(None, "one", (q.columns,)), ResultPage("one", "one", (values,))]
    if fault == "header":
        pages[0] = ResultPage(None, None, (("wrong",), values))
    if fault == "null":
        pages[0] = ResultPage(None, None, (q.columns, (*values[:-1], None)))
    if fault == "width":
        pages[0] = ResultPage(None, None, (q.columns, values[:-1]))
    if fault == "number":
        bad = list(values)
        bad[q.columns.index(AMOUNTS[q.family][0])] = "1.0"
        pages[0] = ResultPage(None, None, (q.columns, tuple(bad)))
    if fault == "row-bound":
        pages[0] = ResultPage(
            None,
            None,
            (q.columns, *(values for _ in range(MAX_RESULT_ROWS + 1))),
        )
    if fault == "incomplete":
        pages[0] = ResultPage(None, "one", pages[0].rows)
    if fault == "value":
        expected = ({**row, "status": "MATCHED"},)
    with pytest.raises(ControlRejected):
        verify_query(
            q,
            execution(q),
            tuple(pages),
            expected,
            workgroup="ledgerguard-checks",
            output_location="s3://ledgerguard-bucket/query-results/id.csv",
            account_id="857229544428",
        )
