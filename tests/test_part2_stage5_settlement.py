from __future__ import annotations

import json
import os
import subprocess
import sys
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from typing import Any, cast

import pytest

import ledgerguard.reconciliation.settlement as settlement_module
from ledgerguard.reconciliation import (
    AdmissionRejected,
    AdmissionState,
    AdmittedBatch,
    AdmittedRecord,
    SettlementKey,
    SettlementState,
    admit_bundle,
    canonical_json_bytes,
    normalize_bank_reference,
    reconcile_settlements,
    settlement_key,
)
from ledgerguard.reconciliation.arithmetic import MAX_I64
from ledgerguard_reference_oracle import evaluate_settlement

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = json.loads((ROOT / "spec/financial-examples-v1.json").read_text())


def _record(family: str, value: dict[str, Any]) -> AdmittedRecord:
    raw = canonical_json_bytes(value)
    if family == "PROCESSOR_SETTLEMENT":
        identity = (family, str(value["processor"]), str(value["source_record_id"]))
    elif family == "LEDGER_JOURNAL":
        identity = (family, str(value["ledger_system"]), str(value["journal_id"]))
    elif family == "BANK_ENTRY":
        identity = (family, str(value["bank_account_id"]), str(value["bank_record_id"]))
    else:
        identity = (family, "unused")
    key = None
    if family in {"PROCESSOR_SETTLEMENT", "LEDGER_JOURNAL"}:
        key = settlement_key(
            {
                name: value[name]
                for name in (
                    "processor",
                    "merchant_id",
                    "settlement_id",
                    "settlement_cycle",
                    "currency",
                )
            }
        )
    return AdmittedRecord(
        family=family,
        source_identity=identity,
        business_sha256=sha256(raw).hexdigest(),
        canonical_bytes=raw,
        reconciliation_key=key,
        normalized_settlement_reference=(
            normalize_bank_reference(value.get("settlement_reference"))
            if family == "BANK_ENTRY"
            else None
        ),
        journal_balanced_total_minor=0 if family == "LEDGER_JOURNAL" else None,
        journal_clearing_role_valid=True if family == "LEDGER_JOURNAL" else None,
    )


def _processor(
    source_id: str = "processor-settlement",
    *,
    settlement_id: str = "settlement-1",
    cycle: str = "2026-09-01",
    gross: int = 100,
    fee: int = 0,
    refund: int = 0,
    chargeback: int = 0,
    reserve: int = 0,
    reported: int | None = None,
    processor: str = "processor-a",
    merchant: str = "merchant-1",
    currency: str = "INR",
) -> AdmittedRecord:
    return _record(
        "PROCESSOR_SETTLEMENT",
        {
            "processor": processor,
            "merchant_id": merchant,
            "settlement_id": settlement_id,
            "settlement_cycle": cycle,
            "currency": currency,
            "source_record_id": source_id,
            "gross_minor": gross,
            "fee_minor": fee,
            "refund_minor": refund,
            "chargeback_minor": chargeback,
            "reserve_minor": reserve,
            "reported_net_minor": (
                reported if reported is not None else gross - fee - refund - chargeback - reserve
            ),
        },
    )


def _journal(
    journal_id: str = "journal-1",
    *,
    settlement_id: str = "settlement-1",
    cycle: str = "2026-09-01",
    amount: int = 100,
    side: str = "CREDIT",
    processor: str = "processor-a",
    merchant: str = "merchant-1",
    currency: str = "INR",
    role: str = "PROCESSOR_CLEARING",
) -> AdmittedRecord:
    record = _record(
        "LEDGER_JOURNAL",
        {
            "ledger_system": "ledger-1",
            "journal_id": journal_id,
            "processor": processor,
            "merchant_id": merchant,
            "settlement_id": settlement_id,
            "settlement_cycle": cycle,
            "currency": currency,
            "entry_type": "SETTLEMENT",
            "postings": [
                {"line_id": "1", "account_role": role, "side": side, "amount_minor": amount},
                {
                    "line_id": "2",
                    "account_role": "MERCHANT_PAYABLE",
                    "side": "DEBIT" if side == "CREDIT" else "CREDIT",
                    "amount_minor": amount,
                },
            ],
        },
    )
    return replace(record, journal_clearing_role_valid=role == "PROCESSOR_CLEARING")


