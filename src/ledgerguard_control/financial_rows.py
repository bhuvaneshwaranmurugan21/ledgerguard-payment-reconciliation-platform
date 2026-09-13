"""Independent exact-row comparison of Parquet against externally admitted evidence.

No production reconciliation engine or expectation generator is imported. The caller
must obtain the expected-file digest from the admitted run, not from the candidate.
This component is local validation; it does not establish Glue ownership or live AWS.
"""

from __future__ import annotations

import importlib
import re
import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

from ledgerguard.stage3.canonical import canonical_bytes

from .contracts import MAX_DOCUMENT_BYTES, ControlRejected, strict_json

KEYS = {
    "transactions": "processor merchant_id payment_id event_class currency",
    "settlements": "processor merchant_id settlement_id settlement_cycle currency",
}
TOTALS = {
    "transactions": "processor_minor ledger_minor processor_ledger_delta_minor difference_minor "
    "processor_record_count ledger_journal_count",
    "settlements": "processor_net_minor ledger_clearing_minor bank_minor "
    "processor_ledger_delta_minor processor_bank_delta_minor ledger_bank_delta_minor "
    "difference_minor processor_settlement_count ledger_journal_count allocated_bank_entry_count",
}
SHAPES: dict[str, Any] = {
    family: {
        "reconciliation_key": "string",
        "key_components": dict.fromkeys(keys.split(), "string"),
        "totals": dict.fromkeys(TOTALS[family].split(), "int64"),
        "status": "string",
        "reason_codes": ["string"],
        "source_identities": [["string"]],
        "authoritative_proof": "bool",
    }
    for family, keys in KEYS.items()
}
SHAPES["bank-allocations"] = {
    "source_identity": ["string"],
    "merchant_id": "string",
    "currency": "string",
    "normalized_settlement_reference": "string",
    "disposition": "string",
    "settlement_reconciliation_key": "string",
    "signed_minor": "int64",
    "account_permitted": "bool",
    "duplicate_current_bundle": "bool",
    "reason_codes": ["string"],
}
OPTIONAL = {"normalized_settlement_reference", "settlement_reconciliation_key", "account_permitted"}
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
    "bank-allocations": frozenset(
        {
            "UNALLOCATED_BANK_MOVEMENT",
            "INVALID_BANK_ACCOUNT",
            "DUPLICATE_BANK_MOVEMENT",
        }
    ),
}


@dataclass(frozen=True)
class ParquetMember:
    family: str
    path: Path
    sha256: str
    size_bytes: int


def _hash_file(path: Path) -> tuple[int, str]:
    size = 0
    digest = sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            size += len(chunk)
            digest.update(chunk)
    return size, digest.hexdigest()


def _typed(value: Any, shape: Any, optional: bool = False) -> None:
    if value is None and optional:
        return
    if isinstance(shape, dict):
        if type(value) is not dict or set(value) != set(shape):
            raise ControlRejected("financial row fields differ")
        for name, child in shape.items():
            _typed(value[name], child, name in OPTIONAL)
    elif isinstance(shape, list):
        if type(value) is not list:
            raise ControlRejected("financial array type differs")
        for item in value:
            _typed(item, shape[0])
    elif shape == "string":
        if type(value) is not str or not 1 <= len(value) <= 1024:
            raise ControlRejected("financial text type or size differs")
    elif shape == "int64":
        if type(value) is not int or not -(2**63) <= value < 2**63:
            raise ControlRejected("financial integer type or range differs")
    elif type(value) is not bool:
        raise ControlRejected("financial boolean type differs")


