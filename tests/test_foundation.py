from __future__ import annotations

import json
import shutil
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError

from ledgerguard.foundation import FoundationError, validate_foundation

ROOT = Path(__file__).resolve().parents[1]


def _schema(name: str) -> dict[str, object]:
    value: object = json.loads((ROOT / "contracts" / name).read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _validate(name: str, instance: dict[str, object]) -> None:
    Draft202012Validator(_schema(name), format_checker=FormatChecker()).validate(instance)


def _digest() -> str:
    return "a" * 64


def _copy_repository(tmp_path: Path) -> Path:
    destination = tmp_path / "repository"
    shutil.copytree(
        ROOT,
        destination,
        ignore=shutil.ignore_patterns(
            ".venv", ".mypy_cache", ".pytest_cache", ".ruff_cache", "__pycache__"
        ),
    )
    return destination


def test_complete_foundation_passes_deterministically() -> None:
    first = validate_foundation(ROOT)
    second = validate_foundation(ROOT)
    assert first == second
    assert first["state"] == "PART1_FOUNDATION_COMPLETE"
    assert first["aws_execution"] is False
    assert len(first["schema_digests"]) == 8
    assert len(first["foundation_sha256"]) == 64


def test_processor_event_contract_requires_reference_for_refund() -> None:
    event: dict[str, object] = {
        "schema_version": "1.0",
        "source_record_id": "evt-1",
        "source_batch_id": "processor-2026-09-01",
        "processor": "processor-a",
        "merchant_id": "merchant-1",
        "payment_id": "payment-1",
        "event_type": "CAPTURE",
        "amount_minor": 10000,
        "currency": "INR",
        "occurred_at": "2026-09-01T01:00:00Z",
        "received_at": "2026-09-01T01:00:01Z",
        "payload_sha256": _digest(),
    }
    _validate("processor-event-v1.schema.json", event)
    invalid = deepcopy(event)
    invalid["event_type"] = "REFUND"
    with pytest.raises(ValidationError):
        _validate("processor-event-v1.schema.json", invalid)
    invalid["reference_event_id"] = "evt-original"
    _validate("processor-event-v1.schema.json", invalid)


def test_journal_contract_requires_two_postings_and_a_business_key() -> None:
    journal: dict[str, object] = {
        "schema_version": "1.0",
        "journal_id": "journal-1",
        "source_batch_id": "ledger-2026-09-01",
        "merchant_id": "merchant-1",
        "payment_id": "payment-1",
        "settlement_id": None,
        "entry_type": "CAPTURE",
        "currency": "INR",
        "effective_at": "2026-09-01T01:00:00Z",
        "received_at": "2026-09-01T01:00:01Z",
        "postings": [
            {
                "line_id": "line-1",
                "account_role": "PROCESSOR_CLEARING",
                "side": "DEBIT",
                "amount_minor": 10000,
            },
            {
                "line_id": "line-2",
                "account_role": "MERCHANT_PAYABLE",
                "side": "CREDIT",
                "amount_minor": 10000,
            },
        ],
        "payload_sha256": _digest(),
    }
    _validate("journal-v1.schema.json", journal)
    invalid = deepcopy(journal)
    invalid["postings"] = invalid["postings"][:1]  # type: ignore[index]
    with pytest.raises(ValidationError):
        _validate("journal-v1.schema.json", invalid)


def test_bank_entry_has_no_payment_identity_requirement() -> None:
    entry: dict[str, object] = {
        "schema_version": "1.0",
        "bank_record_id": "bank-1",
        "source_batch_id": "bank-2026-09-01",
        "bank_account_id": "account-synthetic-1",
        "merchant_id": "merchant-1",
        "settlement_reference": "settlement-1",
        "direction": "CREDIT",
        "amount_minor": 9500,
        "currency": "INR",
        "value_at": "2026-09-02T01:00:00Z",
        "received_at": "2026-09-02T01:10:00Z",
        "payload_sha256": _digest(),
    }
    _validate("bank-entry-v1.schema.json", entry)
    assert "payment_id" not in entry


def test_settlement_and_policy_contracts_freeze_net_formula() -> None:
    settlement: dict[str, object] = {
        "schema_version": "1.0",
        "source_record_id": "payout-1",
        "source_batch_id": "payout-2026-09-01",
        "processor": "processor-a",
        "merchant_id": "merchant-1",
        "settlement_id": "settlement-1",
        "settlement_cycle": "2026-09-01",
        "currency": "INR",
        "gross_minor": 10000,
        "fee_minor": 500,
        "refund_minor": 0,
        "chargeback_minor": 0,
        "reserve_minor": 0,
        "expected_net_minor": 9500,
        "occurred_at": "2026-09-01T23:00:00Z",
        "received_at": "2026-09-01T23:10:00Z",
        "payload_sha256": _digest(),
    }
    _validate("processor-settlement-v1.schema.json", settlement)
    policy: dict[str, object] = {
        "schema_version": "1.0",
        "policy_version": "v1",
        "currency_exponents": {"INR": 2, "USD": 2, "JPY": 0},
        "transaction_tolerance_minor": {"INR": 0, "USD": 0, "JPY": 0},
        "settlement_tolerance_minor": {"INR": 0, "USD": 0, "JPY": 0},
        "settlement_formula": "".join(
            [
                "gross_minor-fee_minor-refund_minor-chargeback_minor-",
                "reserve_minor=expected_net_minor",
            ]
        ),
        "late_data_strategy": "NEW_IMMUTABLE_REVISION",
    }
    _validate("reconciliation-policy-v1.schema.json", policy)


def test_target_region_change_is_rejected(tmp_path: Path) -> None:
    repository = _copy_repository(tmp_path)
    path = repository / ".github/ledgerguard-target.json"
    target = json.loads(path.read_text(encoding="utf-8"))
    target["region"] = "us-east-1"
    path.write_text(json.dumps(target), encoding="utf-8")
    with pytest.raises(FoundationError, match="target region"):
        validate_foundation(repository)


def test_scorecard_target_at_or_below_seven_is_rejected(tmp_path: Path) -> None:
    repository = _copy_repository(tmp_path)
    path = repository / "contracts/project-completion-v1.json"
    completion = json.loads(path.read_text(encoding="utf-8"))
    completion["scorecard"]["performance_and_scale"] = 7
    path.write_text(json.dumps(completion), encoding="utf-8")
    with pytest.raises(FoundationError, match="above 7"):
        validate_foundation(repository)


def test_only_part_four_can_authorize_managed_workload(tmp_path: Path) -> None:
    repository = _copy_repository(tmp_path)
    path = repository / "contracts/project-completion-v1.json"
    completion = json.loads(path.read_text(encoding="utf-8"))
    completion["parts"][2]["aws_workload_allowed"] = True
    path.write_text(json.dumps(completion), encoding="utf-8")
    with pytest.raises(FoundationError, match="only in Part 4"):
        validate_foundation(repository)


def test_forbidden_presentation_document_is_rejected(tmp_path: Path) -> None:
    repository = _copy_repository(tmp_path)
    forbidden = repository / "docs" / "INTERVIEW.md"
    forbidden.write_text("not part of the engineering project", encoding="utf-8")
    with pytest.raises(FoundationError, match="forbidden repository paths"):
        validate_foundation(repository)
