"""Side-effect-free expected-result calculations for both reconciliation grains."""

from __future__ import annotations

import unicodedata
from collections.abc import Mapping, Sequence
from typing import Any

MIN_I64 = -(2**63)
MAX_I64 = 2**63 - 1
SUPPORTED_CURRENCIES = {"INR", "JPY", "USD"}
EVENT_SIGNS = {"CAPTURE": 1, "REFUND": -1, "CHARGEBACK": -1, "REVERSAL": -1}
TRANSACTION_LEDGER_SIGNS = {"DEBIT": 1, "CREDIT": -1}
SETTLEMENT_LEDGER_SIGNS = {"DEBIT": -1, "CREDIT": 1}
BANK_SIGNS = {"CREDIT": 1, "DEBIT": -1}
FINANCIAL_REASON_ORDER = (
    "INVALID_ACCOUNT_ROLE",
    "UNRESOLVED_REFERENCE",
    "OVER_APPLIED_REFERENCE",
    "MISSING_LEDGER_MOVEMENT",
    "MISSING_PROCESSOR_ACTIVITY",
    "MISSING_BANK_SETTLEMENT",
    "UNALLOCATED_BANK_MOVEMENT",
    "INVALID_BANK_ACCOUNT",
    "DUPLICATE_BANK_MOVEMENT",
    "SETTLEMENT_FORMULA_MISMATCH",
    "PROCESSOR_LEDGER_MISMATCH",
    "PROCESSOR_BANK_MISMATCH",
    "LEDGER_BANK_MISMATCH",
)


class OracleError(ValueError):
    """Base error for an invalid oracle request."""


