from __future__ import annotations

import json
import os
import subprocess
import sys
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from typing import Any

import pytest

import ledgerguard.reconciliation.finalization as finalization_module
from ledgerguard.reconciliation import (
    AdmissionRejected,
    BankAllocation,
    FinalizationReceipt,
    FinalizationRejected,
    FinalizationStore,
    SettlementCandidate,
    SettlementKey,
    SettlementReconciliationBatch,
    SettlementState,
    TransactionCandidate,
    TransactionKey,
    TransactionReconciliationBatch,
    TransactionState,
    admit_bundle,
    business_digest,
    canonical_json_bytes,
    canonical_sha256,
    case_id,
    proof_id,
    reconcile_settlements,
    reconcile_transactions,
)
from ledgerguard.reconciliation.admission import AdmissionState, SourceStateEntry
from ledgerguard.reconciliation.contracts import ContractRegistry

ROOT = Path(__file__).resolve().parents[1]


def _transaction_candidate(
    *,
    payment_id: str = "payment-1",
    status: str = "MATCHED",
    reasons: tuple[str, ...] = (),
    processor: int = 100,
    ledger: int = 100,
) -> TransactionCandidate:
    key = TransactionKey("processor-a", "merchant-1", payment_id, "CAPTURE", "INR")
    difference = abs(processor - ledger)
    return TransactionCandidate(
        reconciliation_key=key.reconciliation_key,
        key_components=key,
        processor_minor=processor,
        ledger_minor=ledger,
        processor_ledger_delta_minor=processor - ledger,
        difference_minor=difference,
        processor_record_count=1,
        ledger_journal_count=1,
        status=status,
        reason_codes=reasons,
        source_identities=(
            ("LEDGER_JOURNAL", "ledger-a", f"journal-{payment_id}"),
            ("PROCESSOR_EVENT", "processor-a", f"event-{payment_id}"),
        ),
    )


def _transaction_batch(
    *candidates: TransactionCandidate,
    run_id: str = "run-stage6-001",
    manifest: str = "a" * 64,
    policy: str = "b" * 64,
    policy_version: str = "v1",
) -> TransactionReconciliationBatch:
    rows = candidates or (_transaction_candidate(),)
    return TransactionReconciliationBatch(
        run_id=run_id,
        policy_version=policy_version,
        policy_sha256=policy,
        manifest_sha256=manifest,
        candidates=tuple(rows),
        state=TransactionState(),
    )


def _settlement_candidate(
    *,
    settlement_id: str = "settlement-1",
    status: str = "MATCHED",
    reasons: tuple[str, ...] = (),
) -> SettlementCandidate:
    key = SettlementKey("processor-a", "merchant-1", settlement_id, "cycle-1", "INR")
    return SettlementCandidate(
        reconciliation_key=key.reconciliation_key,
        key_components=key,
        processor_net_minor=100,
        ledger_clearing_minor=100,
        bank_minor=100,
        processor_ledger_delta_minor=0,
        processor_bank_delta_minor=0,
        ledger_bank_delta_minor=0,
        difference_minor=0,
        processor_settlement_count=1,
        ledger_journal_count=1,
        allocated_bank_entry_count=1,
        status=status,
        reason_codes=reasons,
        source_identities=(
            ("BANK_ENTRY", "bank-1", f"bank-{settlement_id}"),
            ("LEDGER_JOURNAL", "ledger-a", f"journal-{settlement_id}"),
            ("PROCESSOR_SETTLEMENT", "processor-a", f"processor-{settlement_id}"),
        ),
    )


def _settlement_batch(
    *candidates: SettlementCandidate,
    run_id: str = "run-stage6-001",
    manifest: str = "a" * 64,
    policy: str = "b" * 64,
    policy_version: str = "v1",
) -> SettlementReconciliationBatch:
    rows = candidates or (_settlement_candidate(),)
    return SettlementReconciliationBatch(
        run_id=run_id,
        policy_version=policy_version,
        policy_sha256=policy,
        manifest_sha256=manifest,
        candidates=tuple(rows),
        bank_allocations=(
            BankAllocation(
                source_identity=("BANK_ENTRY", "bank-1", "bank-settlement-1"),
                merchant_id="merchant-1",
                currency="INR",
                normalized_settlement_reference="settlement-1",
                disposition="ALLOCATED",
                settlement_reconciliation_key=rows[0].reconciliation_key,
                signed_minor=100,
                account_permitted=True,
                duplicate_current_bundle=False,
                reason_codes=(),
            ),
        ),
        state=SettlementState(),
        status="EXCEPTION" if any(row.status == "EXCEPTION" for row in rows) else "MATCHED",
        reason_codes=tuple(reason for row in rows for reason in row.reason_codes),
    )


def _store(tmp_path: Path, name: str = "store") -> FinalizationStore:
    return FinalizationStore(ROOT, tmp_path / name)


def _real_batches(
    *, run_id: str = "run-0001"
) -> tuple[TransactionReconciliationBatch, SettlementReconciliationBatch]:
    from test_part2_stage3_admission import build_bundle

    policy_bytes, manifest_bytes, supplied, _ = build_bundle(run_id=run_id)
    admitted = admit_bundle(ROOT, policy_bytes, manifest_bytes, supplied)
    return reconcile_transactions(admitted), reconcile_settlements(admitted)


def _finalize_transaction(
    store: FinalizationStore,
    *,
    attempt: str = "attempt-stage6-001",
    expected: str | None = None,
    batch: TransactionReconciliationBatch | None = None,
    created_at: str = "2026-09-04T01:00:00Z",
    fault: str | None = None,
) -> FinalizationReceipt:
    return store.finalize(
        attempt_id=attempt,
        expected_head=expected,
        created_at=created_at,
        transaction_batch=batch or _transaction_batch(),
        fault_point=fault,
    )


def _persist_object(store: FinalizationStore, value: dict[str, Any]) -> str:
    raw = canonical_json_bytes(value)
    digest = sha256(raw).hexdigest()
    (store.root / "objects" / f"{digest}.json").write_bytes(raw)
    return digest


def _replace_head_commit(store: FinalizationStore, value: dict[str, Any]) -> str:
    raw = canonical_json_bytes(value)
    digest = sha256(raw).hexdigest()
    (store.root / "commits" / f"{digest}.json").write_bytes(raw)
    (store.root / "control/HEAD").write_text(digest + "\n")
    return digest


def test_p2s6_production_identity_matches_frozen_golden_vector() -> None:
    chain = json.loads((ROOT / "spec/contract-coherence-vectors-v1.json").read_text())[
        "policy_manifest_proof_case_chain"
    ]
    proof = chain["proof"]
    proof_components = {
        key: proof[key]
        for key in (
            "grain",
            "reconciliation_key",
            "revision",
            "source_manifest_sha256",
            "policy_sha256",
        )
    }
    case = chain["case_revision_one"]
    case_components = {
        key: case[key] for key in ("grain", "reconciliation_key", "initial_exception_proof_id")
    }
    assert proof_id(proof_components) == chain["expected_proof_id"]
    assert case_id(case_components) == chain["expected_case_id"]


def test_p2s6_matched_proof_is_atomic_canonical_and_has_no_case(tmp_path: Path) -> None:
    store = _store(tmp_path)
    receipt = _finalize_transaction(store)
    assert store.read_head() == receipt.commit_sha256
    assert len(receipt.proofs) == 1
    assert receipt.cases == ()
    proof = store.read_proof(receipt.proofs[0].object_sha256)
    assert proof["status"] == "MATCHED"
    assert proof["revision"] == 1
    assert proof["reason_codes"] == []
    assert "prior_proof_id" not in proof
    assert store.verify_history() is not None
    raw = (store.root / "objects" / f"{receipt.proofs[0].object_sha256}.json").read_bytes()
    assert raw == canonical_json_bytes(proof)


