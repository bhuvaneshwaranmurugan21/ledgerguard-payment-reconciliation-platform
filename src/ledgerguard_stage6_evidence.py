"""Fail-closed primitives for Stage 6 deterministic and CI evidence validation."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from hashlib import sha256
from typing import Any


class Stage6EvidenceError(ValueError):
    """Raised when Stage 6 evidence is incomplete or contradictory."""


def canonical_bytes(value: Mapping[str, Any]) -> bytes:
    """Return stable UTF-8 JSON bytes for a deterministic payload."""

    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def payload_digest(value: Mapping[str, Any]) -> str:
    """Digest a deterministic payload without timestamps or runner metadata."""

    return sha256(canonical_bytes(value)).hexdigest()


def require_equal_runs(first: Mapping[str, Any], second: Mapping[str, Any]) -> str:
    """Reject non-identical deterministic clean-environment results."""

    if canonical_bytes(first) != canonical_bytes(second):
        raise Stage6EvidenceError("OP-S6-R015 clean-run deterministic payloads differ")
    return payload_digest(first)


def validate_ci_envelope(envelope: Mapping[str, Any], required_gate_ids: Sequence[str]) -> None:
    """Validate exact-head, complete, no-AWS Stage 6 CI evidence."""

    required_text = ("repository", "commit_sha", "workflow_run_id", "workflow_run_attempt")
    for field in required_text:
        if not str(envelope.get(field, "")).strip():
            raise Stage6EvidenceError(f"Stage 6 CI evidence field missing: {field}")
    if envelope.get("checked_out_sha") != envelope.get("commit_sha"):
        raise Stage6EvidenceError("OP-S6-R031 CI did not validate the raw exact head")
    if envelope.get("aws_execution") is not False:
        raise Stage6EvidenceError("OP-S6-R027 Stage 6 AWS execution boundary differs")
    if envelope.get("infrastructure_mutation") is not False:
        raise Stage6EvidenceError("Stage 6 infrastructure mutation boundary differs")
    if envelope.get("pull_request_draft") is not True:
        raise Stage6EvidenceError("OP-S6-R029 corrective PR is not draft")
    gates = envelope.get("part1_gate_results")
    if not isinstance(gates, list):
        raise Stage6EvidenceError("OP-S6-R028 Part 1 gate results missing")
    actual = [str(item.get("gate_id")) for item in gates if isinstance(item, Mapping)]
    if actual != list(required_gate_ids):
        raise Stage6EvidenceError("OP-S6-R028 Part 1 gate inventory differs")
    digest = str(envelope.get("deterministic_payload_sha256", ""))
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise Stage6EvidenceError("Stage 6 deterministic payload digest is invalid")
