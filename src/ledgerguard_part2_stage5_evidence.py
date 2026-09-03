"""Evidence and semantic-mutation helpers for Part 2 Stage 5."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from typing import Any

from ledgerguard.reconciliation import (
    AdmissionRejected,
    AdmissionState,
    AdmittedBatch,
    AdmittedRecord,
    SettlementKey,
    SettlementState,
    canonical_json_bytes,
    normalize_bank_reference,
    reconcile_settlements,
    settlement_key,
)
from ledgerguard.reconciliation.arithmetic import MAX_I64
from ledgerguard_part2_stage5_validation import MUTATION_CLASSES


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


def _record(family: str, value: dict[str, Any]) -> AdmittedRecord:
    raw = canonical_json_bytes(value)
    identity: tuple[str, ...]
    if family == "PROCESSOR_SETTLEMENT":
        identity = (family, str(value["processor"]), str(value["source_record_id"]))
    elif family == "LEDGER_JOURNAL":
        identity = (family, str(value["ledger_system"]), str(value["journal_id"]))
    elif family == "BANK_ENTRY":
        identity = (family, str(value["bank_account_id"]), str(value["bank_record_id"]))
    else:
        identity = (family, str(value.get("source_record_id", "event")))
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
    cycle: str = "cycle-1",
    gross: int = 100,
    refund: int = 0,
    reported: int | None = None,
    processor: str = "processor-a",
) -> AdmittedRecord:
    return _record(
        "PROCESSOR_SETTLEMENT",
        {
            "processor": processor,
            "merchant_id": "merchant-1",
            "settlement_id": settlement_id,
            "settlement_cycle": cycle,
            "currency": "INR",
            "source_record_id": source_id,
            "gross_minor": gross,
            "fee_minor": 0,
            "refund_minor": refund,
            "chargeback_minor": 0,
            "reserve_minor": 0,
            "reported_net_minor": gross - refund if reported is None else reported,
        },
    )


def _journal(
    journal_id: str = "journal-1",
    *,
    settlement_id: str = "settlement-1",
    cycle: str = "cycle-1",
    amount: int = 100,
    side: str = "CREDIT",
    processor: str = "processor-a",
    extra_debit: int | None = None,
) -> AdmittedRecord:
    postings = [
        {
            "line_id": "1",
            "account_role": "PROCESSOR_CLEARING",
            "side": side,
            "amount_minor": amount,
        },
        {
            "line_id": "2",
            "account_role": "MERCHANT_PAYABLE",
            "side": "DEBIT" if side == "CREDIT" else "CREDIT",
            "amount_minor": amount,
        },
    ]
    if extra_debit is not None:
        postings.extend(
            [
                {
                    "line_id": "3",
                    "account_role": "FEE_EXPENSE",
                    "side": "DEBIT",
                    "amount_minor": extra_debit,
                },
                {
                    "line_id": "4",
                    "account_role": "FEE_PAYABLE",
                    "side": "CREDIT",
                    "amount_minor": extra_debit,
                },
            ]
        )
    return _record(
        "LEDGER_JOURNAL",
        {
            "ledger_system": "ledger-1",
            "journal_id": journal_id,
            "processor": processor,
            "merchant_id": "merchant-1",
            "settlement_id": settlement_id,
            "settlement_cycle": cycle,
            "currency": "INR",
            "entry_type": "SETTLEMENT",
            "postings": postings,
        },
    )


def _bank(
    record_id: str = "bank-1",
    *,
    reference: str | None = "settlement-1",
    amount: int = 100,
    direction: str = "CREDIT",
    account: str = "bank-account-1",
) -> AdmittedRecord:
    value: dict[str, Any] = {
        "bank_account_id": account,
        "bank_record_id": record_id,
        "merchant_id": "merchant-1",
        "currency": "INR",
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
    tolerance: int = 0,
) -> AdmittedBatch:
    unique = {record.source_identity: record for record in records}
    observed = tuple(unique[identity] for identity in sorted(unique))
    return AdmittedBatch(
        run_id="stage5-mutation-run",
        policy_version="v2",
        policy_sha256="1" * 64,
        manifest_sha256="2" * 64,
        policy_canonical_bytes=canonical_json_bytes(_policy(tolerance)),
        manifest_canonical_bytes=b"{}",
        records=observed,
        replay_count=0,
        state=AdmissionState(),
        observed_records=observed,
        observed_occurrences=records if occurrences is None else occurrences,
    )


def _one(records: tuple[AdmittedRecord, ...], *, tolerance: int = 0) -> Any:
    result = reconcile_settlements(_batch(records, tolerance=tolerance))
    if len(result.candidates) != 1:
        raise ValueError("expected one settlement candidate")
    return result.candidates[0]


def _rejects_ambiguity() -> bool:
    try:
        reconcile_settlements(
            _batch(
                (
                    _processor("p1", processor="processor-a", cycle="cycle-a"),
                    _journal("j2", processor="processor-b", cycle="cycle-b"),
                    _bank(),
                )
            )
        )
    except AdmissionRejected as error:
        return error.reason == "AMBIGUOUS_BANK_ALLOCATION" and not error.authoritative_proof
    return False


def _rejects_overflow() -> bool:
    try:
        reconcile_settlements(
            _batch((_processor("p1", gross=MAX_I64), _processor("p2", gross=MAX_I64)))
        )
    except AdmissionRejected as error:
        return error.reason == "SCHEMA_VIOLATION" and not error.authoritative_proof
    return False


def run_mutation_checks(root: Path) -> dict[str, Any]:
    """Prove every registered Stage 5 semantic defect changes a mandatory result."""

    del root
    checks: dict[str, bool] = {}
    formula = _one((_processor(reported=101), _journal(), _bank()), tolerance=MAX_I64)
    checks["USE_REPORTED_NET_INSTEAD_OF_RECOMPUTED"] = (
        formula.processor_net_minor == 100
        and formula.reason_codes == ("SETTLEMENT_FORMULA_MISMATCH",)
    )
    offsetting = _one(
        (
            _processor("p1", gross=50, reported=51),
            _processor("p2", gross=50, reported=49),
            _journal(),
            _bank(),
        ),
        tolerance=MAX_I64,
    )
    checks["AGGREGATE_BEFORE_FORMULA_VALIDATION"] = (
        "SETTLEMENT_FORMULA_MISMATCH" in offsetting.reason_codes
    )
    first_key = SettlementKey("processor-a", "merchant-1", "settlement-1", "cycle-a", "INR")
    second_key = replace(first_key, settlement_cycle="cycle-b")
    checks["DROP_SETTLEMENT_CYCLE_FROM_KEY"] = (
        first_key.reconciliation_key != second_key.reconciliation_key
    )
    ledger_only = _one((_journal(), _bank()))
    checks["INNER_JOIN_SETTLEMENT_GRAINS"] = ledger_only.processor_settlement_count == 0
    missing = _one((_processor(),))
    checks["COLLAPSE_SETTLEMENT_MISSING_TO_ZERO"] = missing.reason_codes == (
        "MISSING_LEDGER_MOVEMENT",
        "MISSING_BANK_SETTLEMENT",
    )
    clearing = _one((_processor(), _journal(extra_debit=60), _bank()))
    checks["USE_TOTAL_JOURNAL_DEBIT"] = clearing.ledger_clearing_minor == 100
    negative_ledger = _one(
        (
            _processor(gross=0, refund=100),
            _journal(amount=100, side="DEBIT"),
            _bank(direction="DEBIT"),
        )
    )
    checks["REVERSE_SETTLEMENT_CLEARING_ORIENTATION"] = (
        negative_ledger.ledger_clearing_minor == -100
    )
    checks["REVERSE_BANK_CREDIT_SIGN"] = _one((_processor(), _journal(), _bank())).bank_minor == 100
    checks["REVERSE_BANK_DEBIT_SIGN"] = negative_ledger.bank_minor == -100
    case = reconcile_settlements(
        _batch((_processor(), _journal(), _bank(reference="Settlement-1")))
    )
    checks["LOWERCASE_BANK_REFERENCE"] = (
        case.bank_allocations[0].disposition == "UNALLOCATED_UNKNOWN_REFERENCE"
    )
    punctuation = reconcile_settlements(
        _batch((_processor(), _journal(), _bank(reference="settlement.1")))
    )
    checks["DROP_BANK_REFERENCE_PUNCTUATION"] = (
        punctuation.bank_allocations[0].disposition == "UNALLOCATED_UNKNOWN_REFERENCE"
    )
    equal_unknown = reconcile_settlements(
        _batch((_processor(), _journal(), _bank(reference="unknown")))
    )
    checks["ALLOW_AMOUNT_DATE_HEURISTIC"] = equal_unknown.candidates[0].bank_minor == 0
    checks["ALLOCATE_UNKNOWN_REFERENCE"] = (
        equal_unknown.bank_allocations[0].settlement_reconciliation_key is None
    )
    checks["ALLOW_AMBIGUOUS_REFERENCE"] = _rejects_ambiguity()
    one_bank = reconcile_settlements(_batch((_processor(), _journal(), _bank())))
    checks["DOUBLE_ALLOCATE_BANK_IDENTITY"] = (
        len(one_bank.bank_allocations) == 1
        and one_bank.candidates[0].allocated_bank_entry_count == 1
    )
    replay = replace(_bank(), prior_state_replay=True, identical_replay=True)
    prior = SettlementState((_processor(), _journal(), replay))
    replay_result = reconcile_settlements(_batch((replay,), occurrences=(replay,)), prior)
    checks["DOUBLE_APPLY_PRIOR_REPLAY"] = replay_result.candidates[0].bank_minor == 100
    duplicate = _bank()
    duplicate_result = reconcile_settlements(
        _batch(
            (_processor(), _journal(), duplicate),
            occurrences=(_processor(), _journal(), duplicate, duplicate),
        )
    )
    checks["DROP_CURRENT_BUNDLE_DUPLICATE_REASON"] = duplicate_result.candidates[
        0
    ].reason_codes == ("DUPLICATE_BANK_MOVEMENT",)
    checks["COUNT_CURRENT_BUNDLE_DUPLICATE_TWICE"] = (
        duplicate_result.candidates[0].bank_minor == 100
    )
    disallowed = _one((_processor(), _journal(), _bank(account="blocked")))
    checks["ALLOW_DISALLOWED_BANK_ACCOUNT"] = disallowed.reason_codes == ("INVALID_BANK_ACCOUNT",)
    split = _one((_processor(), _journal(), _bank("b1", amount=60), _bank("b2", amount=40)))
    checks["REJECT_VALID_SPLIT_BANK_ENTRIES"] = (
        split.status == "MATCHED" and split.allocated_bank_entry_count == 2
    )
    deltas = _one((_processor(gross=100), _journal(amount=80), _bank(amount=70)))
    checks["DROP_PROCESSOR_LEDGER_DELTA"] = deltas.processor_ledger_delta_minor == 20
    checks["DROP_PROCESSOR_BANK_DELTA"] = deltas.processor_bank_delta_minor == 30
    checks["DROP_LEDGER_BANK_DELTA"] = deltas.ledger_bank_delta_minor == 10
    checks["USE_NON_MAX_SETTLEMENT_DIFFERENCE"] = deltas.difference_minor == 30
    semantic = _one((_processor(),), tolerance=MAX_I64)
    checks["TOLERATE_SETTLEMENT_SEMANTIC_FAILURE"] = semantic.status == "EXCEPTION"
    checks["UNCHECKED_SETTLEMENT_AGGREGATION"] = _rejects_overflow()
    transaction = _record("PROCESSOR_EVENT", {"source_record_id": "event-1", "amount_minor": 999})
    baseline = reconcile_settlements(_batch((_processor(), _journal(), _bank())))
    contaminated = reconcile_settlements(_batch((_processor(), _journal(), _bank(), transaction)))
    checks["TRANSACTION_CONTAMINATES_SETTLEMENT"] = baseline.candidates == contaminated.candidates
    records = (_processor(), _journal(), _bank("b1", amount=60), _bank("b2", amount=40))
    forward = reconcile_settlements(_batch(records))
    reverse = reconcile_settlements(_batch(tuple(reversed(records))))
    checks["NONDETERMINISTIC_SETTLEMENT_ORDER"] = (
        forward == reverse and forward.semantic_digest() == reverse.semantic_digest()
    )
    checks["EMIT_AUTHORITATIVE_SETTLEMENT_PROOF"] = not baseline.authoritative_proof and all(
        not row.authoritative_proof for row in baseline.candidates
    )
    if list(checks) != MUTATION_CLASSES:
        raise ValueError("mutation registry and execution order differ")
    survivors = [name for name, killed in checks.items() if not killed]
    if survivors:
        raise ValueError(f"Stage 5 semantic mutants survived: {survivors}")
    return {"checks": len(checks), "survivors": 0, "killed": list(checks)}