def validate_row(family: str, row: dict[str, Any]) -> str:
    if type(family) is not str or family not in SHAPES:
        raise ControlRejected("unknown financial family")
    _typed(row, SHAPES[family])
    # Canonical transport rejects floating-point, invalid Unicode and excessive depth.
    strict_json(canonical_bytes(row))
    currency = (
        row["currency"] if family == "bank-allocations" else row["key_components"]["currency"]
    )
    if re.fullmatch(r"[A-Z]{3}", currency) is None:
        raise ControlRejected("invalid financial currency")
    reasons = row["reason_codes"]
    if len(reasons) != len(set(reasons)) or not set(reasons) <= REASONS[family]:
        raise ControlRejected("duplicate or unknown financial reason")
    if family == "bank-allocations":
        if not row["source_identity"] or row["disposition"] not in {
            "ALLOCATED",
            "UNALLOCATED_MISSING_REFERENCE",
            "UNALLOCATED_UNKNOWN_REFERENCE",
        }:
            raise ControlRejected("invalid bank allocation identity or disposition")
        allocated = row["disposition"] == "ALLOCATED"
        if len(row["source_identity"]) != 3 or row["source_identity"][0] != "BANK_ENTRY":
            raise ControlRejected("bank source identity differs")
        if allocated != (row["settlement_reconciliation_key"] is not None):
            raise ControlRejected("bank allocation target differs")
        if allocated != (row["account_permitted"] is not None):
            raise ControlRejected("bank allocation permission differs")
        target = row["settlement_reconciliation_key"]
        if target is not None and re.fullmatch(r"stl:[0-9a-f]{64}", target) is None:
            raise ControlRejected("bank allocation target identity differs")
        return canonical_bytes(row["source_identity"]).decode()
    if row["authoritative_proof"] is not False:
        raise ControlRejected("candidate cannot claim financial authority")
    if row["status"] not in {"MATCHED", "WITHIN_TOLERANCE", "EXCEPTION"}:
        raise ControlRejected("invalid financial status")
    amounts = row["totals"]
    processor = amounts["processor_minor" if family == "transactions" else "processor_net_minor"]
    ledger = amounts["ledger_minor" if family == "transactions" else "ledger_clearing_minor"]
    deltas = {"processor_ledger_delta_minor": processor - ledger}
    if family == "settlements":
        deltas.update(
            processor_bank_delta_minor=processor - amounts["bank_minor"],
            ledger_bank_delta_minor=ledger - amounts["bank_minor"],
        )
    if any(amounts[name] != amount for name, amount in deltas.items()):
        raise ControlRejected("financial delta arithmetic differs")
    if amounts["difference_minor"] != max(abs(value) for value in deltas.values()):
        raise ControlRejected("financial difference arithmetic differs")
    if any(value < 0 for name, value in amounts.items() if name.endswith("_count")):
        raise ControlRejected("negative financial record count")
    difference = amounts["difference_minor"]
    if (row["status"] == "MATCHED") != (difference == 0 and not reasons) or (
        row["status"] == "WITHIN_TOLERANCE"
    ) != (difference > 0 and reasons == ["TOLERATED_DIFFERENCE"]):
        raise ControlRejected("financial status and reasons disagree")
    prefix = "txn:" if family == "transactions" else "stl:"
    expected_key = prefix + sha256(canonical_bytes(row["key_components"])).hexdigest()
    if row["reconciliation_key"] != expected_key:
        raise ControlRejected("financial reconciliation key differs")
    return str(row["reconciliation_key"])


def _arrow_shape(data_type: Any) -> Any:
    arrow = importlib.import_module("pyarrow")
    if arrow.types.is_struct(data_type):
        result = {field.name: _arrow_shape(field.type) for field in data_type}
        if len(result) != len(data_type):
            raise ControlRejected("duplicate Parquet struct field")
        return result
    if arrow.types.is_list(data_type):
        return [_arrow_shape(data_type.value_type)]
    return str(data_type)


