import pytest

from ledgerguard import ExternalRecord, Journal, Posting, ReconciliationEngine
from ledgerguard.engine import ContractViolation, IdentityConflict, InjectedFailure


def test_three_way_reconciliation_and_case_recovery() -> None:
    engine = ReconciliationEngine()
    capture = ExternalRecord("p1", "pay", "processor", "capture", 100, "INR", 1)
    engine.ingest_external([capture])
    engine.ingest_journals(
        [Journal("j1", "pay", "capture", "INR", 1, (Posting("a", 100), Posting("b", 0, 100)))]
    )
    assert engine.reconcile("pay", currency="INR").status == "EXCEPTION"
    engine.ingest_external([ExternalRecord("b1", "pay", "bank", "settlement", 100, "INR", 2)])
    assert engine.reconcile("pay", currency="INR").status == "MATCHED"
    assert engine.case_history["pay"][0].startswith("NEW->EXCEPTION")
    assert engine.case_history["pay"][1].startswith("EXCEPTION->MATCHED")


def test_idempotency_conflict_and_atomicity() -> None:
    engine = ReconciliationEngine()
    record = ExternalRecord("p1", "pay", "processor", "capture", 100, "INR", 1)
    assert engine.ingest_external([record]) == "applied"
    assert engine.ingest_external([record]) == "replayed"
    with pytest.raises(IdentityConflict):
        engine.ingest_external([ExternalRecord("p1", "pay", "processor", "capture", 101, "INR", 1)])
    with pytest.raises(InjectedFailure):
        engine.ingest_external(
            [ExternalRecord("p2", "pay2", "processor", "capture", 50, "INR", 2)],
            fail_before_commit=True,
        )
    assert "p2" not in engine.records


def test_unbalanced_and_invalid_tolerance_are_blocked() -> None:
    engine = ReconciliationEngine()
    with pytest.raises(ContractViolation):
        engine.ingest_journals(
            [Journal("j1", "pay", "capture", "INR", 1, (Posting("cash", debit_cents=100),))]
        )
    with pytest.raises(ContractViolation):
        engine.reconcile("pay", currency="INR", tolerance_cents=-1)


def test_reversal_requires_original() -> None:
    engine = ReconciliationEngine()
    with pytest.raises(ContractViolation):
        engine.ingest_external(
            [ExternalRecord("r1", "pay", "processor", "reversal", 100, "INR", 2, "missing")]
        )

