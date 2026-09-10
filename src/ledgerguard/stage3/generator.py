"""Streaming, deterministic, counter-derived Stage 3 source generation."""

from __future__ import annotations

import os
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any

from .canonical import canonical_bytes, canonical_digest, semantic_id
from .errors import Stage3Rejected
from .formats import CSV_FIELDS, FAMILIES, SOURCE_DIGEST_EXCLUSIONS
from .profiles import Profile, validate_profile
from .scenarios import scenario_inventory


@dataclass(frozen=True)
class GenerationResult:
    root: Path
    profile_name: str
    dataset_id: str
    run_id: str
    source_bundle_sha256: str
    manifest_sha256: str
    asset_manifest_sha256: str
    counts: dict[str, int]


def _timestamp(profile: Profile, index: int, offset: int = 0) -> str:
    base = datetime.fromisoformat(profile.base_timestamp.replace("Z", "+00:00"))
    value = base + timedelta(seconds=index + offset)
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def _counter(profile: Profile, namespace: str, index: int) -> int:
    raw = f"{profile.profile_sha256}:{namespace}:{index}".encode()
    return int.from_bytes(sha256(raw).digest()[:8], "big")


def _merchant(profile: Profile, settlement_index: int) -> str:
    if (
        profile.merchant_count == 1
        or settlement_index % profile.skew_cycle < profile.skew_hotspot_slots
    ):
        merchant_index = 0
    else:
        merchant_index = 1 + _counter(profile, "merchant", settlement_index) % (
            profile.merchant_count - 1
        )
    return f"merchant-{merchant_index:03d}"


def _signed(record: dict[str, Any]) -> dict[str, Any]:
    result = dict(record)
    result["payload_sha256"] = canonical_digest(
        {key: value for key, value in result.items() if key not in SOURCE_DIGEST_EXCLUSIONS}
    )
    return result


