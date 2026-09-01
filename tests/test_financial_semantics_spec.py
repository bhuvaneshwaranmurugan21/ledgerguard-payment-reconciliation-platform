"""Executable acceptance examples for the Stage 1 financial specification.

These helpers verify frozen decisions and examples. They are not a reconciliation engine and are
deliberately kept under tests rather than the public package.
"""

from __future__ import annotations

import json
import unicodedata
from collections.abc import Mapping
from copy import deepcopy
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
SEMANTICS: dict[str, Any] = json.loads(
    (ROOT / "spec" / "financial-semantics-v1.json").read_text(encoding="utf-8")
)
EXAMPLES: dict[str, Any] = json.loads(
    (ROOT / "spec" / "financial-examples-v1.json").read_text(encoding="utf-8")
)
EVIDENCE: dict[str, Any] = json.loads(
    (ROOT / "evidence" / "part1-stage1-local.json").read_text(encoding="utf-8")
)
INT64_MIN = -(2**63)
INT64_MAX = 2**63 - 1


def _int64(value: int) -> int:
    if value < INT64_MIN or value > INT64_MAX:
        raise ValueError("signed 64-bit overflow")
    return value


def _normalize_unicode(value: Any) -> Any:
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, list):
        return [_normalize_unicode(item) for item in value]
    if isinstance(value, dict):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            canonical_key = unicodedata.normalize("NFC", key)
            if canonical_key in normalized:
                raise ValueError("Unicode-normalized object-key collision")
            normalized[canonical_key] = _normalize_unicode(item)
        return normalized
    return value


def _canonical_timestamp(value: str) -> str:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include an offset")
    canonical = parsed.astimezone(UTC).isoformat(timespec="microseconds")
    date_part, offset = canonical.split("+")
    date_part = date_part.rstrip("0").rstrip(".")
    return f"{date_part}Z" if offset == "00:00" else canonical


