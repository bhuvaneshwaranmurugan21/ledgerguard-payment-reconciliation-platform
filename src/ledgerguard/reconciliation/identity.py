"""Canonical source and reconciliation identities."""

from __future__ import annotations

from collections.abc import Mapping
from hashlib import sha256
from typing import Any

from .canonical import canonical_json_bytes, normalize_string
from .errors import AdmissionRejected

SOURCE_IDENTITIES = {
    "PROCESSOR_EVENT": ("processor", "source_record_id"),
    "PROCESSOR_SETTLEMENT": ("processor", "source_record_id"),
    "LEDGER_JOURNAL": ("ledger_system", "journal_id"),
    "BANK_ENTRY": ("bank_account_id", "bank_record_id"),
}


def source_identity(family: str, record: Mapping[str, Any]) -> tuple[str, ...]:
    fields = SOURCE_IDENTITIES.get(family)
    if fields is None:
        raise AdmissionRejected("SOURCE_IDENTITY_MISMATCH", "unknown source family")
    values = [family]
    for field in fields:
        value = record.get(field)
        if not isinstance(value, str) or not value:
            raise AdmissionRejected("SOURCE_IDENTITY_MISMATCH", f"missing {field}")
        values.append(normalize_string(value))
    return tuple(values)


def _derived_id(prefix: str, components: Mapping[str, Any]) -> str:
    return prefix + sha256(canonical_json_bytes(components)).hexdigest()


def transaction_key(components: Mapping[str, Any]) -> str:
    expected = {"processor", "merchant_id", "payment_id", "event_class", "currency"}
    if set(components) != expected:
        raise AdmissionRejected("SOURCE_IDENTITY_MISMATCH", "transaction key components")
    return _derived_id("txn:", components)


def settlement_key(components: Mapping[str, Any]) -> str:
    expected = {
        "processor",
        "merchant_id",
        "settlement_id",
        "settlement_cycle",
        "currency",
    }
    if set(components) != expected:
        raise AdmissionRejected("SOURCE_IDENTITY_MISMATCH", "settlement key components")
    return _derived_id("stl:", components)


def normalize_bank_reference(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise AdmissionRejected("SCHEMA_VIOLATION", "settlement reference must be text")
    return normalize_string(value).strip()
