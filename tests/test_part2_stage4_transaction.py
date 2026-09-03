from __future__ import annotations

import json
import os
import subprocess
import sys
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from typing import Any

import pytest

from ledgerguard.reconciliation import (
    AdmissionRejected,
    AdmittedBatch,
    AdmittedRecord,
    TransactionCandidate,
    TransactionKey,
    TransactionState,
    admit_bundle,
    canonical_json_bytes,
    reconcile_transactions,
)
from ledgerguard.reconciliation.arithmetic import MAX_I64
from ledgerguard.reconciliation.transaction import (
    REASON_ORDER,
    _journal_facts,
    _merge_reasons,
    _object,
    _policy,
    _reference_reasons,
    _status,
    _text,
    _transaction_records,
)
from ledgerguard_reference_oracle import evaluate_transaction
from tests.test_part2_stage3_admission import (
    ROOT,
    build_bundle,
    journal,
    policy,
    processor_event,
    signed_record,
)


def empty_families() -> dict[str, list[dict[str, Any]]]:
    return {
        "PROCESSOR_EVENTS": [],
        "PROCESSOR_SETTLEMENTS": [],
        "LEDGER_JOURNALS": [],
        "BANK_ENTRIES": [],
    }


def transaction_journal(
    journal_id: str,
    event_type: str,
    amount: int,
    side: str,
    *,
    merchant_id: str = "merchant-1",
    payment_id: str = "payment-1",
    clearing_role: str = "PROCESSOR_CLEARING",
    counterpart_role: str = "MERCHANT_PAYABLE",
) -> dict[str, Any]:
    return journal(
        journal_id=journal_id,
        merchant_id=merchant_id,
        payment_id=payment_id,
        entry_type=event_type,
        postings=[
            {
                "line_id": f"{journal_id}-1",
                "account_role": clearing_role,
                "side": side,
                "amount_minor": amount,
            },
            {
                "line_id": f"{journal_id}-2",
                "account_role": counterpart_role,
                "side": "CREDIT" if side == "DEBIT" else "DEBIT",
                "amount_minor": amount,
            },
        ],
    )


def admitted(
    events: list[dict[str, Any]],
    journals: list[dict[str, Any]],
    *,
    tolerance: int = 0,
    prior_state: Any = None,
    run_id: str = "run-0001",
) -> AdmittedBatch:
    families = empty_families()
    families["PROCESSOR_EVENTS"] = events
    families["LEDGER_JOURNALS"] = journals
    policy_value = deepcopy(policy())
    for currency in policy_value["currency_rules"].values():
        currency["transaction_tolerance_minor"] = tolerance
    policy_value["policy_sha256"] = "0" * 64
    from ledgerguard.reconciliation import canonical_sha256

    policy_value["policy_sha256"] = canonical_sha256(policy_value, {"policy_sha256"})
    policy_bytes, manifest_bytes, supplied, _ = build_bundle(
        families, policy_value=policy_value, run_id=run_id
    )
    return admit_bundle(ROOT, policy_bytes, manifest_bytes, supplied, prior_state)


def candidate(batch: AdmittedBatch, event_class: str) -> TransactionCandidate:
    matches = [
        row
        for row in reconcile_transactions(batch).candidates
        if row.key_components.event_class == event_class
    ]
    assert len(matches) == 1
    return matches[0]


def test_p2s4_t001_matched_capture_matches_oracle() -> None:
    batch = admitted(
        [processor_event(amount_minor=10_000)],
        [transaction_journal("journal-capture", "CAPTURE", 10_000, "DEBIT")],
    )
    result = candidate(batch, "CAPTURE")
    oracle = evaluate_transaction(
        {
            "event_type": "CAPTURE",
            "processor_amount_minor": 10_000,
            "processor_currency": "INR",
            "ledger_side": "DEBIT",
            "ledger_amount_minor": 10_000,
            "ledger_currency": "INR",
            "account_role_valid": True,
            "reference_resolved": True,
            "processor_record_count": 1,
            "ledger_journal_count": 1,
            "tolerance_minor": 0,
        }
    )
    assert result.processor_minor == oracle["processor_minor"]
    assert result.ledger_minor == oracle["ledger_minor"]
    assert result.processor_ledger_delta_minor == oracle["processor_ledger_delta_minor"]
    assert result.difference_minor == oracle["difference_minor"]
    assert result.status == oracle["status"]
    assert list(result.reason_codes) == oracle["reason_codes"]
    assert result.authoritative_proof is False


