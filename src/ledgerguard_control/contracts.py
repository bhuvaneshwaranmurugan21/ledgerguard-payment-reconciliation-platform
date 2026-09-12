"""Strict, bounded control documents with exact numeric transport.

Schema validation is structural admission, never proof that an object, query,
publication, or AWS identity exists. Consumers must verify those observations.
"""

from __future__ import annotations

import json
import re
import unicodedata
from typing import Any

from jsonschema import Draft202012Validator

from ledgerguard.stage3.arguments import JobArguments, parse_job_arguments
from ledgerguard.stage3.canonical import canonical_bytes

MAX_DOCUMENT_BYTES = 131072
IDENTIFIER = r"^[a-z0-9][a-z0-9-]{7,63}$"
SHA256 = {"type": "string", "pattern": r"^[0-9a-f]{64}$"}
SHA1 = {"type": "string", "pattern": r"^[0-9a-f]{40}$"}
ID = {"type": "string", "pattern": IDENTIFIER}
TEXT = {"type": "string", "minLength": 1, "maxLength": 1024}
UINT = {"type": "integer", "minimum": 0, "maximum": 2**63 - 1}
EXACT_AMOUNT = {"type": "string", "pattern": r"^(0|-?[1-9][0-9]{0,37})$"}


class ControlRejected(ValueError):
    """Stable fail-closed control-plane rejection."""


def closed(properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": sorted(properties),
        "properties": properties,
    }


OBJECT = closed({"uri": TEXT, "version_id": TEXT, "sha256": SHA256, "size_bytes": UINT})
IDENTITY = {
    "run_id": ID,
    "attempt_id": ID,
    "control_record_identity": ID,
    "policy_sha256": SHA256,
    "manifest_sha256": SHA256,
    "source_bundle_sha256": SHA256,
}
JOB = closed(
    {
        **IDENTITY,
        "input_prefix": TEXT,
        "candidate_output_prefix": TEXT,
        "evidence_prefix": TEXT,
        "source_commit": SHA1,
        "source_tree": SHA1,
        "runtime_package_sha256": SHA256,
        "workload_bucket": {"type": "string", "minLength": 3, "maxLength": 63},
    }
)
RUNTIME = closed(
    {
        "source_commit": SHA1,
        "source_tree": SHA1,
        "runtime_package_sha256": SHA256,
        "script_sha256": SHA256,
        "wheels_sha256": SHA256,
    }
)
FENCED = {
    **IDENTITY,
    "execution_arn": TEXT,
    "fence": {**UINT, "minimum": 1},
    "predecessor": {"anyOf": [SHA256, {"type": "null"}]},
}


def document(kind: str, properties: dict[str, Any]) -> dict[str, Any]:
    return closed({"schema_version": {"const": f"ledgerguard.{kind}.v1"}, **properties})