def test_p2s6_exception_opens_case_and_late_match_appends_resolution(tmp_path: Path) -> None:
    store = _store(tmp_path)
    exception = _transaction_candidate(
        status="EXCEPTION",
        reasons=("PROCESSOR_LEDGER_MISMATCH",),
        ledger=99,
    )
    first = _finalize_transaction(store, batch=_transaction_batch(exception))
    first_proof = store.read_proof(first.proofs[0].object_sha256)
    first_case = store.read_case_revision(first.cases[0].object_sha256)
    first_proof_raw = canonical_json_bytes(first_proof)
    first_case_raw = canonical_json_bytes(first_case)
    assert first_case["status"] == "OPEN"
    assert first_case["proof_id"] == first_proof["proof_id"]

    second = _finalize_transaction(
        store,
        attempt="attempt-stage6-002",
        expected=first.commit_sha256,
        batch=_transaction_batch(
            _transaction_candidate(), run_id="run-stage6-002", manifest="c" * 64
        ),
        created_at="2026-09-04T01:05:00+00:00",
    )
    second_proof = store.read_proof(second.proofs[0].object_sha256)
    second_case = store.read_case_revision(second.cases[0].object_sha256)
    assert second_proof["revision"] == 2
    assert second_proof["prior_proof_id"] == first_proof["proof_id"]
    assert second_case["revision"] == 2
    assert second_case["case_id"] == first_case["case_id"]
    assert second_case["prior_case_revision_id"] == first_case["case_revision_sha256"]
    assert second_case["proof_id"] == second_proof["proof_id"]
    assert second_case["status"] == "RESOLVED_BY_LATE_DATA"
    assert canonical_json_bytes(first_proof) == first_proof_raw
    assert canonical_json_bytes(first_case) == first_case_raw
    assert store.verify_history() is not None


def test_p2s6_exception_successor_and_changed_policy_append_revisions(tmp_path: Path) -> None:
    store = _store(tmp_path)
    candidate = _transaction_candidate(
        status="EXCEPTION",
        reasons=("MISSING_LEDGER_MOVEMENT",),
        ledger=0,
    )
    first = _finalize_transaction(store, batch=_transaction_batch(candidate))
    second = _finalize_transaction(
        store,
        attempt="attempt-stage6-002",
        expected=first.commit_sha256,
        batch=_transaction_batch(
            candidate,
            run_id="run-stage6-002",
            manifest="c" * 64,
            policy="d" * 64,
            policy_version="v2",
        ),
        created_at="2026-09-04T01:05:00Z",
    )
    proof = store.read_proof(second.proofs[0].object_sha256)
    case = store.read_case_revision(second.cases[0].object_sha256)
    assert proof["revision"] == 2
    assert proof["policy_version"] == "v2"
    assert case["revision"] == 2
    assert case["status"] == "OPEN"


def test_p2s6_transaction_and_settlement_candidates_commit_together(tmp_path: Path) -> None:
    store = _store(tmp_path)
    receipt = store.finalize(
        attempt_id="attempt-stage6-001",
        expected_head=None,
        created_at="2026-09-04T01:00:00Z",
        transaction_batch=_transaction_batch(),
        settlement_batch=_settlement_batch(),
    )
    assert len(receipt.proofs) == 2
    assert {store.read_proof(row.object_sha256)["grain"] for row in receipt.proofs} == {
        "TRANSACTION",
        "SETTLEMENT",
    }
    assert store.verify_history() is not None


def test_p2s6_authoritative_history_recovers_real_admission_and_grain_states(
    tmp_path: Path,
) -> None:
    from test_part2_stage3_admission import build_bundle

    policy_bytes, manifest_bytes, supplied, _ = build_bundle()
    admitted = admit_bundle(ROOT, policy_bytes, manifest_bytes, supplied)
    transaction_batch = reconcile_transactions(admitted)
    settlement_batch = reconcile_settlements(admitted)
    store = _store(tmp_path)
    receipt = store.finalize(
        attempt_id="attempt-stage6-001",
        expected_head=None,
        created_at="2026-09-04T01:00:00Z",
        transaction_batch=transaction_batch,
        settlement_batch=settlement_batch,
    )
    admission_state, transaction_state, settlement_state = store.load_states()
    assert admission_state == admitted.state
    assert transaction_state == transaction_batch.state
    assert settlement_state == settlement_batch.state

    next_policy, next_manifest, next_supplied, _ = build_bundle(run_id="run-0002")
    next_admitted = admit_bundle(
        ROOT,
        next_policy,
        next_manifest,
        next_supplied,
        prior_state=admission_state,
    )
    next_transactions = reconcile_transactions(next_admitted, transaction_state)
    next_settlements = reconcile_settlements(next_admitted, settlement_state)
    assert next_admitted.replay_count == 4
    second = store.finalize(
        attempt_id="attempt-stage6-002",
        expected_head=receipt.commit_sha256,
        created_at="2026-09-04T01:05:00Z",
        transaction_batch=next_transactions,
        settlement_batch=next_settlements,
    )
    assert all(reference.revision == 2 for reference in second.proofs)
    assert store.load_states()[0] == next_admitted.state
    (store.root / "attempts/attempt-stage6-001/outcome.json").unlink()
    recovered = store.finalize(
        attempt_id="attempt-stage6-001",
        expected_head=None,
        created_at="2026-09-04T01:00:00Z",
        transaction_batch=transaction_batch,
        settlement_batch=settlement_batch,
    )
    assert recovered == receipt
    assert store.read_head() == second.commit_sha256


def test_p2s6_cross_grain_source_conflict_cannot_become_authoritative(tmp_path: Path) -> None:
    transaction_batch, settlement_batch = _real_batches()
    transaction_journal = next(
        record for record in transaction_batch.state.records if record.family == "LEDGER_JOURNAL"
    )
    changed_value = transaction_journal.value()
    changed_value.pop("payment_id")
    changed_value["entry_type"] = "SETTLEMENT"
    changed_value["settlement_id"] = "settlement-1"
    changed_value["settlement_cycle"] = "cycle-1"
    conflicting_journal = replace(
        transaction_journal,
        business_sha256=business_digest(changed_value),
        canonical_bytes=canonical_json_bytes(changed_value),
        reconciliation_key=settlement_batch.candidates[0].reconciliation_key,
    )
    conflicting_settlement = replace(
        settlement_batch,
        state=SettlementState(
            (*settlement_batch.state.records, conflicting_journal),
            settlement_batch.state.duplicate_bank_identities,
        ),
    )
    store = _store(tmp_path)
    with pytest.raises(AdmissionRejected, match="source identity reused"):
        store.finalize(
            attempt_id="attempt-stage6-001",
            expected_head=None,
            created_at="2026-09-04T01:00:00Z",
            transaction_batch=transaction_batch,
            settlement_batch=conflicting_settlement,
        )
    assert store.read_head() is None


def test_p2s6_exact_retry_is_idempotent_and_historical_retry_recovers(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    first = _finalize_transaction(store)
    counts = tuple(len(list((store.root / name).rglob("*"))) for name in ("objects", "commits"))
    assert _finalize_transaction(store) == first
    assert (
        tuple(len(list((store.root / name).rglob("*"))) for name in ("objects", "commits"))
        == counts
    )
    second = _finalize_transaction(
        store,
        attempt="attempt-stage6-002",
        expected=first.commit_sha256,
        batch=_transaction_batch(
            _transaction_candidate(payment_id="payment-2"),
            run_id="run-stage6-002",
            manifest="c" * 64,
        ),
    )
    assert store.read_head() == second.commit_sha256
    assert _finalize_transaction(store) == first
    assert store.read_head() == second.commit_sha256


def test_p2s6_reused_attempt_and_stale_head_leave_authority_unchanged(tmp_path: Path) -> None:
    store = _store(tmp_path)
    first = _finalize_transaction(store)
    with pytest.raises(FinalizationRejected, match="different request") as reused:
        _finalize_transaction(
            store,
            batch=_transaction_batch(_transaction_candidate(payment_id="changed")),
        )
    assert reused.value.as_dict()["authoritative_proof"] is False
    with pytest.raises(FinalizationRejected, match="stale authoritative") as stale:
        _finalize_transaction(
            store,
            attempt="attempt-stage6-002",
            batch=_transaction_batch(_transaction_candidate(payment_id="payment-2")),
        )
    assert stale.value.ownership == "EXECUTION"
    assert stale.value.reason == "EXECUTION_FAILURE"
    assert store.read_head() == first.commit_sha256


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        ({"attempt_id": "bad"}, "SCHEMA_VIOLATION"),
        ({"expected_head": "bad"}, "SCHEMA_VIOLATION"),
        ({"transaction_batch": None}, "SCHEMA_VIOLATION"),
        ({"fault_point": "unknown"}, "SCHEMA_VIOLATION"),
    ],
)
def test_p2s6_invalid_requests_fail_before_authority(
    tmp_path: Path, kwargs: dict[str, Any], reason: str
) -> None:
    store = _store(tmp_path)
    arguments: dict[str, Any] = {
        "attempt_id": "attempt-stage6-001",
        "expected_head": None,
        "created_at": "2026-09-04T01:00:00Z",
        "transaction_batch": _transaction_batch(),
    }
    arguments.update(kwargs)
    with pytest.raises(AdmissionRejected) as captured:
        store.finalize(**arguments)
    assert captured.value.reason == reason
    assert captured.value.authoritative_proof is False
    assert store.read_head() is None


