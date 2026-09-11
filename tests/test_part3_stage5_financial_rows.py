"""Real Arrow Parquet files and explicit independent financial test values."""

from __future__ import annotations

import importlib
from copy import deepcopy
from hashlib import sha256
from types import SimpleNamespace

import pytest

from ledgerguard.stage3.canonical import canonical_bytes
from ledgerguard_control.contracts import ControlRejected
from ledgerguard_control.financial_rows import (
    ParquetMember,
    _arrow_shape,
    compare_parquet,
    parquet_rows,
    validate_row,
)

pa = importlib.import_module("pyarrow")
pq = importlib.import_module("pyarrow.parquet")


def transaction(currency="INR", amount=100, identity="transaction-1"):
    components = {
        "processor": "processor-a",
        "merchant_id": "merchant-1",
        "payment_id": identity,
        "event_class": "CAPTURE",
        "currency": currency,
    }
    return {
        "reconciliation_key": "txn:" + sha256(canonical_bytes(components)).hexdigest(),
        "key_components": components,
        "totals": {
            "processor_minor": amount,
            "ledger_minor": amount - 10,
            "processor_ledger_delta_minor": 10,
            "difference_minor": 10,
            "processor_record_count": 1,
            "ledger_journal_count": 1,
        },
        "status": "EXCEPTION",
        "reason_codes": ["PROCESSOR_LEDGER_MISMATCH"],
        "source_identities": [["PROCESSOR_EVENT", "processor-a", "event-1"]],
        "authoritative_proof": False,
    }


def settlement():
    row = transaction()
    components = {
        "processor": "processor-a",
        "merchant_id": "merchant-1",
        "settlement_id": "settlement-1",
        "settlement_cycle": "cycle-1",
        "currency": "INR",
    }
    row["key_components"] = components
    row["reconciliation_key"] = "stl:" + sha256(canonical_bytes(components)).hexdigest()
    row["totals"] = {
        "processor_net_minor": 100,
        "ledger_clearing_minor": 90,
        "bank_minor": 80,
        "processor_ledger_delta_minor": 10,
        "processor_bank_delta_minor": 20,
        "ledger_bank_delta_minor": 10,
        "difference_minor": 20,
        "processor_settlement_count": 1,
        "ledger_journal_count": 1,
        "allocated_bank_entry_count": 1,
    }
    return row


def bank():
    target = settlement()["reconciliation_key"]
    return {
        "source_identity": ["BANK_ENTRY", "bank-a", "entry-1"],
        "merchant_id": "merchant-1",
        "currency": "INR",
        "normalized_settlement_reference": "settlement-1",
        "disposition": "ALLOCATED",
        "settlement_reconciliation_key": target,
        "signed_minor": 80,
        "account_permitted": True,
        "duplicate_current_bundle": False,
        "reason_codes": ["INVALID_BANK_ACCOUNT"],
    }


def member(tmp_path, family, rows, name="candidate.parquet"):
    path = tmp_path / name
    table = pa.Table.from_pylist(rows)
    pq.write_table(table, path, row_group_size=1)
    raw = path.read_bytes()
    return ParquetMember(family, path, sha256(raw).hexdigest(), len(raw))


def expected(tmp_path, rows):
    path = tmp_path / "expected.jsonl"
    raw = b"".join(canonical_bytes({"family": family, "row": row}) + b"\n" for family, row in rows)
    path.write_bytes(raw)
    return path, sha256(raw).hexdigest()


def test_real_parquet_every_family_and_exact_large_integer(tmp_path):
    rows = [
        ("transactions", transaction(amount=2**53 + 19)),
        ("settlements", settlement()),
        ("bank-allocations", bank()),
    ]
    files = tuple(member(tmp_path, family, [row], family + ".parquet") for family, row in rows)
    path, digest = expected(tmp_path, rows)
    result = compare_parquet(path, digest, files, tmp_path / "comparison")
    assert result["counts"] == {"transactions": 1, "settlements": 1, "bank-allocations": 1}
    assert result["expected_sha256"] == digest
    assert next(parquet_rows(files[0]))["totals"]["processor_minor"] == 2**53 + 19


def test_offsetting_cross_currency_errors_do_not_cancel(tmp_path):
    truth = [transaction("INR", 100, "inr-key"), transaction("USD", 200, "usd-key")]
    changed = [transaction("INR", 200, "inr-key"), transaction("USD", 100, "usd-key")]
    path, digest = expected(tmp_path, [("transactions", row) for row in truth])
    actual = member(tmp_path, "transactions", changed)
    with pytest.raises(ControlRejected, match="disagree"):
        compare_parquet(path, digest, (actual,), tmp_path / "comparison")


@pytest.mark.parametrize(
    "fault", ["extra", "missing", "duplicate-expected", "duplicate-actual", "duplicate-file", "pin"]
)
def test_exact_inventory_and_expected_pin(tmp_path, fault):
    rows = [transaction()]
    truth = deepcopy(rows)
    if fault == "extra":
        rows += [transaction(identity="extra-key")]
    if fault == "missing":
        truth += [transaction(identity="extra-key")]
    if fault == "duplicate-expected":
        truth *= 2
    if fault == "duplicate-actual":
        rows *= 2
    path, digest = expected(tmp_path, [("transactions", row) for row in truth])
    actual = member(tmp_path, "transactions", rows)
    files = (actual, actual) if fault == "duplicate-file" else (actual,)
    with pytest.raises(ControlRejected):
        compare_parquet(
            path, "0" * 64 if fault == "pin" else digest, files, tmp_path / "comparison"
        )