def _bank(
    record_id: str = "bank-1",
    *,
    reference: str | None = "settlement-1",
    amount: int = 100,
    direction: str = "CREDIT",
    account: str = "bank-account-1",
    merchant: str = "merchant-1",
    currency: str = "INR",
) -> AdmittedRecord:
    value: dict[str, Any] = {
        "bank_account_id": account,
        "bank_record_id": record_id,
        "merchant_id": merchant,
        "currency": currency,
        "direction": direction,
        "amount_minor": amount,
    }
    if reference is not None:
        value["settlement_reference"] = reference
    return _record("BANK_ENTRY", value)


def _policy(tolerance: int = 0) -> dict[str, Any]:
    return {
        "settlement_rules": {
            "formula": "gross_minor-fee_minor-refund_minor-chargeback_minor-reserve_minor",
            "ledger_side_signs": {"DEBIT": -1, "CREDIT": 1},
            "bank_side_signs": {"CREDIT": 1, "DEBIT": -1},
            "bank_allocation": {
                "strategy": "EXACT_SETTLEMENT_REFERENCE",
                "amount_date_heuristic_forbidden": True,
                "one_bank_identity_one_allocation": True,
            },
            "permitted_bank_accounts": [
                {
                    "merchant_id": "merchant-1",
                    "currency": "INR",
                    "bank_account_ids": ["bank-account-1"],
                }
            ],
        },
        "currency_rules": {"INR": {"settlement_tolerance_minor": tolerance}},
    }


def _batch(
    records: tuple[AdmittedRecord, ...],
    *,
    occurrences: tuple[AdmittedRecord, ...] | None = None,
    policy: dict[str, Any] | None = None,
) -> AdmittedBatch:
    unique = {record.source_identity: record for record in records}
    observed = tuple(unique[identity] for identity in sorted(unique))
    return AdmittedBatch(
        run_id="stage5-test-run",
        policy_version="v1",
        policy_sha256="1" * 64,
        manifest_sha256="2" * 64,
        policy_canonical_bytes=canonical_json_bytes(policy or _policy()),
        manifest_canonical_bytes=b"{}",
        records=observed,
        replay_count=0,
        state=AdmissionState(),
        observed_records=observed,
        observed_occurrences=occurrences or records,
    )


def _from_example(source: dict[str, Any]) -> tuple[AdmittedRecord, ...]:
    records: list[AdmittedRecord] = []
    if source["processor_settlement_count"]:
        records.append(
            _processor(
                gross=source["gross_minor"],
                fee=source["fee_minor"],
                refund=source["refund_minor"],
                chargeback=source["chargeback_minor"],
                reserve=source["reserve_minor"],
                reported=source["reported_net_minor"],
                settlement_id=source["settlement_reference"],
            )
        )
    if source["ledger_journal_count"]:
        records.append(
            _journal(
                amount=source["ledger_amount_minor"],
                side=source["ledger_side"],
                settlement_id=source["settlement_reference"],
            )
        )
    for entry in source["bank_entries"]:
        records.append(
            _bank(
                entry["bank_record_id"],
                reference=entry.get("settlement_reference"),
                amount=entry["amount_minor"],
                direction=entry["direction"],
                account=entry["bank_account_id"],
            )
        )
    return tuple(records)


@pytest.mark.parametrize("case", EXAMPLES["settlement_cases"], ids=lambda row: row["name"])
def test_p2s5_frozen_settlement_examples(case: dict[str, Any]) -> None:
    source = case["input"]
    result = reconcile_settlements(
        _batch(_from_example(source), policy=_policy(source["tolerance_minor"]))
    )
    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    expected = case["expected"]
    assert evaluate_settlement(source) == expected
    for field in (
        "processor_net_minor",
        "ledger_clearing_minor",
        "bank_minor",
        "processor_ledger_delta_minor",
        "processor_bank_delta_minor",
        "ledger_bank_delta_minor",
        "difference_minor",
    ):
        assert getattr(candidate, field) == expected[field]
    assert candidate.allocated_bank_entry_count == expected["allocated_bank_count"]
    unallocated = sum(row.disposition.startswith("UNALLOCATED") for row in result.bank_allocations)
    assert unallocated == expected["unallocated_bank_count"]
    assert result.status == expected["status"]
    assert list(result.reason_codes) == expected["reason_codes"]
    assert candidate.authoritative_proof is False
    assert result.authoritative_proof is False


