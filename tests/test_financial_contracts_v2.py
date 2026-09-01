from __future__ import annotations

import json
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parents[1]
V2_DIR = ROOT / "contracts/v2"
SEMANTICS = json.loads((ROOT / "spec/financial-semantics-v1.json").read_text(encoding="utf-8"))
INVARIANTS = json.loads((ROOT / "spec/contract-invariants-v1.json").read_text(encoding="utf-8"))
TRACEABILITY = json.loads((ROOT / "spec/contract-traceability-v1.json").read_text(encoding="utf-8"))
ACTIVE = json.loads((ROOT / "contracts/active-contract-set-v1.json").read_text(encoding="utf-8"))


def _schemas() -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for path in sorted(V2_DIR.glob("*.schema.json")):
        value: object = json.loads(path.read_text(encoding="utf-8"))
        assert isinstance(value, dict)
        identifier = value.get("$id")
        assert isinstance(identifier, str)
        result[identifier] = value
    return result


def _validators() -> dict[str, Draft202012Validator]:
    schemas = _schemas()
    registry: Registry[Any] = Registry()
    for identifier, schema in schemas.items():
        registry = registry.with_resource(identifier, Resource.from_contents(schema))
    return {
        identifier: Draft202012Validator(schema, registry=registry, format_checker=FormatChecker())
        for identifier, schema in schemas.items()
    }


VALIDATORS = _validators()


def _validate(identifier: str, instance: dict[str, object]) -> None:
    VALIDATORS[identifier].validate(instance)


def _digest(character: str = "a") -> str:
    return character * 64


def _event() -> dict[str, object]:
    return {
        "schema_version": "2.0",
        "source_record_id": "event-1",
        "source_batch_id": "processor-batch-1",
        "processor": "processor-a",
        "merchant_id": "merchant-1",
        "payment_id": "payment-1",
        "event_type": "REFUND",
        "amount_minor": 2500,
        "currency": "INR",
        "occurred_at": "2026-09-01T01:00:00Z",
        "received_at": "2026-09-01T01:00:01Z",
        "reference_event_id": "capture-1",
        "payload_sha256": _digest(),
    }


def _settlement() -> dict[str, object]:
    return {
        "schema_version": "2.0",
        "source_record_id": "settlement-source-1",
        "source_batch_id": "processor-settlement-batch-1",
        "processor": "processor-a",
        "merchant_id": "merchant-1",
        "settlement_id": "settlement-1",
        "settlement_cycle": "2026-09-01",
        "currency": "INR",
        "gross_minor": 100000,
        "fee_minor": 3000,
        "refund_minor": 10000,
        "chargeback_minor": 5000,
        "reserve_minor": 2000,
        "reported_net_minor": 80000,
        "occurred_at": "2026-09-01T23:00:00Z",
        "received_at": "2026-09-01T23:00:01Z",
        "payload_sha256": _digest(),
    }


def _postings() -> list[dict[str, object]]:
    return [
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
    ]


def _transaction_journal() -> dict[str, object]:
    return {
        "schema_version": "2.0",
        "journal_id": "journal-1",
        "source_batch_id": "ledger-batch-1",
        "ledger_system": "ledger-a",
        "processor": "processor-a",
        "merchant_id": "merchant-1",
        "payment_id": "payment-1",
        "entry_type": "CAPTURE",
        "currency": "INR",
        "effective_at": "2026-09-01T01:00:00Z",
        "received_at": "2026-09-01T01:00:01Z",
        "postings": _postings(),
        "payload_sha256": _digest(),
    }


def _settlement_journal() -> dict[str, object]:
    journal = _transaction_journal()
    journal.pop("payment_id")
    journal.update(
        {
            "settlement_id": "settlement-1",
            "settlement_cycle": "2026-09-01",
            "entry_type": "SETTLEMENT",
        }
    )
    return journal