def test_p2s4_t002_all_event_signs_and_multiple_records_aggregate_once() -> None:
    cases = (
        ("CAPTURE", "DEBIT", 1),
        ("REFUND", "CREDIT", -1),
        ("CHARGEBACK", "CREDIT", -1),
        ("REVERSAL", "CREDIT", -1),
    )
    for event_type, side, sign in cases:
        first = processor_event(
            source_record_id=f"{event_type}-1", event_type=event_type, amount_minor=40
        )
        second = processor_event(
            source_record_id=f"{event_type}-2", event_type=event_type, amount_minor=60
        )
        if event_type != "CAPTURE":
            first = signed_record(dict(first, reference_event_id="capture-1", payload_sha256=""))
            second = signed_record(dict(second, reference_event_id="capture-1", payload_sha256=""))
            capture = processor_event(source_record_id="capture-1", amount_minor=100)
            events = [capture, first, second]
        else:
            events = [first, second]
        row = candidate(
            admitted(events, [transaction_journal(f"journal-{event_type}", event_type, 100, side)]),
            event_type,
        )
        assert row.processor_minor == sign * 100
        assert row.ledger_minor == sign * 100
        assert row.processor_record_count == 2
        assert row.status == "MATCHED"


def test_p2s4_t003_full_outer_join_preserves_missing_sources() -> None:
    batch = admitted(
        [processor_event(event_type="CAPTURE", amount_minor=100)],
        [transaction_journal("refund-ledger", "REFUND", 25, "CREDIT")],
    )
    results = {
        row.key_components.event_class: row for row in reconcile_transactions(batch).candidates
    }
    assert results["CAPTURE"].reason_codes == ("MISSING_LEDGER_MOVEMENT",)
    assert results["REFUND"].reason_codes == ("MISSING_PROCESSOR_ACTIVITY",)


def test_p2s4_t004_tolerance_applies_only_to_clean_difference() -> None:
    within = candidate(
        admitted(
            [processor_event(amount_minor=100)],
            [transaction_journal("j1", "CAPTURE", 99, "DEBIT")],
            tolerance=1,
        ),
        "CAPTURE",
    )
    assert within.status == "WITHIN_TOLERANCE"
    assert within.reason_codes == ("TOLERATED_DIFFERENCE",)
    outside = candidate(
        admitted(
            [processor_event(amount_minor=100)],
            [transaction_journal("j1", "CAPTURE", 98, "DEBIT")],
            tolerance=1,
        ),
        "CAPTURE",
    )
    assert outside.status == "EXCEPTION"
    assert outside.reason_codes == ("PROCESSOR_LEDGER_MISMATCH",)


def test_p2s4_t005_role_side_and_counterpart_failures_precede_tolerance() -> None:
    invalid_rows = [
        transaction_journal("wrong-side", "CAPTURE", 100, "CREDIT"),
        transaction_journal(
            "wrong-counterpart", "CAPTURE", 100, "DEBIT", counterpart_role="BANK_CASH"
        ),
        transaction_journal(
            "missing-clearing", "CAPTURE", 100, "DEBIT", clearing_role="MERCHANT_PAYABLE"
        ),
    ]
    for row in invalid_rows:
        result = candidate(
            admitted([processor_event(amount_minor=100)], [row], tolerance=MAX_I64), "CAPTURE"
        )
        assert result.status == "EXCEPTION"
        assert result.reason_codes == ("INVALID_ACCOUNT_ROLE",)


def test_p2s4_t006_exact_reference_capacity_shared_across_negative_classes() -> None:
    capture = processor_event(source_record_id="capture-1", amount_minor=100)
    refund = processor_event(
        source_record_id="refund-1",
        event_type="REFUND",
        amount_minor=60,
        reference_event_id="capture-1",
    )
    chargeback = processor_event(
        source_record_id="chargeback-1",
        event_type="CHARGEBACK",
        amount_minor=41,
        reference_event_id="capture-1",
    )
    rows = reconcile_transactions(
        admitted(
            [capture, refund, chargeback],
            [
                transaction_journal("jc", "CAPTURE", 100, "DEBIT"),
                transaction_journal("jr", "REFUND", 60, "CREDIT"),
                transaction_journal("jb", "CHARGEBACK", 41, "CREDIT"),
            ],
        )
    ).candidates
    negative = {row.key_components.event_class: row for row in rows}
    assert "OVER_APPLIED_REFERENCE" in negative["REFUND"].reason_codes
    assert "OVER_APPLIED_REFERENCE" in negative["CHARGEBACK"].reason_codes