class AdmissionRejected(OracleError):
    """An input cannot produce an authoritative reconciliation proof."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.detail = detail


def checked_i64(value: object) -> int:
    """Admit only a real signed 64-bit integer; bool is not money."""

    if isinstance(value, bool) or not isinstance(value, int):
        raise AdmissionRejected("SCHEMA_VIOLATION", "signed integer required")
    if value < MIN_I64 or value > MAX_I64:
        raise AdmissionRejected("SCHEMA_VIOLATION", "signed 64-bit overflow")
    return value


def checked_nonnegative(value: object, reason: str = "SCHEMA_VIOLATION") -> int:
    result = checked_i64(value)
    if result < 0:
        raise AdmissionRejected(reason, "non-negative integer required")
    return result


def checked_add(left: object, right: object) -> int:
    return checked_i64(checked_i64(left) + checked_i64(right))


def checked_subtract(left: object, right: object) -> int:
    return checked_i64(checked_i64(left) - checked_i64(right))


def checked_abs(value: object) -> int:
    result = checked_i64(value)
    if result == MIN_I64:
        raise AdmissionRejected("SCHEMA_VIOLATION", "absolute-value overflow")
    return abs(result)


def _signed(value: object, sign: int) -> int:
    return checked_i64(checked_i64(value) * sign)


def _required_text(source: Mapping[str, Any], field: str) -> str:
    value = source.get(field)
    if not isinstance(value, str) or not value:
        raise AdmissionRejected("SCHEMA_VIOLATION", f"{field} is required")
    return value


def _reason_list(reasons: set[str]) -> list[str]:
    unknown = reasons.difference(FINANCIAL_REASON_ORDER)
    if unknown:
        raise OracleError(f"unknown financial reasons: {sorted(unknown)}")
    return [reason for reason in FINANCIAL_REASON_ORDER if reason in reasons]


def _status(difference: int, tolerance: int, reasons: set[str]) -> tuple[str, list[str]]:
    tolerance = checked_nonnegative(tolerance, "POLICY_MISMATCH")
    if reasons:
        return "EXCEPTION", _reason_list(reasons)
    if difference == 0:
        return "MATCHED", []
    if difference <= tolerance:
        return "WITHIN_TOLERANCE", ["TOLERATED_DIFFERENCE"]
    raise OracleError("a difference above tolerance requires mismatch reasons")


def _rejection(error: AdmissionRejected) -> dict[str, Any]:
    return {
        "outcome": "ADMISSION_REJECTED",
        "authoritative_proof": False,
        "reason_codes": [error.reason],
    }


def _transaction(source: Mapping[str, Any]) -> dict[str, Any]:
    event_type = _required_text(source, "event_type")
    if event_type not in EVENT_SIGNS:
        raise AdmissionRejected("SCHEMA_VIOLATION", "unsupported event type")
    processor_currency = _required_text(source, "processor_currency")
    ledger_currency = _required_text(source, "ledger_currency")
    if (
        processor_currency not in SUPPORTED_CURRENCIES
        or ledger_currency not in SUPPORTED_CURRENCIES
    ):
        raise AdmissionRejected("SCHEMA_VIOLATION", "unsupported currency")
    if processor_currency != ledger_currency:
        raise AdmissionRejected("CURRENCY_DOMAIN_VIOLATION", "transaction currencies differ")
    ledger_side = _required_text(source, "ledger_side")
    if ledger_side not in TRANSACTION_LEDGER_SIGNS:
        raise AdmissionRejected("SCHEMA_VIOLATION", "unsupported ledger side")

    processor = _signed(source.get("processor_amount_minor"), EVENT_SIGNS[event_type])
    ledger = _signed(source.get("ledger_amount_minor"), TRANSACTION_LEDGER_SIGNS[ledger_side])
    delta = checked_subtract(processor, ledger)
    difference = checked_abs(delta)
    processor_count = checked_nonnegative(source.get("processor_record_count"))
    ledger_count = checked_nonnegative(source.get("ledger_journal_count"))
    tolerance = checked_nonnegative(source.get("tolerance_minor"), "POLICY_MISMATCH")
    reasons: set[str] = set()
    if processor_count == 0:
        reasons.add("MISSING_PROCESSOR_ACTIVITY")
    if ledger_count == 0:
        reasons.add("MISSING_LEDGER_MOVEMENT")
    if source.get("account_role_valid") is not True:
        reasons.add("INVALID_ACCOUNT_ROLE")
    has_reference = source.get("has_reference")
    if event_type == "CAPTURE" and has_reference is True:
        reasons.add("UNRESOLVED_REFERENCE")
    if event_type != "CAPTURE":
        if (
            source.get("reference_resolved") is not True
            or source.get("reference_targets_negative") is True
        ):
            reasons.add("UNRESOLVED_REFERENCE")
        if source.get("over_applied_reference") is True:
            reasons.add("OVER_APPLIED_REFERENCE")
    if not reasons and difference > tolerance:
        reasons.add("PROCESSOR_LEDGER_MISMATCH")
    status, reason_codes = _status(difference, tolerance, reasons)
    return {
        "processor_minor": processor,
        "ledger_minor": ledger,
        "processor_ledger_delta_minor": delta,
        "difference_minor": difference,
        "status": status,
        "reason_codes": reason_codes,
    }


def evaluate_transaction(source: Mapping[str, Any]) -> dict[str, Any]:
    """Calculate the transaction-grain expected result or admission rejection."""

    try:
        return _transaction(source)
    except AdmissionRejected as error:
        return _rejection(error)


def evaluate_capture_capacity(
    captured_minor: object, negative_applied_minor: object
) -> dict[str, Any]:
    """Evaluate exact-capture cumulative negative capacity."""

    captured = checked_nonnegative(captured_minor)
    applied = checked_nonnegative(negative_applied_minor)
    remaining = checked_subtract(captured, applied)
    reasons = ["OVER_APPLIED_REFERENCE"] if remaining < 0 else []
    return {
        "remaining_capacity_minor": remaining,
        "status": "EXCEPTION" if reasons else "VALID",
        "reason_codes": reasons,
    }


def expected_failure_outcome(owner: str, reason: str) -> dict[str, Any]:
    """Model failure ownership without performing finalization."""

    if owner == "ADMISSION":
        return {
            "outcome": "RUN_REJECTED_NO_PROOF",
            "authoritative_proof": False,
            "reason_codes": [reason],
        }
    if owner == "EXECUTION":
        return {
            "outcome": "NO_AUTHORITATIVE_PARTIAL_PROOF",
            "authoritative_proof": False,
            "reason_codes": [reason],
        }
    if owner == "FINANCIAL":
        return {
            "outcome": "EXCEPTION_PROOF_EXPECTED",
            "authoritative_proof": True,
            "reason_codes": [reason],
        }
    raise OracleError(f"unknown failure owner: {owner}")


def next_revision(previous_revision: object, previous_digest: str) -> dict[str, Any]:
    """Calculate an append-only successor expectation without storing it."""

    revision = checked_add(checked_nonnegative(previous_revision), 1)
    if len(previous_digest) != 64 or any(
        character not in "0123456789abcdef" for character in previous_digest
    ):
        raise OracleError("previous digest must be lowercase SHA-256")
    return {"revision": revision, "prior_revision_sha256": previous_digest}


def _normalized_reference(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AdmissionRejected("SCHEMA_VIOLATION", "settlement reference required")
    return unicodedata.normalize("NFC", value.strip())


def _settlement(source: Mapping[str, Any]) -> dict[str, Any]:
    processor_count = checked_nonnegative(source.get("processor_settlement_count"))
    ledger_count = checked_nonnegative(source.get("ledger_journal_count"))
    tolerance = checked_nonnegative(source.get("tolerance_minor"), "POLICY_MISMATCH")
    net = checked_i64(source.get("gross_minor"))
    for field in ("fee_minor", "refund_minor", "chargeback_minor", "reserve_minor"):
        net = checked_subtract(net, source.get(field))

    ledger = 0
    ledger_side = source.get("ledger_side")
    if ledger_count:
        if not isinstance(ledger_side, str) or ledger_side not in SETTLEMENT_LEDGER_SIGNS:
            raise AdmissionRejected("SCHEMA_VIOLATION", "unsupported settlement ledger side")
        ledger = _signed(source.get("ledger_amount_minor"), SETTLEMENT_LEDGER_SIGNS[ledger_side])

    target = _normalized_reference(source.get("settlement_reference"))
    candidate_references = source.get("candidate_settlement_references", [target])
    if not isinstance(candidate_references, Sequence) or isinstance(candidate_references, str):
        raise AdmissionRejected("SCHEMA_VIOLATION", "candidate references must be a sequence")
    normalized_candidates = [_normalized_reference(value) for value in candidate_references]
    if normalized_candidates.count(target) != 1:
        raise AdmissionRejected("AMBIGUOUS_BANK_ALLOCATION", "reference is not unique")

    permitted_source = source.get("permitted_bank_account_ids")
    if not isinstance(permitted_source, Sequence) or isinstance(permitted_source, str):
        raise AdmissionRejected("POLICY_MISMATCH", "permitted accounts are required")
    permitted = {str(value) for value in permitted_source}
    entries = source.get("bank_entries")
    if not isinstance(entries, Sequence) or isinstance(entries, (str, bytes)):
        raise AdmissionRejected("SCHEMA_VIOLATION", "bank entries must be a sequence")

    allocated: list[Mapping[str, Any]] = []
    unallocated_count = 0
    seen: set[tuple[str, str]] = set()
    reasons: set[str] = set()
    sortable: list[Mapping[str, Any]] = []
    for item in entries:
        if not isinstance(item, Mapping):
            raise AdmissionRejected("SCHEMA_VIOLATION", "bank entry must be an object")
        sortable.append(item)
    for entry in sorted(
        sortable,
        key=lambda item: (str(item.get("bank_account_id")), str(item.get("bank_record_id"))),
    ):
        identity = (
            _required_text(entry, "bank_account_id"),
            _required_text(entry, "bank_record_id"),
        )
        if identity in seen:
            reasons.add("DUPLICATE_BANK_MOVEMENT")
            continue
        seen.add(identity)
        if _normalized_reference(entry.get("settlement_reference")) != target:
            unallocated_count += 1
            reasons.add("UNALLOCATED_BANK_MOVEMENT")
            continue
        allocated.append(entry)
        if identity[0] not in permitted:
            reasons.add("INVALID_BANK_ACCOUNT")

    bank = 0
    for entry in allocated:
        direction = _required_text(entry, "direction")
        if direction not in BANK_SIGNS:
            raise AdmissionRejected("SCHEMA_VIOLATION", "unsupported bank direction")
        bank = checked_add(bank, _signed(entry.get("amount_minor"), BANK_SIGNS[direction]))
    if processor_count == 0:
        reasons.add("MISSING_PROCESSOR_ACTIVITY")
    if ledger_count == 0 and net != 0:
        reasons.add("MISSING_LEDGER_MOVEMENT")
    if not allocated and net != 0:
        reasons.add("MISSING_BANK_SETTLEMENT")
    if checked_i64(source.get("reported_net_minor")) != net:
        reasons.add("SETTLEMENT_FORMULA_MISMATCH")

    processor_ledger = checked_subtract(net, ledger)
    processor_bank = checked_subtract(net, bank)
    ledger_bank = checked_subtract(ledger, bank)
    difference = max(
        checked_abs(processor_ledger), checked_abs(processor_bank), checked_abs(ledger_bank)
    )
    if not reasons and difference > tolerance:
        if processor_ledger:
            reasons.add("PROCESSOR_LEDGER_MISMATCH")
        if processor_bank:
            reasons.add("PROCESSOR_BANK_MISMATCH")
        if ledger_bank:
            reasons.add("LEDGER_BANK_MISMATCH")
    status, reason_codes = _status(difference, tolerance, reasons)
    return {
        "processor_net_minor": net,
        "ledger_clearing_minor": ledger,
        "bank_minor": bank,
        "processor_ledger_delta_minor": processor_ledger,
        "processor_bank_delta_minor": processor_bank,
        "ledger_bank_delta_minor": ledger_bank,
        "difference_minor": difference,
        "allocated_bank_count": len(allocated),
        "unallocated_bank_count": unallocated_count,
        "status": status,
        "reason_codes": reason_codes,
    }


def evaluate_settlement(source: Mapping[str, Any]) -> dict[str, Any]:
    """Calculate the settlement-grain expected result or admission rejection."""

    try:
        return _settlement(source)
    except AdmissionRejected as error:
        return _rejection(error)


def validate_journal(journal: Mapping[str, Any]) -> dict[str, Any]:
    """Validate financial journal semantics independent of JSON Schema shape checks."""

    _required_text(journal, "processor")
    _required_text(journal, "entry_type")
    postings = journal.get("postings")
    if (
        not isinstance(postings, Sequence)
        or isinstance(postings, (str, bytes))
        or len(postings) < 2
    ):
        raise AdmissionRejected("UNBALANCED_JOURNAL", "at least two postings required")
    line_ids: set[str] = set()
    currencies = {_required_text(journal, "currency")}
    debits = 0
    credits = 0
    clearing_count = 0
    for item in postings:
        if not isinstance(item, Mapping):
            raise AdmissionRejected("UNBALANCED_JOURNAL", "posting must be an object")
        line_id = _required_text(item, "line_id")
        if line_id in line_ids:
            raise AdmissionRejected("UNBALANCED_JOURNAL", "duplicate line identifier")
        line_ids.add(line_id)
        amount = checked_i64(item.get("amount_minor"))
        if amount <= 0:
            raise AdmissionRejected("UNBALANCED_JOURNAL", "posting amount must be positive")
        side = _required_text(item, "side")
        if side == "DEBIT":
            debits = checked_add(debits, amount)
        elif side == "CREDIT":
            credits = checked_add(credits, amount)
        else:
            raise AdmissionRejected("UNBALANCED_JOURNAL", "posting side is invalid")
        if item.get("account_role") == "PROCESSOR_CLEARING":
            clearing_count += 1
        if "currency" in item:
            currencies.add(_required_text(item, "currency"))
    if debits != credits or debits <= 0 or len(currencies) != 1:
        raise AdmissionRejected("UNBALANCED_JOURNAL", "journal totals or currency differ")
    transaction_key_present = "payment_id" in journal
    settlement_key_present = "settlement_id" in journal and "settlement_cycle" in journal
    if transaction_key_present == settlement_key_present:
        raise AdmissionRejected("UNBALANCED_JOURNAL", "exactly one business key is required")
    return {
        "admitted": True,
        "balanced_total_minor": debits,
        "posting_count": len(postings),
        "account_role_valid": clearing_count == 1,
        "financial_reason_codes": [] if clearing_count == 1 else ["INVALID_ACCOUNT_ROLE"],
    }