def test_p2s6_metadata_mismatch_empty_batch_and_duplicate_key_reject(tmp_path: Path) -> None:
    store = _store(tmp_path)
    with pytest.raises(AdmissionRejected, match="metadata differ"):
        store.finalize(
            attempt_id="attempt-stage6-001",
            expected_head=None,
            created_at="2026-09-04T01:00:00Z",
            transaction_batch=_transaction_batch(),
            settlement_batch=_settlement_batch(manifest="c" * 64),
        )
    with pytest.raises(AdmissionRejected, match="no reconciliation candidate"):
        store.finalize(
            attempt_id="attempt-stage6-002",
            expected_head=None,
            created_at="2026-09-04T01:00:00Z",
            transaction_batch=replace(_transaction_batch(), candidates=()),
        )
    duplicate = _transaction_candidate()
    with pytest.raises(AdmissionRejected, match="duplicate finalization candidate"):
        store.finalize(
            attempt_id="attempt-stage6-003",
            expected_head=None,
            created_at="2026-09-04T01:00:00Z",
            transaction_batch=_transaction_batch(duplicate, duplicate),
        )
    assert store.read_head() is None


def test_p2s6_invalid_candidate_contract_cannot_publish(tmp_path: Path) -> None:
    store = _store(tmp_path)
    invalid = replace(_transaction_candidate(), status="MATCHED", reason_codes=("NOT_OWNED",))
    with pytest.raises(AdmissionRejected) as captured:
        _finalize_transaction(store, batch=_transaction_batch(invalid))
    assert captured.value.reason == "SCHEMA_VIOLATION"
    assert store.read_head() is None


@pytest.mark.parametrize(
    ("fault", "exit_code", "head_exists"),
    [
        ("after_attempt", 71, False),
        ("after_objects", 72, False),
        ("after_commit", 73, False),
        ("after_head", 74, True),
    ],
)
def test_p2s6_real_process_crash_recovers_deterministically(
    tmp_path: Path, fault: str, exit_code: int, head_exists: bool
) -> None:
    store = _store(tmp_path, fault)
    child = os.fork()
    if child == 0:
        _finalize_transaction(store, fault=fault)
        os._exit(0)
    _, status = os.waitpid(child, 0)
    assert os.waitstatus_to_exitcode(status) == exit_code
    recovered_store = _store(tmp_path, fault)
    assert (recovered_store.read_head() is not None) is head_exists
    receipt = _finalize_transaction(recovered_store)
    assert recovered_store.read_head() == receipt.commit_sha256
    assert recovered_store.verify_history() is not None


def test_p2s6_after_head_crash_can_recover_after_later_commit(tmp_path: Path) -> None:
    store = _store(tmp_path)
    child = os.fork()
    if child == 0:
        _finalize_transaction(store, fault="after_head")
        os._exit(0)
    os.waitpid(child, 0)
    recovered = _store(tmp_path)
    first_head = recovered.read_head()
    assert first_head is not None
    second = _finalize_transaction(
        recovered,
        attempt="attempt-stage6-002",
        expected=first_head,
        batch=_transaction_batch(
            _transaction_candidate(payment_id="payment-2"),
            run_id="run-stage6-002",
            manifest="c" * 64,
        ),
    )
    first = _finalize_transaction(recovered)
    assert first.commit_sha256 == first_head
    assert recovered.read_head() == second.commit_sha256


def test_p2s6_competing_processes_produce_exactly_one_winner(tmp_path: Path) -> None:
    store_root = tmp_path / "race"
    start_read, start_write = os.pipe()
    children: list[int] = []
    for index in (1, 2):
        child = os.fork()
        if child == 0:
            os.close(start_write)
            os.read(start_read, 1)
            store = FinalizationStore(ROOT, store_root)
            try:
                _finalize_transaction(
                    store,
                    attempt=f"attempt-stage6-00{index}",
                    batch=_transaction_batch(
                        _transaction_candidate(payment_id=f"payment-{index}"),
                        run_id=f"run-stage6-00{index}",
                        manifest=str(index) * 64,
                    ),
                )
            except FinalizationRejected:
                os._exit(4)
            os._exit(0)
        children.append(child)
    os.close(start_read)
    os.write(start_write, b"xx")
    os.close(start_write)
    results = [os.waitstatus_to_exitcode(os.waitpid(child, 0)[1]) for child in children]
    assert sorted(results) == [0, 4]
    store = FinalizationStore(ROOT, store_root)
    commit = store.verify_history()
    assert commit is not None
    assert commit["attempt_id"] in {"attempt-stage6-001", "attempt-stage6-002"}


def test_p2s6_independent_stores_are_byte_deterministic(tmp_path: Path) -> None:
    stores = [_store(tmp_path, name) for name in ("first", "second")]
    receipts = [_finalize_transaction(store) for store in stores]
    assert receipts[0] == receipts[1]
    inventories = [
        {
            path.relative_to(store.root): path.read_bytes()
            for directory in ("objects", "commits", "attempts", "control")
            for path in sorted((store.root / directory).rglob("*"))
            if path.is_file()
        }
        for store in stores
    ]
    assert inventories[0] == inventories[1]


def test_p2s6_tampering_and_malformed_control_fail_closed(tmp_path: Path) -> None:
    store = _store(tmp_path)
    receipt = _finalize_transaction(store)
    proof_path = store.root / "objects" / f"{receipt.proofs[0].object_sha256}.json"
    original = proof_path.read_bytes()
    proof_path.write_bytes(original + b" ")
    with pytest.raises(FinalizationRejected, match="digest mismatch"):
        store.verify_history()
    proof_path.write_bytes(original)
    (store.root / "control/HEAD").write_text("not-a-digest\n")
    with pytest.raises(FinalizationRejected, match="head is malformed"):
        store.verify_history()


def test_p2s6_commit_and_outcome_corruption_fail_closed(tmp_path: Path) -> None:
    store = _store(tmp_path)
    receipt = _finalize_transaction(store)
    outcome = store.root / "attempts/attempt-stage6-001/outcome.json"
    outcome_value = json.loads(outcome.read_text())
    outcome_value["commit_sha256"] = "0" * 64
    outcome.write_bytes(canonical_json_bytes(outcome_value))
    with pytest.raises(FinalizationRejected, match="persisted object unavailable"):
        _finalize_transaction(store)

    commit_path = store.root / "commits" / f"{receipt.commit_sha256}.json"
    commit = json.loads(commit_path.read_text())
    commit["updated_keys"] = []
    raw = canonical_json_bytes(commit)
    replacement = sha256(raw).hexdigest()
    (store.root / "commits" / f"{replacement}.json").write_bytes(raw)
    (store.root / "control/HEAD").write_text(replacement + "\n")
    with pytest.raises(FinalizationRejected, match="update inventory differs"):
        store.verify_history()


def test_p2s6_real_storage_failure_has_execution_ownership(tmp_path: Path) -> None:
    store = _store(tmp_path)
    objects = store.root / "objects"
    objects.rmdir()
    objects.write_text("not-a-directory")
    with pytest.raises(FinalizationRejected, match="storage operation failed") as captured:
        _finalize_transaction(store)
    assert captured.value.as_dict() == {
        "outcome": "NO_AUTHORITATIVE_PARTIAL_PROOF",
        "ownership": "EXECUTION",
        "reason_code": "EXECUTION_FAILURE",
        "detail": "local finalization storage operation failed",
        "authoritative_proof": False,
    }
    assert store.read_head() is None


def test_p2s6_identity_and_candidate_authority_guards() -> None:
    with pytest.raises(AdmissionRejected, match="proof identity components"):
        proof_id({"grain": "TRANSACTION"})
    with pytest.raises(AdmissionRejected, match="case identity components"):
        case_id({"grain": "TRANSACTION"})
    candidate = replace(_transaction_candidate(), authoritative_proof=True)
    with pytest.raises(AdmissionRejected, match="candidate authority boundary"):
        finalization_module._candidate_value(candidate)


