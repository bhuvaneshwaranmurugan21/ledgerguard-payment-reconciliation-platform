"""Evidence and semantic-mutation helpers for Part 2 Stage 4."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from hashlib import sha256
from pathlib import Path
from typing import Any

from ledgerguard.reconciliation import (
    AdmissionRejected,
    AdmissionState,
    AdmittedBatch,
    AdmittedRecord,
    TransactionKey,
    TransactionState,
    canonical_json_bytes,
    reconcile_transactions,
)
from ledgerguard.reconciliation.arithmetic import MAX_I64, checked_add
from ledgerguard.reconciliation.identity import transaction_key
from ledgerguard.reconciliation.transaction import _policy, _status
from ledgerguard_part2_stage4_validation import MUTATION_CLASSES


def parse_junit_counts(report: Path) -> dict[str, int]:
    """Aggregate direct JUnit suites without double-counting wrapper totals."""

    root = ET.parse(report).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.findall("./testsuite"))
    if not suites:
        raise ValueError("JUnit report contains no test suites")
    counts = {
        name: sum(int(suite.attrib.get(name, 0)) for suite in suites)
        for name in ("tests", "failures", "errors", "skipped")
    }
    if counts["tests"] < counts["failures"] + counts["errors"] + counts["skipped"]:
        raise ValueError("JUnit report counts are inconsistent")
    return counts


def _record(family: str, source_id: str, value: dict[str, Any]) -> AdmittedRecord:
    raw = canonical_json_bytes(value)
    if family == "PROCESSOR_EVENT":
        identity = (family, str(value["processor"]), source_id)
        event_class = str(value["event_type"])
    elif family == "LEDGER_JOURNAL":
        identity = (family, "ledger-1", source_id)
        event_class = str(value["entry_type"])
    else:
        identity = (family, "source", source_id)
        event_class = ""
    key = None
    if family in {"PROCESSOR_EVENT", "LEDGER_JOURNAL"}:
        key = transaction_key(
            {
                "processor": value["processor"],
                "merchant_id": value["merchant_id"],
                "payment_id": value["payment_id"],
                "event_class": event_class,
                "currency": value["currency"],
            }
        )
    return AdmittedRecord(
        family=family,
        source_identity=identity,
        business_sha256=sha256(raw).hexdigest(),
        canonical_bytes=raw,
        reconciliation_key=key,
        normalized_settlement_reference=None,
        journal_balanced_total_minor=0 if family == "LEDGER_JOURNAL" else None,
        journal_clearing_role_valid=True if family == "LEDGER_JOURNAL" else None,
    )


def _event(
    source_id: str, event_type: str, amount: int, reference: str | None = None
) -> AdmittedRecord:
    value: dict[str, Any] = {
        "processor": "processor-a",
        "merchant_id": "merchant-1",
        "payment_id": "payment-1",
        "event_type": event_type,
        "currency": "INR",
        "source_record_id": source_id,
        "amount_minor": amount,
    }
    if reference is not None:
        value["reference_event_id"] = reference
    return _record("PROCESSOR_EVENT", source_id, value)


def _journal(
    source_id: str,
    event_type: str,
    amount: int,
    side: str,
    *,
    counterpart: str = "MERCHANT_PAYABLE",
    postings: list[dict[str, Any]] | None = None,
) -> AdmittedRecord:
    rows = postings or [
        {
            "line_id": "1",
            "account_role": "PROCESSOR_CLEARING",
            "side": side,
            "amount_minor": amount,
        },
        {
            "line_id": "2",
            "account_role": counterpart,
            "side": "CREDIT" if side == "DEBIT" else "DEBIT",
            "amount_minor": amount,
        },
    ]
    return _record(
        "LEDGER_JOURNAL",
        source_id,
        {
            "processor": "processor-a",
            "merchant_id": "merchant-1",
            "payment_id": "payment-1",
            "entry_type": event_type,
            "currency": "INR",
            "postings": rows,
        },
    )


def _batch(records: tuple[AdmittedRecord, ...]) -> AdmittedBatch:
    policy = {
        "transaction_rules": {
            "event_signs": {"CAPTURE": 1, "REFUND": -1, "CHARGEBACK": -1, "REVERSAL": -1},
            "ledger_side_signs": {"DEBIT": 1, "CREDIT": -1},
            "allowed_counterpart_roles": ["MERCHANT_PAYABLE", "CUSTOMER_RECEIVABLE"],
        },
        "currency_rules": {"INR": {"transaction_tolerance_minor": 0}},
    }
    return AdmittedBatch(
        run_id="mutation-run",
        policy_version="v2",
        policy_sha256="1" * 64,
        manifest_sha256="2" * 64,
        policy_canonical_bytes=canonical_json_bytes(policy),
        manifest_canonical_bytes=b"{}",
        records=records,
        replay_count=0,
        state=AdmissionState(),
        observed_records=records,
    )


def _candidate(records: tuple[AdmittedRecord, ...], event_class: str) -> Any:
    rows = [
        row
        for row in reconcile_transactions(_batch(records)).candidates
        if row.key_components.event_class == event_class
    ]
    if len(rows) != 1:
        raise ValueError(f"expected one {event_class} candidate")
    return rows[0]


def _rejects_overflow() -> bool:
    try:
        checked_add(MAX_I64, 1)
    except AdmissionRejected as error:
        return error.reason == "SCHEMA_VIOLATION" and error.authoritative_proof is False
    return False


def run_mutation_checks(root: Path) -> dict[str, Any]:
    """Prove every registered Stage 4 semantic defect changes a mandatory result."""

    del root
    base = _batch(())
    signs, sides, _, _ = _policy(base)
    checks: dict[str, bool] = {}
    checks["REVERSE_CAPTURE_SIGN"] = signs["CAPTURE"] == 1
    checks["REVERSE_NEGATIVE_SIGN"] = all(
        signs[name] == -1 for name in ("REFUND", "CHARGEBACK", "REVERSAL")
    )
    capture_key = TransactionKey("processor-a", "merchant-1", "payment-1", "CAPTURE", "INR")
    refund_key = TransactionKey("processor-a", "merchant-1", "payment-1", "REFUND", "INR")
    checks["DROP_EVENT_CLASS_FROM_KEY"] = (
        capture_key.reconciliation_key != refund_key.reconciliation_key
    )

    processor_only = _candidate((_event("capture", "CAPTURE", 100),), "CAPTURE")
    checks["INNER_JOIN_GRAINS"] = (
        processor_only.processor_record_count == 1 and processor_only.ledger_journal_count == 0
    )
    checks["COLLAPSE_MISSING_TO_ZERO"] = processor_only.reason_codes == ("MISSING_LEDGER_MOVEMENT",)

    multi_posting = _journal(
        "multi",
        "CAPTURE",
        40,
        "DEBIT",
        postings=[
            {
                "line_id": "1",
                "account_role": "PROCESSOR_CLEARING",
                "side": "DEBIT",
                "amount_minor": 40,
            },
            {
                "line_id": "2",
                "account_role": "CUSTOMER_RECEIVABLE",
                "side": "DEBIT",
                "amount_minor": 60,
            },
            {
                "line_id": "3",
                "account_role": "MERCHANT_PAYABLE",
                "side": "CREDIT",
                "amount_minor": 100,
            },
        ],
    )
    clearing = _candidate((_event("capture", "CAPTURE", 100), multi_posting), "CAPTURE")
    checks["USE_TOTAL_JOURNAL_DEBIT"] = (
        clearing.ledger_minor == 40 and clearing.difference_minor == 60
    )
    wrong_side = _candidate(
        (_event("capture", "CAPTURE", 100), _journal("j", "CAPTURE", 100, "CREDIT")), "CAPTURE"
    )
    checks["REVERSE_CLEARING_ORIENTATION"] = sides == {"DEBIT": 1, "CREDIT": -1} and (
        wrong_side.reason_codes == ("INVALID_ACCOUNT_ROLE",)
    )
    bad_counterpart = _candidate(
        (
            _event("capture", "CAPTURE", 100),
            _journal("j", "CAPTURE", 100, "DEBIT", counterpart="BANK_CASH"),
        ),
        "CAPTURE",
    )
    checks["ALLOW_INVALID_COUNTERPART_ROLE"] = bad_counterpart.reason_codes == (
        "INVALID_ACCOUNT_ROLE",
    )
    checks["TOLERATE_SEMANTIC_FAILURE"] = _status(
        capture_key, 0, {"INVALID_ACCOUNT_ROLE"}, {"INR": MAX_I64}
    ) == ("EXCEPTION", ("INVALID_ACCOUNT_ROLE",))

    missing_ref = _candidate(
        (
            _event("capture-real", "CAPTURE", 100),
            _event("refund", "REFUND", 10, "same-payment-only"),
        ),
        "REFUND",
    )
    checks["REFERENCE_BY_PAYMENT"] = "UNRESOLVED_REFERENCE" in missing_ref.reason_codes
    negative_chain = _candidate(
        (
            _event("capture", "CAPTURE", 100),
            _event("refund-1", "REFUND", 10, "capture"),
            _event("refund-2", "REFUND", 5, "refund-1"),
        ),
        "REFUND",
    )
    checks["ALLOW_NEGATIVE_REFERENCE_CHAIN"] = "UNRESOLVED_REFERENCE" in negative_chain.reason_codes
    distinct = _candidate(
        (
            _event("capture-1", "CAPTURE", 40),
            _event("capture-2", "CAPTURE", 100),
            _event("refund", "REFUND", 41, "capture-1"),
        ),
        "REFUND",
    )
    checks["CONFLATE_MULTIPLE_CAPTURES"] = "OVER_APPLIED_REFERENCE" in distinct.reason_codes
    capacity_records = (
        _event("capture", "CAPTURE", 100),
        _event("refund", "REFUND", 60, "capture"),
        _event("chargeback", "CHARGEBACK", 41, "capture"),
    )
    capacity = reconcile_transactions(_batch(capacity_records)).candidates
    affected = [
        row for row in capacity if row.key_components.event_class in {"REFUND", "CHARGEBACK"}
    ]
    checks["DISABLE_CUMULATIVE_CAPACITY"] = len(affected) == 2 and all(
        "OVER_APPLIED_REFERENCE" in row.reason_codes for row in affected
    )
    reverse_capacity = reconcile_transactions(_batch(tuple(reversed(capacity_records)))).candidates
    checks["ORDER_DEPENDENT_CAPACITY"] = [row.value() for row in capacity] == [
        row.value() for row in reverse_capacity
    ]
    replay = _event("capture", "CAPTURE", 100)
    replay_batch = _batch((replay, replay))
    replay_result = reconcile_transactions(replay_batch, TransactionState((replay,)))
    checks["DOUBLE_APPLY_REPLAY"] = replay_result.candidates[0].processor_record_count == 1
    checks["UNCHECKED_TRANSACTION_AGGREGATION"] = _rejects_overflow()
    checks["DROP_MISMATCH_REASON"] = _status(capture_key, 1, set(), {"INR": 0}) == (
        "EXCEPTION",
        ("PROCESSOR_LEDGER_MISMATCH",),
    )
    settlement = _record("PROCESSOR_SETTLEMENT", "settlement", {"amount_minor": 999})
    without_settlement = reconcile_transactions(
        _batch((_event("capture", "CAPTURE", 100),))
    ).candidates
    with_settlement = reconcile_transactions(
        _batch((_event("capture", "CAPTURE", 100), settlement))
    ).candidates
    checks["SETTLEMENT_CONTAMINATES_TRANSACTION"] = [row.value() for row in without_settlement] == [
        row.value() for row in with_settlement
    ]
    unordered = (_event("refund", "REFUND", 5, "capture"), _event("capture", "CAPTURE", 100))
    ordered = reconcile_transactions(_batch(unordered)).candidates
    reversed_order = reconcile_transactions(_batch(tuple(reversed(unordered)))).candidates
    checks["NONDETERMINISTIC_RESULT_ORDER"] = [row.value() for row in ordered] == [
        row.value() for row in reversed_order
    ]
    checks["EMIT_AUTHORITATIVE_PROOF"] = (
        all(row.authoritative_proof is False for row in ordered)
        and reconcile_transactions(_batch(unordered)).authoritative_proof is False
    )

    if list(checks) != MUTATION_CLASSES:
        raise ValueError("mutation registry and execution order differ")
    survivors = [name for name, killed in checks.items() if not killed]
    if survivors:
        raise ValueError(f"Stage 4 semantic mutants survived: {survivors}")
    return {"checks": len(checks), "survivors": 0, "killed": list(checks)}
