from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from typing import Any, Literal

Source = Literal["processor", "bank"]
Kind = Literal["capture", "refund", "reversal", "settlement"]


def digest(value: Any) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class ExternalRecord:
    record_id: str
    payment_id: str
    source: Source
    kind: Kind
    amount_cents: int
    currency: str
    occurred_at: int
    reference_id: str | None = None

    @property
    def payload_digest(self) -> str:
        return digest(asdict(self))


@dataclass(frozen=True, slots=True)
class Posting:
    account: str
    debit_cents: int = 0
    credit_cents: int = 0


@dataclass(frozen=True, slots=True)
class Journal:
    journal_id: str
    payment_id: str
    kind: Literal["capture", "refund", "reversal"]
    currency: str
    occurred_at: int
    postings: tuple[Posting, ...]

    @property
    def payload_digest(self) -> str:
        return digest(asdict(self))

    @property
    def business_amount_cents(self) -> int:
        amount = sum(line.debit_cents for line in self.postings)
        return amount if self.kind == "capture" else -amount


@dataclass(frozen=True, slots=True)
class ReconciliationResult:
    payment_id: str
    currency: str
    processor_cents: int
    ledger_cents: int
    bank_cents: int
    difference_cents: int
    status: Literal["MATCHED", "EXCEPTION"]
    policy_version: str