def test_p2s6_low_level_proof_shape_guard() -> None:
    with pytest.raises(AdmissionRejected, match="candidate proof shape"):
        finalization_module._proof(
            ContractRegistry.load(ROOT),
            candidate={"key_components": [], "totals": {}},
            metadata={
                "manifest_sha256": "a" * 64,
                "policy_sha256": "b" * 64,
                "run_id": "run-stage6-001",
                "policy_version": "v1",
            },
            created_at="2026-09-04T01:00:00Z",
            revision=1,
            prior=None,
        )


def test_p2s6_temporary_files_are_removed_after_real_replace_failures(tmp_path: Path) -> None:
    store = _store(tmp_path)
    destination = store.root / "objects/destination.json"
    destination.mkdir()
    with pytest.raises(IsADirectoryError):
        store._write_immutable(destination, b"value")
    assert not list((store.root / "objects").glob(".destination.json.*.tmp"))

    head = store.root / "control/HEAD"
    head.mkdir()
    with pytest.raises(IsADirectoryError):
        store._replace_head("0" * 64)
    assert not list((store.root / "control").glob(".HEAD.*.tmp"))


def test_p2s6_immutable_collision_and_interrupted_replace_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path)
    destination = store.root / "objects/collision.json"
    destination.write_bytes(b"first")
    with pytest.raises(FinalizationRejected, match="immutable path conflict"):
        store._write_immutable(destination, b"second")

    target = store.root / "objects/interrupted.json"

    def fail_replace(source: Path, destination_path: Path) -> None:
        raise OSError(f"replace interrupted: {source} -> {destination_path}")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(OSError, match="replace interrupted"):
        store._write_immutable(target, b"value")
    assert not list((store.root / "objects").glob(".interrupted.json.*.tmp"))


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        (b"{ }", "not canonical"),
        (b"{", "is invalid"),
    ],
)
def test_p2s6_persisted_json_must_be_strict_and_canonical(
    tmp_path: Path, raw: bytes, message: str
) -> None:
    store = _store(tmp_path)
    path = store.root / "objects/value.json"
    path.write_bytes(raw)
    with pytest.raises(FinalizationRejected, match=message):
        store._read_canonical(path)


def test_p2s6_unreadable_head_and_invalid_addresses_fail_closed(tmp_path: Path) -> None:
    store = _store(tmp_path)
    (store.root / "control/HEAD").write_bytes(b"\xff")
    with pytest.raises(FinalizationRejected, match="head is unreadable"):
        store.read_head()
    with pytest.raises(FinalizationRejected, match="invalid content address"):
        store.read_proof("bad")
    with pytest.raises(FinalizationRejected, match="invalid commit address"):
        store._read_commit("bad")


def test_p2s6_persisted_contract_and_self_digest_fail_closed(tmp_path: Path) -> None:
    store = _store(tmp_path)
    invalid_digest = _persist_object(store, {})
    with pytest.raises(FinalizationRejected, match="violates its contract"):
        store.read_proof(invalid_digest)

    receipt = _finalize_transaction(store)
    proof = store.read_proof(receipt.proofs[0].object_sha256)
    proof["proof_sha256"] = "0" * 64
    digest = _persist_object(store, proof)
    with pytest.raises(FinalizationRejected, match="self-digest mismatch"):
        store.read_proof(digest)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"schema_version": "2.0"}, "commit shape differs"),
        ({"proof_heads": []}, "commit proof_heads differs"),
        ({"case_heads": {"key": "bad"}}, "commit case_heads differs"),
        ({"updated_keys": "bad"}, "commit updated_keys differs"),
        ({"written_proofs": ["same", "same"]}, "commit written_proofs differs"),
        ({"parent_sha256": "bad"}, "commit parent differs"),
        ({"attempt_id": "bad"}, "commit identity differs"),
        ({"request_sha256": "bad"}, "commit identity differs"),
    ],
)
def test_p2s6_malformed_commit_envelopes_fail_closed(
    tmp_path: Path, change: dict[str, Any], message: str
) -> None:
    store = _store(tmp_path)
    receipt = _finalize_transaction(store)
    commit = json.loads((store.root / "commits" / f"{receipt.commit_sha256}.json").read_text())
    commit.update(change)
    _replace_head_commit(store, commit)
    with pytest.raises(FinalizationRejected, match=message):
        store.verify_history()


@pytest.mark.parametrize(
    ("field", "message"),
    [
        ("written_proofs", "proof write inventory differs"),
        ("written_cases", "case write inventory differs"),
    ],
)
def test_p2s6_commit_write_inventories_are_exact(tmp_path: Path, field: str, message: str) -> None:
    store = _store(tmp_path)
    candidate = _transaction_candidate(
        status="EXCEPTION", reasons=("PROCESSOR_LEDGER_MISMATCH",), ledger=99
    )
    receipt = _finalize_transaction(store, batch=_transaction_batch(candidate))
    commit = json.loads((store.root / "commits" / f"{receipt.commit_sha256}.json").read_text())
    commit[field] = []
    _replace_head_commit(store, commit)
    with pytest.raises(FinalizationRejected, match=message):
        store.verify_history()


def test_p2s6_history_cannot_remove_heads_or_mislabel_proof_key(tmp_path: Path) -> None:
    store = _store(tmp_path)
    first = _finalize_transaction(store)
    second = _finalize_transaction(
        store,
        attempt="attempt-stage6-002",
        expected=first.commit_sha256,
        batch=_transaction_batch(
            _transaction_candidate(payment_id="payment-2"),
            run_id="run-stage6-002",
            manifest="c" * 64,
        ),
    )
    commit = json.loads((store.root / "commits" / f"{second.commit_sha256}.json").read_text())
    first_key = first.proofs[0].reconciliation_key
    del commit["proof_heads"][first_key]
    _replace_head_commit(store, commit)
    with pytest.raises(FinalizationRejected, match="removes an immutable head"):
        store.verify_history()

    store = _store(tmp_path, "mislabel")
    receipt = _finalize_transaction(store)
    commit = json.loads((store.root / "commits" / f"{receipt.commit_sha256}.json").read_text())
    actual_key = receipt.proofs[0].reconciliation_key
    false_key = "txn:" + "0" * 64
    commit["proof_heads"] = {false_key: commit["proof_heads"].pop(actual_key)}
    commit["updated_keys"] = [false_key]
    _replace_head_commit(store, commit)
    with pytest.raises(FinalizationRejected, match="request and commit updates differ"):
        store.verify_history()


def test_p2s6_initial_and_successor_proof_chains_are_verified(tmp_path: Path) -> None:
    store = _store(tmp_path, "initial")
    receipt = _finalize_transaction(store)
    proof = store.read_proof(receipt.proofs[0].object_sha256)
    proof["revision"] = 2
    proof["prior_proof_id"] = "prf:" + "0" * 64
    identity = {
        key: proof[key]
        for key in (
            "grain",
            "reconciliation_key",
            "revision",
            "source_manifest_sha256",
            "policy_sha256",
        )
    }
    proof["proof_id"] = proof_id(identity)
    proof["proof_sha256"] = canonical_sha256(proof, {"proof_sha256"})
    proof_digest = _persist_object(store, proof)
    commit = json.loads((store.root / "commits" / f"{receipt.commit_sha256}.json").read_text())
    key = receipt.proofs[0].reconciliation_key
    commit["proof_heads"][key] = proof_digest
    commit["written_proofs"] = [proof_digest]
    _replace_head_commit(store, commit)
    with pytest.raises(FinalizationRejected, match="initial proof revision differs"):
        store.verify_history()

    store = _store(tmp_path, "successor")
    first = _finalize_transaction(store)
    second = _finalize_transaction(
        store,
        attempt="attempt-stage6-002",
        expected=first.commit_sha256,
        batch=_transaction_batch(run_id="run-stage6-002", manifest="c" * 64),
    )
    proof = store.read_proof(second.proofs[0].object_sha256)
    proof["prior_proof_id"] = "prf:" + "0" * 64
    proof["proof_sha256"] = canonical_sha256(proof, {"proof_sha256"})
    proof_digest = _persist_object(store, proof)
    commit = json.loads((store.root / "commits" / f"{second.commit_sha256}.json").read_text())
    commit["proof_heads"][key] = proof_digest
    commit["written_proofs"] = [proof_digest]
    _replace_head_commit(store, commit)
    with pytest.raises(FinalizationRejected, match="proof predecessor chain differs"):
        store.verify_history()