def _bank_entry() -> dict[str, object]:
    return {
        "schema_version": "2.0",
        "bank_record_id": "bank-record-1",
        "source_batch_id": "bank-batch-1",
        "bank_account_id": "bank-account-1",
        "merchant_id": "merchant-1",
        "settlement_reference": " settlement-1 ",
        "direction": "CREDIT",
        "amount_minor": 80000,
        "currency": "INR",
        "value_at": "2026-09-02T01:00:00Z",
        "received_at": "2026-09-02T01:00:01Z",
        "payload_sha256": _digest(),
    }


def _currency_rule(exponent: int) -> dict[str, int]:
    return {
        "exponent": exponent,
        "transaction_tolerance_minor": 0,
        "settlement_tolerance_minor": 1,
    }


def _policy() -> dict[str, object]:
    return {
        "schema_version": "2.0",
        "policy_version": "v1",
        "currency_rules": {
            "INR": _currency_rule(2),
            "JPY": _currency_rule(0),
            "USD": _currency_rule(2),
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
            "permitted_bank_accounts": [
                {
                    "merchant_id": "merchant-1",
                    "currency": "INR",
                    "bank_account_ids": ["bank-account-1"],
                }
            ],
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
        "policy_sha256": _digest("b"),
    }


def _manifest_object(family: str, number: int) -> dict[str, object]:
    return {
        "family": family,
        "schema_version": "2.0",
        "locator_type": "LOCAL_FILE",
        "relative_path": f"fixtures/source-{number}.jsonl",
        "size_bytes": 100,
        "record_count": 1,
        "sha256": _digest(str(number)),
    }


def _local_manifest() -> dict[str, object]:
    families = ["PROCESSOR_EVENTS", "PROCESSOR_SETTLEMENTS", "LEDGER_JOURNALS", "BANK_ENTRIES"]
    return {
        "schema_version": "2.0",
        "run_id": "run-0001",
        "source_commit": "a" * 40,
        "policy_version": "v1",
        "policy_sha256": _digest("b"),
        "created_at": "2026-09-01T01:00:00Z",
        "objects": [_manifest_object(family, number) for number, family in enumerate(families, 1)],
        "manifest_sha256": _digest("f"),
    }


def _s3_manifest() -> dict[str, object]:
    manifest = _local_manifest()
    objects = manifest["objects"]
    assert isinstance(objects, list)
    for number, value in enumerate(objects, 1):
        assert isinstance(value, dict)
        value["locator_type"] = "S3_OBJECT"
        value["s3_uri"] = f"s3://ledgerguard-evidence/source-{number}.jsonl"
        value["version_id"] = f"version-{number}"
        value.pop("relative_path")
    return manifest


def _proof_base(grain: str, prefix: str) -> dict[str, object]:
    return {
        "schema_version": "2.0",
        "proof_id": "proof-1",
        "run_id": "run-0001",
        "grain": grain,
        "reconciliation_key": prefix + "a" * 64,
        "revision": 1,
        "currency": "INR",
        "policy_version": "v1",
        "source_manifest_sha256": _digest("b"),
        "policy_sha256": _digest("c"),
        "status": "MATCHED",
        "reason_codes": [],
        "created_at": "2026-09-01T01:00:00Z",
        "proof_sha256": _digest("d"),
    }


def _transaction_proof() -> dict[str, object]:
    proof = _proof_base("TRANSACTION", "txn:")
    proof["key_components"] = {
        "processor": "processor-a",
        "merchant_id": "merchant-1",
        "payment_id": "payment-1",
        "event_class": "CAPTURE",
        "currency": "INR",
    }
    proof["totals"] = {
        "processor_minor": 10000,
        "ledger_minor": 10000,
        "processor_ledger_delta_minor": 0,
        "difference_minor": 0,
        "processor_record_count": 1,
        "ledger_journal_count": 1,
    }
    return proof


def _settlement_proof() -> dict[str, object]:
    proof = _proof_base("SETTLEMENT", "stl:")
    proof["key_components"] = {
        "processor": "processor-a",
        "merchant_id": "merchant-1",
        "settlement_id": "settlement-1",
        "settlement_cycle": "2026-09-01",
        "currency": "INR",
    }
    proof["totals"] = {
        "processor_net_minor": 80000,
        "ledger_clearing_minor": 80000,
        "bank_minor": 80000,
        "processor_ledger_delta_minor": 0,
        "processor_bank_delta_minor": 0,
        "ledger_bank_delta_minor": 0,
        "difference_minor": 0,
        "processor_settlement_count": 1,
        "ledger_journal_count": 1,
        "allocated_bank_entry_count": 2,
    }
    return proof


def _case() -> dict[str, object]:
    return {
        "schema_version": "2.0",
        "case_id": "case-1",
        "grain": "TRANSACTION",
        "reconciliation_key": "txn:" + "a" * 64,
        "initial_exception_proof_id": "proof-exception-1",
        "revision": 1,
        "status": "OPEN",
        "reason_codes": ["INVALID_ACCOUNT_ROLE"],
        "proof_id": "proof-exception-1",
        "actor_type": "SYSTEM",
        "occurred_at": "2026-09-01T01:00:00Z",
        "case_revision_sha256": _digest("e"),
    }


@pytest.mark.parametrize(
    "identifier,instance",
    [
        ("urn:ledgerguard:processor-event:v2", _event()),
        ("urn:ledgerguard:processor-settlement:v2", _settlement()),
        ("urn:ledgerguard:journal:v2", _transaction_journal()),
        ("urn:ledgerguard:journal:v2", _settlement_journal()),
        ("urn:ledgerguard:bank-entry:v2", _bank_entry()),
        ("urn:ledgerguard:reconciliation-policy:v2", _policy()),
        ("urn:ledgerguard:run-manifest:v2", _local_manifest()),
        ("urn:ledgerguard:run-manifest:v2", _s3_manifest()),
        ("urn:ledgerguard:reconciliation-proof:v2", _transaction_proof()),
        ("urn:ledgerguard:reconciliation-proof:v2", _settlement_proof()),
        ("urn:ledgerguard:case-revision:v2", _case()),
    ],
)
def test_valid_v2_contract_specimens(identifier: str, instance: dict[str, object]) -> None:
    _validate(identifier, instance)


def test_processor_event_reference_and_numeric_boundaries() -> None:
    validator = VALIDATORS["urn:ledgerguard:processor-event:v2"]
    invalid = _event()
    invalid.pop("reference_event_id")
    with pytest.raises(ValidationError):
        validator.validate(invalid)

    invalid = _event()
    invalid["reference_event_id"] = None
    with pytest.raises(ValidationError):
        validator.validate(invalid)

    capture = _event()
    capture["event_type"] = "CAPTURE"
    with pytest.raises(ValidationError):
        validator.validate(capture)
    capture.pop("reference_event_id")
    validator.validate(capture)

    overflow = _event()
    overflow["amount_minor"] = 9223372036854775808
    with pytest.raises(ValidationError):
        validator.validate(overflow)

    floating = _event()
    floating["amount_minor"] = 1.5
    with pytest.raises(ValidationError):
        validator.validate(floating)


def test_canonical_timestamp_shape_rejects_offset_naive_and_trailing_zero() -> None:
    validator = VALIDATORS["urn:ledgerguard:processor-event:v2"]
    for timestamp in (
        "2026-09-01T06:30:00+05:30",
        "2026-09-01T01:00:00",
        "2026-09-01T01:00:00.120Z",
    ):
        invalid = _event()
        invalid["occurred_at"] = timestamp
        with pytest.raises(ValidationError):
            validator.validate(invalid)
    valid = _event()
    valid["occurred_at"] = "2026-09-01T01:00:00.12Z"
    validator.validate(valid)


def test_journal_requires_namespace_and_exactly_one_applicable_key() -> None:
    validator = VALIDATORS["urn:ledgerguard:journal:v2"]
    for field in ("entry_type", "processor", "ledger_system"):
        invalid = _transaction_journal()
        invalid.pop(field)
        with pytest.raises(ValidationError):
            validator.validate(invalid)

    dual = _transaction_journal()
    dual["settlement_id"] = "settlement-1"
    dual["settlement_cycle"] = "2026-09-01"
    with pytest.raises(ValidationError):
        validator.validate(dual)

    wrong_key = _settlement_journal()
    wrong_key.pop("settlement_cycle")
    with pytest.raises(ValidationError):
        validator.validate(wrong_key)


def test_policy_requires_complete_currency_and_financial_rules() -> None:
    validator = VALIDATORS["urn:ledgerguard:reconciliation-policy:v2"]
    incomplete = _policy()
    currency_rules = incomplete["currency_rules"]
    assert isinstance(currency_rules, dict)
    currency_rules.pop("JPY")
    with pytest.raises(ValidationError):
        validator.validate(incomplete)

    bad_sign = _policy()
    transaction_rules = bad_sign["transaction_rules"]
    assert isinstance(transaction_rules, dict)
    event_signs = transaction_rules["event_signs"]
    assert isinstance(event_signs, dict)
    event_signs["REFUND"] = 1
    with pytest.raises(ValidationError):
        validator.validate(bad_sign)


def test_manifest_locator_variants_are_honest_and_complete() -> None:
    validator = VALIDATORS["urn:ledgerguard:run-manifest:v2"]
    traversal = _local_manifest()
    objects = traversal["objects"]
    assert isinstance(objects, list) and isinstance(objects[0], dict)
    objects[0]["relative_path"] = "../outside.jsonl"
    with pytest.raises(ValidationError):
        validator.validate(traversal)

    mixed = _local_manifest()
    objects = mixed["objects"]
    assert isinstance(objects, list) and isinstance(objects[0], dict)
    objects[0]["s3_uri"] = "s3://bucket/key"
    objects[0]["version_id"] = "version-1"
    with pytest.raises(ValidationError):
        validator.validate(mixed)

    missing_family = _local_manifest()
    objects = missing_family["objects"]
    assert isinstance(objects, list) and isinstance(objects[0], dict)
    objects[0]["family"] = "BANK_ENTRIES"
    with pytest.raises(ValidationError):
        validator.validate(missing_family)


def test_proof_grains_reason_taxonomy_and_revision_shapes_are_closed() -> None:
    validator = VALIDATORS["urn:ledgerguard:reconciliation-proof:v2"]
    transaction = _transaction_proof()
    totals = transaction["totals"]
    assert isinstance(totals, dict)
    totals["bank_minor"] = 10000
    with pytest.raises(ValidationError):
        validator.validate(transaction)

    settlement = _settlement_proof()
    totals = settlement["totals"]
    assert isinstance(totals, dict)
    totals.pop("ledger_bank_delta_minor")
    with pytest.raises(ValidationError):
        validator.validate(settlement)

    exception = _transaction_proof()
    exception["status"] = "EXCEPTION"
    exception["reason_codes"] = ["SCHEMA_VIOLATION"]
    with pytest.raises(ValidationError):
        validator.validate(exception)
    exception["reason_codes"] = ["INVALID_ACCOUNT_ROLE"]
    validator.validate(exception)

    revision = _transaction_proof()
    revision["revision"] = 2
    with pytest.raises(ValidationError):
        validator.validate(revision)
    revision["prior_proof_id"] = "proof-previous"
    validator.validate(revision)


def test_case_revision_enforces_predecessor_and_operator_boundary() -> None:
    validator = VALIDATORS["urn:ledgerguard:case-revision:v2"]
    later = _case()
    later["revision"] = 2
    with pytest.raises(ValidationError):
        validator.validate(later)
    later["prior_case_revision_id"] = "case-revision-1"
    validator.validate(later)

    system_writeoff = _case()
    system_writeoff["status"] = "WRITTEN_OFF"
    with pytest.raises(ValidationError):
        validator.validate(system_writeoff)

    operator_writeoff = _case()
    operator_writeoff.update(
        {
            "revision": 2,
            "prior_case_revision_id": "case-revision-1",
            "status": "WRITTEN_OFF",
            "actor_type": "OPERATOR",
            "actor_id": "operator-1",
        }
    )
    validator.validate(operator_writeoff)


def test_active_registry_binds_unique_offline_v2_contracts_and_preserves_v1() -> None:
    entries = ACTIVE["contracts"]
    assert len(entries) == 9
    assert len({entry["family"] for entry in entries}) == 9
    assert len({entry["id"] for entry in entries}) == 9
    for entry in entries:
        path = ROOT / entry["path"]
        assert path.is_file()
        assert sha256(path.read_bytes()).hexdigest() == entry["sha256"]
        assert json.loads(path.read_text(encoding="utf-8"))["$id"] == entry["id"]

    legacy = ACTIVE["legacy_contract_set"]
    assert legacy["status"] == "SUPERSEDED_BEFORE_RUNTIME_USE"
    actual_legacy = {
        path.name: sha256(path.read_bytes()).hexdigest()
        for path in sorted((ROOT / "contracts").glob("*-v1.schema.json"))
    }
    assert actual_legacy == legacy["digests"]


def test_every_requirement_and_semantic_decision_has_contract_ownership() -> None:
    invariants = INVARIANTS["invariants"]
    assert [item["id"] for item in invariants] == [f"CTR-{number:03d}" for number in range(1, 19)]
    assert {decision for item in invariants for decision in item["decision_ids"]} == {
        f"SEM-{number:03d}" for number in range(1, 19)
    }
    assert {requirement for item in invariants for requirement in item["requirement_ids"]} == {
        f"P1-R{number:02d}" for number in range(1, 13)
    }
    assert INVARIANTS["unmapped_decision_ids"] == []
    assert INVARIANTS["unmapped_requirement_ids"] == []
    assert [item["id"] for item in TRACEABILITY["requirements"]] == [
        f"P1-R{number:02d}" for number in range(1, 13)
    ]


def test_reason_taxonomy_matches_frozen_failure_ownership() -> None:
    common = _schemas()["urn:ledgerguard:common:v2"]
    actual = set(common["$defs"]["financialReason"]["enum"])
    expected = set(SEMANTICS["failure_ownership"]["FINANCIAL_EXCEPTION"])
    assert actual == expected
    assert actual.isdisjoint(SEMANTICS["failure_ownership"]["ADMISSION"])
    assert actual.isdisjoint(SEMANTICS["failure_ownership"]["EXECUTION"])


def test_shared_money_bounds_include_exact_signed_limits() -> None:
    common = _schemas()["urn:ledgerguard:common:v2"]
    signed = common["$defs"]["signedInt64"]
    assert signed == {
        "type": "integer",
        "minimum": -9223372036854775808,
        "maximum": 9223372036854775807,
    }
    specimen = _settlement()
    specimen["reported_net_minor"] = -9223372036854775808
    _validate("urn:ledgerguard:processor-settlement:v2", specimen)
    specimen["reported_net_minor"] = 9223372036854775808
    with pytest.raises(ValidationError):
        _validate("urn:ledgerguard:processor-settlement:v2", specimen)


def test_validators_resolve_every_reference_without_remote_retrieval() -> None:
    for validator in VALIDATORS.values():
        Draft202012Validator.check_schema(validator.schema)
    assert len(VALIDATORS) == 9
    assert all(identifier.startswith("urn:ledgerguard:") for identifier in VALIDATORS)


def test_formula_mismatch_remains_interpretable_source_evidence() -> None:
    mismatch = _settlement()
    mismatch["reported_net_minor"] = 81000
    _validate("urn:ledgerguard:processor-settlement:v2", mismatch)
    assert (
        SEMANTICS["failure_ownership"]["FINANCIAL_EXCEPTION"].count("SETTLEMENT_FORMULA_MISMATCH")
        == 1
    )


def test_schema_specimens_do_not_claim_runtime_reconciliation() -> None:
    assert INVARIANTS["enforcement_layers"] == [
        "JSON_SCHEMA",
        "STAGE2_GOVERNANCE",
        "PART2_RUNTIME",
    ]
    for invariant in INVARIANTS["invariants"]:
        assert invariant["schema_enforcement"]
        assert invariant["runtime_enforcement"]


def test_unknown_properties_fail_closed() -> None:
    specimen = deepcopy(_bank_entry())
    specimen["payment_id"] = "payment-1"
    with pytest.raises(ValidationError):
        _validate("urn:ledgerguard:bank-entry:v2", specimen)