def test_p2s4_t007_exact_capacity_and_multiple_captures_remain_distinct() -> None:
    events = [
        processor_event(source_record_id="capture-1", amount_minor=40),
        processor_event(source_record_id="capture-2", amount_minor=90),
        processor_event(
            source_record_id="refund-1",
            event_type="REFUND",
            amount_minor=41,
            reference_event_id="capture-1",
        ),
    ]
    result = candidate(
        admitted(events, [transaction_journal("jr", "REFUND", 41, "CREDIT")]), "REFUND"
    )
    assert "OVER_APPLIED_REFERENCE" in result.reason_codes
    exact = candidate(
        admitted(
            [
                processor_event(source_record_id="capture-x", amount_minor=41),
                processor_event(
                    source_record_id="refund-x",
                    event_type="REFUND",
                    amount_minor=41,
                    reference_event_id="capture-x",
                ),
            ],
            [transaction_journal("jx", "REFUND", 41, "CREDIT")],
        ),
        "REFUND",
    )
    assert "OVER_APPLIED_REFERENCE" not in exact.reason_codes


@pytest.mark.parametrize(
    "updates",
    [
        {"reference_event_id": "missing"},
        {"reference_event_id": "refund-target"},
        {"reference_event_id": "capture-other", "merchant_id": "merchant-other"},
    ],
)
def test_p2s4_t008_unresolved_reference_variants(updates: dict[str, Any]) -> None:
    events = [processor_event(source_record_id="capture-1", amount_minor=100)]
    if updates["reference_event_id"] == "refund-target":
        events.append(
            processor_event(
                source_record_id="refund-target",
                event_type="REFUND",
                amount_minor=1,
                reference_event_id="capture-1",
            )
        )
    if updates["reference_event_id"] == "capture-other":
        events.append(processor_event(source_record_id="capture-other", amount_minor=100))
    events.append(
        processor_event(
            source_record_id="negative", event_type="REFUND", amount_minor=10, **updates
        )
    )
    matches = [
        row
        for row in reconcile_transactions(admitted(events, [])).candidates
        if row.key_components.event_class == "REFUND"
        and row.key_components.merchant_id == updates.get("merchant_id", "merchant-1")
    ]
    assert len(matches) == 1
    assert "UNRESOLVED_REFERENCE" in matches[0].reason_codes


def test_p2s4_t009_mixed_replay_new_bundle_uses_observations_once() -> None:
    first = admitted(
        [processor_event(source_record_id="capture-1", amount_minor=100)],
        [transaction_journal("capture-journal", "CAPTURE", 100, "DEBIT")],
    )
    first_result = reconcile_transactions(first)
    second = admitted(
        [
            processor_event(source_record_id="capture-1", amount_minor=100),
            processor_event(
                source_record_id="refund-1",
                event_type="REFUND",
                amount_minor=25,
                reference_event_id="capture-1",
            ),
        ],
        [
            transaction_journal("capture-journal", "CAPTURE", 100, "DEBIT"),
            transaction_journal("refund-journal", "REFUND", 25, "CREDIT"),
        ],
        prior_state=first.state,
        run_id="run-0002",
    )
    assert second.replay_count == 2
    assert len(second.records) == 2
    assert len(second.observed_records) == 4
    assert sum(row.identical_replay for row in second.observed_records) == 2
    result = reconcile_transactions(second, first_result.state)
    assert len(result.state.records) == 4
    assert (
        next(row for row in result.candidates if row.key_components.event_class == "REFUND").status
        == "MATCHED"
    )