def test_p2s6_proof_case_transition_and_case_bindings_are_verified(tmp_path: Path) -> None:
    candidate = _transaction_candidate(
        status="EXCEPTION", reasons=("PROCESSOR_LEDGER_MISMATCH",), ledger=99
    )
    store = _store(tmp_path, "missing-case")
    receipt = _finalize_transaction(store, batch=_transaction_batch(candidate))
    commit = json.loads((store.root / "commits" / f"{receipt.commit_sha256}.json").read_text())
    commit["case_heads"] = {}
    commit["written_cases"] = []
    _replace_head_commit(store, commit)
    with pytest.raises(FinalizationRejected, match="proof-to-case transition differs"):
        store.verify_history()

    for name, field, value, message in (
        ("case-key", "reconciliation_key", "txn:" + "0" * 64, "case head key differs"),
        ("case-proof", "proof_id", "prf:" + "0" * 64, "case does not bind current proof"),
    ):
        store = _store(tmp_path, name)
        receipt = _finalize_transaction(store, batch=_transaction_batch(candidate))
        case = store.read_case_revision(receipt.cases[0].object_sha256)
        case[field] = value
        if field == "reconciliation_key":
            identity = {
                "grain": case["grain"],
                "reconciliation_key": case["reconciliation_key"],
                "initial_exception_proof_id": case["initial_exception_proof_id"],
            }
            case["case_id"] = case_id(identity)
        case["case_revision_sha256"] = canonical_sha256(case, {"case_revision_sha256"})
        case_digest = _persist_object(store, case)
        commit = json.loads((store.root / "commits" / f"{receipt.commit_sha256}.json").read_text())
        key = receipt.proofs[0].reconciliation_key
        commit["case_heads"][key] = case_digest
        commit["written_cases"] = [case_digest]
        _replace_head_commit(store, commit)
        with pytest.raises(FinalizationRejected, match=message):
            store.verify_history()


def test_p2s6_initial_and_successor_case_chains_are_verified(tmp_path: Path) -> None:
    candidate = _transaction_candidate(
        status="EXCEPTION", reasons=("PROCESSOR_LEDGER_MISMATCH",), ledger=99
    )
    store = _store(tmp_path, "initial-case")
    receipt = _finalize_transaction(store, batch=_transaction_batch(candidate))
    case = store.read_case_revision(receipt.cases[0].object_sha256)
    case["revision"] = 2
    case["prior_case_revision_id"] = "0" * 64
    case["case_revision_sha256"] = canonical_sha256(case, {"case_revision_sha256"})
    case_digest = _persist_object(store, case)
    commit = json.loads((store.root / "commits" / f"{receipt.commit_sha256}.json").read_text())
    key = receipt.proofs[0].reconciliation_key
    commit["case_heads"][key] = case_digest
    commit["written_cases"] = [case_digest]
    _replace_head_commit(store, commit)
    with pytest.raises(FinalizationRejected, match="initial case revision differs"):
        store.verify_history()

    store = _store(tmp_path, "successor-case")
    first = _finalize_transaction(store, batch=_transaction_batch(candidate))
    second = _finalize_transaction(
        store,
        attempt="attempt-stage6-002",
        expected=first.commit_sha256,
        batch=_transaction_batch(candidate, run_id="run-stage6-002", manifest="c" * 64),
    )
    case = store.read_case_revision(second.cases[0].object_sha256)
    case["prior_case_revision_id"] = "0" * 64
    case["case_revision_sha256"] = canonical_sha256(case, {"case_revision_sha256"})
    case_digest = _persist_object(store, case)
    commit = json.loads((store.root / "commits" / f"{second.commit_sha256}.json").read_text())
    commit["case_heads"][key] = case_digest
    commit["written_cases"] = [case_digest]
    _replace_head_commit(store, commit)
    with pytest.raises(FinalizationRejected, match="case predecessor chain differs"):
        store.verify_history()


def test_p2s6_empty_history_and_outcome_guards(tmp_path: Path) -> None:
    store = _store(tmp_path)
    assert store.verify_history() is None
    _finalize_transaction(store)
    outcome = store.root / "attempts/attempt-stage6-001/outcome.json"
    value = json.loads(outcome.read_text())
    value.pop("proofs")
    outcome.write_bytes(canonical_json_bytes(value))
    with pytest.raises(FinalizationRejected, match="outcome shape differs"):
        _finalize_transaction(store)

    store = _store(tmp_path, "outcome-mismatch")
    _finalize_transaction(store)
    outcome = store.root / "attempts/attempt-stage6-001/outcome.json"
    value = json.loads(outcome.read_text())
    value["proofs"][0]["revision"] = 2
    outcome.write_bytes(canonical_json_bytes(value))
    with pytest.raises(FinalizationRejected, match="does not match authoritative commit"):
        _finalize_transaction(store)

    store = _store(tmp_path, "outcome-inventory")
    _finalize_transaction(store)
    outcome = store.root / "attempts/attempt-stage6-001/outcome.json"
    value = json.loads(outcome.read_text())
    value["proofs"] = {}
    outcome.write_bytes(canonical_json_bytes(value))
    with pytest.raises(FinalizationRejected, match="outcome shape differs"):
        _finalize_transaction(store)

    store = _store(tmp_path, "outcome-row")
    _finalize_transaction(store)
    outcome = store.root / "attempts/attempt-stage6-001/outcome.json"
    value = json.loads(outcome.read_text())
    value["proofs"][0]["extra"] = True
    outcome.write_bytes(canonical_json_bytes(value))
    with pytest.raises(FinalizationRejected, match="outcome shape differs"):
        _finalize_transaction(store)


def test_p2s6_outcome_must_belong_to_request_and_authoritative_history(tmp_path: Path) -> None:
    store = _store(tmp_path)
    first = _finalize_transaction(store)
    second = _finalize_transaction(
        store,
        attempt="attempt-stage6-002",
        expected=first.commit_sha256,
        batch=_transaction_batch(
            _transaction_candidate(payment_id="payment-2"),
            run_id="run-stage6-002",
            manifest="c" * 64,
        ),
    )
    first_outcome = store.root / "attempts/attempt-stage6-001/outcome.json"
    second_outcome = store.root / "attempts/attempt-stage6-002/outcome.json"
    first_outcome.write_bytes(second_outcome.read_bytes())
    with pytest.raises(FinalizationRejected, match="outcome request differs"):
        _finalize_transaction(store)

    value = json.loads(second_outcome.read_text())
    orphan_commit = json.loads(
        (store.root / "commits" / f"{second.commit_sha256}.json").read_text()
    )
    orphan_commit["attempt_id"] = "attempt-stage6-003"
    request = json.loads((store.root / "attempts/attempt-stage6-002/request.json").read_text())
    request["attempt_id"] = "attempt-stage6-003"
    request_raw = canonical_json_bytes(request)
    request_digest = sha256(request_raw).hexdigest()
    orphan_commit["request_sha256"] = request_digest
    value["attempt_id"] = "attempt-stage6-003"
    value["request_sha256"] = request_digest
    (store.root / "attempts/attempt-stage6-003").mkdir()
    (store.root / "attempts/attempt-stage6-003/request.json").write_bytes(request_raw)
    orphan_digest = _replace_head_commit(store, orphan_commit)
    value["commit_sha256"] = orphan_digest
    orphan_outcome = store.root / "attempts/attempt-stage6-003/outcome.json"
    orphan_outcome.write_bytes(canonical_json_bytes(value))
    (store.root / "control/HEAD").write_text(first.commit_sha256 + "\n")
    with pytest.raises(FinalizationRejected, match="not in authoritative history"):
        store._read_outcome(orphan_outcome)


@pytest.mark.parametrize(
    ("fault", "exit_code"),
    [("after_attempt", 71), ("after_objects", 72), ("after_commit", 73), ("after_head", 74)],
)
def test_p2s6_fault_branches_have_in_process_coverage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
    exit_code: int,
) -> None:
    class InjectedExit(Exception):
        pass

    def exit_with(code: int) -> None:
        raise InjectedExit(code)

    monkeypatch.setattr(os, "_exit", exit_with)
    with pytest.raises(InjectedExit, match=str(exit_code)):
        _finalize_transaction(_store(tmp_path), fault=fault)


def test_p2s6_cycle_guards_fail_closed_under_fault_injected_commit_reader(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path)
    digest = "0" * 64
    commit = {
        "schema_version": "1.0",
        "attempt_id": "attempt-stage6-001",
        "request_sha256": "1" * 64,
        "parent_sha256": digest,
        "proof_heads": {},
        "case_heads": {},
        "updated_keys": [],
        "written_proofs": [],
        "written_cases": [],
    }
    (store.root / "control/HEAD").write_text(digest + "\n")
    monkeypatch.setattr(store, "_read_commit", lambda _: commit)
    with pytest.raises(FinalizationRejected, match="commit cycle"):
        store.verify_history()
    with pytest.raises(FinalizationRejected, match="commit cycle"):
        store._find_attempt(digest, "absent-stage6-001", "2" * 64)


