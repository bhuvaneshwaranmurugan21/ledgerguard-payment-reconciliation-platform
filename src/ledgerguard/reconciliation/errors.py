"""Fail-closed admission errors with stable ownership."""

from __future__ import annotations

from typing import Any

ADMISSION_REASONS = frozenset(
    {
        "SCHEMA_VIOLATION",
        "IDENTITY_CONFLICT",
        "UNBALANCED_JOURNAL",
        "CURRENCY_DOMAIN_VIOLATION",
        "POLICY_MISMATCH",
        "SOURCE_IDENTITY_MISMATCH",
        "AMBIGUOUS_BANK_ALLOCATION",
    }
)


class AdmissionRejected(ValueError):
    """An input set cannot authorize reconciliation processing."""

    authoritative_proof = False

    def __init__(self, reason: str, detail: str, path: str = "") -> None:
        if reason not in ADMISSION_REASONS:
            raise ValueError(f"unknown admission reason: {reason}")
        message = f"{reason}: {detail}"
        if path:
            message += f" at {path}"
        super().__init__(message)
        self.reason = reason
        self.detail = detail
        self.path = path

    def as_dict(self) -> dict[str, Any]:
        return {
            "outcome": "ADMISSION_REJECTED",
            "reason_code": self.reason,
            "detail": self.detail,
            "path": self.path,
            "authoritative_proof": False,
        }
