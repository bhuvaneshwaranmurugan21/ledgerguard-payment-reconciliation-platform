"""Pure settlement-grain reconciliation over admitted source facts."""

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
from .identity import (
    normalize_bank_reference,
    source_identity,
)
from .identity import (
    settlement_key as derive_settlement_key,
)

FINANCIAL_REASONS = frozenset(
    {
        "INVALID_ACCOUNT_ROLE",
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
    }
)
REASON_ORDER = (
    "INVALID_ACCOUNT_ROLE",
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


@dataclass(frozen=True, order=True)
class SettlementKey:
    processor: str
    merchant_id: str
    settlement_id: str
    settlement_cycle: str
    currency: str

    def value(self) -> dict[str, str]:
        return {
            "processor": self.processor,
            "merchant_id": self.merchant_id,
            "settlement_id": self.settlement_id,
            "settlement_cycle": self.settlement_cycle,
            "currency": self.currency,
        }

    @property
    def reconciliation_key(self) -> str:
        return derive_settlement_key(self.value())


@dataclass(frozen=True)
class SettlementState:
    records: tuple[AdmittedRecord, ...] = ()
    duplicate_bank_identities: tuple[tuple[str, ...], ...] = ()

    def semantic_digest(self) -> str:
        payload = [
            {
                "family": record.family,
                "source_identity": list(record.source_identity),
                "business_sha256": record.business_sha256,
                "reconciliation_key": record.reconciliation_key,
                "normalized_settlement_reference": record.normalized_settlement_reference,
            }
            for record in self.records
        ]
        return sha256(
            canonical_json_bytes(
                {
                    "records": payload,
                    "duplicate_bank_identities": [
                        list(identity) for identity in self.duplicate_bank_identities
                    ],
                }
            )
        ).hexdigest()


@dataclass(frozen=True)
class BankAllocation:
    source_identity: tuple[str, ...]
    merchant_id: str
    currency: str
    normalized_settlement_reference: str | None
    disposition: str
    settlement_reconciliation_key: str | None
    signed_minor: int
    account_permitted: bool | None
    duplicate_current_bundle: bool
    reason_codes: tuple[str, ...]

    def value(self) -> dict[str, Any]:
        return {
            "source_identity": list(self.source_identity),
            "merchant_id": self.merchant_id,
            "currency": self.currency,
            "normalized_settlement_reference": self.normalized_settlement_reference,
            "disposition": self.disposition,
            "settlement_reconciliation_key": self.settlement_reconciliation_key,
            "signed_minor": self.signed_minor,
            "account_permitted": self.account_permitted,
            "duplicate_current_bundle": self.duplicate_current_bundle,
            "reason_codes": list(self.reason_codes),
        }


@dataclass(frozen=True)
class SettlementCandidate:
    reconciliation_key: str
    key_components: SettlementKey
    processor_net_minor: int
    ledger_clearing_minor: int
    bank_minor: int
    processor_ledger_delta_minor: int
    processor_bank_delta_minor: int
    ledger_bank_delta_minor: int
    difference_minor: int
    processor_settlement_count: int
    ledger_journal_count: int
    allocated_bank_entry_count: int
    status: str
    reason_codes: tuple[str, ...]
    source_identities: tuple[tuple[str, ...], ...]
    authoritative_proof: bool = False

    def value(self) -> dict[str, Any]:
        return {
            "reconciliation_key": self.reconciliation_key,
            "key_components": self.key_components.value(),
            "totals": {
                "processor_net_minor": self.processor_net_minor,
                "ledger_clearing_minor": self.ledger_clearing_minor,
                "bank_minor": self.bank_minor,
                "processor_ledger_delta_minor": self.processor_ledger_delta_minor,
                "processor_bank_delta_minor": self.processor_bank_delta_minor,
                "ledger_bank_delta_minor": self.ledger_bank_delta_minor,
                "difference_minor": self.difference_minor,
                "processor_settlement_count": self.processor_settlement_count,
                "ledger_journal_count": self.ledger_journal_count,
                "allocated_bank_entry_count": self.allocated_bank_entry_count,
            },
            "status": self.status,
            "reason_codes": list(self.reason_codes),
            "source_identities": [list(identity) for identity in self.source_identities],
            "authoritative_proof": False,
        }


@dataclass(frozen=True)
class SettlementReconciliationBatch:
    run_id: str
    policy_version: str
    policy_sha256: str
    manifest_sha256: str
    candidates: tuple[SettlementCandidate, ...]
    bank_allocations: tuple[BankAllocation, ...]
    state: SettlementState
    status: str
    reason_codes: tuple[str, ...]
    authoritative_proof: bool = False

    def semantic_digest(self) -> str:
        payload = {
            "run_id": self.run_id,
            "policy_version": self.policy_version,
            "policy_sha256": self.policy_sha256,
            "manifest_sha256": self.manifest_sha256,
            "candidates": [candidate.value() for candidate in self.candidates],
            "bank_allocations": [allocation.value() for allocation in self.bank_allocations],
            "state_sha256": self.state.semantic_digest(),
            "status": self.status,
            "reason_codes": list(self.reason_codes),
            "authoritative_proof": False,
        }
        return sha256(canonical_json_bytes(payload)).hexdigest()


@dataclass(frozen=True)
class _SettlementPolicy:
    ledger_signs: Mapping[str, int]
    bank_signs: Mapping[str, int]
    permitted_accounts: Mapping[tuple[str, str], frozenset[str]]
    tolerances: Mapping[str, int]


def _object(raw: bytes, detail: str) -> dict[str, Any]:
    value = parse_strict_json(raw)
    if not isinstance(value, dict):
        raise AdmissionRejected("SCHEMA_VIOLATION", detail)
    return value


def _text(value: Mapping[str, Any], name: str) -> str:
    result = value.get(name)
    if not isinstance(result, str) or not result:
        raise AdmissionRejected("SCHEMA_VIOLATION", f"settlement field missing: {name}")
    return result


def _key(value: Mapping[str, Any]) -> SettlementKey:
    return SettlementKey(
        processor=_text(value, "processor"),
        merchant_id=_text(value, "merchant_id"),
        settlement_id=_text(value, "settlement_id"),
        settlement_cycle=_text(value, "settlement_cycle"),
        currency=_text(value, "currency"),
    )


def _policy(batch: AdmittedBatch) -> _SettlementPolicy:
    value = _object(batch.policy_canonical_bytes, "policy must be an object")
    settlement = value.get("settlement_rules")
    currencies = value.get("currency_rules")
    if not isinstance(settlement, Mapping) or not isinstance(currencies, Mapping):
        raise AdmissionRejected("POLICY_MISMATCH", "settlement policy is incomplete")
    if settlement.get("formula") != (
        "gross_minor-fee_minor-refund_minor-chargeback_minor-reserve_minor"
    ):
        raise AdmissionRejected("POLICY_MISMATCH", "settlement formula differs")
    ledger_source = settlement.get("ledger_side_signs")
    bank_source = settlement.get("bank_side_signs")
    allocation = settlement.get("bank_allocation")
    accounts = settlement.get("permitted_bank_accounts")
    if (
        not isinstance(ledger_source, Mapping)
        or not isinstance(bank_source, Mapping)
        or not isinstance(allocation, Mapping)
        or not isinstance(accounts, Sequence)
        or isinstance(accounts, (str, bytes))
    ):
        raise AdmissionRejected("POLICY_MISMATCH", "settlement policy shape differs")
    if (
        allocation.get("strategy") != "EXACT_SETTLEMENT_REFERENCE"
        or allocation.get("amount_date_heuristic_forbidden") is not True
        or allocation.get("one_bank_identity_one_allocation") is not True
    ):
        raise AdmissionRejected("POLICY_MISMATCH", "bank allocation policy differs")
    ledger_signs = {str(key): checked_i64(item) for key, item in ledger_source.items()}
    bank_signs = {str(key): checked_i64(item) for key, item in bank_source.items()}
    if ledger_signs != {"DEBIT": -1, "CREDIT": 1}:
        raise AdmissionRejected("POLICY_MISMATCH", "settlement ledger signs differ")
    if bank_signs != {"CREDIT": 1, "DEBIT": -1}:
        raise AdmissionRejected("POLICY_MISMATCH", "bank signs differ")
    permitted: dict[tuple[str, str], frozenset[str]] = {}
    for row in accounts:
        if not isinstance(row, Mapping):
            raise AdmissionRejected("POLICY_MISMATCH", "permitted account row differs")
        identifiers = row.get("bank_account_ids")
        if not isinstance(identifiers, Sequence) or isinstance(identifiers, (str, bytes)):
            raise AdmissionRejected("POLICY_MISMATCH", "permitted accounts unavailable")
        domain = (_text(row, "merchant_id"), _text(row, "currency"))
        if domain in permitted:
            raise AdmissionRejected("POLICY_MISMATCH", "duplicate permitted-account domain")
        permitted[domain] = frozenset(str(identifier) for identifier in identifiers)
    tolerances: dict[str, int] = {}
    for currency, rule in currencies.items():
        if not isinstance(rule, Mapping):
            raise AdmissionRejected("POLICY_MISMATCH", "currency policy shape differs")
        tolerance = checked_i64(rule.get("settlement_tolerance_minor"))
        if tolerance < 0:
            raise AdmissionRejected("POLICY_MISMATCH", "negative settlement tolerance")
        tolerances[str(currency)] = tolerance
    return _SettlementPolicy(ledger_signs, bank_signs, permitted, tolerances)


def _settlement_records(
    batch: AdmittedBatch, prior_state: SettlementState
) -> tuple[AdmittedRecord, ...]:
    merged: dict[tuple[str, ...], AdmittedRecord] = {}
    observed = batch.observed_occurrences or batch.observed_records or batch.records
    for record in prior_state.records + observed:
        is_settlement = record.family in {"PROCESSOR_SETTLEMENT", "BANK_ENTRY"} or (
            record.family == "LEDGER_JOURNAL"
            and isinstance(record.reconciliation_key, str)
            and record.reconciliation_key.startswith("stl:")
        )
        if not is_settlement:
            continue
        previous = merged.get(record.source_identity)
        if previous is not None:
            if previous.business_sha256 != record.business_sha256:
                raise AdmissionRejected("IDENTITY_CONFLICT", "settlement state identity conflict")
            continue
        merged[record.source_identity] = record
    return tuple(merged[identity] for identity in sorted(merged))


def _duplicate_bank_identities(batch: AdmittedBatch) -> frozenset[tuple[str, ...]]:
    occurrences = batch.observed_occurrences or batch.observed_records or batch.records
    counts: dict[tuple[str, ...], int] = {}
    for record in occurrences:
        if record.family == "BANK_ENTRY":
            counts[record.source_identity] = checked_add(counts.get(record.source_identity, 0), 1)
    return frozenset(identity for identity, count in counts.items() if count > 1)


def _processor_facts(
    records: tuple[AdmittedRecord, ...],
) -> tuple[
    dict[SettlementKey, list[tuple[AdmittedRecord, int]]],
    dict[SettlementKey, set[str]],
]:
    grouped: dict[SettlementKey, list[tuple[AdmittedRecord, int]]] = {}
    reasons: dict[SettlementKey, set[str]] = {}
    for record in records:
        if record.family != "PROCESSOR_SETTLEMENT":
            continue
        value = _object(record.canonical_bytes, "processor settlement must be an object")
        if source_identity("PROCESSOR_SETTLEMENT", value) != record.source_identity:
            raise AdmissionRejected("SOURCE_IDENTITY_MISMATCH", "settlement identity drift")
        key = _key(value)
        if record.reconciliation_key != key.reconciliation_key:
            raise AdmissionRejected("SOURCE_IDENTITY_MISMATCH", "settlement key drift")
        net = checked_i64(value.get("gross_minor"))
        for field in ("fee_minor", "refund_minor", "chargeback_minor", "reserve_minor"):
            net = checked_subtract(net, value.get(field))
        if checked_i64(value.get("reported_net_minor")) != net:
            reasons.setdefault(key, set()).add("SETTLEMENT_FORMULA_MISMATCH")
        grouped.setdefault(key, []).append((record, net))
    return grouped, reasons


def _journal_facts(
    records: tuple[AdmittedRecord, ...], ledger_signs: Mapping[str, int]
) -> tuple[
    dict[SettlementKey, list[tuple[AdmittedRecord, int]]],
    dict[SettlementKey, set[str]],
]:
    grouped: dict[SettlementKey, list[tuple[AdmittedRecord, int]]] = {}
    reasons: dict[SettlementKey, set[str]] = {}
    for record in records:
        if record.family != "LEDGER_JOURNAL" or not str(record.reconciliation_key).startswith(
            "stl:"
        ):
            continue
        value = _object(record.canonical_bytes, "settlement journal must be an object")
        if source_identity("LEDGER_JOURNAL", value) != record.source_identity:
            raise AdmissionRejected("SOURCE_IDENTITY_MISMATCH", "journal identity drift")
        key = _key(value)
        if record.reconciliation_key != key.reconciliation_key:
            raise AdmissionRejected("SOURCE_IDENTITY_MISMATCH", "settlement journal key drift")
        postings = value.get("postings")
        if not isinstance(postings, Sequence) or isinstance(postings, (str, bytes)):
            raise AdmissionRejected("UNBALANCED_JOURNAL", "journal postings unavailable")
        movement = 0
        clearing_count = 0
        for posting in postings:
            if not isinstance(posting, Mapping):
                raise AdmissionRejected("UNBALANCED_JOURNAL", "posting must be an object")
            if posting.get("account_role") != "PROCESSOR_CLEARING":
                continue
            clearing_count += 1
            side = posting.get("side")
            if side not in ledger_signs:
                raise AdmissionRejected("POLICY_MISMATCH", "settlement ledger side unavailable")
            movement = checked_add(
                movement,
                checked_multiply_sign(posting.get("amount_minor"), ledger_signs[str(side)]),
            )
        if clearing_count != 1 or record.journal_clearing_role_valid is not True:
            reasons.setdefault(key, set()).add("INVALID_ACCOUNT_ROLE")
        grouped.setdefault(key, []).append((record, movement))
    return grouped, reasons


def _target_index(keys: set[SettlementKey]) -> dict[tuple[str, str, str], SettlementKey]:
    candidates: dict[tuple[str, str, str], set[SettlementKey]] = {}
    for key in keys:
        normalized = normalize_bank_reference(key.settlement_id)
        if normalized is None:
            raise AdmissionRejected("SCHEMA_VIOLATION", "settlement identifier is empty")
        lookup = (key.merchant_id, key.currency, normalized)
        candidates.setdefault(lookup, set()).add(key)
    result: dict[tuple[str, str, str], SettlementKey] = {}
    for lookup, targets in candidates.items():
        if len(targets) != 1:
            raise AdmissionRejected(
                "AMBIGUOUS_BANK_ALLOCATION", "settlement reference has multiple targets"
            )
        result[lookup] = next(iter(targets))
    return result


def _ordered_reasons(reasons: set[str]) -> tuple[str, ...]:
    unknown = reasons.difference(FINANCIAL_REASONS)
    if unknown:
        raise AdmissionRejected("SCHEMA_VIOLATION", "unknown settlement financial reason")
    return tuple(reason for reason in REASON_ORDER if reason in reasons)


def _status(
    key: SettlementKey,
    difference: int,
    reasons: set[str],
    tolerances: Mapping[str, int],
    deltas: tuple[int, int, int],
) -> tuple[str, tuple[str, ...]]:
    if reasons:
        return "EXCEPTION", _ordered_reasons(reasons)
    if difference == 0:
        return "MATCHED", ()
    tolerance = tolerances.get(key.currency)
    if tolerance is None:
        raise AdmissionRejected("POLICY_MISMATCH", "settlement tolerance unavailable")
    if difference <= tolerance:
        return "WITHIN_TOLERANCE", ("TOLERATED_DIFFERENCE",)
    mismatch_names = (
        "PROCESSOR_LEDGER_MISMATCH",
        "PROCESSOR_BANK_MISMATCH",
        "LEDGER_BANK_MISMATCH",
    )
    mismatches = {name for name, delta in zip(mismatch_names, deltas, strict=True) if delta}
    return "EXCEPTION", _ordered_reasons(mismatches)


def reconcile_settlements(
    batch: AdmittedBatch, prior_state: SettlementState | None = None
) -> SettlementReconciliationBatch:
    """Produce immutable settlement candidates; never finalize authoritative proofs."""

    policy = _policy(batch)
    records = _settlement_records(batch, prior_state or SettlementState())
    current_duplicate_identities = _duplicate_bank_identities(batch)
    duplicate_identities = (
        frozenset((prior_state or SettlementState()).duplicate_bank_identities)
        | current_duplicate_identities
    )
    processors, processor_reasons = _processor_facts(records)
    journals, journal_reasons = _journal_facts(records, policy.ledger_signs)
    keys = set(processors) | set(journals)
    targets = _target_index(keys)
    allocated: dict[SettlementKey, list[tuple[AdmittedRecord, int, bool, bool]]] = {}
    allocations: list[BankAllocation] = []
    allocation_reasons: set[str] = set()
    for record in records:
        if record.family != "BANK_ENTRY":
            continue
        value = _object(record.canonical_bytes, "bank entry must be an object")
        if source_identity("BANK_ENTRY", value) != record.source_identity:
            raise AdmissionRejected("SOURCE_IDENTITY_MISMATCH", "bank identity drift")
        normalized = normalize_bank_reference(value.get("settlement_reference"))
        if normalized != record.normalized_settlement_reference:
            raise AdmissionRejected("SOURCE_IDENTITY_MISMATCH", "bank reference drift")
        direction = value.get("direction")
        if direction not in policy.bank_signs:
            raise AdmissionRejected("POLICY_MISMATCH", "bank direction unavailable")
        movement = checked_multiply_sign(
            value.get("amount_minor"), policy.bank_signs[str(direction)]
        )
        merchant = _text(value, "merchant_id")
        currency = _text(value, "currency")
        target = targets.get((merchant, currency, normalized)) if normalized is not None else None
        duplicate = record.source_identity in duplicate_identities
        duplicate_current = record.source_identity in current_duplicate_identities
        reasons: set[str] = set()
        if duplicate:
            reasons.add("DUPLICATE_BANK_MOVEMENT")
        if target is None:
            reasons.add("UNALLOCATED_BANK_MOVEMENT")
            allocation_reasons.update(reasons)
            allocations.append(
                BankAllocation(
                    source_identity=record.source_identity,
                    merchant_id=merchant,
                    currency=currency,
                    normalized_settlement_reference=normalized,
                    disposition=(
                        "UNALLOCATED_MISSING_REFERENCE"
                        if normalized is None
                        else "UNALLOCATED_UNKNOWN_REFERENCE"
                    ),
                    settlement_reconciliation_key=None,
                    signed_minor=movement,
                    account_permitted=None,
                    duplicate_current_bundle=duplicate_current,
                    reason_codes=_ordered_reasons(reasons),
                )
            )
            continue
        account = _text(value, "bank_account_id")
        permitted = account in policy.permitted_accounts.get(
            (target.merchant_id, target.currency), frozenset()
        )
        if not permitted:
            reasons.add("INVALID_BANK_ACCOUNT")
        allocated.setdefault(target, []).append((record, movement, permitted, duplicate))
        allocations.append(
            BankAllocation(
                source_identity=record.source_identity,
                merchant_id=merchant,
                currency=currency,
                normalized_settlement_reference=normalized,
                disposition="ALLOCATED",
                settlement_reconciliation_key=target.reconciliation_key,
                signed_minor=movement,
                account_permitted=permitted,
                duplicate_current_bundle=duplicate_current,
                reason_codes=_ordered_reasons(reasons),
            )
        )

    candidates: list[SettlementCandidate] = []
    for key in sorted(keys):
        processor_rows = processors.get(key, [])
        journal_rows = journals.get(key, [])
        bank_rows = allocated.get(key, [])
        reasons = set(processor_reasons.get(key, set()))
        reasons.update(journal_reasons.get(key, set()))
        processor_net = 0
        for _, net in processor_rows:
            processor_net = checked_add(processor_net, net)
        ledger = 0
        for _, movement in journal_rows:
            ledger = checked_add(ledger, movement)
        bank = 0
        for _, movement, permitted, duplicate in bank_rows:
            bank = checked_add(bank, movement)
            if not permitted:
                reasons.add("INVALID_BANK_ACCOUNT")
            if duplicate:
                reasons.add("DUPLICATE_BANK_MOVEMENT")
        if not processor_rows:
            reasons.add("MISSING_PROCESSOR_ACTIVITY")
        if not journal_rows and processor_net != 0:
            reasons.add("MISSING_LEDGER_MOVEMENT")
        if not bank_rows and processor_net != 0:
            reasons.add("MISSING_BANK_SETTLEMENT")
        processor_ledger = checked_subtract(processor_net, ledger)
        processor_bank = checked_subtract(processor_net, bank)
        ledger_bank = checked_subtract(ledger, bank)
        deltas = (processor_ledger, processor_bank, ledger_bank)
        difference = max(checked_abs(delta) for delta in deltas)
        status, reason_codes = _status(key, difference, reasons, policy.tolerances, deltas)
        identities = tuple(
            sorted(
                record.source_identity for record, *_ in processor_rows + journal_rows + bank_rows
            )
        )
        candidates.append(
            SettlementCandidate(
                reconciliation_key=key.reconciliation_key,
                key_components=key,
                processor_net_minor=processor_net,
                ledger_clearing_minor=ledger,
                bank_minor=bank,
                processor_ledger_delta_minor=processor_ledger,
                processor_bank_delta_minor=processor_bank,
                ledger_bank_delta_minor=ledger_bank,
                difference_minor=difference,
                processor_settlement_count=checked_i64(len(processor_rows)),
                ledger_journal_count=checked_i64(len(journal_rows)),
                allocated_bank_entry_count=checked_i64(len(bank_rows)),
                status=status,
                reason_codes=reason_codes,
                source_identities=identities,
            )
        )

    all_reasons = set(allocation_reasons)
    for candidate in candidates:
        all_reasons.update(
            reason for reason in candidate.reason_codes if reason != "TOLERATED_DIFFERENCE"
        )
    if all_reasons:
        overall_status = "EXCEPTION"
        overall_reasons = _ordered_reasons(all_reasons)
    elif any(candidate.status == "WITHIN_TOLERANCE" for candidate in candidates):
        overall_status = "WITHIN_TOLERANCE"
        overall_reasons = ("TOLERATED_DIFFERENCE",)
    else:
        overall_status = "MATCHED"
        overall_reasons = ()
    state = SettlementState(records, tuple(sorted(duplicate_identities)))
    return SettlementReconciliationBatch(
        run_id=batch.run_id,
        policy_version=batch.policy_version,
        policy_sha256=batch.policy_sha256,
        manifest_sha256=batch.manifest_sha256,
        candidates=tuple(candidates),
        bank_allocations=tuple(sorted(allocations, key=lambda row: row.source_identity)),
        state=state,
        status=overall_status,
        reason_codes=overall_reasons,
    )