def test_p2s6_persisted_record_and_state_payloads_fail_closed(tmp_path: Path) -> None:
    transaction_batch, settlement_batch = _real_batches()
    store = _store(tmp_path)
    transaction_payload = finalization_module._batch_payload(transaction_batch)
    settlement_payload = finalization_module._batch_payload(settlement_batch)
    transaction_record = transaction_payload["state"]["records"][0]
    settlement_record = settlement_payload["state"]["records"][0]

    malformed = deepcopy(transaction_record)
    malformed["source_identity"] = "not-an-array"
    with pytest.raises(FinalizationRejected, match="state differs"):
        store._record_from_payload(malformed)
    malformed = deepcopy(transaction_record)
    malformed["value"] = []
    with pytest.raises(FinalizationRejected, match="state differs"):
        store._record_from_payload(malformed)
    malformed = deepcopy(transaction_record)
    malformed["source_identity"][-1] = "wrong-source"
    with pytest.raises(FinalizationRejected, match="source identity differs"):
        store._record_from_payload(malformed)
    malformed = deepcopy(transaction_record)
    malformed["business_sha256"] = "0" * 64
    with pytest.raises(FinalizationRejected, match="business digest differs"):
        store._record_from_payload(malformed)
    malformed = deepcopy(transaction_record)
    malformed.pop("family")
    with pytest.raises(FinalizationRejected, match="state differs"):
        store._record_from_payload(malformed)
    malformed = deepcopy(transaction_record)
    malformed["extra"] = True
    with pytest.raises(FinalizationRejected, match="state shape differs"):
        store._record_from_payload(malformed)

    missing_state = deepcopy(transaction_payload)
    missing_state.pop("state")
    with pytest.raises(FinalizationRejected, match="state is unavailable"):
        store._state_from_payload(missing_state, False)
    bad_inventory = deepcopy(transaction_payload)
    bad_inventory["state"]["records"] = {}
    with pytest.raises(FinalizationRejected, match="record inventory differs"):
        store._state_from_payload(bad_inventory, False)
    contaminated_settlement = deepcopy(settlement_payload)
    contaminated_settlement["state"]["records"] = [transaction_record]
    with pytest.raises(FinalizationRejected, match="settlement state contains another grain"):
        store._state_from_payload(contaminated_settlement, True)
    contaminated_transaction = deepcopy(transaction_payload)
    contaminated_transaction["state"]["records"] = [settlement_record]
    with pytest.raises(FinalizationRejected, match="transaction state contains another grain"):
        store._state_from_payload(contaminated_transaction, False)
    for duplicate_value in ({}, [1], [[1]]):
        malformed_duplicates = deepcopy(settlement_payload)
        malformed_duplicates["state"]["duplicate_bank_identities"] = duplicate_value
        with pytest.raises(FinalizationRejected, match="duplicate-bank state differs"):
            store._state_from_payload(malformed_duplicates, True)
    extra_transaction_state = deepcopy(transaction_payload)
    extra_transaction_state["state"]["extra"] = True
    with pytest.raises(FinalizationRejected, match="transaction state shape differs"):
        store._state_from_payload(extra_transaction_state, False)
    wrong_digest = deepcopy(transaction_payload)
    wrong_digest["state_sha256"] = "0" * 64
    with pytest.raises(FinalizationRejected, match="state digest differs"):
        store._state_from_payload(wrong_digest, False)


def test_p2s6_state_recovery_metadata_and_source_conflicts_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path)
    assert store.load_states() == (AdmissionState(), TransactionState(), SettlementState())
    request = {
        "transaction_batch": {
            "run_id": "run-0001",
            "policy_version": "v1",
            "policy_sha256": "a" * 64,
            "manifest_sha256": "b" * 64,
        },
        "settlement_batch": None,
    }
    commit = {
        "attempt_id": "attempt-stage6-001",
        "request_sha256": "c" * 64,
        "parent_sha256": None,
    }
    monkeypatch.setattr(store, "read_head", lambda: "d" * 64)
    monkeypatch.setattr(store, "_read_commit", lambda _: commit)
    monkeypatch.setattr(store, "_read_canonical", lambda *args: request)
    monkeypatch.setattr(store, "_state_from_payload", lambda *args: TransactionState())
    admission, transaction_state, settlement_state = store.load_states()
    assert admission.policy_versions == (("v1", "a" * 64),)
    assert transaction_state == TransactionState()
    assert settlement_state == SettlementState()

    bad_metadata = deepcopy(request)
    bad_metadata["transaction_batch"]["policy_version"] = 1
    monkeypatch.setattr(store, "_read_canonical", lambda *args: bad_metadata)
    with pytest.raises(FinalizationRejected, match="metadata differs"):
        store.load_states()

    conflicting_request = deepcopy(request)
    conflicting_request["settlement_batch"] = {
        **request["transaction_batch"],
        "policy_sha256": "e" * 64,
    }
    monkeypatch.setattr(store, "_read_canonical", lambda *args: conflicting_request)
    with pytest.raises(FinalizationRejected, match="admission history conflicts"):
        store.load_states()

    transaction_batch, _ = _real_batches()
    transaction_record = transaction_batch.state.records[0]
    conflicting_record = replace(transaction_record, business_sha256="f" * 64)
    monkeypatch.setattr(store, "_read_canonical", lambda *args: request)
    monkeypatch.setattr(
        store,
        "_state_from_payload",
        lambda _payload, settlement: (
            SettlementState((conflicting_record,), ())
            if settlement
            else TransactionState((transaction_record,))
        ),
    )
    request["settlement_batch"] = deepcopy(request["transaction_batch"])
    with pytest.raises(FinalizationRejected, match="source state conflicts"):
        store.load_states()


def test_p2s6_request_state_guards_preserve_prior_admission_and_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    transaction_batch, settlement_batch = _real_batches()
    store = _store(tmp_path)
    store.finalize(
        attempt_id="attempt-stage6-001",
        expected_head=None,
        created_at="2026-09-04T01:00:00Z",
        transaction_batch=transaction_batch,
        settlement_batch=settlement_batch,
    )
    request = finalization_module._request_payload(
        attempt_id="attempt-stage6-002",
        expected_head=store.read_head(),
        created_at="2026-09-04T01:05:00Z",
        transaction_batch=transaction_batch,
        settlement_batch=settlement_batch,
    )
    malformed = deepcopy(request)
    malformed["transaction_batch"]["policy_version"] = 1
    with pytest.raises(AdmissionRejected, match="metadata differs"):
        store._validate_request_state(malformed)
    wrong_policy = deepcopy(request)
    wrong_policy["transaction_batch"]["policy_sha256"] = "0" * 64
    with pytest.raises(AdmissionRejected, match="policy version reused"):
        store._validate_request_state(wrong_policy)
    wrong_run = deepcopy(request)
    wrong_run["transaction_batch"]["manifest_sha256"] = "0" * 64
    with pytest.raises(AdmissionRejected, match="run identity reused"):
        store._validate_request_state(wrong_run)
    removed = deepcopy(request)
    removed["transaction_batch"]["state"] = {"records": []}
    removed["transaction_batch"]["state_sha256"] = TransactionState().semantic_digest()
    with pytest.raises(AdmissionRejected, match="history removed"):
        store._validate_request_state(removed)

    admission, prior_transactions, prior_settlements = store.load_states()
    source = prior_transactions.records[0]
    injected_admission = replace(
        admission,
        source_records=(
            *admission.source_records,
            SourceStateEntry(source.source_identity, "0" * 64),
        ),
    )
    monkeypatch.setattr(
        store,
        "load_states",
        lambda: (injected_admission, TransactionState(), prior_settlements),
    )
    with pytest.raises(AdmissionRejected, match="source identity reused"):
        store._validate_request_state(request)