def parquet_rows(member: ParquetMember) -> Iterator[dict[str, Any]]:
    if member.family not in SHAPES:
        raise ControlRejected("unknown Parquet family")
    if _hash_file(member.path) != (member.size_bytes, member.sha256):
        raise ControlRejected("Parquet physical identity differs")
    parquet = importlib.import_module("pyarrow.parquet")
    with parquet.ParquetFile(
        member.path,
        thrift_string_size_limit=MAX_DOCUMENT_BYTES,
        thrift_container_size_limit=MAX_DOCUMENT_BYTES,
    ) as file:
        schema = file.schema_arrow
        shape = {field.name: _arrow_shape(field.type) for field in schema}
        if len(shape) != len(schema) or shape != SHAPES[member.family]:
            raise ControlRejected("Parquet physical schema differs")
        count = 0
        for batch in file.iter_batches(batch_size=256, use_threads=False):
            for row in batch.to_pylist():
                validate_row(member.family, row)
                count += 1
                yield row
        if count != file.metadata.num_rows:
            raise ControlRejected("Parquet row count differs")
    if _hash_file(member.path) != (member.size_bytes, member.sha256):
        raise ControlRejected("Parquet changed during read")


def compare_parquet(
    expected_file: Path,
    trusted_expected_sha256: str,
    members: tuple[ParquetMember, ...],
    workspace: Path,
) -> dict[str, Any]:
    """Disk-backed exact multiset comparison, preserving grain, key and currency.

    Expected JSONL contains canonical {family,row} records provided independently.
    Both inputs are exhausted and hash-checked before a success receipt is returned.
    SQLite is used only for candidate comparison, never as financial authority.
    """
    workspace.mkdir(parents=True, exist_ok=False)
    connection = sqlite3.connect(workspace / "comparison.sqlite")
    try:
        connection.execute("PRAGMA cache_size=-2048")
        connection.execute("PRAGMA temp_store=FILE")
        connection.execute(
            "CREATE TABLE rows(side INTEGER,family TEXT,identity TEXT,body BLOB, "
            "PRIMARY KEY(side,family,identity))"
        )

        def insert(side: int, family: str, row: dict[str, Any]) -> None:
            identity = validate_row(family, row)
            try:
                connection.execute(
                    "INSERT INTO rows VALUES (?,?,?,?)",
                    (side, family, identity, canonical_bytes(row)),
                )
            except sqlite3.IntegrityError as error:
                raise ControlRejected("duplicate financial identity") from error

        if re.fullmatch(r"[0-9a-f]{64}", trusted_expected_sha256) is None:
            raise ControlRejected("independent expectation digest format differs")
        digest = sha256()
        expected_counts = dict.fromkeys(SHAPES, 0)
        with expected_file.open("rb") as stream:
            while raw := stream.readline(MAX_DOCUMENT_BYTES + 1):
                value = strict_json(raw)
                if set(value) != {"family", "row"} or raw != canonical_bytes(value) + b"\n":
                    raise ControlRejected("expected row framing or shape differs")
                insert(0, value["family"], value["row"])
                expected_counts[value["family"]] += 1
                digest.update(raw)
        if digest.hexdigest() != trusted_expected_sha256:
            raise ControlRejected("independent expectation digest differs")
        expected_families = {family for family, count in expected_counts.items() if count}
        member_families = {member.family for member in members}
        if not expected_families or member_families != expected_families:
            raise ControlRejected("financial family inventory differs")
        seen = set()
        for member in members:
            if member.path in seen:
                raise ControlRejected("duplicate Parquet member")
            seen.add(member.path)
            for row in parquet_rows(member):
                insert(1, member.family, row)
        for left, right in ((0, 1), (1, 0)):
            mismatch = connection.execute(
                "SELECT family,identity,body FROM rows WHERE side=? EXCEPT "
                "SELECT family,identity,body FROM rows WHERE side=? LIMIT 1",
                (left, right),
            ).fetchone()
            if mismatch is not None:
                raise ControlRejected("independent financial rows disagree")
        counts = dict.fromkeys(SHAPES, 0)
        result_digest = sha256()
        for family, body in connection.execute(
            "SELECT family,body FROM rows WHERE side=1 ORDER BY family,identity"
        ):
            counts[family] += 1
            result_digest.update(
                canonical_bytes({"family": family, "row": strict_json(body)}) + b"\n"
            )
        return {
            "expected_sha256": trusted_expected_sha256,
            "rows_sha256": result_digest.hexdigest(),
            "counts": counts,
        }
    finally:
        connection.close()