@pytest.mark.parametrize(
    "raw",
    [b"{}\n", b'{"family":"transactions","row":{}}', b'{"family":"transactions","row":{}}\r\n'],
)
def test_expected_framing(tmp_path, raw):
    path = tmp_path / "expected.jsonl"
    path.write_bytes(raw)
    with pytest.raises(ControlRejected):
        compare_parquet(path, sha256(raw).hexdigest(), (), tmp_path / "comparison")


@pytest.mark.parametrize(
    "fault",
    [
        "fields",
        "array",
        "text",
        "integer",
        "boolean",
        "currency",
        "reason",
        "authority",
        "status",
        "delta",
        "difference",
        "count",
    ],
)
def test_financial_shape_and_arithmetic_rejections(fault):
    row = transaction()
    if fault == "fields":
        row["extra"] = 1
    if fault == "array":
        row["reason_codes"] = "bad"
    if fault == "text":
        row["reconciliation_key"] = ""
    if fault == "integer":
        row["totals"]["processor_minor"] = True
    if fault == "boolean":
        row["authoritative_proof"] = 0
    if fault == "currency":
        row["key_components"]["currency"] = "inr"
    if fault == "reason":
        row["reason_codes"] *= 2
    if fault == "authority":
        row["authoritative_proof"] = True
    if fault == "status":
        row["status"] = "RESOLVED_MANUALLY"
    if fault == "delta":
        row["totals"]["processor_ledger_delta_minor"] = 0
    if fault == "difference":
        row["totals"]["difference_minor"] = 0
    if fault == "count":
        row["totals"]["processor_record_count"] = -1
    with pytest.raises(ControlRejected):
        validate_row("transactions", row)


def test_optional_bank_values_and_bad_family():
    row = bank()
    row.update(
        account_permitted=None,
        normalized_settlement_reference=None,
        settlement_reconciliation_key=None,
        disposition="UNALLOCATED_MISSING_REFERENCE",
    )
    assert validate_row("bank-allocations", row)
    row["source_identity"] = []
    with pytest.raises(ControlRejected):
        validate_row("bank-allocations", row)
    with pytest.raises(ControlRejected):
        validate_row("other", {})


@pytest.mark.parametrize("fault", ["identity", "target", "permission", "target-format"])
def test_bank_relationship_rejections(fault):
    row = bank()
    if fault == "identity":
        row["source_identity"] = ["WRONG", "bank-a", "entry-1"]
    if fault == "target":
        row["settlement_reconciliation_key"] = None
    if fault == "permission":
        row["account_permitted"] = None
    if fault == "target-format":
        row["settlement_reconciliation_key"] = "stl:wrong"
    with pytest.raises(ControlRejected):
        validate_row("bank-allocations", row)


@pytest.mark.parametrize("fault", ["status-reasons", "identity"])
def test_financial_semantic_relationship_rejections(fault):
    row = transaction()
    if fault == "status-reasons":
        row.update(status="MATCHED", reason_codes=[])
    if fault == "identity":
        row["reconciliation_key"] = "txn:" + "0" * 64
    with pytest.raises(ControlRejected):
        validate_row("transactions", row)


def test_duplicate_arrow_struct_field_rejected():
    duplicate = pa.struct([("value", pa.string()), ("value", pa.string())])
    with pytest.raises(ControlRejected, match="duplicate"):
        _arrow_shape(duplicate)


def test_reported_parquet_row_count_must_match(tmp_path, monkeypatch):
    from ledgerguard_control import financial_rows

    actual = member(tmp_path, "transactions", [transaction()])
    real_file = pq.ParquetFile(actual.path)
    real_import = financial_rows.importlib.import_module

    class MiscountedParquetFile:
        schema_arrow = real_file.schema_arrow
        metadata = SimpleNamespace(num_rows=real_file.metadata.num_rows + 1)

        def __init__(self, *_args, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            real_file.close()

        def iter_batches(self, **kwargs):
            return real_file.iter_batches(**kwargs)

    def import_module(name):
        if name == "pyarrow.parquet":
            return SimpleNamespace(ParquetFile=MiscountedParquetFile)
        return real_import(name)

    monkeypatch.setattr(financial_rows.importlib, "import_module", import_module)
    with pytest.raises(ControlRejected, match="row count"):
        list(parquet_rows(actual))


@pytest.mark.parametrize("case", ["empty", "family", "digest-format"])
def test_expected_inventory_is_explicit(tmp_path, case):
    rows = [] if case == "empty" else [("transactions", transaction())]
    path, digest = expected(tmp_path, rows)
    files = ()
    if case == "digest-format":
        digest = "not-a-sha256"
    match = "family inventory" if case == "family" else None
    with pytest.raises(ControlRejected, match=match):
        compare_parquet(path, digest, files, tmp_path / "comparison")


def test_physical_hash_schema_and_changed_file(tmp_path):
    actual = member(tmp_path, "transactions", [transaction()])
    with pytest.raises(ControlRejected, match="family"):
        list(parquet_rows(ParquetMember("other", actual.path, actual.sha256, actual.size_bytes)))
    with pytest.raises(ControlRejected, match="identity"):
        list(parquet_rows(ParquetMember(actual.family, actual.path, "0" * 64, actual.size_bytes)))
    row = transaction()
    row["totals"]["processor_minor"] = 100.0
    invalid = member(tmp_path, "transactions", [row], "wrong-schema.parquet")
    with pytest.raises(ControlRejected, match="schema"):
        list(parquet_rows(invalid))
    stream = parquet_rows(actual)
    next(stream)
    with actual.path.open("ab") as output:
        output.write(b"changed")
    with pytest.raises(ControlRejected, match="changed"):
        list(stream)