def test_p2s6_request_identity_binding_and_recovery_api(tmp_path: Path) -> None:
    transaction_batch, settlement_batch = _real_batches()
    store = _store(tmp_path)
    assert (
        store.recover_attempt(
            attempt_id="attempt-stage6-001",
            expected_head=None,
            created_at="2026-09-04T01:00:00Z",
            run_id=transaction_batch.run_id,
            policy_version=transaction_batch.policy_version,
            policy_sha256=transaction_batch.policy_sha256,
            manifest_sha256=transaction_batch.manifest_sha256,
        )
        is None
    )
    receipt = store.finalize(
        attempt_id="attempt-stage6-001",
        expected_head=None,
        created_at="2026-09-04T01:00:00Z",
        transaction_batch=transaction_batch,
        settlement_batch=settlement_batch,
    )
    parameters = {
        "attempt_id": "attempt-stage6-001",
        "expected_head": None,
        "created_at": "2026-09-04T01:00:00Z",
        "run_id": transaction_batch.run_id,
        "policy_version": transaction_batch.policy_version,
        "policy_sha256": transaction_batch.policy_sha256,
        "manifest_sha256": transaction_batch.manifest_sha256,
    }
    assert store.recover_attempt(**parameters) == receipt
    outcome = store.root / "attempts/attempt-stage6-001/outcome.json"
    outcome.unlink()
    assert store.recover_attempt(**parameters) == receipt
    assert outcome.exists()
    for key, value in (
        ("expected_head", "0" * 64),
        ("created_at", "2026-09-04T01:00:01Z"),
        ("policy_sha256", "0" * 64),
    ):
        changed = dict(parameters)
        changed[key] = value
        with pytest.raises(FinalizationRejected, match="different inputs"):
            store.recover_attempt(**changed)
    for changed in (
        {**parameters, "attempt_id": "bad"},
        {**parameters, "expected_head": "bad"},
    ):
        with pytest.raises(AdmissionRejected):
            store.recover_attempt(**changed)

    request_path = store.root / "attempts/attempt-stage6-001/request.json"
    request = json.loads(request_path.read_text())
    request["attempt_id"] = "attempt-stage6-999"
    request_raw = canonical_json_bytes(request)
    request_path.write_bytes(request_raw)
    commit = json.loads((store.root / "commits" / f"{receipt.commit_sha256}.json").read_text())
    commit["request_sha256"] = sha256(request_raw).hexdigest()
    _replace_head_commit(store, commit)
    with pytest.raises(FinalizationRejected, match="request identity differs"):
        store.read_head()


def test_p2s6_recovery_api_orphan_and_storage_failure_are_non_authoritative(
    tmp_path: Path,
) -> None:
    transaction_batch, settlement_batch = _real_batches()
    store = _store(tmp_path)
    request = finalization_module._request_payload(
        attempt_id="attempt-stage6-001",
        expected_head=None,
        created_at="2026-09-04T01:00:00Z",
        transaction_batch=transaction_batch,
        settlement_batch=settlement_batch,
    )
    attempt = store.root / "attempts/attempt-stage6-001"
    attempt.mkdir()
    (attempt / "request.json").write_bytes(canonical_json_bytes(request))
    parameters = {
        "attempt_id": "attempt-stage6-001",
        "expected_head": None,
        "created_at": "2026-09-04T01:00:00Z",
        "run_id": transaction_batch.run_id,
        "policy_version": transaction_batch.policy_version,
        "policy_sha256": transaction_batch.policy_sha256,
        "manifest_sha256": transaction_batch.manifest_sha256,
    }
    assert store.recover_attempt(**parameters) is None
    lock_path = store.root / "locks/finalization.lock"
    lock_path.unlink()
    lock_path.mkdir()
    with pytest.raises(FinalizationRejected, match="storage operation failed") as captured:
        store.recover_attempt(**parameters)
    assert captured.value.authoritative_proof is False


def test_p2s6_authoritative_request_envelope_guards(tmp_path: Path) -> None:
    store = _store(tmp_path)
    base = finalization_module._request_payload(
        attempt_id="attempt-read-001",
        expected_head=None,
        created_at="2026-09-04T01:00:00Z",
        transaction_batch=_transaction_batch(),
        settlement_batch=_settlement_batch(),
    )

    def rejected(value: dict[str, Any], message: str) -> None:
        raw = canonical_json_bytes(value)
        attempt = store.root / "attempts/attempt-read-001"
        attempt.mkdir(exist_ok=True)
        (attempt / "request.json").write_bytes(raw)
        with pytest.raises(FinalizationRejected, match=message):
            store._read_request("attempt-read-001", sha256(raw).hexdigest())

    changed = deepcopy(base)
    changed["extra"] = True
    rejected(changed, "request shape differs")
    changed = deepcopy(base)
    changed["expected_head"] = "bad"
    rejected(changed, "expected head differs")
    changed = deepcopy(base)
    changed["created_at"] = 1
    rejected(changed, "timestamp differs")
    changed = deepcopy(base)
    changed["transaction_batch"] = []
    rejected(changed, "request batch differs")
    changed = deepcopy(base)
    changed["transaction_batch"]["extra"] = True
    rejected(changed, "batch shape differs")
    for field, value in (("run_id", 1), ("semantic_sha256", "bad")):
        changed = deepcopy(base)
        changed["transaction_batch"][field] = value
        rejected(changed, "request metadata differs")
    candidate_mutations = (
        {},
        [1],
        [{**base["transaction_batch"]["candidates"][0], "reconciliation_key": 1}],
        [{**base["transaction_batch"]["candidates"][0], "authoritative_proof": True}],
    )
    for candidates in candidate_mutations:
        changed = deepcopy(base)
        changed["transaction_batch"]["candidates"] = candidates
        rejected(changed, "candidate inventory differs")
    for field, value in (
        ("bank_allocations", {}),
        ("batch_status", 1),
        ("batch_reason_codes", {}),
    ):
        changed = deepcopy(base)
        changed["settlement_batch"][field] = value
        rejected(changed, "settlement evidence differs")
    changed = deepcopy(base)
    changed["settlement_batch"]["run_id"] = "run-other"
    rejected(changed, "request batch set differs")
    changed = deepcopy(base)
    changed["transaction_batch"]["candidates"] = []
    changed["settlement_batch"] = None
    rejected(changed, "request batch set differs")


def test_p2s6_persisted_proof_and_case_identities_are_rederived(tmp_path: Path) -> None:
    store = _store(tmp_path)
    receipt = _finalize_transaction(
        store,
        batch=_transaction_batch(
            _transaction_candidate(
                status="EXCEPTION", reasons=("PROCESSOR_LEDGER_MISMATCH",), ledger=90
            )
        ),
    )
    for reference, reader, field, message in (
        (
            receipt.proofs[0],
            store.read_proof,
            "proof_id",
            "reconciliation_proof identity differs",
        ),
        (
            receipt.cases[0],
            store.read_case_revision,
            "case_id",
            "case_revision identity differs",
        ),
    ):
        original = json.loads(
            (store.root / "objects" / f"{reference.object_sha256}.json").read_text()
        )
        original[field] = str(original[field])[:-1] + (
            "0" if not str(original[field]).endswith("0") else "1"
        )
        digest_field = "proof_sha256" if field == "proof_id" else "case_revision_sha256"
        original[digest_field] = canonical_sha256(original, {digest_field})
        raw = canonical_json_bytes(original)
        digest = sha256(raw).hexdigest()
        (store.root / "objects" / f"{digest}.json").write_bytes(raw)
        with pytest.raises(FinalizationRejected, match=message):
            reader(digest)


def test_p2s6_commit_is_exactly_bound_to_request_parent_candidates_and_proof(
    tmp_path: Path,
) -> None:
    def mutate_request_and_commit(
        name: str,
        request_change: Any,
        commit_change: Any,
        message: str,
    ) -> None:
        store = _store(tmp_path, name)
        receipt = _finalize_transaction(store)
        request_path = store.root / "attempts/attempt-stage6-001/request.json"
        request = json.loads(request_path.read_text())
        commit = json.loads((store.root / "commits" / f"{receipt.commit_sha256}.json").read_text())
        request_change(request)
        request_raw = canonical_json_bytes(request)
        request_path.write_bytes(request_raw)
        commit["request_sha256"] = sha256(request_raw).hexdigest()
        commit_change(commit, request, receipt)
        _replace_head_commit(store, commit)
        with pytest.raises(FinalizationRejected, match=message):
            store.verify_history()

    mutate_request_and_commit(
        "parent-binding",
        lambda request: request.__setitem__("expected_head", "0" * 64),
        lambda *_: None,
        "expected head differs from commit parent",
    )
    mutate_request_and_commit(
        "duplicate-request",
        lambda request: request["transaction_batch"]["candidates"].append(
            deepcopy(request["transaction_batch"]["candidates"][0])
        ),
        lambda *_: None,
        "duplicate candidate",
    )

    def mislabel_request(request: dict[str, Any]) -> None:
        request["transaction_batch"]["candidates"][0]["reconciliation_key"] = "txn:" + "0" * 64

    def mislabel_commit(
        commit: dict[str, Any], _request: dict[str, Any], receipt: FinalizationReceipt
    ) -> None:
        actual = receipt.proofs[0].reconciliation_key
        false = "txn:" + "0" * 64
        commit["proof_heads"] = {false: commit["proof_heads"].pop(actual)}
        commit["updated_keys"] = [false]

    mutate_request_and_commit(
        "proof-key-binding",
        mislabel_request,
        mislabel_commit,
        "proof head key differs",
    )

    def change_candidate(request: dict[str, Any]) -> None:
        request["transaction_batch"]["candidates"][0]["totals"]["processor_minor"] = 101

    mutate_request_and_commit(
        "proof-request-binding",
        change_candidate,
        lambda *_: None,
        "proof differs from authoritative request",
    )