def test_p2s5_full_outer_journal_only_candidate_and_bank_allocation() -> None:
    result = reconcile_settlements(_batch((_journal(), _bank())))
    candidate = result.candidates[0]
    assert candidate.processor_settlement_count == 0
    assert candidate.ledger_clearing_minor == 100
    assert candidate.bank_minor == 100
    assert candidate.reason_codes == ("MISSING_PROCESSOR_ACTIVITY",)


def test_p2s5_bank_only_is_unallocated_without_inventing_a_settlement_key() -> None:
    result = reconcile_settlements(_batch((_bank(),)))
    assert result.candidates == ()
    assert result.bank_allocations[0].disposition == "UNALLOCATED_UNKNOWN_REFERENCE"
    assert result.reason_codes == ("UNALLOCATED_BANK_MOVEMENT",)


def test_p2s5_cross_key_reference_ambiguity_rejects_before_candidates() -> None:
    records = (
        _processor("p1", processor="processor-a", cycle="cycle-a"),
        _journal("j2", processor="processor-b", cycle="cycle-b"),
        _bank(),
    )
    with pytest.raises(AdmissionRejected) as captured:
        reconcile_settlements(_batch(records))
    assert captured.value.reason == "AMBIGUOUS_BANK_ALLOCATION"
    assert captured.value.authoritative_proof is False


def test_p2s5_duplicate_current_bank_is_counted_once_and_forces_exception() -> None:
    bank = _bank()
    result = reconcile_settlements(
        _batch((_processor(), _journal(), bank), occurrences=(_processor(), _journal(), bank, bank))
    )
    candidate = result.candidates[0]
    assert candidate.bank_minor == 100
    assert candidate.allocated_bank_entry_count == 1
    assert candidate.reason_codes == ("DUPLICATE_BANK_MOVEMENT",)
    assert result.bank_allocations[0].duplicate_current_bundle is True
    assert result.state.duplicate_bank_identities == (bank.source_identity,)


def test_p2s5_duplicate_bank_diagnostic_survives_cross_batch_state() -> None:
    bank = _bank()
    processor = _processor()
    journal = _journal()
    first = reconcile_settlements(
        _batch(
            (processor, journal, bank),
            occurrences=(processor, journal, bank, bank),
        )
    )
    second = reconcile_settlements(_batch(()), first.state)
    assert second.candidates[0].bank_minor == 100
    assert second.candidates[0].reason_codes == ("DUPLICATE_BANK_MOVEMENT",)
    assert second.state.duplicate_bank_identities == (bank.source_identity,)
    assert second.bank_allocations[0].duplicate_current_bundle is False


def test_p2s5_admission_handoff_preserves_bank_multiplicity_end_to_end() -> None:
    from test_part2_stage3_admission import (
        bank_entry,
        build_bundle,
        journal,
        processor_event,
        processor_settlement,
        signed_record,
    )

    settlement_journal = journal(entry_type="SETTLEMENT")
    settlement_journal.pop("payment_id")
    settlement_journal["settlement_id"] = "settlement-1"
    settlement_journal["settlement_cycle"] = "cycle-1"
    settlement_journal = signed_record(settlement_journal)
    bank = bank_entry()
    families = {
        "PROCESSOR_EVENTS": [processor_event()],
        "PROCESSOR_SETTLEMENTS": [processor_settlement()],
        "LEDGER_JOURNALS": [settlement_journal],
        "BANK_ENTRIES": [bank, bank],
    }
    policy_bytes, manifest_bytes, supplied, _ = build_bundle(families)
    admitted = admit_bundle(ROOT, policy_bytes, manifest_bytes, supplied)
    result = reconcile_settlements(admitted)
    assert len([row for row in admitted.observed_occurrences if row.family == "BANK_ENTRY"]) == 2
    assert result.candidates[0].bank_minor == 95
    assert result.candidates[0].reason_codes == ("DUPLICATE_BANK_MOVEMENT",)


