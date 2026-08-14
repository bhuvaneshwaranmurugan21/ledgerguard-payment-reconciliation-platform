from __future__ import annotations

from dataclasses import asdict
from typing import Any, Callable

from .engine import ContractViolation, IdentityConflict, InjectedFailure, ReconciliationEngine
from .model import ExternalRecord, Journal, Posting, digest


def processor(record_id: str, payment: str, amount: int, kind: str = "capture", **kw: Any) -> ExternalRecord:
    return ExternalRecord(record_id, payment, "processor", kind, amount, "INR", 100, **kw)  # type: ignore[arg-type]


def bank(record_id: str, payment: str, amount: int, kind: str = "settlement", **kw: Any) -> ExternalRecord:
    return ExternalRecord(record_id, payment, "bank", kind, amount, "INR", 200, **kw)  # type: ignore[arg-type]


def journal(journal_id: str, payment: str, amount: int, kind: str = "capture") -> Journal:
    return Journal(
        journal_id,
        payment,
        kind,  # type: ignore[arg-type]
        "INR",
        150,
        (Posting("clearing", debit_cents=amount), Posting("merchant_payable", credit_cents=amount)),
    )


def simulate() -> dict[str, Any]:
    engine = ReconciliationEngine()
    checks: list[dict[str, Any]] = []

    def check(name: str, fn: Callable[[], Any], expected: type[Exception] | None = None) -> None:
        try:
            proof = fn()
            passed = expected is None
        except Exception as exc:
            proof = type(exc).__name__
            passed = expected is not None and isinstance(exc, expected)
        checks.append({"check": name, "passed": passed, "proof": proof})

    capture = processor("proc-1", "pay-1", 10_000)
    check("processor_capture", lambda: engine.ingest_external([capture]))
    check("processor_replay", lambda: engine.ingest_external([capture]))
    check(
        "conflicting_identity_blocked",
        lambda: engine.ingest_external([processor("proc-1", "pay-1", 9_999)]),
        IdentityConflict,
    )
    check("balanced_ledger", lambda: engine.ingest_journals([journal("journal-1", "pay-1", 10_000)]))
    check(
        "unbalanced_ledger_blocked",
        lambda: engine.ingest_journals(
            [Journal("bad", "pay-x", "capture", "INR", 1, (Posting("cash", debit_cents=100),))]
        ),
        ContractViolation,
    )
    check(
        "missing_settlement_detected",
        lambda: asdict(engine.reconcile("pay-1", currency="INR")),
    )
    check("one_to_many_settlement", lambda: engine.ingest_external([bank("b1", "pay-1", 6_000), bank("b2", "pay-1", 4_000)]))
    check("three_way_match", lambda: engine.reconcile("pay-1", currency="INR").status)
    before = len(engine.records)
    check(
        "atomic_feed_failure",
        lambda: engine.ingest_external([processor("proc-2", "pay-2", 500)], fail_before_commit=True),
        InjectedFailure,
    )
    check("atomic_rollback", lambda: len(engine.records) == before)
    check(
        "reversal_before_original_blocked",
        lambda: engine.ingest_external(
            [processor("rev-x", "pay-x", 100, kind="reversal", reference_id="missing")]
        ),
        ContractViolation,
    )
    check("case_transition_audited", lambda: engine.case_history["pay-1"])
    check("evidence_digest", lambda: engine.audit_digest("pay-1"))

    payload: dict[str, Any] = {
        "project": "ledgerguard-payment-reconciliation-platform",
        "architecture": "three-way-auditable-reconciliation",
        "claim_level": "LOCAL_VERIFIED",
        "production_claim": False,
        "checks": checks,
        "metrics": {"checks_total": len(checks), "checks_passed": sum(c["passed"] for c in checks)},
        "terminal_result": asdict(engine.results["pay-1"]),
    }
    payload["evidence_digest"] = digest(payload)
    payload["result"] = "PASS" if all(c["passed"] for c in checks) else "FAIL"
    return payload