def test_p2s6_case_change_requires_proof_revision_and_exact_request(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path, "case-without-proof")
    first = _finalize_transaction(
        store,
        batch=_transaction_batch(
            _transaction_candidate(
                status="EXCEPTION", reasons=("PROCESSOR_LEDGER_MISMATCH",), ledger=90
            ),
            _transaction_candidate(payment_id="payment-2"),
        ),
    )
    second = _finalize_transaction(
        store,
        attempt="attempt-stage6-002",
        expected=first.commit_sha256,
        batch=_transaction_batch(
            _transaction_candidate(payment_id="payment-2"),
            run_id="run-stage6-002",
            manifest="c" * 64,
        ),
    )
    case_reference = first.cases[0]
    case = store.read_case_revision(case_reference.object_sha256)
    case["revision"] = 2
    case["prior_case_revision_id"] = case["case_revision_sha256"]
    case["occurred_at"] = "2026-09-04T01:05:00Z"
    case["case_revision_sha256"] = canonical_sha256(case, {"case_revision_sha256"})
    case_digest = _persist_object(store, case)
    commit = json.loads((store.root / "commits" / f"{second.commit_sha256}.json").read_text())
    commit["case_heads"][case_reference.reconciliation_key] = case_digest
    commit["written_cases"] = [case_digest]
    _replace_head_commit(store, commit)
    with pytest.raises(FinalizationRejected, match="case changes without a proof revision"):
        store.verify_history()

    store = _store(tmp_path, "case-request-binding")
    receipt = _finalize_transaction(
        store,
        batch=_transaction_batch(
            _transaction_candidate(
                status="EXCEPTION", reasons=("PROCESSOR_LEDGER_MISMATCH",), ledger=90
            )
        ),
    )
    reference = receipt.cases[0]
    case = store.read_case_revision(reference.object_sha256)
    case["reason_codes"] = ["MISSING_LEDGER_MOVEMENT"]
    case["case_revision_sha256"] = canonical_sha256(case, {"case_revision_sha256"})
    case_digest = _persist_object(store, case)
    commit = json.loads((store.root / "commits" / f"{receipt.commit_sha256}.json").read_text())
    commit["case_heads"][reference.reconciliation_key] = case_digest
    commit["written_cases"] = [case_digest]
    _replace_head_commit(store, commit)
    with pytest.raises(FinalizationRejected, match="case differs from authoritative request"):
        store.verify_history()


def _write_cli_bundle(root: Path, run_id: str) -> tuple[Path, Path, Path]:
    from test_part2_stage3_admission import build_bundle

    policy_bytes, manifest_bytes, supplied, manifest = build_bundle(run_id=run_id)
    policy_path = root / f"{run_id}-policy.json"
    manifest_path = root / f"{run_id}-manifest.json"
    input_root = root / f"{run_id}-objects"
    input_root.mkdir()
    policy_path.write_bytes(policy_bytes)
    manifest_path.write_bytes(manifest_bytes)
    for descriptor in manifest["objects"]:
        relative = descriptor["relative_path"]
        (input_root / relative).write_bytes(supplied[f"local:{relative}"])
    return policy_path, manifest_path, input_root


def _cli_command(
    root: Path,
    store: Path,
    *,
    run_id: str = "run-0001",
    attempt: str = "attempt-stage6-001",
    expected: str = "NONE",
) -> list[str]:
    policy, manifest, inputs = _write_cli_bundle(root, run_id)
    return [
        sys.executable,
        "-m",
        "ledgerguard_part2_stage6",
        "--repository",
        str(ROOT),
        "--policy",
        str(policy),
        "--manifest",
        str(manifest),
        "--input-root",
        str(inputs),
        "--store",
        str(store),
        "--attempt-id",
        attempt,
        "--expected-head",
        expected,
        "--created-at",
        "2026-09-04T01:00:00Z",
    ]


def test_p2s6_cli_finalizes_retries_and_appends_late_run(tmp_path: Path) -> None:
    environment = dict(os.environ, PYTHONPATH=str(ROOT / "src"))
    store = tmp_path / "store"
    command = _cli_command(tmp_path, store)
    first = subprocess.run(
        command, cwd=ROOT, env=environment, text=True, capture_output=True, check=True
    )
    first_value = json.loads(first.stdout)
    assert first_value["outcome"] == "AUTHORITATIVE_PROOFS_FINALIZED"
    assert first_value["authoritative_proof"] is True
    assert first_value["proof_count"] == 2
    retry = subprocess.run(
        command, cwd=ROOT, env=environment, text=True, capture_output=True, check=True
    )
    assert json.loads(retry.stdout) == first_value

    second_command = _cli_command(
        tmp_path,
        store,
        run_id="run-0002",
        attempt="attempt-stage6-002",
        expected=first_value["commit_sha256"],
    )
    second = subprocess.run(
        second_command, cwd=ROOT, env=environment, text=True, capture_output=True, check=True
    )
    second_value = json.loads(second.stdout)
    assert second_value["commit_sha256"] != first_value["commit_sha256"]
    assert {row["revision"] for row in second_value["proofs"]} == {2}
    assert FinalizationStore(ROOT, store).verify_history() is not None


def test_p2s6_cli_owns_admission_execution_and_store_failures(tmp_path: Path) -> None:
    environment = dict(os.environ, PYTHONPATH=str(ROOT / "src"))
    store = tmp_path / "store"
    command = _cli_command(tmp_path, store)
    first = subprocess.run(
        command, cwd=ROOT, env=environment, text=True, capture_output=True, check=True
    )
    stale = _cli_command(
        tmp_path,
        store,
        run_id="run-0002",
        attempt="attempt-stage6-002",
        expected="NONE",
    )
    rejected = subprocess.run(
        stale, cwd=ROOT, env=environment, text=True, capture_output=True, check=False
    )
    assert rejected.returncode == 3
    assert json.loads(rejected.stdout)["reason_code"] == "EXECUTION_FAILURE"
    assert FinalizationStore(ROOT, store).read_head() == json.loads(first.stdout)["commit_sha256"]

    bad_manifest = _cli_command(
        tmp_path,
        tmp_path / "bad-manifest-store",
        run_id="run-0003",
        attempt="attempt-stage6-003",
    )
    manifest_index = bad_manifest.index("--manifest") + 1
    Path(bad_manifest[manifest_index]).write_bytes(b"[]")
    admission = subprocess.run(
        bad_manifest, cwd=ROOT, env=environment, text=True, capture_output=True, check=False
    )
    assert admission.returncode == 2
    assert json.loads(admission.stdout)["reason_code"] == "SCHEMA_VIOLATION"

    missing = _cli_command(
        tmp_path,
        tmp_path / "missing-input-store",
        run_id="run-0004",
        attempt="attempt-stage6-004",
    )
    policy_index = missing.index("--policy") + 1
    missing[policy_index] = str(tmp_path / "absent.json")
    unavailable = subprocess.run(
        missing, cwd=ROOT, env=environment, text=True, capture_output=True, check=False
    )
    assert unavailable.returncode == 2
    assert json.loads(unavailable.stdout)["reason_code"] == "SOURCE_IDENTITY_MISMATCH"

    parent_file = tmp_path / "not-a-directory"
    parent_file.write_text("occupied")
    store_failure = _cli_command(
        tmp_path,
        parent_file / "store",
        run_id="run-0005",
        attempt="attempt-stage6-005",
    )
    failed = subprocess.run(
        store_failure, cwd=ROOT, env=environment, text=True, capture_output=True, check=False
    )
    assert failed.returncode == 3
    assert json.loads(failed.stdout)["detail"] == "local finalization store unavailable"