def test_p2s5_prior_replay_is_idempotent_without_duplicate_reason() -> None:
    bank = replace(_bank(), identical_replay=True, prior_state_replay=True)
    processor = _processor()
    journal = _journal()
    result = reconcile_settlements(
        _batch((processor, journal, bank), occurrences=(processor, journal, bank))
    )
    assert result.candidates[0].status == "MATCHED"
    assert result.candidates[0].reason_codes == ()


def test_p2s5_prior_replay_duplicated_inside_current_bundle_is_still_visible() -> None:
    bank = replace(_bank(), identical_replay=True, prior_state_replay=True)
    processor = _processor()
    journal = _journal()
    result = reconcile_settlements(
        _batch((processor, journal, bank), occurrences=(processor, journal, bank, bank))
    )
    assert result.candidates[0].bank_minor == 100
    assert result.candidates[0].reason_codes == ("DUPLICATE_BANK_MOVEMENT",)


def test_p2s5_prior_state_representation_is_immutable_across_transport_replay() -> None:
    prior_bank = _bank()
    replay_value = prior_bank.value() | {"source_batch_id": "later-transport"}
    replay = replace(
        prior_bank,
        canonical_bytes=canonical_json_bytes(replay_value),
        identical_replay=True,
        prior_state_replay=True,
    )
    processor = _processor()
    journal = _journal()
    result = reconcile_settlements(
        _batch((processor, journal, replay), occurrences=(processor, journal, replay)),
        SettlementState((prior_bank,)),
    )
    retained = next(row for row in result.state.records if row.family == "BANK_ENTRY")
    assert retained == prior_bank
    assert result.candidates[0].status == "MATCHED"


def test_p2s5_missing_reference_is_visible_and_never_allocated() -> None:
    result = reconcile_settlements(_batch((_processor(), _journal(), _bank(reference=None))))
    assert result.candidates[0].reason_codes == ("MISSING_BANK_SETTLEMENT",)
    allocation = result.bank_allocations[0]
    assert allocation.disposition == "UNALLOCATED_MISSING_REFERENCE"
    assert allocation.reason_codes == ("UNALLOCATED_BANK_MOVEMENT",)
    assert result.reason_codes == ("MISSING_BANK_SETTLEMENT", "UNALLOCATED_BANK_MOVEMENT")


def test_p2s5_case_and_punctuation_never_allocate() -> None:
    records = (
        _processor(),
        _journal(),
        _bank("case", reference="Settlement-1"),
        _bank("punctuation", reference="settlement.1"),
    )
    result = reconcile_settlements(_batch(records))
    assert result.candidates[0].allocated_bank_entry_count == 0
    assert all(
        row.disposition == "UNALLOCATED_UNKNOWN_REFERENCE" for row in result.bank_allocations
    )


def test_p2s5_nfc_and_outer_whitespace_allocate_exactly() -> None:
    records = (
        _processor(settlement_id="settle-é.1"),
        _journal(settlement_id="settle-é.1"),
        _bank(reference="  settle-e\u0301.1  "),
    )
    result = reconcile_settlements(_batch(records))
    assert result.candidates[0].status == "MATCHED"


def test_p2s5_disallowed_account_is_diagnostic_not_a_false_match() -> None:
    result = reconcile_settlements(
        _batch((_processor(), _journal(), _bank(account="blocked-account")))
    )
    candidate = result.candidates[0]
    assert candidate.bank_minor == 100
    assert candidate.reason_codes == ("INVALID_BANK_ACCOUNT",)
    assert result.bank_allocations[0].account_permitted is False


def test_p2s5_formula_mismatch_is_per_record_before_aggregation() -> None:
    records = (
        _processor("p1", gross=50, reported=51),
        _processor("p2", gross=50, reported=49),
        _journal(amount=100),
        _bank(amount=100),
    )
    candidate = reconcile_settlements(_batch(records, policy=_policy(MAX_I64))).candidates[0]
    assert candidate.processor_net_minor == 100
    assert candidate.reason_codes == ("SETTLEMENT_FORMULA_MISMATCH",)
    assert candidate.status == "EXCEPTION"


def test_p2s5_bank_first_then_settlement_converges_without_double_use() -> None:
    first = reconcile_settlements(_batch((_bank(),)))
    second = reconcile_settlements(_batch((_processor(), _journal())), prior_state=first.state)
    direct = reconcile_settlements(_batch((_processor(), _journal(), _bank())))
    assert second.candidates == direct.candidates
    assert second.bank_allocations == direct.bank_allocations
    assert second.state.semantic_digest() == direct.state.semantic_digest()