def test_p2s4_t010_permutation_determinism_and_immutable_results() -> None:
    events = [
        processor_event(source_record_id="capture-1", amount_minor=100),
        processor_event(
            source_record_id="refund-1",
            event_type="REFUND",
            amount_minor=25,
            reference_event_id="capture-1",
        ),
    ]
    journals = [
        transaction_journal("capture-journal", "CAPTURE", 100, "DEBIT"),
        transaction_journal("refund-journal", "REFUND", 25, "CREDIT"),
    ]
    first = reconcile_transactions(admitted(events, journals))
    second = reconcile_transactions(admitted(list(reversed(events)), list(reversed(journals))))
    assert [row.value() for row in first.candidates] == [row.value() for row in second.candidates]
    assert first.state.semantic_digest() == second.state.semantic_digest()
    assert first.manifest_sha256 != second.manifest_sha256
    assert first.semantic_digest() != second.semantic_digest()
    with pytest.raises(FrozenInstanceError):
        first.authoritative_proof = True  # type: ignore[misc]


def test_p2s4_t011_checked_aggregate_and_absolute_overflow_fail_closed() -> None:
    with pytest.raises(AdmissionRejected, match="SCHEMA_VIOLATION"):
        reconcile_transactions(
            admitted(
                [
                    processor_event(source_record_id="c1", amount_minor=MAX_I64),
                    processor_event(source_record_id="c2", amount_minor=1),
                ],
                [],
            )
        )
    with pytest.raises(AdmissionRejected, match="SCHEMA_VIOLATION"):
        reconcile_transactions(
            admitted(
                [
                    processor_event(
                        source_record_id="r1",
                        event_type="REFUND",
                        amount_minor=1,
                        reference_event_id="c1",
                    ),
                    processor_event(source_record_id="c1", amount_minor=MAX_I64),
                ],
                [transaction_journal("jr", "REFUND", MAX_I64, "DEBIT")],
            )
        )


def test_p2s4_t012_state_conflict_and_internal_guards_fail_closed() -> None:
    batch = admitted([processor_event()], [])
    source = batch.observed_records[0]
    conflict = replace(source, business_sha256="f" * 64)
    with pytest.raises(AdmissionRejected, match="IDENTITY_CONFLICT"):
        _transaction_records(batch, TransactionState((conflict,)))
    with pytest.raises(AdmissionRejected, match="SCHEMA_VIOLATION"):
        _object(b"[]", "bad")
    with pytest.raises(AdmissionRejected, match="transaction field missing"):
        _text({}, "processor")
    with pytest.raises(AdmissionRejected, match="transaction event key drift"):
        reconcile_transactions(
            replace(
                batch, observed_records=(replace(source, reconciliation_key="txn:" + "0" * 64),)
            )
        )


def test_p2s4_t013_policy_guards_and_reason_merge() -> None:
    batch = admitted([], [])
    parsed = json.loads(batch.policy_canonical_bytes)
    del parsed["transaction_rules"]
    with pytest.raises(AdmissionRejected, match="transaction policy is incomplete"):
        _policy(replace(batch, policy_canonical_bytes=canonical_json_bytes(parsed)))
    assert _merge_reasons(
        {TransactionKey("p", "m", "pay", "CAPTURE", "INR"): {"UNRESOLVED_REFERENCE"}},
        {TransactionKey("p", "m", "pay", "CAPTURE", "INR"): {"INVALID_ACCOUNT_ROLE"}},
    ) == {
        TransactionKey("p", "m", "pay", "CAPTURE", "INR"): {
            "UNRESOLVED_REFERENCE",
            "INVALID_ACCOUNT_ROLE",
        }
    }
    assert REASON_ORDER[0] == "INVALID_ACCOUNT_ROLE"


def test_p2s4_t014_candidate_value_and_empty_state_are_deterministic() -> None:
    key = TransactionKey("p", "m", "pay", "CAPTURE", "INR")
    row = TransactionCandidate(key.reconciliation_key, key, 0, 0, 0, 0, 0, 0, "MATCHED", (), ())
    assert row.value()["authoritative_proof"] is False
    assert TransactionState().semantic_digest() == TransactionState().semantic_digest()


def test_p2s4_t015_cli_success_and_owned_failure(tmp_path: Path) -> None:
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
        "ledgerguard_part2_stage4",
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
    assert result["outcome"] == "TRANSACTION_RECONCILIATION_CANDIDATE"
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


