"""Independent streaming readback for generated Stage 3 assets.

This module deliberately does not import production reconciliation or Spark code.
"""

from __future__ import annotations

import csv
import json
from collections.abc import Iterator
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

from .canonical import canonical_digest
from .errors import Stage3Rejected
from .formats import CSV_FIELDS, FAMILIES, SOURCE_DIGEST_EXCLUSIONS

_INTEGER_FIELDS = frozenset(
    {
        "amount_minor",
        "gross_minor",
        "fee_minor",
        "refund_minor",
        "chargeback_minor",
        "reserve_minor",
        "reported_net_minor",
    }
)


@dataclass(frozen=True)
class ReadbackResult:
    dataset_id: str
    run_id: str
    counts: dict[str, int]
    currency_totals: dict[str, dict[str, int]]
    verified_file_count: int
    logical_sha256: str


def _load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise Stage3Rejected("ASSET_VIOLATION", f"invalid JSON document: {path.name}") from error
    if not isinstance(value, dict):
        raise Stage3Rejected("ASSET_VIOLATION", f"document is not an object: {path.name}")
    return value


def _file_identity(path: Path) -> tuple[int, str]:
    digest = sha256()
    size = 0
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return size, digest.hexdigest()


def _json_rows(paths: list[Path]) -> Iterator[dict[str, Any]]:
    for path in paths:
        with path.open("r", encoding="utf-8", newline="") as handle:
            for line in handle:
                if not line.endswith("\n") or "\r" in line or line == "\n":
                    raise Stage3Rejected("FORMAT_VIOLATION", f"invalid JSONL framing: {path}")
                try:
                    value = json.loads(line)
                except json.JSONDecodeError as error:
                    raise Stage3Rejected("FORMAT_VIOLATION", f"invalid JSONL: {path}") from error
                if not isinstance(value, dict) or canonical_digest(
                    {
                        key: item
                        for key, item in value.items()
                        if key not in SOURCE_DIGEST_EXCLUSIONS
                    }
                ) != value.get("payload_sha256"):
                    raise Stage3Rejected("SOURCE_IDENTITY_MISMATCH", f"payload digest: {path}")
                yield value


def _csv_rows(paths: list[Path], family: str) -> Iterator[dict[str, Any]]:
    fields = CSV_FIELDS[family]
    for path in paths:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle, dialect="excel", lineterminator="\n")
            if tuple(reader.fieldnames or ()) != fields:
                raise Stage3Rejected("FORMAT_VIOLATION", f"CSV header mismatch: {path}")
            for row in reader:
                if None in row or any(value is None for value in row.values()):
                    raise Stage3Rejected("FORMAT_VIOLATION", f"CSV width mismatch: {path}")
                value: dict[str, Any] = {
                    key: int(item) if key in _INTEGER_FIELDS else item
                    for key, item in row.items()
                    if item != ""
                }
                if canonical_digest(
                    {
                        key: item
                        for key, item in value.items()
                        if key not in SOURCE_DIGEST_EXCLUSIONS
                    }
                ) != value.get("payload_sha256"):
                    raise Stage3Rejected("SOURCE_IDENTITY_MISMATCH", f"CSV payload digest: {path}")
                yield value


def _paths(root: Path, form: str, family: str, suffix: str) -> list[Path]:
    result = sorted((root / form / family.lower().replace("_", "-")).glob(f"*.{suffix}"))
    if not result:
        raise Stage3Rejected("ASSET_VIOLATION", f"missing {form} {family}")
    return result


def _compare_raw_canonical(root: Path, family: str) -> int:
    canonical = _json_rows(_paths(root, "canonical", family, "jsonl"))
    if family in CSV_FIELDS:
        raw = _csv_rows(_paths(root, "raw", family, "csv"), family)
    else:
        raw = _json_rows(_paths(root, "raw", family, "jsonl"))
    count = 0
    while True:
        try:
            left = next(raw)
        except StopIteration:
            left = None
        try:
            right = next(canonical)
        except StopIteration:
            right = None
        if left is None or right is None:
            if left != right:
                raise Stage3Rejected("NORMALIZATION_MISMATCH", f"row count differs: {family}")
            break
        if left != right:
            raise Stage3Rejected("NORMALIZATION_MISMATCH", f"row differs: {family}:{count}")
        count += 1
    return count


