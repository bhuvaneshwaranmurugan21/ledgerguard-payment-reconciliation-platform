"""Canonical identities implemented independently from the production namespace."""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Mapping
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any, NoReturn

from .oracle import AdmissionRejected, checked_i64

_TIMESTAMP_FIELDS = {"occurred_at", "received_at", "effective_at", "value_at", "created_at"}
_DIGEST_EXCLUSIONS = {"payload_sha256", "received_at", "source_batch_id"}
_RFC3339 = re.compile(
    r"^(?P<date>[0-9]{4}-[0-9]{2}-[0-9]{2})T"
    r"(?P<time>[0-9]{2}:[0-9]{2}:[0-9]{2})"
    r"(?P<fraction>\.[0-9]{1,6})?"
    r"(?P<offset>Z|[+-][0-9]{2}:[0-9]{2})$"
)
_SOURCE_IDENTITIES = {
    "PROCESSOR_EVENT": ("processor", "source_record_id"),
    "PROCESSOR_SETTLEMENT": ("processor", "source_record_id"),
    "LEDGER_JOURNAL": ("ledger_system", "journal_id"),
    "BANK_ENTRY": ("bank_account_id", "bank_record_id"),
}


def _normalize_string(value: str) -> str:
    if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
        raise AdmissionRejected("SCHEMA_VIOLATION", "Unicode surrogate code point")
    return unicodedata.normalize("NFC", value)


def _reject_float(_: str) -> NoReturn:
    raise AdmissionRejected("SCHEMA_VIOLATION", "floating-point JSON number")


def _reject_constant(_: str) -> NoReturn:
    raise AdmissionRejected("SCHEMA_VIOLATION", "non-finite JSON number")


def _parse_integer(value: str) -> int:
    return checked_i64(int(value))


def _strict_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    raw_keys: set[str] = set()
    for raw_key, item in pairs:
        if raw_key in raw_keys:
            raise AdmissionRejected("SCHEMA_VIOLATION", "duplicate JSON key")
        raw_keys.add(raw_key)
        key = _normalize_string(raw_key)
        if key in result:
            raise AdmissionRejected("SCHEMA_VIOLATION", "NFC key collision")
        result[key] = item
    return result


def parse_strict_json(text: str) -> Any:
    """Parse JSON with the frozen integer, duplicate-key and Unicode rules."""

    if text.startswith("\ufeff"):
        raise AdmissionRejected("SCHEMA_VIOLATION", "UTF-8 BOM")
    try:
        return json.loads(
            text,
            parse_float=_reject_float,
            parse_int=_parse_integer,
            parse_constant=_reject_constant,
            object_pairs_hook=_strict_pairs,
        )
    except json.JSONDecodeError as error:
        raise AdmissionRejected("SCHEMA_VIOLATION", error.msg) from error


def canonical_timestamp(value: str) -> str:
    """Normalize a strict offset-aware RFC 3339 timestamp to UTC."""

    if _RFC3339.fullmatch(value) is None:
        raise AdmissionRejected("SCHEMA_VIOLATION", "timestamp profile")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise AdmissionRejected("SCHEMA_VIOLATION", "calendar timestamp") from error
    rendered = parsed.astimezone(UTC).isoformat(timespec="microseconds")
    date_and_time, _ = rendered.split("+")
    return date_and_time.rstrip("0").rstrip(".") + "Z"


def _normalize(value: Any, field: str | None = None) -> Any:
    if isinstance(value, str):
        normalized = _normalize_string(value)
        return canonical_timestamp(normalized) if field in _TIMESTAMP_FIELDS else normalized
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return checked_i64(value)
    if isinstance(value, float):
        raise AdmissionRejected("SCHEMA_VIOLATION", "floating-point value")
    if isinstance(value, list):
        return [_normalize(item) for item in value]
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for raw_key, item in value.items():
            if not isinstance(raw_key, str):
                raise AdmissionRejected("SCHEMA_VIOLATION", "non-string object key")
            key = _normalize_string(raw_key)
            if key in result:
                raise AdmissionRejected("SCHEMA_VIOLATION", "NFC key collision")
            result[key] = _normalize(item, key)
        return result
    raise AdmissionRejected("SCHEMA_VIOLATION", f"unsupported value {type(value).__name__}")


def canonical_json_bytes(value: Any) -> bytes:
    """Return deterministic, NFC-normalized UTF-8 JSON bytes."""

    return json.dumps(
        _normalize(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def canonical_sha256(value: Mapping[str, Any], excluded_fields: set[str] | None = None) -> str:
    """Hash a canonical object after excluding named top-level fields."""

    excluded = excluded_fields or set()
    scoped = {key: item for key, item in value.items() if key not in excluded}
    return sha256(canonical_json_bytes(scoped)).hexdigest()


def business_digest(record: Mapping[str, Any]) -> str:
    """Calculate the frozen transport-independent source digest."""

    return canonical_sha256(record, _DIGEST_EXCLUSIONS)


def source_identity(family: str, record: Mapping[str, Any]) -> tuple[str, ...]:
    """Return the exact source-family identity tuple."""

    if family not in _SOURCE_IDENTITIES:
        raise AdmissionRejected("SOURCE_IDENTITY_MISMATCH", "unknown source family")
    values = [family]
    for field in _SOURCE_IDENTITIES[family]:
        value = record.get(field)
        if not isinstance(value, str) or not value:
            raise AdmissionRejected("SOURCE_IDENTITY_MISMATCH", f"missing {field}")
        values.append(_normalize_string(value))
    return tuple(values)


def classify_replay(family: str, first: Mapping[str, Any], second: Mapping[str, Any]) -> str:
    """Classify two source deliveries as distinct, replay, or conflict."""

    if source_identity(family, first) != source_identity(family, second):
        return "DISTINCT_IDENTITY"
    return (
        "IDENTICAL_REPLAY"
        if business_digest(first) == business_digest(second)
        else "IDENTITY_CONFLICT"
    )


def _derived_id(prefix: str, components: Mapping[str, Any]) -> str:
    return prefix + sha256(canonical_json_bytes(components)).hexdigest()


def transaction_key(components: Mapping[str, Any]) -> str:
    return _derived_id("txn:", components)


def settlement_key(components: Mapping[str, Any]) -> str:
    return _derived_id("stl:", components)


def proof_id(components: Mapping[str, Any]) -> str:
    return _derived_id("prf:", components)


def case_id(components: Mapping[str, Any]) -> str:
    return _derived_id("case:", components)