def test_p2s5_state_identity_conflict_rejects_atomically() -> None:
    prior_record = _bank(amount=100)
    current_record = _bank(amount=99)
    with pytest.raises(AdmissionRejected) as captured:
        reconcile_settlements(
            _batch((current_record,)), prior_state=SettlementState((prior_record,))
        )
    assert captured.value.reason == "IDENTITY_CONFLICT"


def test_p2s5_checked_aggregation_overflow_rejects_without_candidate() -> None:
    records = (
        _processor("p1", gross=MAX_I64),
        _processor("p2", gross=MAX_I64),
    )
    with pytest.raises(AdmissionRejected) as captured:
        reconcile_settlements(_batch(records))
    assert captured.value.reason == "SCHEMA_VIOLATION"
    assert captured.value.authoritative_proof is False


def test_p2s5_result_is_permutation_invariant_and_digest_stable() -> None:
    records = [_processor(), _journal(), _bank("b1", amount=60), _bank("b2", amount=40)]
    forward = reconcile_settlements(_batch(tuple(records)))
    records.reverse()
    reverse = reconcile_settlements(_batch(tuple(records)))
    assert forward == reverse
    assert forward.semantic_digest() == reverse.semantic_digest()


def test_p2s5_cli_success_and_owned_failure(tmp_path: Path) -> None:
    from test_part2_stage3_admission import build_bundle

    policy_bytes, manifest_bytes, supplied, manifest = build_bundle()
    policy_path = tmp_path / "policy.json"
    manifest_path = tmp_path / "manifest.json"
    object_root = tmp_path / "objects"
    object_root.mkdir()
    policy_path.write_bytes(policy_bytes)
    manifest_path.write_bytes(manifest_bytes)
    for descriptor in manifest["objects"]:
        relative = descriptor["relative_path"]
        (object_root / relative).write_bytes(supplied[f"local:{relative}"])
    command = [
        sys.executable,
        "-m",
        "ledgerguard_part2_stage5",
        "--repository",
        str(ROOT),
        "--policy",
        str(policy_path),
        "--manifest",
        str(manifest_path),
        "--input-root",
        str(object_root),
    ]
    environment = dict(os.environ, PYTHONPATH=str(ROOT / "src"))
    completed = subprocess.run(
        command, cwd=ROOT, env=environment, check=True, text=True, capture_output=True
    )
    result = json.loads(completed.stdout)
    assert result["outcome"] == "SETTLEMENT_RECONCILIATION_CANDIDATE"
    assert result["settlement_candidate_count"] == 1
    assert result["bank_allocation_count"] == 1
    assert result["authoritative_proof"] is False
    manifest_path.write_bytes(b"[]")
    rejected = subprocess.run(
        command, cwd=ROOT, env=environment, check=False, text=True, capture_output=True
    )
    assert rejected.returncode == 2
    assert json.loads(rejected.stdout)["reason_code"] == "SCHEMA_VIOLATION"
    command[command.index(str(policy_path))] = str(tmp_path / "missing-policy.json")
    missing = subprocess.run(
        command, cwd=ROOT, env=environment, check=False, text=True, capture_output=True
    )
    assert missing.returncode == 2
    assert json.loads(missing.stdout)["reason_code"] == "SOURCE_IDENTITY_MISMATCH"


def test_p2s5_transaction_records_never_contaminate_settlement_state() -> None:
    transaction = replace(
        _processor(),
        family="PROCESSOR_EVENT",
        source_identity=("PROCESSOR_EVENT", "processor-a", "event-1"),
        reconciliation_key="txn:" + "0" * 64,
    )
    result = reconcile_settlements(_batch((transaction,)))
    assert result.candidates == ()
    assert result.state.records == ()


def test_p2s5_processor_only_nonzero_preserves_missing_sources() -> None:
    candidate = reconcile_settlements(_batch((_processor(),))).candidates[0]
    assert candidate.reason_codes == (
        "MISSING_LEDGER_MOVEMENT",
        "MISSING_BANK_SETTLEMENT",
    )