def _canonical(value: Any) -> bytes:
    return json.dumps(
        _normalize_unicode(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def _business_digest(record: Mapping[str, Any]) -> str:
    exclusions = set(SEMANTICS["canonical_identity"]["business_digest_excludes"])
    business = {
        key: _canonical_timestamp(value)
        if key.endswith("_at") and isinstance(value, str)
        else value
        for key, value in record.items()
        if key not in exclusions
    }
    return sha256(_canonical(business)).hexdigest()


def _status(difference: int, tolerance: int, semantic_reasons: list[str]) -> str:
    if tolerance < 0:
        raise ValueError("tolerance must be non-negative")
    if semantic_reasons:
        return "EXCEPTION"
    if difference == 0:
        return "MATCHED"
    if difference <= tolerance:
        return "WITHIN_TOLERANCE"
    return "EXCEPTION"


def _transaction_result(case: Mapping[str, Any]) -> dict[str, Any]:
    values = case["input"]
    reasons: list[str] = []
    if values["processor_currency"] != values["ledger_currency"]:
        return {
            "outcome": "ADMISSION_REJECTED",
            "authoritative_proof": False,
            "reason_codes": ["CURRENCY_DOMAIN_VIOLATION"],
        }
    if not values["account_role_valid"]:
        reasons.append("INVALID_ACCOUNT_ROLE")
    if values["processor_record_count"] == 0:
        reasons.append("MISSING_PROCESSOR_ACTIVITY")
    if values["ledger_journal_count"] == 0:
        reasons.append("MISSING_LEDGER_MOVEMENT")
    if values["event_type"] != "CAPTURE" and not values["reference_resolved"]:
        reasons.append("UNRESOLVED_REFERENCE")
    processor = _int64(
        SEMANTICS["transaction"]["processor_sign"][values["event_type"]]
        * values["processor_amount_minor"]
    )
    ledger = _int64(
        SEMANTICS["transaction"]["ledger_side_sign"][values["ledger_side"]]
        * values["ledger_amount_minor"]
    )
    delta = _int64(processor - ledger)
    difference = _int64(abs(delta))
    result_status = _status(difference, values["tolerance_minor"], reasons)
    if result_status == "WITHIN_TOLERANCE":
        reasons.append(SEMANTICS["status"]["tolerance_reason"])
    elif result_status == "EXCEPTION" and not reasons:
        reasons.append("PROCESSOR_LEDGER_MISMATCH")
    return {
        "processor_minor": processor,
        "ledger_minor": ledger,
        "processor_ledger_delta_minor": delta,
        "difference_minor": difference,
        "status": result_status,
        "reason_codes": sorted(reasons),
    }


def _settlement_result(case: Mapping[str, Any]) -> dict[str, Any]:
    values = case["input"]
    expected_net = _int64(values["gross_minor"] - values["fee_minor"])
    expected_net = _int64(expected_net - values["refund_minor"])
    expected_net = _int64(expected_net - values["chargeback_minor"])
    expected_net = _int64(expected_net - values["reserve_minor"])
    reasons: list[str] = []
    if expected_net != values["reported_net_minor"]:
        reasons.append("SETTLEMENT_FORMULA_MISMATCH")
    if values["processor_settlement_count"] == 0:
        reasons.append("MISSING_PROCESSOR_ACTIVITY")
    if expected_net != 0 and values["ledger_journal_count"] == 0:
        reasons.append("MISSING_LEDGER_MOVEMENT")
    ledger_side = values["ledger_side"]
    ledger = 0
    if ledger_side is not None:
        ledger = _int64(
            SEMANTICS["settlement"]["ledger_side_sign"][ledger_side] * values["ledger_amount_minor"]
        )
    seen_bank_ids: set[str] = set()
    bank = 0
    allocated_count = 0
    unallocated_count = 0
    expected_reference = unicodedata.normalize("NFC", values["settlement_reference"]).strip()
    permitted_accounts = set(values["permitted_bank_account_ids"])
    for entry in values["bank_entries"]:
        bank_id = entry["bank_record_id"]
        if bank_id in seen_bank_ids:
            reasons.append("DUPLICATE_BANK_MOVEMENT")
            continue
        seen_bank_ids.add(bank_id)
        if entry["bank_account_id"] not in permitted_accounts:
            reasons.append("INVALID_BANK_ACCOUNT")
            continue
        bank_reference = unicodedata.normalize("NFC", entry["settlement_reference"]).strip()
        if bank_reference != expected_reference:
            unallocated_count += 1
            continue
        allocated_count += 1
        bank = _int64(
            bank
            + SEMANTICS["settlement"]["bank_side_sign"][entry["direction"]] * entry["amount_minor"]
        )
    if unallocated_count:
        reasons.append("UNALLOCATED_BANK_MOVEMENT")
    if expected_net != 0 and allocated_count == 0:
        reasons.append("MISSING_BANK_SETTLEMENT")
    processor_ledger = _int64(expected_net - ledger)
    processor_bank = _int64(expected_net - bank)
    ledger_bank = _int64(ledger - bank)
    difference = _int64(max(abs(processor_ledger), abs(processor_bank), abs(ledger_bank)))
    result_status = _status(difference, values["tolerance_minor"], reasons)
    if result_status == "WITHIN_TOLERANCE":
        reasons.append(SEMANTICS["status"]["tolerance_reason"])
    elif result_status == "EXCEPTION" and not reasons:
        if processor_ledger:
            reasons.append("PROCESSOR_LEDGER_MISMATCH")
        if processor_bank:
            reasons.append("PROCESSOR_BANK_MISMATCH")
        if ledger_bank:
            reasons.append("LEDGER_BANK_MISMATCH")
    return {
        "processor_net_minor": expected_net,
        "ledger_clearing_minor": ledger,
        "bank_minor": bank,
        "processor_ledger_delta_minor": processor_ledger,
        "processor_bank_delta_minor": processor_bank,
        "ledger_bank_delta_minor": ledger_bank,
        "difference_minor": difference,
        "allocated_bank_count": allocated_count,
        "unallocated_bank_count": unallocated_count,
        "status": result_status,
        "reason_codes": sorted(set(reasons)),
    }


def _ids(values: list[Mapping[str, Any]]) -> list[str]:
    return [str(value["id"]) for value in values]


def _capture_capacity_result(captured: int, applied: int) -> dict[str, Any]:
    remaining = captured - applied
    reasons = ["OVER_APPLIED_REFERENCE"] if remaining < 0 else []
    return {
        "remaining_capacity_minor": remaining,
        "status": "EXCEPTION" if reasons else "VALID",
        "reason_codes": reasons,
    }


def _bank_allocation_result(bank_reference: str, candidate_references: list[str]) -> dict[str, Any]:
    normalized_bank = unicodedata.normalize("NFC", bank_reference).strip()
    matches = [
        value
        for value in candidate_references
        if unicodedata.normalize("NFC", value).strip() == normalized_bank
    ]
    if len(matches) > 1:
        return {
            "outcome": "ADMISSION_REJECTED",
            "authoritative_proof": False,
            "reason_codes": ["AMBIGUOUS_BANK_ALLOCATION"],
        }
    return {
        "outcome": "ALLOCATED" if len(matches) == 1 else "UNALLOCATED",
        "authoritative_proof": None,
        "reason_codes": [] if matches else ["UNALLOCATED_BANK_MOVEMENT"],
    }


def test_semantic_decision_inventory_is_closed_and_complete() -> None:
    decisions = SEMANTICS["decisions"]
    decision_ids = _ids(decisions)
    assert decision_ids == [f"SEM-{number:03d}" for number in range(1, 19)]
    assert len(decision_ids) == len(set(decision_ids))
    assert all(decision["state"] == "FROZEN" for decision in decisions)
    assert SEMANTICS["unresolved_decisions"] == []
    assert SEMANTICS["state"] == "PART1_FINANCIAL_SEMANTICS_FROZEN"


def test_failure_ownership_is_disjoint() -> None:
    ownership = SEMANTICS["failure_ownership"]
    admission = set(ownership["ADMISSION"])
    financial = set(ownership["FINANCIAL_EXCEPTION"])
    execution = set(ownership["EXECUTION"])
    assert admission.isdisjoint(financial)
    assert admission.isdisjoint(execution)
    assert financial.isdisjoint(execution)
    assert ownership["admission_failure_authoritative_proof"] == "FORBIDDEN"
    assert ownership["execution_failure_authoritative_partial_proof"] == "FORBIDDEN"


@pytest.mark.parametrize("case", EXAMPLES["transaction_cases"], ids=lambda case: case["name"])
def test_transaction_examples(case: Mapping[str, Any]) -> None:
    assert _transaction_result(case) == case["expected"]


@pytest.mark.parametrize("case", EXAMPLES["settlement_cases"], ids=lambda case: case["name"])
def test_settlement_examples(case: Mapping[str, Any]) -> None:
    assert _settlement_result(case) == case["expected"]


def test_identity_replay_conflict_and_unicode_rules() -> None:
    original = {
        "schema_version": "1.0",
        "source_record_id": "capture-1",
        "source_batch_id": "batch-1",
        "processor": "processor-a",
        "merchant_id": "merchant-1",
        "payment_id": "payment-1",
        "event_type": "CAPTURE",
        "amount_minor": 10000,
        "currency": "INR",
        "occurred_at": "2026-09-01T01:00:00Z",
        "received_at": "2026-09-01T01:01:00Z",
        "payload_sha256": "a" * 64,
    }
    replay = dict(original, source_batch_id="batch-2", received_at="2026-09-01T02:00:00Z")
    conflict = dict(original, amount_minor=10001)
    unicode_nfc = dict(original, merchant_id="Caf\u00e9")
    unicode_nfd = dict(original, merchant_id="Cafe\u0301")
    assert _business_digest(original) == _business_digest(replay)
    assert _business_digest(original) != _business_digest(conflict)
    assert _business_digest(unicode_nfc) == _business_digest(unicode_nfd)


def test_canonical_timestamp_offsets_are_stable_and_naive_time_fails() -> None:
    original = {
        "source_record_id": "capture-1",
        "occurred_at": "2026-09-01T01:00:00Z",
    }
    equivalent = dict(original, occurred_at="2026-09-01T06:30:00+05:30")
    assert _business_digest(original) == _business_digest(equivalent)
    with pytest.raises(ValueError, match="offset"):
        _business_digest(dict(original, occurred_at="2026-09-01T01:00:00"))


def test_canonicalization_rejects_unicode_key_collision() -> None:
    with pytest.raises(ValueError, match="object-key collision"):
        _canonical({"Caf\u00e9": 1, "Cafe\u0301": 2})


def test_negative_application_cannot_exceed_capture() -> None:
    capacity = EXAMPLES["capture_capacity_case"]
    assert (
        _capture_capacity_result(capacity["captured_minor"], capacity["negative_applied_minor"])
        == capacity["expected"]
    )


def test_ambiguous_bank_reference_fails_admission_without_proof() -> None:
    case = EXAMPLES["ambiguous_bank_allocation_case"]
    result = _bank_allocation_result(
        case["bank_reference"], case["candidate_settlement_references"]
    )
    assert result["outcome"] == case["expected_outcome"]
    assert result["reason_codes"] == [case["expected_reason"]]
    assert result["authoritative_proof"] is False


def test_negative_tolerance_is_rejected() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        _status(0, -1, [])


def test_settlement_arithmetic_overflow_fails_admission() -> None:
    case = deepcopy(EXAMPLES["settlement_cases"][1])
    case["input"].update(
        {
            "gross_minor": 0,
            "fee_minor": 0,
            "refund_minor": INT64_MAX,
            "chargeback_minor": 1,
            "reserve_minor": 1,
        }
    )
    with pytest.raises(ValueError, match="overflow"):
        _settlement_result(case)


def test_transaction_difference_above_tolerance_has_exact_reason() -> None:
    case = deepcopy(EXAMPLES["transaction_cases"][0])
    case["input"]["ledger_amount_minor"] = 9998
    case["input"]["tolerance_minor"] = 1
    result = _transaction_result(case)
    assert result["difference_minor"] == 2
    assert result["status"] == "EXCEPTION"
    assert result["reason_codes"] == ["PROCESSOR_LEDGER_MISMATCH"]


def test_transaction_missing_ledger_is_not_treated_as_zero() -> None:
    case = deepcopy(EXAMPLES["transaction_cases"][0])
    case["input"]["ledger_journal_count"] = 0
    case["input"]["ledger_amount_minor"] = 0
    result = _transaction_result(case)
    assert result["difference_minor"] == 10000
    assert result["status"] == "EXCEPTION"
    assert result["reason_codes"] == ["MISSING_LEDGER_MOVEMENT"]


def test_duplicate_bank_identity_is_not_allocated_twice() -> None:
    case = deepcopy(EXAMPLES["settlement_cases"][0])
    duplicate = dict(case["input"]["bank_entries"][0])
    duplicate["amount_minor"] = 1
    case["input"]["bank_entries"].append(duplicate)
    result = _settlement_result(case)
    assert result["bank_minor"] == 80000
    assert result["status"] == "EXCEPTION"
    assert result["reason_codes"] == ["DUPLICATE_BANK_MOVEMENT"]


def test_disallowed_bank_account_is_not_allocated() -> None:
    case = deepcopy(EXAMPLES["settlement_cases"][0])
    for entry in case["input"]["bank_entries"]:
        entry["bank_account_id"] = "bank-account-unapproved"
    result = _settlement_result(case)
    assert result["bank_minor"] == 0
    assert result["allocated_bank_count"] == 0
    assert result["status"] == "EXCEPTION"
    assert result["reason_codes"] == ["INVALID_BANK_ACCOUNT", "MISSING_BANK_SETTLEMENT"]


def test_bank_reference_is_unicode_normalized_trimmed_and_case_sensitive() -> None:
    case = deepcopy(EXAMPLES["settlement_cases"][0])
    case["input"]["settlement_reference"] = "  settleme\u0301nt-1  "
    for entry in case["input"]["bank_entries"]:
        entry["settlement_reference"] = "settlem\u00e9nt-1"
    normalized_result = _settlement_result(case)
    assert normalized_result["status"] == "MATCHED"
    case["input"]["bank_entries"][0]["settlement_reference"] = "SETTLEMENT-1"
    case_sensitive_result = _settlement_result(case)
    assert case_sensitive_result["status"] == "EXCEPTION"
    assert "UNALLOCATED_BANK_MOVEMENT" in case_sensitive_result["reason_codes"]


def test_stage_one_does_not_add_reconciliation_implementation() -> None:
    package_files = {path.name for path in (ROOT / "src" / "ledgerguard").glob("*.py")}
    assert package_files == {
        "__init__.py",
        "foundation.py",
        "part1.py",
        "stage0.py",
        "stage1.py",
    }


def test_stage_one_evidence_binds_exact_specification_bytes() -> None:
    semantic_evidence = EVIDENCE["semantic_specification"]
    example_evidence = EVIDENCE["acceptance_examples"]
    semantic_path = ROOT / semantic_evidence["path"]
    example_path = ROOT / example_evidence["path"]
    assert sha256(semantic_path.read_bytes()).hexdigest() == semantic_evidence["sha256"]
    assert sha256(example_path.read_bytes()).hexdigest() == example_evidence["sha256"]
    assert semantic_evidence["decision_count"] == len(SEMANTICS["decisions"])
    assert semantic_evidence["unresolved_decision_count"] == len(SEMANTICS["unresolved_decisions"])
    assert EVIDENCE["stage_state"] == SEMANTICS["state"]
    for key, value in SEMANTICS["claim_boundary"].items():
        assert EVIDENCE["claim_boundary"][key] == value