def test_p2s4_t016_nontransaction_observations_are_excluded_and_record_fallback_works() -> None:
    policy_bytes, manifest_bytes, supplied, _ = build_bundle()
    batch = admit_bundle(ROOT, policy_bytes, manifest_bytes, supplied)
    transaction_records = _transaction_records(batch, TransactionState())
    assert {row.family for row in transaction_records} == {"PROCESSOR_EVENT", "LEDGER_JOURNAL"}
    fallback = _transaction_records(replace(batch, observed_records=()), TransactionState())
    assert fallback == transaction_records
    settlement = next(row for row in batch.observed_records if row.family == "PROCESSOR_SETTLEMENT")
    assert (
        _transaction_records(replace(batch, observed_records=()), TransactionState((settlement,)))
        == transaction_records
    )


def test_p2s4_t017_policy_shape_domain_currency_and_tolerance_guards() -> None:
    batch = admitted([], [])

    def changed(update: Any) -> AdmittedBatch:
        value = json.loads(batch.policy_canonical_bytes)
        update(value)
        return replace(batch, policy_canonical_bytes=canonical_json_bytes(value))

    with pytest.raises(AdmissionRejected, match="transaction policy shape differs"):
        _policy(changed(lambda value: value["transaction_rules"].update(event_signs=[])))
    with pytest.raises(AdmissionRejected, match="transaction policy domain differs"):
        _policy(changed(lambda value: value["transaction_rules"]["event_signs"].pop("CAPTURE")))
    with pytest.raises(AdmissionRejected, match="currency policy shape differs"):
        _policy(changed(lambda value: value["currency_rules"].update(INR=[])))
    with pytest.raises(AdmissionRejected, match="negative transaction tolerance"):
        _policy(
            changed(
                lambda value: value["currency_rules"]["INR"].update(transaction_tolerance_minor=-1)
            )
        )


def test_p2s4_t018_internal_reference_and_journal_guards() -> None:
    batch = admitted(
        [processor_event()], [transaction_journal("journal-1", "CAPTURE", 100, "DEBIT")]
    )
    event_record = next(row for row in batch.records if row.family == "PROCESSOR_EVENT")
    journal_record = next(row for row in batch.records if row.family == "LEDGER_JOURNAL")
    key = TransactionKey("processor-a", "merchant-1", "payment-1", "CAPTURE", "INR")
    event_value = event_record.value()
    event_value["reference_event_id"] = "invalid"
    assert _reference_reasons({key: [(event_record, event_value)]}, {}) == {
        key: {"UNRESOLVED_REFERENCE"}
    }
    with pytest.raises(AdmissionRejected, match="transaction journal key drift"):
        _journal_facts(
            (replace(journal_record, reconciliation_key="txn:" + "0" * 64),),
            {"DEBIT": 1, "CREDIT": -1},
            {"MERCHANT_PAYABLE"},
        )

    def invalid_journal(postings: Any) -> AdmittedRecord:
        value = journal_record.value()
        value["postings"] = postings
        return replace(journal_record, canonical_bytes=canonical_json_bytes(value))

    with pytest.raises(AdmissionRejected, match="journal postings unavailable"):
        _journal_facts(
            (invalid_journal("invalid"),),
            {"DEBIT": 1, "CREDIT": -1},
            {"MERCHANT_PAYABLE"},
        )
    with pytest.raises(AdmissionRejected, match="posting must be an object"):
        _journal_facts(
            (invalid_journal(["invalid"]),),
            {"DEBIT": 1, "CREDIT": -1},
            {"MERCHANT_PAYABLE"},
        )
    with pytest.raises(AdmissionRejected, match="ledger side policy missing"):
        _journal_facts(
            (journal_record,),
            {"CREDIT": -1},
            {"MERCHANT_PAYABLE"},
        )


def test_p2s4_t019_status_rejects_unknown_reason_and_missing_currency_policy() -> None:
    key = TransactionKey("p", "m", "pay", "CAPTURE", "INR")
    with pytest.raises(AdmissionRejected, match="unknown financial reason"):
        _status(key, 0, {"INVENTED_REASON"}, {"INR": 0})
    with pytest.raises(AdmissionRejected, match="currency tolerance unavailable"):
        _status(key, 1, set(), {})