@pytest.mark.parametrize(
    ("ledger_amount", "bank_amount", "expected"),
    [
        (99, 100, ("PROCESSOR_LEDGER_MISMATCH", "LEDGER_BANK_MISMATCH")),
        (100, 99, ("PROCESSOR_BANK_MISMATCH", "LEDGER_BANK_MISMATCH")),
        (99, 99, ("PROCESSOR_LEDGER_MISMATCH", "PROCESSOR_BANK_MISMATCH")),
        (
            98,
            99,
            (
                "PROCESSOR_LEDGER_MISMATCH",
                "PROCESSOR_BANK_MISMATCH",
                "LEDGER_BANK_MISMATCH",
            ),
        ),
    ],
)
def test_p2s5_pairwise_mismatch_reasons(
    ledger_amount: int, bank_amount: int, expected: tuple[str, ...]
) -> None:
    records = (_processor(), _journal(amount=ledger_amount), _bank(amount=bank_amount))
    candidate = reconcile_settlements(_batch(records)).candidates[0]
    assert candidate.reason_codes == expected


def test_p2s5_low_level_shape_guards() -> None:
    with pytest.raises(AdmissionRejected, match="not an object"):
        settlement_module._object(b"[]", "not an object")
    for value in (None, 1, ""):
        with pytest.raises(AdmissionRejected, match="settlement field missing"):
            settlement_module._text({"field": value}, "field")
    with pytest.raises(AdmissionRejected, match="unknown settlement financial reason"):
        settlement_module._ordered_reasons({"NOT_OWNED"})
    with pytest.raises(AdmissionRejected, match="settlement identifier is empty"):
        settlement_module._target_index(
            {SettlementKey("processor-a", "merchant-1", cast(str, None), "cycle-1", "INR")}
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("settlement_rules", None, "settlement policy is incomplete"),
        ("currency_rules", None, "settlement policy is incomplete"),
    ],
)
def test_p2s5_incomplete_policy_rejects(field: str, value: object, message: str) -> None:
    policy = _policy()
    policy[field] = value
    with pytest.raises(AdmissionRejected, match=message):
        reconcile_settlements(_batch((), policy=policy))


def test_p2s5_changed_formula_rejects() -> None:
    policy = _policy()
    policy["settlement_rules"]["formula"] = "reported_net_minor"
    with pytest.raises(AdmissionRejected, match="settlement formula differs"):
        reconcile_settlements(_batch((), policy=policy))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("ledger_side_signs", None),
        ("bank_side_signs", None),
        ("bank_allocation", None),
        ("permitted_bank_accounts", None),
        ("permitted_bank_accounts", "accounts"),
    ],
)
def test_p2s5_policy_shape_rejects(field: str, value: object) -> None:
    policy = _policy()
    policy["settlement_rules"][field] = value
    with pytest.raises(AdmissionRejected, match="settlement policy shape differs"):
        reconcile_settlements(_batch((), policy=policy))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("strategy", "HEURISTIC"),
        ("amount_date_heuristic_forbidden", False),
        ("one_bank_identity_one_allocation", False),
    ],
)
def test_p2s5_allocation_policy_drift_rejects(field: str, value: object) -> None:
    policy = _policy()
    policy["settlement_rules"]["bank_allocation"][field] = value
    with pytest.raises(AdmissionRejected, match="bank allocation policy differs"):
        reconcile_settlements(_batch((), policy=policy))


def test_p2s5_sign_policy_drift_rejects() -> None:
    policy = _policy()
    policy["settlement_rules"]["ledger_side_signs"]["DEBIT"] = 1
    with pytest.raises(AdmissionRejected, match="settlement ledger signs differ"):
        reconcile_settlements(_batch((), policy=policy))
    policy = _policy()
    policy["settlement_rules"]["bank_side_signs"]["CREDIT"] = -1
    with pytest.raises(AdmissionRejected, match="bank signs differ"):
        reconcile_settlements(_batch((), policy=policy))


