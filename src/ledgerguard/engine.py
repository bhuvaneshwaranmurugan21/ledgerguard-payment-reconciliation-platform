from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict
from typing import Iterable, Literal

from .model import ExternalRecord, Journal, ReconciliationResult, digest


class ContractViolation(ValueError):
    pass


class IdentityConflict(ValueError):
    pass


class InjectedFailure(RuntimeError):
    pass


class ReconciliationEngine:
    """Auditable three-way processor, ledger, and bank reconciliation oracle."""

    def __init__(self) -> None:
        self.records: dict[str, ExternalRecord] = {}
        self.record_digests: dict[str, str] = {}
        self.journals: dict[str, Journal] = {}
        self.journal_digests: dict[str, str] = {}
        self.results: dict[str, ReconciliationResult] = {}
        self.case_history: dict[str, list[str]] = defaultdict(list)

    def ingest_external(
        self, records: Iterable[ExternalRecord], *, fail_before_commit: bool = False
    ) -> str:
        staged_records = self.records.copy()
        staged_digests = self.record_digests.copy()
        changed = False
        for record in records:
            self._validate_record(record, staged_records)
            known = staged_digests.get(record.record_id)
            if known is not None:
                if known != record.payload_digest:
                    raise IdentityConflict(f"record {record.record_id} changed payload")
                continue
            staged_records[record.record_id] = record
            staged_digests[record.record_id] = record.payload_digest
            changed = True
        if fail_before_commit:
            raise InjectedFailure("external feed failed before commit")
        self.records = staged_records
        self.record_digests = staged_digests
        return "applied" if changed else "replayed"

    def ingest_journals(self, journals: Iterable[Journal]) -> str:
        staged = self.journals.copy()
        digests = self.journal_digests.copy()
        changed = False
        for journal in journals:
            self._validate_journal(journal)
            known = digests.get(journal.journal_id)
            if known is not None:
                if known != journal.payload_digest:
                    raise IdentityConflict(f"journal {journal.journal_id} changed payload")
                continue
            staged[journal.journal_id] = journal
            digests[journal.journal_id] = journal.payload_digest
            changed = True
        self.journals = staged
        self.journal_digests = digests
        return "applied" if changed else "replayed"

    def reconcile(
        self, payment_id: str, *, currency: str, tolerance_cents: int = 0, policy_version: str = "v1"
    ) -> ReconciliationResult:
        if tolerance_cents < 0:
            raise ContractViolation("tolerance cannot be negative")
        processor = sum(
            self._signed_external(record)
            for record in self.records.values()
            if record.payment_id == payment_id
            and record.source == "processor"
            and record.currency == currency
        )
        bank = sum(
            self._signed_external(record)
            for record in self.records.values()
            if record.payment_id == payment_id
            and record.source == "bank"
            and record.currency == currency
        )
        ledger = sum(
            journal.business_amount_cents
            for journal in self.journals.values()
            if journal.payment_id == payment_id and journal.currency == currency
        )
        difference = max(processor, ledger, bank) - min(processor, ledger, bank)
        status: Literal["MATCHED", "EXCEPTION"] = (
            "MATCHED" if difference <= tolerance_cents else "EXCEPTION"
        )
        result = ReconciliationResult(
            payment_id,
            currency,
            processor,
            ledger,
            bank,
            difference,
            status,
            policy_version,
        )
        previous = self.results.get(payment_id)
        self.results[payment_id] = result
        transition = f"{previous.status if previous else 'NEW'}->{status}:{digest(asdict(result))[:12]}"
        self.case_history[payment_id].append(transition)
        return result

    def audit_digest(self, payment_id: str) -> str:
        result = self.results[payment_id]
        return digest({"result": asdict(result), "history": self.case_history[payment_id]})

    def _validate_record(
        self, record: ExternalRecord, staged_records: dict[str, ExternalRecord]
    ) -> None:
        if record.amount_cents <= 0 or not isinstance(record.amount_cents, int):
            raise ContractViolation("amount must be positive integer minor units")
        if len(record.currency) != 3 or record.currency.upper() != record.currency:
            raise ContractViolation("currency must be an uppercase ISO-like code")
        if record.source == "bank" and record.kind not in {"settlement", "reversal"}:
            raise ContractViolation("bank feed supports settlements and reversals")
        if record.kind == "reversal":
            if record.reference_id is None or record.reference_id not in staged_records:
                raise ContractViolation("reversal references unknown record")
            original = staged_records[record.reference_id]
            if original.payment_id != record.payment_id or original.currency != record.currency:
                raise ContractViolation("reversal identity differs from original")

    def _validate_journal(self, journal: Journal) -> None:
        if not journal.postings:
            raise ContractViolation("journal requires postings")
        debit = sum(line.debit_cents for line in journal.postings)
        credit = sum(line.credit_cents for line in journal.postings)
        if any(
            line.debit_cents < 0
            or line.credit_cents < 0
            or (line.debit_cents > 0 and line.credit_cents > 0)
            for line in journal.postings
        ):
            raise ContractViolation("posting line must be one-sided and non-negative")
        if debit <= 0 or debit != credit:
            raise ContractViolation("journal must balance debits and credits")

    @staticmethod
    def _signed_external(record: ExternalRecord) -> int:
        return record.amount_cents if record.kind in {"capture", "settlement"} else -record.amount_cents
