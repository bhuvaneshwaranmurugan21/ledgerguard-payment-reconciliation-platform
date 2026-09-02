from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from ledgerguard_stage6_evidence import (
    Stage6EvidenceError,
    canonical_bytes,
    payload_digest,
    require_equal_runs,
    validate_ci_envelope,
)

GATES = [f"OP-GATE-R{number:03d}" for number in range(1, 15)]
ROOT = Path(__file__).resolve().parents[1]


def _valid_envelope() -> dict[str, Any]:
    return {
        "repository": "bhuvaneshwaranmurugan21/ledgerguard-payment-reconciliation-platform",
        "schema_version": "1.0",
        "commit_sha": "a" * 40,
        "checked_out_sha": "a" * 40,
        "base_sha": "c" * 40,
        "workflow_run_id": "123",
        "workflow_run_attempt": "1",
        "python_version": "3.11.13",
        "dependency_versions": [f"package-{number}==1.0" for number in range(21)],
        "test_counts": {"tests": 222, "failures": 0, "errors": 0, "skipped": 0},
        "coverage": {
            "line_percent": 95.1,
            "minimum_line_percent": 95.0,
            "critical_branch_percent": 100.0,
            "required_critical_branch_percent": 100.0,
        },
        "mutation": {"catalog_entries": 20, "executed_tests": 20, "survivors": 0, "skipped": 0},
        "schema_digests": {"contracts/example.schema.json": "d" * 64},
        "foundation_digest": "e" * 64,
        "aws_execution": False,
        "infrastructure_mutation": False,
        "pull_request_number": 8,
        "pull_request_draft": True,
        "part1_gate_results": [{"gate_id": gate, "state": "CANDIDATE"} for gate in GATES],
        "deterministic_payload_sha256": "b" * 64,
    }


def test_canonical_payload_is_stable_and_unicode_preserving() -> None:
    first = {"z": "₹", "a": [2, 1]}
    second = {"a": [2, 1], "z": "₹"}
    assert canonical_bytes(first) == canonical_bytes(second)
    assert payload_digest(first) == payload_digest(second)
    assert b"\\u20b9" not in canonical_bytes(first)


def test_clean_run_equality_accepts_identical_and_rejects_difference() -> None:
    assert require_equal_runs({"value": 1}, {"value": 1}) == payload_digest({"value": 1})
    with pytest.raises(Stage6EvidenceError, match="OP-S6-R015"):
        require_equal_runs({"value": 1}, {"value": 2})


def test_valid_ci_envelope_passes() -> None:
    validate_ci_envelope(_valid_envelope(), GATES)


def test_ci_evidence_schema_accepts_complete_envelope_and_rejects_unknown_fields() -> None:
    schema = json.loads(
        (ROOT / "spec/part1-stage6-ci-evidence-v1.schema.json").read_text(encoding="utf-8")
    )
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    assert list(validator.iter_errors(_valid_envelope())) == []
    changed = _valid_envelope()
    changed["untrusted"] = True
    assert list(validator.iter_errors(changed))


@pytest.mark.parametrize(
    "mutation,match",
    [
        (lambda value: value.update({"repository": ""}), "field missing: repository"),
        (lambda value: value.update({"commit_sha": ""}), "field missing: commit_sha"),
        (lambda value: value.update({"workflow_run_id": ""}), "field missing: workflow_run_id"),
        (
            lambda value: value.update({"workflow_run_attempt": ""}),
            "field missing: workflow_run_attempt",
        ),
        (lambda value: value.update({"checked_out_sha": "c" * 40}), "raw exact head"),
        (lambda value: value.update({"aws_execution": True}), "OP-S6-R027"),
        (lambda value: value.update({"infrastructure_mutation": True}), "infrastructure mutation"),
        (lambda value: value.update({"pull_request_draft": False}), "OP-S6-R029"),
        (lambda value: value.update({"part1_gate_results": None}), "gate results missing"),
        (lambda value: value.update({"part1_gate_results": []}), "gate inventory differs"),
        (
            lambda value: value.update({"deterministic_payload_sha256": "x" * 64}),
            "digest is invalid",
        ),
        (
            lambda value: value.update({"deterministic_payload_sha256": "a" * 63}),
            "digest is invalid",
        ),
    ],
)
def test_ci_envelope_mutations_fail_closed(
    mutation: Callable[[dict[str, Any]], None], match: str
) -> None:
    envelope = _valid_envelope()
    mutation(envelope)
    with pytest.raises(Stage6EvidenceError, match=match):
        validate_ci_envelope(envelope, GATES)