def verify_assets(root: Path) -> ReadbackResult:
    root = root.resolve()
    if not (root / "COMPLETED.json").is_file():
        raise Stage3Rejected("PARTIAL_OUTPUT", "completion marker unavailable")
    asset = _load_object(root / "asset-manifest.json")
    completion = _load_object(root / "COMPLETED.json")
    digest_value = asset.get("asset_manifest_sha256")
    if (
        canonical_digest(
            {key: value for key, value in asset.items() if key != "asset_manifest_sha256"}
        )
        != digest_value
    ):
        raise Stage3Rejected("ASSET_VIOLATION", "asset manifest digest mismatch")
    if completion.get("asset_manifest_sha256") != digest_value:
        raise Stage3Rejected("PARTIAL_OUTPUT", "completion marker mismatch")
    scenario = _load_object(root / "scenario-inventory.json")
    if canonical_digest(
        {key: value for key, value in scenario.items() if key != "scenario_inventory_sha256"}
    ) != scenario.get("scenario_inventory_sha256"):
        raise Stage3Rejected("ASSET_VIOLATION", "scenario inventory digest mismatch")
    files = asset.get("files")
    if not isinstance(files, list):
        raise Stage3Rejected("ASSET_VIOLATION", "file inventory unavailable")
    seen: set[str] = set()
    for row in files:
        if not isinstance(row, dict) or not isinstance(row.get("path"), str):
            raise Stage3Rejected("ASSET_VIOLATION", "invalid inventory row")
        relative = row["path"]
        if relative in seen or relative.startswith("/") or ".." in Path(relative).parts:
            raise Stage3Rejected("ASSET_VIOLATION", "unsafe or duplicate inventory path")
        seen.add(relative)
        path = root / relative
        size, digest = _file_identity(path)
        if size != row.get("size_bytes") or digest != row.get("sha256"):
            raise Stage3Rejected("ASSET_VIOLATION", f"file identity mismatch: {relative}")
    counts = {family: _compare_raw_canonical(root, family) for family in FAMILIES}
    expectations = _load_object(root / "expectations.json")
    if counts != expectations.get("counts"):
        raise Stage3Rejected("EXPECTATION_MISMATCH", "construction count mismatch")
    totals: dict[str, dict[str, int]] = {}

    def add(currency: str, field: str, amount: int) -> None:
        totals.setdefault(currency, {}).setdefault(field, 0)
        totals[currency][field] += amount

    for row in _json_rows(_paths(root, "canonical", "PROCESSOR_EVENTS", "jsonl")):
        sign = 1 if row["event_type"] == "CAPTURE" else -1
        add(str(row["currency"]), "processor_transaction_minor", sign * int(row["amount_minor"]))
    for row in _json_rows(_paths(root, "canonical", "PROCESSOR_SETTLEMENTS", "jsonl")):
        net = int(row["gross_minor"])
        for field in ("fee_minor", "refund_minor", "chargeback_minor", "reserve_minor"):
            net -= int(row[field])
        if net != row["reported_net_minor"]:
            raise Stage3Rejected("EXPECTATION_MISMATCH", "settlement formula mismatch")
        add(str(row["currency"]), "processor_settlement_minor", net)
    for row in _json_rows(_paths(root, "canonical", "LEDGER_JOURNALS", "jsonl")):
        clearing = [
            item for item in row["postings"] if item["account_role"] == "PROCESSOR_CLEARING"
        ]
        if len(clearing) != 1:
            raise Stage3Rejected("EXPECTATION_MISMATCH", "clearing role count")
        posting = clearing[0]
        if row["entry_type"] == "SETTLEMENT":
            sign = 1 if posting["side"] == "CREDIT" else -1
            field = "ledger_settlement_minor"
        else:
            sign = 1 if posting["side"] == "DEBIT" else -1
            field = "ledger_transaction_minor"
        add(str(row["currency"]), field, sign * int(posting["amount_minor"]))
    for row in _json_rows(_paths(root, "canonical", "BANK_ENTRIES", "jsonl")):
        sign = 1 if row["direction"] == "CREDIT" else -1
        add(str(row["currency"]), "bank_minor", sign * int(row["amount_minor"]))
    for currency, values in totals.items():
        if values.get("processor_transaction_minor") != values.get("ledger_transaction_minor"):
            raise Stage3Rejected("EXPECTATION_MISMATCH", f"transaction total: {currency}")
        expected = values.get("processor_settlement_minor")
        if expected != values.get("ledger_settlement_minor") or expected != values.get(
            "bank_minor"
        ):
            raise Stage3Rejected("EXPECTATION_MISMATCH", f"settlement total: {currency}")
    logical = canonical_digest({"counts": counts, "currency_totals": totals})
    return ReadbackResult(
        str(asset["dataset_id"]),
        str(asset["run_id"]),
        counts,
        totals,
        len(files),
        logical,
    )
