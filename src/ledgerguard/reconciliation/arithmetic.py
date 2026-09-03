"""Checked signed 64-bit arithmetic used by all financial stages."""

from __future__ import annotations

from collections.abc import Iterable

from .errors import AdmissionRejected

MIN_I64 = -(2**63)
MAX_I64 = 2**63 - 1


def checked_i64(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise AdmissionRejected("SCHEMA_VIOLATION", "signed integer required")
    if value < MIN_I64 or value > MAX_I64:
        raise AdmissionRejected("SCHEMA_VIOLATION", "signed 64-bit overflow")
    return value


def checked_add(left: object, right: object) -> int:
    return checked_i64(checked_i64(left) + checked_i64(right))


def checked_subtract(left: object, right: object) -> int:
    return checked_i64(checked_i64(left) - checked_i64(right))


def checked_multiply_sign(value: object, sign: object) -> int:
    amount = checked_i64(value)
    direction = checked_i64(sign)
    if direction not in {-1, 1}:
        raise AdmissionRejected("POLICY_MISMATCH", "sign must be -1 or 1")
    return checked_i64(amount * direction)


def checked_abs(value: object) -> int:
    result = checked_i64(value)
    if result == MIN_I64:
        raise AdmissionRejected("SCHEMA_VIOLATION", "absolute-value overflow")
    return abs(result)


def checked_sum(values: Iterable[object]) -> int:
    result = 0
    for value in values:
        result = checked_add(result, value)
    return result
