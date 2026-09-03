"""Strict JSON admission and canonical content identity."""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Mapping
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any, NoReturn

from .arithmetic import checked_i64
from .errors import AdmissionRejected

TIMESTAMP_FIELDS = frozenset(
    {"occurred_at", "received_at", "effective_at", "value_at", "created_at"}
)
SOURCE_DIGEST_EXCLUSIONS = frozenset({"payload_sha256", "received_at", "source_batch_id"})
RFC3339 = re.compile(
    r"^(?P<date>[0-9]{4}-[0-9]{2}-[0-9]{2})T"
    r"(?P<time>[0-9]{2}:[0-9]{2}:[0-9]{2})"
    r"(?P<fraction>\.[0-9]{1,6})?"
    r"(?P<offset>Z|[+-][0-9]{2}:[0-9]{2})$"
)


def normalize_string(value: str) -> str:
    if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
        raise AdmissionRejected("SCHEMA_VIOLATION", "Unicode surrogate code point")
    return unicodedata.normalize("NFC", value)


def _reject_float(_: str) -> NoReturn:
    raise AdmissionRejected("SCHEMA_VIOLATION", "decimal or exponent JSON number")


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
        key = normalize_string(raw_key)
        if key in result:
            raise AdmissionRejected("SCHEMA_VIOLATION", "NFC-normalized key collision")
        result[key] = item
    return result


def canonical_timestamp(value: str) -> str:
    if RFC3339.fullmatch(value) is None:
        raise AdmissionRejected("SCHEMA_VIOLATION", "timestamp profile")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise AdmissionRejected("SCHEMA_VIOLATION", "calendar timestamp") from error
    rendered = parsed.astimezone(UTC).isoformat(timespec="microseconds")
    date_and_time, _ = rendered.split("+")
    return date_and_time.rstrip("0").rstrip(".") + "Z"


def normalize_json(value: Any, field: str | None = None) -> Any:
    if isinstance(value, str):
        normalized = normalize_string(value)
        return canonical_timestamp(normalized) if field in TIMESTAMP_FIELDS else normalized
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return checked_i64(value)
    if isinstance(value, float):
        raise AdmissionRejected("SCHEMA_VIOLATION", "floating-point value")
    if isinstance(value, list):
        return [normalize_json(item) for item in value]
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for raw_key, item in value.items():
            if not isinstance(raw_key, str):
                raise AdmissionRejected("SCHEMA_VIOLATION", "non-string object key")
            key = normalize_string(raw_key)
            if key in result:
                raise AdmissionRejected("SCHEMA_VIOLATION", "NFC-normalized key collision")
            result[key] = normalize_json(item, key)
        return result
    raise AdmissionRejected("SCHEMA_VIOLATION", f"unsupported value {type(value).__name__}")


def parse_strict_json(raw: bytes) -> Any:
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise AdmissionRejected("SCHEMA_VIOLATION", "invalid UTF-8") from error
    if text.startswith("\ufeff"):
        raise AdmissionRejected("SCHEMA_VIOLATION", "UTF-8 BOM")
    try:
        value = json.loads(
            text,
            parse_float=_reject_float,
            parse_int=_parse_integer,
            parse_constant=_reject_constant,
            object_pairs_hook=_strict_pairs,
        )
    except json.JSONDecodeError as error:
        raise AdmissionRejected("SCHEMA_VIOLATION", error.msg) from error
    return normalize_json(value)


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        normalize_json(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def canonical_sha256(
    value: Mapping[str, Any], excluded_fields: set[str] | frozenset[str] | None = None
) -> str:
    excluded = excluded_fields or frozenset()
    scoped = {key: item for key, item in value.items() if key not in excluded}
    return sha256(canonical_json_bytes(scoped)).hexdigest()


def business_digest(record: Mapping[str, Any]) -> str:
    return canonical_sha256(record, SOURCE_DIGEST_EXCLUSIONS)