SCHEMAS = {
    "execution-input": document(
        "execution-input",
        {
            "job": JOB,
            "runtime": RUNTIME,
            "release_manifest_sha256": SHA256,
            "expected_results": OBJECT,
            "input_inventory": OBJECT,
            "namespace": ID,
            "predecessor": {"anyOf": [SHA256, {"type": "null"}]},
        },
    ),
    "registration": document(
        "registration",
        {
            **FENCED,
            "namespace": ID,
            "execution_input_sha256": SHA256,
            "immutable_run_sha256": SHA256,
        },
    ),
    "validation-receipt": document(
        "validation-receipt",
        {
            **FENCED,
            "glue_job_name": TEXT,
            "glue_job_run_id": TEXT,
            "glue_arguments_sha256": SHA256,
            "glue_observation_sha256": SHA256,
            "glue_started_at": TEXT,
            "glue_completed_at": TEXT,
            "glue_execution_seconds": UINT,
            "glue_dpu_seconds": {
                "type": "string",
                "pattern": r"^(0|[1-9][0-9]{0,3})(?:\.[0-9]{1,6})?$",
            },
            "completion": OBJECT,
            "candidate_manifest": OBJECT,
            "physical_inventory": OBJECT,
            "version_inventory_sha256": SHA256,
            "logical_sha256": SHA256,
            "expected_results_sha256": SHA256,
        },
    ),
    "physical-inventory": document(
        "physical-inventory",
        {
            "run_id": ID,
            "attempt_id": ID,
            "version_inventory_sha256": SHA256,
            "objects": {
                "type": "array",
                "items": OBJECT,
                "minItems": 3,
                "maxItems": 1024,
            },
            "financial_comparison": closed(
                {
                    "expected_sha256": SHA256,
                    "rows_sha256": SHA256,
                    "counts": closed(
                        {
                            "transactions": UINT,
                            "settlements": UINT,
                            "bank-allocations": UINT,
                        }
                    ),
                }
            ),
        },
    ),
    "query-proof": document(
        "query-proof",
        {
            **IDENTITY,
            "family": {
                "enum": ["transactions", "settlements", "bank_allocations"]
            },
            "query_execution_id": TEXT,
            "sql_sha256": SHA256,
            "workgroup": TEXT,
            "engine_version": {"const": "Athena engine version 3"},
            "status": {"const": "SUCCEEDED"},
            "scanned_bytes": UINT,
            "execution_ms": UINT,
            "result": OBJECT,
            "rows_sha256": SHA256,
            "row_count": UINT,
            "version_inventory_before_sha256": SHA256,
            "version_inventory_after_sha256": SHA256,
        },
    ),
    "candidate-index": document(
        "candidate-index",
        {
            **FENCED,
            "namespace": ID,
            "registration_sha256": SHA256,
            "validation_receipt": OBJECT,
            "query_proofs": {"type": "array", "items": OBJECT, "minItems": 3, "maxItems": 3},
            "pages": {"type": "array", "items": OBJECT, "minItems": 1, "maxItems": 128},
            "item_count": UINT,
        },
    ),
    "failure-record": document(
        "failure-record",
        {
            **FENCED,
            "failed_state": TEXT,
            "error": TEXT,
            "cause": TEXT,
            "glue_job_run_id": {"anyOf": [TEXT, {"type": "null"}]},
            "query_execution_ids": {"type": "array", "items": TEXT, "maxItems": 16},
            "candidate_prefix": TEXT,
            "recovery_required": {"const": True},
        },
    ),
    "publication": document(
        "publication",
        {
            **FENCED,
            "namespace": ID,
            "commit_sha256": SHA256,
            "candidate_index": OBJECT,
            "registration_sha256": SHA256,
            "validated_inventory_sha256": SHA256,
        },
    ),
}


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ControlRejected("duplicate JSON key")
        result[key] = value
    return result


def _not_exact(value: str) -> None:
    raise ControlRejected(f"non-integer JSON numeric token: {value}")


def _canonical_types(value: Any, depth: int = 0) -> None:
    if depth > 32:
        raise ControlRejected("document nesting exceeds bound")
    if value is None or type(value) in (bool, int):
        return
    if type(value) is str:
        if unicodedata.normalize("NFC", value) != value:
            raise ControlRejected("noncanonical Unicode")
        if any(ord(c) < 32 or 0xD800 <= ord(c) <= 0xDFFF for c in value):
            raise ControlRejected("control character or surrogate")
        return
    if type(value) is list:
        for item in value:
            _canonical_types(item, depth + 1)
        return
    if type(value) is dict:
        for key, item in value.items():
            if type(key) is not str:
                raise ControlRejected("non-string JSON key")
            _canonical_types(key, depth + 1)
            _canonical_types(item, depth + 1)
        return
    raise ControlRejected("non-JSON or inexact value")


def strict_json(raw: bytes) -> dict[str, Any]:
    if len(raw) > MAX_DOCUMENT_BYTES:
        raise ControlRejected("document exceeds byte bound")
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_pairs,
            parse_float=_not_exact,
            parse_constant=_not_exact,
        )
    except (UnicodeError, ValueError, RecursionError) as error:
        raise ControlRejected("invalid strict JSON") from error
    _canonical_types(value)
    if type(value) is not dict:
        raise ControlRejected("document must be an object")
    return value


def validate(kind: str, value: dict[str, Any]) -> dict[str, Any]:
    if kind not in SCHEMAS:
        raise ControlRejected("unknown document contract")
    _canonical_types(value)
    if len(canonical_bytes(value)) > MAX_DOCUMENT_BYTES:
        raise ControlRejected("document exceeds byte bound")
    errors = list(Draft202012Validator(SCHEMAS[kind]).iter_errors(value))
    if errors:
        raise ControlRejected(f"{kind}: {errors[0].message}")
    # Return a detached document: caller mutation cannot change an admitted snapshot.
    return strict_json(canonical_bytes(value))


def exact_amount(value: str) -> int:
    if type(value) is not str or re.fullmatch(EXACT_AMOUNT["pattern"], value) is None:
        raise ControlRejected("amount must be a canonical DECIMAL(38,0) string")
    return int(value)


def job_arguments(value: dict[str, Any]) -> JobArguments:
    errors = list(Draft202012Validator(JOB).iter_errors(value))
    if errors:
        raise ControlRejected("invalid job argument document")
    argv = [part for key, item in value.items() for part in (f"--{key.replace('_', '-')}", item)]
    return parse_job_arguments(argv)