def _event(profile: Profile, index: int, batch_id: str) -> dict[str, Any]:
    settlement_index = index // profile.events_per_settlement
    local = index % profile.events_per_settlement
    payment_index = index // 2
    event_type = (
        "CAPTURE"
        if local % 2 == 0
        else profile.negative_event_cycle[payment_index % len(profile.negative_event_cycle)]
    )
    capture_amount = 1_000 + (_counter(profile, "amount", payment_index) % 90_000)
    amount = capture_amount if event_type == "CAPTURE" else max(1, capture_amount // 3)
    record: dict[str, Any] = {
        "schema_version": "2.0",
        "source_record_id": f"evt-{index:09d}",
        "source_batch_id": batch_id,
        "processor": "processor-a",
        "merchant_id": _merchant(profile, settlement_index),
        "payment_id": f"payment-{payment_index:09d}",
        "event_type": event_type,
        "amount_minor": amount,
        "currency": profile.currencies[settlement_index % len(profile.currencies)],
        "occurred_at": _timestamp(profile, index),
        "received_at": _timestamp(profile, index, 60),
    }
    if event_type != "CAPTURE":
        record["reference_event_id"] = f"evt-{index - 1:09d}"
    return _signed(record)


def _transaction_journal(event: dict[str, Any], batch_id: str) -> dict[str, Any]:
    index = int(str(event["source_record_id"]).split("-")[1])
    capture = event["event_type"] == "CAPTURE"
    clearing_side = "DEBIT" if capture else "CREDIT"
    counterpart = {
        "CAPTURE": "MERCHANT_PAYABLE",
        "REFUND": "REFUND_LIABILITY",
        "CHARGEBACK": "CHARGEBACK_RESERVE",
        "REVERSAL": "MERCHANT_PAYABLE",
    }[str(event["event_type"])]
    return _signed(
        {
            "schema_version": "2.0",
            "journal_id": f"txn-journal-{index:09d}",
            "source_batch_id": batch_id,
            "ledger_system": "ledger-a",
            "processor": event["processor"],
            "merchant_id": event["merchant_id"],
            "payment_id": event["payment_id"],
            "entry_type": event["event_type"],
            "currency": event["currency"],
            "effective_at": event["occurred_at"],
            "received_at": event["received_at"],
            "postings": [
                {
                    "line_id": f"txn-line-{index:09d}-1",
                    "account_role": "PROCESSOR_CLEARING",
                    "side": clearing_side,
                    "amount_minor": event["amount_minor"],
                },
                {
                    "line_id": f"txn-line-{index:09d}-2",
                    "account_role": counterpart,
                    "side": "CREDIT" if clearing_side == "DEBIT" else "DEBIT",
                    "amount_minor": event["amount_minor"],
                },
            ],
        }
    )


def _settlement(profile: Profile, index: int, batch_id: str) -> dict[str, Any]:
    start = index * profile.events_per_settlement
    stop = min(start + profile.events_per_settlement, profile.processor_event_count)
    gross = 0
    refunds = 0
    chargebacks = 0
    for event_index in range(start, stop):
        event = _event(profile, event_index, batch_id)
        if event["event_type"] == "CAPTURE":
            gross += int(event["amount_minor"])
        elif event["event_type"] in {"REFUND", "REVERSAL"}:
            refunds += int(event["amount_minor"])
        else:
            chargebacks += int(event["amount_minor"])
    merchant = _merchant(profile, index)
    currency = profile.currencies[index % len(profile.currencies)]
    fee = gross // 100
    reserve = gross // 200
    net = gross - fee - refunds - chargebacks - reserve
    return _signed(
        {
            "schema_version": "2.0",
            "source_record_id": f"settlement-record-{index:08d}",
            "source_batch_id": batch_id,
            "processor": "processor-a",
            "merchant_id": merchant,
            "settlement_id": f"settlement-{index:08d}",
            "settlement_cycle": f"cycle-{index:08d}",
            "currency": currency,
            "gross_minor": gross,
            "fee_minor": fee,
            "refund_minor": refunds,
            "chargeback_minor": chargebacks,
            "reserve_minor": reserve,
            "reported_net_minor": net,
            "occurred_at": _timestamp(profile, start, 3_600),
            "received_at": _timestamp(profile, start, 3_660),
        }
    )


def _settlement_journal(settlement: dict[str, Any], batch_id: str) -> dict[str, Any]:
    index = int(str(settlement["settlement_id"]).split("-")[1])
    amount = int(settlement["reported_net_minor"])
    return _signed(
        {
            "schema_version": "2.0",
            "journal_id": f"stl-journal-{index:08d}",
            "source_batch_id": batch_id,
            "ledger_system": "ledger-a",
            "processor": settlement["processor"],
            "merchant_id": settlement["merchant_id"],
            "settlement_id": settlement["settlement_id"],
            "settlement_cycle": settlement["settlement_cycle"],
            "entry_type": "SETTLEMENT",
            "currency": settlement["currency"],
            "effective_at": settlement["occurred_at"],
            "received_at": settlement["received_at"],
            "postings": [
                {
                    "line_id": f"stl-line-{index:08d}-1",
                    "account_role": "PROCESSOR_CLEARING",
                    "side": "CREDIT",
                    "amount_minor": amount,
                },
                {
                    "line_id": f"stl-line-{index:08d}-2",
                    "account_role": "MERCHANT_PAYABLE",
                    "side": "DEBIT",
                    "amount_minor": amount,
                },
            ],
        }
    )


def _bank_entries(
    profile: Profile, settlement: dict[str, Any], batch_id: str
) -> Iterable[dict[str, Any]]:
    index = int(str(settlement["settlement_id"]).split("-")[1])
    total = int(settlement["reported_net_minor"])
    pieces = (
        (total // 2, total - total // 2)
        if index % profile.split_every_settlements == 0
        else (total,)
    )
    for piece_index, amount in enumerate(pieces):
        yield _signed(
            {
                "schema_version": "2.0",
                "bank_record_id": f"bank-{index:08d}-{piece_index}",
                "source_batch_id": batch_id,
                "bank_account_id": (
                    f"bank-{settlement['merchant_id']}-{str(settlement['currency']).lower()}"
                ),
                "merchant_id": settlement["merchant_id"],
                "settlement_reference": settlement["settlement_id"],
                "direction": "CREDIT",
                "amount_minor": amount,
                "currency": settlement["currency"],
                "value_at": settlement["occurred_at"],
                "received_at": settlement["received_at"],
            }
        )


class _Writer:
    def __init__(
        self, root: Path, family: str, form: str, suffix: str, limit: int, header: bytes = b""
    ) -> None:
        self.root = root
        self.family = family
        self.form = form
        self.suffix = suffix
        self.limit = limit
        self.header = header
        self.descriptors: list[dict[str, Any]] = []
        self._file: Any = None
        self._hash = sha256()
        self._rows = 0
        self._bytes = 0
        self._first = 0
        self._index = 0

    def _open(self) -> None:
        directory = self.root / self.form / self.family.lower().replace("_", "-")
        directory.mkdir(parents=True, exist_ok=True)
        stem = self.family.lower().replace("_", "-")
        relative = f"{self.form}/{stem}/part-{self._index:05d}.{self.suffix}"
        self._path = self.root / relative
        self._relative = relative
        self._file = self._path.open("xb")
        self._hash = sha256()
        self._rows = 0
        self._bytes = 0
        self._first = self._index * self.limit
        if self.header:
            self._write(self.header)

    def _write(self, raw: bytes) -> None:
        self._file.write(raw)
        self._hash.update(raw)
        self._bytes += len(raw)

    def add(self, raw: bytes) -> None:
        if self._file is None:
            self._open()
        if self._rows == self.limit:
            self.close_shard()
            self._index += 1
            self._open()
        self._write(raw)
        self._rows += 1

    def close_shard(self) -> None:
        if self._file is None:
            return
        self._file.flush()
        os.fsync(self._file.fileno())
        self._file.close()
        self.descriptors.append(
            {
                "family": self.family,
                "relative_path": self._relative,
                "record_count": self._rows,
                "size_bytes": self._bytes,
                "sha256": self._hash.hexdigest(),
                "first_logical_index": self._first,
                "last_logical_index": self._first + self._rows - 1,
            }
        )
        self._file = None

    def close(self) -> None:
        self.close_shard()


def _csv_line(record: dict[str, Any], fields: tuple[str, ...]) -> bytes:
    values: list[str] = []
    for field in fields:
        value = record.get(field, "")
        text = str(value)
        if any(character in text for character in (",", '"', "\r", "\n")):
            text = '"' + text.replace('"', '""') + '"'
        values.append(text)
    return (",".join(values) + "\n").encode("utf-8")


def _policy(profile: Profile) -> dict[str, Any]:
    accounts = []
    for merchant_index in range(profile.merchant_count):
        merchant = f"merchant-{merchant_index:03d}"
        for currency in profile.currencies:
            accounts.append(
                {
                    "merchant_id": merchant,
                    "currency": currency,
                    "bank_account_ids": [f"bank-{merchant}-{currency.lower()}"],
                }
            )
    value: dict[str, Any] = {
        "schema_version": "2.0",
        "policy_version": "v1",
        "currency_rules": {
            "INR": {
                "exponent": 2,
                "transaction_tolerance_minor": 0,
                "settlement_tolerance_minor": 1,
            },
            "JPY": {
                "exponent": 0,
                "transaction_tolerance_minor": 0,
                "settlement_tolerance_minor": 1,
            },
            "USD": {
                "exponent": 2,
                "transaction_tolerance_minor": 0,
                "settlement_tolerance_minor": 1,
            },
        },
        "transaction_rules": {
            "event_signs": {"CAPTURE": 1, "REFUND": -1, "CHARGEBACK": -1, "REVERSAL": -1},
            "ledger_role": "PROCESSOR_CLEARING",
            "ledger_side_signs": {"DEBIT": 1, "CREDIT": -1},
            "allowed_counterpart_roles": [
                "MERCHANT_PAYABLE",
                "REFUND_LIABILITY",
                "CHARGEBACK_RESERVE",
            ],
            "reference_rules": {
                "capture_reference": "FORBIDDEN",
                "negative_event_reference": "EXACT_CAPTURE_REFERENCE",
                "negative_reference_chain_forbidden": True,
                "cumulative_negative_must_not_exceed_capture": True,
            },
        },
        "settlement_rules": {
            "formula": "gross_minor-fee_minor-refund_minor-chargeback_minor-reserve_minor",
            "reported_net_must_equal_recomputed_net": True,
            "expected_net_may_be_negative": True,
            "ledger_role": "PROCESSOR_CLEARING",
            "ledger_side_signs": {"DEBIT": -1, "CREDIT": 1},
            "bank_side_signs": {"CREDIT": 1, "DEBIT": -1},
            "bank_allocation": {
                "strategy": "EXACT_SETTLEMENT_REFERENCE",
                "normalization": ["UNICODE_NFC", "TRIM_OUTER_WHITESPACE"],
                "case_sensitive": True,
                "punctuation_preserved": True,
                "amount_date_heuristic_forbidden": True,
                "ambiguous_reference": "FAIL_ADMISSION",
                "one_bank_identity_one_allocation": True,
                "split_entries_allowed": True,
                "unknown_reference": "UNALLOCATED_BANK_MOVEMENT",
            },
            "permitted_bank_accounts": accounts,
        },
        "status_rules": {
            "matched": "ZERO_DIFFERENCE_AND_NO_REASON",
            "within_tolerance": "NONZERO_DIFFERENCE_WITHIN_BOUND_AND_ONLY_TOLERATED_REASON",
            "exception": "SEMANTIC_REASON_OR_DIFFERENCE_ABOVE_TOLERANCE",
            "tolerance_cannot_hide": [
                "ADMISSION_FAILURE",
                "IDENTITY_CONFLICT",
                "MISSING_EVIDENCE",
                "REFERENCE_FAILURE",
                "POLICY_FAILURE",
                "SETTLEMENT_FORMULA_MISMATCH",
            ],
        },
        "late_data_strategy": "NEW_IMMUTABLE_REVISION",
    }
    value["policy_sha256"] = canonical_digest(value)
    return value


def _write_document(path: Path, value: Any) -> str:
    raw = canonical_bytes(value) + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    return sha256(raw).hexdigest()


def _writers(root: Path, profile: Profile) -> dict[tuple[str, str], _Writer]:
    result: dict[tuple[str, str], _Writer] = {}
    for family in FAMILIES:
        result[(family, "canonical")] = _Writer(
            root, family, "canonical", "jsonl", profile.shard_rows
        )
        if family in CSV_FIELDS:
            fields = CSV_FIELDS[family]
            result[(family, "raw")] = _Writer(
                root, family, "raw", "csv", profile.shard_rows, (",".join(fields) + "\n").encode()
            )
        else:
            result[(family, "raw")] = _Writer(root, family, "raw", "jsonl", profile.shard_rows)
    return result


def generate_profile(profile: Profile, destination: Path, source_commit: str) -> GenerationResult:
    validate_profile(profile)
    if len(source_commit) != 40 or any(
        character not in "0123456789abcdef" for character in source_commit
    ):
        raise Stage3Rejected("PROFILE_VIOLATION", "source commit must be lowercase SHA-1")
    destination = destination.resolve()
    if destination.exists():
        raise Stage3Rejected("PARTIAL_OUTPUT", "destination already exists")
    partial = destination.with_name(f".{destination.name}.partial")
    if partial.exists():
        raise Stage3Rejected("PARTIAL_OUTPUT", "partial destination already exists")
    partial.mkdir(parents=True)
    dataset_id = profile.dataset_id
    run_id = semantic_id("run", {"dataset_id": dataset_id, "source_commit": source_commit})
    batch_id = semantic_id("batch", {"dataset_id": dataset_id})
    writers = _writers(partial, profile)
    counts = {family: 0 for family in FAMILIES}
    try:
        for index in range(profile.processor_event_count):
            event = _event(profile, index, batch_id)
            journal = _transaction_journal(event, batch_id)
            for family, record in (("PROCESSOR_EVENTS", event), ("LEDGER_JOURNALS", journal)):
                raw = canonical_bytes(record) + b"\n"
                writers[(family, "raw")].add(raw)
                writers[(family, "canonical")].add(raw)
                counts[family] += 1
        settlement_count = (
            profile.processor_event_count + profile.events_per_settlement - 1
        ) // profile.events_per_settlement
        for index in range(settlement_count):
            settlement = _settlement(profile, index, batch_id)
            journal = _settlement_journal(settlement, batch_id)
            canonical = canonical_bytes(settlement) + b"\n"
            writers[("PROCESSOR_SETTLEMENTS", "raw")].add(
                _csv_line(settlement, CSV_FIELDS["PROCESSOR_SETTLEMENTS"])
            )
            writers[("PROCESSOR_SETTLEMENTS", "canonical")].add(canonical)
            counts["PROCESSOR_SETTLEMENTS"] += 1
            journal_raw = canonical_bytes(journal) + b"\n"
            writers[("LEDGER_JOURNALS", "raw")].add(journal_raw)
            writers[("LEDGER_JOURNALS", "canonical")].add(journal_raw)
            counts["LEDGER_JOURNALS"] += 1
            for bank in _bank_entries(profile, settlement, batch_id):
                writers[("BANK_ENTRIES", "raw")].add(_csv_line(bank, CSV_FIELDS["BANK_ENTRIES"]))
                writers[("BANK_ENTRIES", "canonical")].add(canonical_bytes(bank) + b"\n")
                counts["BANK_ENTRIES"] += 1
        for writer in writers.values():
            writer.close()
        policy = _policy(profile)
        policy_sha = _write_document(partial / "policy.json", policy)
        profile_lock = {
            "schema_version": "1.0",
            "profile": profile.semantic_value(),
            "profile_sha256": profile.profile_sha256,
            "dataset_id": dataset_id,
        }
        profile_sha = _write_document(partial / "profile-lock.json", profile_lock)
        scenarios = scenario_inventory()
        scenario_sha = _write_document(partial / "scenario-inventory.json", scenarios)
        canonical_objects: list[dict[str, Any]] = []
        raw_objects: list[dict[str, Any]] = []
        for family in FAMILIES:
            for row in writers[(family, "canonical")].descriptors:
                canonical_objects.append(
                    {
                        "family": family,
                        "schema_version": "2.0",
                        "locator_type": "LOCAL_FILE",
                        "relative_path": row["relative_path"],
                        "size_bytes": row["size_bytes"],
                        "record_count": row["record_count"],
                        "sha256": row["sha256"],
                    }
                )
            raw_format = "CSV_RFC4180_LF" if family in CSV_FIELDS else "JSONL_CANONICAL_LF"
            for row in writers[(family, "raw")].descriptors:
                raw_objects.append({**row, "physical_format": raw_format, "schema_version": "2.0"})
        manifest: dict[str, Any] = {
            "schema_version": "2.0",
            "run_id": run_id,
            "source_commit": source_commit,
            "policy_version": "v1",
            "policy_sha256": policy["policy_sha256"],
            "created_at": profile.base_timestamp,
            "objects": canonical_objects,
        }
        manifest["manifest_sha256"] = canonical_digest(manifest)
        manifest_file_sha = _write_document(partial / "run-manifest.json", manifest)
        source_bundle: dict[str, Any] = {
            "schema_version": "1.0",
            "dataset_id": dataset_id,
            "run_id": run_id,
            "profile_sha256": profile.profile_sha256,
            "policy_sha256": policy["policy_sha256"],
            "manifest_sha256": manifest["manifest_sha256"],
            "objects": raw_objects,
            "normalization": "UNCHANGED_V2_CANONICAL_JSONL",
        }
        source_bundle["source_bundle_sha256"] = canonical_digest(source_bundle)
        source_bundle_file_sha = _write_document(partial / "source-bundle.json", source_bundle)
        expectations: dict[str, Any] = {
            "schema_version": "1.0",
            "dataset_id": dataset_id,
            "run_id": run_id,
            "counts": counts,
            "processor_event_count_semantics": profile.processor_event_count,
            "expected_status": "MATCHED",
            "authoritative_proof": False,
        }
        expectations["expectations_sha256"] = canonical_digest(expectations)
        expectations_file_sha = _write_document(partial / "expectations.json", expectations)
        inventory = [
            {
                "path": row["relative_path"],
                "size_bytes": row["size_bytes"],
                "sha256": row["sha256"],
            }
            for writer in writers.values()
            for row in writer.descriptors
        ]
        for relative, digest in (
            ("policy.json", policy_sha),
            ("profile-lock.json", profile_sha),
            ("scenario-inventory.json", scenario_sha),
            ("run-manifest.json", manifest_file_sha),
            ("source-bundle.json", source_bundle_file_sha),
            ("expectations.json", expectations_file_sha),
        ):
            inventory.append(
                {
                    "path": relative,
                    "size_bytes": (partial / relative).stat().st_size,
                    "sha256": digest,
                }
            )
        inventory.sort(key=lambda row: str(row["path"]))
        asset_manifest: dict[str, Any] = {
            "schema_version": "1.0",
            "dataset_id": dataset_id,
            "run_id": run_id,
            "profile_lock_file_sha256": profile_sha,
            "scenario_inventory_file_sha256": scenario_sha,
            "policy_file_sha256": policy_sha,
            "run_manifest_file_sha256": manifest_file_sha,
            "source_bundle_file_sha256": source_bundle_file_sha,
            "expectations_file_sha256": expectations_file_sha,
            "files": inventory,
            "authoritative_proof": False,
        }
        asset_manifest["asset_manifest_sha256"] = canonical_digest(asset_manifest)
        _write_document(partial / "asset-manifest.json", asset_manifest)
        completion = {
            "schema_version": "1.0",
            "asset_manifest_sha256": asset_manifest["asset_manifest_sha256"],
            "state": "COMPLETE_NON_AUTHORITATIVE_ASSET",
        }
        _write_document(partial / "COMPLETED.json", completion)
        partial.rename(destination)
    except BaseException:
        raise
    return GenerationResult(
        destination,
        profile.name,
        dataset_id,
        run_id,
        source_bundle["source_bundle_sha256"],
        manifest["manifest_sha256"],
        asset_manifest["asset_manifest_sha256"],
        counts,
    )