def test_p2s5_permitted_account_policy_guards() -> None:
    policy = _policy()
    policy["settlement_rules"]["permitted_bank_accounts"] = [1]
    with pytest.raises(AdmissionRejected, match="permitted account row differs"):
        reconcile_settlements(_batch((), policy=policy))
    policy = _policy()
    policy["settlement_rules"]["permitted_bank_accounts"][0]["bank_account_ids"] = "account"
    with pytest.raises(AdmissionRejected, match="permitted accounts unavailable"):
        reconcile_settlements(_batch((), policy=policy))
    policy = _policy()
    row = deepcopy(policy["settlement_rules"]["permitted_bank_accounts"][0])
    policy["settlement_rules"]["permitted_bank_accounts"].append(row)
    with pytest.raises(AdmissionRejected, match="duplicate permitted-account domain"):
        reconcile_settlements(_batch((), policy=policy))


def test_p2s5_currency_policy_guards() -> None:
    policy = _policy()
    policy["currency_rules"]["INR"] = 1
    with pytest.raises(AdmissionRejected, match="currency policy shape differs"):
        reconcile_settlements(_batch((), policy=policy))
    policy = _policy(-1)
    with pytest.raises(AdmissionRejected, match="negative settlement tolerance"):
        reconcile_settlements(_batch((), policy=policy))
    policy = _policy()
    policy["currency_rules"] = {"USD": {"settlement_tolerance_minor": 0}}
    with pytest.raises(AdmissionRejected, match="settlement tolerance unavailable"):
        reconcile_settlements(_batch((_processor(), _journal(amount=99), _bank()), policy=policy))


def test_p2s5_processor_identity_and_key_drift_reject() -> None:
    record = _processor()
    with pytest.raises(AdmissionRejected, match="settlement identity drift"):
        reconcile_settlements(
            _batch((replace(record, source_identity=("PROCESSOR_SETTLEMENT", "wrong", "id")),))
        )
    with pytest.raises(AdmissionRejected, match="settlement key drift"):
        reconcile_settlements(_batch((replace(record, reconciliation_key="stl:" + "0" * 64),)))


def test_p2s5_journal_defensive_guards() -> None:
    record = _journal()
    with pytest.raises(AdmissionRejected, match="journal identity drift"):
        reconcile_settlements(
            _batch((replace(record, source_identity=("LEDGER_JOURNAL", "wrong", "id")),))
        )
    with pytest.raises(AdmissionRejected, match="settlement journal key drift"):
        reconcile_settlements(_batch((replace(record, reconciliation_key="stl:" + "0" * 64),)))
    value = record.value()
    value["postings"] = None
    with pytest.raises(AdmissionRejected, match="journal postings unavailable"):
        reconcile_settlements(_batch((_record("LEDGER_JOURNAL", value),)))
    value = record.value()
    value["postings"] = [1]
    with pytest.raises(AdmissionRejected, match="posting must be an object"):
        reconcile_settlements(_batch((_record("LEDGER_JOURNAL", value),)))
    value = record.value()
    value["postings"][0]["side"] = "LEFT"
    with pytest.raises(AdmissionRejected, match="settlement ledger side unavailable"):
        reconcile_settlements(_batch((_record("LEDGER_JOURNAL", value),)))
    wrong_role = _journal(role="BANK_CASH")
    candidate = reconcile_settlements(_batch((_processor(), wrong_role, _bank()))).candidates[0]
    assert candidate.reason_codes == ("INVALID_ACCOUNT_ROLE",)


def test_p2s5_bank_identity_reference_and_direction_drift_reject() -> None:
    bank = _bank()
    with pytest.raises(AdmissionRejected, match="bank identity drift"):
        reconcile_settlements(
            _batch((replace(bank, source_identity=("BANK_ENTRY", "wrong", "id")),))
        )
    with pytest.raises(AdmissionRejected, match="bank reference drift"):
        reconcile_settlements(_batch((replace(bank, normalized_settlement_reference="different"),)))
    value = bank.value()
    value["direction"] = "LEFT"
    with pytest.raises(AdmissionRejected, match="bank direction unavailable"):
        reconcile_settlements(_batch((_record("BANK_ENTRY", value),)))


def test_p2s5_duplicate_unallocated_bank_reasons_are_owned_once() -> None:
    bank = _bank(reference="unknown")
    result = reconcile_settlements(_batch((bank,), occurrences=(bank, bank)))
    allocation = result.bank_allocations[0]
    assert allocation.reason_codes == (
        "UNALLOCATED_BANK_MOVEMENT",
        "DUPLICATE_BANK_MOVEMENT",
    )
    assert result.reason_codes == allocation.reason_codes
