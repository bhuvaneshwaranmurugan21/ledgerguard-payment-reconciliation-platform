"""Pure transaction-grain reconciliation over admitted source facts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
from typing import Any

from .admission import AdmittedBatch, AdmittedRecord
from .arithmetic import (
    checked_abs,
    checked_add,
    checked_i64,
    checked_multiply_sign,
    checked_subtract,
)
from .canonical import canonical_json_bytes, parse_strict_json
from .errors import AdmissionRejected
from .identity import transaction_key

FINANCIAL_REASONS = frozenset(
    {
        "INVALID_ACCOUNT_ROLE",
        "UNRESOLVED_REFERENCE",
        "OVER_APPLIED_REFERENCE",
        "MISSING_LEDGER_MOVEMENT",
        "MISSING_PROCESSOR_ACTIVITY",
        "PROCESSOR_LEDGER_MISMATCH",
    }
)
TRANSACTION_EVENTS = frozenset({"CAPTURE", "REFUND", "CHARGEBACK", "REVERSAL"})
REASON_ORDER = (
    "INVALID_ACCOUNT_ROLE",
    "UNRESOLVED_REFERENCE",
    "OVER_APPLIED_REFERENCE",
    "MISSING_LEDGER_MOVEMENT",
    "MISSING_PROCESSOR_ACTIVITY",
    "PROCESSOR_LEDGER_MISMATCH",
)


@dataclass(frozen=True, order=True)
class TransactionKey:
    processor: str
    merchant_id: str
    payment_id: str
    event_class: str
    currency: str

    def value(self) -> dict[str, str]:
        return {
            "processor": self.processor,
            "merchant_id": self.merchant_id,
            "payment_id": self.payment_id,
            "event_class": self.event_class,
            "currency": self.currency,
        }

    @property
    def reconciliation_key(self) -> str:
        return transaction_key(self.value())


@dataclass(frozen=True)
class TransactionState:
    records: tuple[AdmittedRecord, ...] = ()

    def semantic_digest(self) -> str:
        payload = [
            {
                "family": record.family,
                "source_identity": list(record.source_identity),
                "business_sha256": record.business_sha256,
                "canonical_sha256": sha256(record.canonical_bytes).hexdigest(),
                "reconciliation_key": record.reconciliation_key,
            }
            for record in self.records
        ]
        return sha256(canonical_json_bytes(payload)).hexdigest()


@dataclass(frozen=True)
class TransactionCandidate:
    reconciliation_key: str
    key_components: TransactionKey
    processor_minor: int
    ledger_minor: int
    processor_ledger_delta_minor: int
    difference_minor: int
    processor_record_count: int
    ledger_journal_count: int
    status: str
    reason_codes: tuple[str, ...]
    source_identities: tuple[tuple[str, ...], ...]
    authoritative_proof: bool = False

    def value(self) -> dict[str, Any]:
        return {
            "reconciliation_key": self.reconciliation_key,
            "key_components": self.key_components.value(),
            "totals": {
                "processor_minor": self.processor_minor,
                "ledger_minor": self.ledger_minor,
                "processor_ledger_delta_minor": self.processor_ledger_delta_minor,
                "difference_minor": self.difference_minor,
                "processor_record_count": self.processor_record_count,
                "ledger_journal_count": self.ledger_journal_count,
            },
            "status": self.status,
            "reason_codes": list(self.reason_codes),
            "source_identities": [list(identity) for identity in self.source_identities],
            "authoritative_proof": False,
        }


@dataclass(frozen=True)
class TransactionReconciliationBatch:
    run_id: str
    policy_version: str
    policy_sha256: str
    manifest_sha256: str
    candidates: tuple[TransactionCandidate, ...]
    state: TransactionState
    authoritative_proof: bool = False

    def semantic_digest(self) -> str:
        payload = {
            "run_id": self.run_id,
            "policy_version": self.policy_version,
            "policy_sha256": self.policy_sha256,
            "manifest_sha256": self.manifest_sha256,
            "candidates": [candidate.value() for candidate in self.candidates],
            "state_sha256": self.state.semantic_digest(),
            "authoritative_proof": False,
        }
        return sha256(canonical_json_bytes(payload)).hexdigest()


def _object(raw: bytes, detail: str) -> dict[str, Any]:
    value = parse_strict_json(raw)
    if not isinstance(value, dict):
        raise AdmissionRejected("SCHEMA_VIOLATION", detail)
    return value


def _text(value: Mapping[str, Any], name: str) -> str:
    result = value.get(name)
    if not isinstance(result, str) or not result:
        raise AdmissionRejected("SCHEMA_VIOLATION", f"transaction field missing: {name}")
    return result


def _key(value: Mapping[str, Any], event_field: str) -> TransactionKey:
    return TransactionKey(
        processor=_text(value, "processor"),
        merchant_id=_text(value, "merchant_id"),
        payment_id=_text(value, "payment_id"),
        event_class=_text(value, event_field),
        currency=_text(value, "currency"),
    )


def _transaction_records(
    batch: AdmittedBatch, prior_state: TransactionState
) -> tuple[AdmittedRecord, ...]:
    merged: dict[tuple[str, ...], AdmittedRecord] = {}
    observed = batch.observed_records or batch.records
    for record in prior_state.records + observed:
        is_transaction = record.family == "PROCESSOR_EVENT" or (
            record.family == "LEDGER_JOURNAL"
            and isinstance(record.reconciliation_key, str)
            and record.reconciliation_key.startswith("txn:")
        )
        if not is_transaction:
            continue
        previous = merged.get(record.source_identity)
        if previous is not None and previous.business_sha256 != record.business_sha256:
            raise AdmissionRejected("IDENTITY_CONFLICT", "transaction state identity conflict")
        merged[record.source_identity] = record
    return tuple(merged[identity] for identity in sorted(merged))


def _policy(
    batch: AdmittedBatch,
) -> tuple[dict[str, int], dict[str, int], set[str], dict[str, int]]:
    value = _object(batch.policy_canonical_bytes, "policy must be an object")
    transaction = value.get("transaction_rules")
    currencies = value.get("currency_rules")
    if not isinstance(transaction, Mapping) or not isinstance(currencies, Mapping):
        raise AdmissionRejected("POLICY_MISMATCH", "transaction policy is incomplete")
    event_signs = transaction.get("event_signs")
    ledger_signs = transaction.get("ledger_side_signs")
    counterpart_roles = transaction.get("allowed_counterpart_roles")
    if (
        not isinstance(event_signs, Mapping)
        or not isinstance(ledger_signs, Mapping)
        or not isinstance(counterpart_roles, Sequence)
        or isinstance(counterpart_roles, (str, bytes))
    ):
        raise AdmissionRejected("POLICY_MISMATCH", "transaction policy shape differs")
    signs = {str(key): checked_i64(item) for key, item in event_signs.items()}
    sides = {str(key): checked_i64(item) for key, item in ledger_signs.items()}
    if set(signs) != TRANSACTION_EVENTS or set(sides) != {"DEBIT", "CREDIT"}:
        raise AdmissionRejected("POLICY_MISMATCH", "transaction policy domain differs")
    roles = {str(item) for item in counterpart_roles}
    tolerance: dict[str, int] = {}
    for currency, rule in currencies.items():
        if not isinstance(rule, Mapping):
            raise AdmissionRejected("POLICY_MISMATCH", "currency policy shape differs")
        amount = checked_i64(rule.get("transaction_tolerance_minor"))
        if amount < 0:
            raise AdmissionRejected("POLICY_MISMATCH", "negative transaction tolerance")
        tolerance[str(currency)] = amount
    return signs, sides, roles, tolerance


def _event_facts(
    records: tuple[AdmittedRecord, ...],
) -> tuple[
    dict[TransactionKey, list[tuple[AdmittedRecord, dict[str, Any]]]],
    dict[tuple[str, str], tuple[AdmittedRecord, dict[str, Any]]],
]:
    grouped: dict[TransactionKey, list[tuple[AdmittedRecord, dict[str, Any]]]] = {}
    captures: dict[tuple[str, str], tuple[AdmittedRecord, dict[str, Any]]] = {}
    for record in records:
        if record.family != "PROCESSOR_EVENT":
            continue
        value = _object(record.canonical_bytes, "processor event must be an object")
        key = _key(value, "event_type")
        if record.reconciliation_key != key.reconciliation_key:
            raise AdmissionRejected("SOURCE_IDENTITY_MISMATCH", "transaction event key drift")
        grouped.setdefault(key, []).append((record, value))
        if key.event_class == "CAPTURE":
            captures[(key.processor, _text(value, "source_record_id"))] = (record, value)
    return grouped, captures


def _reference_reasons(
    grouped: Mapping[TransactionKey, list[tuple[AdmittedRecord, dict[str, Any]]]],
    captures: Mapping[tuple[str, str], tuple[AdmittedRecord, dict[str, Any]]],
) -> dict[TransactionKey, set[str]]:
    reasons: dict[TransactionKey, set[str]] = {}
    applications: dict[tuple[str, str], list[tuple[TransactionKey, int]]] = {}
    for key, rows in grouped.items():
        for _, value in rows:
            if key.event_class == "CAPTURE":
                if "reference_event_id" in value:
                    reasons.setdefault(key, set()).add("UNRESOLVED_REFERENCE")
                continue
            reference = value.get("reference_event_id")
            target_identity = (key.processor, reference if isinstance(reference, str) else "")
            target = captures.get(target_identity)
            if target is None:
                reasons.setdefault(key, set()).add("UNRESOLVED_REFERENCE")
                continue
            target_value = target[1]
            same_scope = (
                _text(target_value, "merchant_id") == key.merchant_id
                and _text(target_value, "payment_id") == key.payment_id
                and _text(target_value, "currency") == key.currency
            )
            if not same_scope:
                reasons.setdefault(key, set()).add("UNRESOLVED_REFERENCE")
                continue
            applications.setdefault(target_identity, []).append(
                (key, checked_i64(value.get("amount_minor")))
            )
    for identity, application_rows in applications.items():
        applied = 0
        for _, amount in application_rows:
            applied = checked_add(applied, amount)
        captured = checked_i64(captures[identity][1].get("amount_minor"))
        if applied > captured:
            for application_key, _ in application_rows:
                reasons.setdefault(application_key, set()).add("OVER_APPLIED_REFERENCE")
    return reasons


def _journal_facts(
    records: tuple[AdmittedRecord, ...],
    ledger_signs: Mapping[str, int],
    allowed_counterparts: set[str],
) -> tuple[dict[TransactionKey, list[tuple[AdmittedRecord, int]]], dict[TransactionKey, set[str]]]:
    grouped: dict[TransactionKey, list[tuple[AdmittedRecord, int]]] = {}
    reasons: dict[TransactionKey, set[str]] = {}
    for record in records:
        if record.family != "LEDGER_JOURNAL" or not str(record.reconciliation_key).startswith(
            "txn:"
        ):
            continue
        value = _object(record.canonical_bytes, "journal must be an object")
        key = _key(value, "entry_type")
        if record.reconciliation_key != key.reconciliation_key:
            raise AdmissionRejected("SOURCE_IDENTITY_MISMATCH", "transaction journal key drift")
        postings = value.get("postings")
        if not isinstance(postings, list):
            raise AdmissionRejected("UNBALANCED_JOURNAL", "journal postings unavailable")
        movement = 0
        clearing_count = 0
        role_mapping_valid = record.journal_clearing_role_valid is True
        expected_side = "DEBIT" if key.event_class == "CAPTURE" else "CREDIT"
        for posting in postings:
            if not isinstance(posting, Mapping):
                raise AdmissionRejected("UNBALANCED_JOURNAL", "posting must be an object")
            role = posting.get("account_role")
            side = posting.get("side")
            if role == "PROCESSOR_CLEARING":
                clearing_count += 1
                if side not in ledger_signs:
                    raise AdmissionRejected("POLICY_MISMATCH", "ledger side policy missing")
                movement = checked_add(
                    movement,
                    checked_multiply_sign(posting.get("amount_minor"), ledger_signs[str(side)]),
                )
                if side != expected_side:
                    role_mapping_valid = False
            elif not isinstance(role, str) or role not in allowed_counterparts:
                role_mapping_valid = False
        if clearing_count != 1:
            role_mapping_valid = False
        if not role_mapping_valid:
            reasons.setdefault(key, set()).add("INVALID_ACCOUNT_ROLE")
        grouped.setdefault(key, []).append((record, movement))
    return grouped, reasons


def _merge_reasons(*sources: Mapping[TransactionKey, set[str]]) -> dict[TransactionKey, set[str]]:
    merged: dict[TransactionKey, set[str]] = {}
    for source in sources:
        for key, values in source.items():
            merged.setdefault(key, set()).update(values)
    return merged


def _status(
    key: TransactionKey,
    difference: int,
    owned: set[str],
    tolerances: Mapping[str, int],
) -> tuple[str, tuple[str, ...]]:
    unknown = owned.difference(FINANCIAL_REASONS)
    if unknown:
        raise AdmissionRejected("SCHEMA_VIOLATION", "unknown financial reason")
    if owned:
        return "EXCEPTION", tuple(reason for reason in REASON_ORDER if reason in owned)
    if difference == 0:
        return "MATCHED", ()
    tolerance = tolerances.get(key.currency)
    if tolerance is None:
        raise AdmissionRejected("POLICY_MISMATCH", "currency tolerance unavailable")
    if difference <= tolerance:
        return "WITHIN_TOLERANCE", ("TOLERATED_DIFFERENCE",)
    return "EXCEPTION", ("PROCESSOR_LEDGER_MISMATCH",)


def reconcile_transactions(
    batch: AdmittedBatch, prior_state: TransactionState | None = None
) -> TransactionReconciliationBatch:
    """Produce immutable transaction candidates; never finalize authoritative proofs."""

    signs, ledger_signs, counterparts, tolerances = _policy(batch)
    records = _transaction_records(batch, prior_state or TransactionState())
    events, captures = _event_facts(records)
    references = _reference_reasons(events, captures)
    journals, role_reasons = _journal_facts(records, ledger_signs, counterparts)
    reasons = _merge_reasons(references, role_reasons)
    candidates: list[TransactionCandidate] = []
    for key in sorted(set(events) | set(journals)):
        event_rows = events.get(key, [])
        journal_rows = journals.get(key, [])
        processor = 0
        for _, value in event_rows:
            processor = checked_add(
                processor,
                checked_multiply_sign(value.get("amount_minor"), signs[key.event_class]),
            )
        ledger = 0
        for _, movement in journal_rows:
            ledger = checked_add(ledger, movement)
        delta = checked_subtract(processor, ledger)
        difference = checked_abs(delta)
        owned = reasons.setdefault(key, set())
        if not event_rows:
            owned.add("MISSING_PROCESSOR_ACTIVITY")
        if not journal_rows:
            owned.add("MISSING_LEDGER_MOVEMENT")
        status, reason_codes = _status(key, difference, owned, tolerances)
        identities = tuple(
            sorted(record.source_identity for record, _ in event_rows + journal_rows)
        )
        candidates.append(
            TransactionCandidate(
                reconciliation_key=key.reconciliation_key,
                key_components=key,
                processor_minor=processor,
                ledger_minor=ledger,
                processor_ledger_delta_minor=delta,
                difference_minor=difference,
                processor_record_count=checked_i64(len(event_rows)),
                ledger_journal_count=checked_i64(len(journal_rows)),
                status=status,
                reason_codes=reason_codes,
                source_identities=identities,
            )
        )
    state = TransactionState(records)
    return TransactionReconciliationBatch(
        run_id=batch.run_id,
        policy_version=batch.policy_version,
        policy_sha256=batch.policy_sha256,
        manifest_sha256=batch.manifest_sha256,
        candidates=tuple(candidates),
        state=state,
    )
