from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from tools.validate_part3_stage4_handoff import admit_receipt, validate

ROOT = Path(__file__).resolve().parents[1]


def inputs() -> tuple[bytes, dict[str, Any], bytes]:
    return (
        (ROOT / "spec/part3-stage3-external-closure-v1.json").read_bytes(),
        json.loads((ROOT / "spec/part3-stage3-external-closure-correction-v1.json").read_text()),
        (ROOT / "spec/part3-master-gates-v1.json").read_bytes(),
    )


def test_original_receipt_and_append_only_correction_are_admitted() -> None:
    admit_receipt(*inputs())
    result = validate(ROOT)
    assert result["original_requirement_count"] == 99
    assert result["inherited_files_verified"] == 330
    assert result["stage4_complete"] is False
    assert result["aws_execution"] is False


@pytest.mark.parametrize("target", ["receipt", "registry"])
def test_changed_historical_bytes_reject(target: str) -> None:
    raw, correction, registry = inputs()
    with pytest.raises(ValueError, match="bytes changed"):
        admit_receipt(
            raw + (b" " if target == "receipt" else b""),
            correction,
            registry + (b" " if target == "registry" else b""),
        )


@pytest.mark.parametrize("field", ["original_receipt_sha256", "authoritative_gate_registry_sha256"])
def test_changed_correction_binding_reject(field: str) -> None:
    raw, correction, registry = inputs()
    correction[field] = "0" * 64
    with pytest.raises(ValueError, match="binding differs"):
        admit_receipt(raw, correction, registry)


@pytest.mark.parametrize(
    "field,value",
    [
        ("json_pointer", "/other"),
        ("superseded_value", ["invented"]),
        ("corrected_value", ["managed_deployment_verified"]),
        ("corrected_value", ["plan_only_verified", "teardown_verified"]),
    ],
)
def test_incorrect_correction_reject(field: str, value: object) -> None:
    raw, correction, registry = inputs()
    correction = deepcopy(correction)
    correction["correction"][field] = value
    with pytest.raises(ValueError):
        admit_receipt(raw, correction, registry)


@pytest.mark.parametrize(
    "field,value",
    [
        ("original_receipt_mutated", True),
        ("unaffected_fields_remain_authoritative", False),
    ],
)
def test_redefinition_of_historical_authority_reject(field: str, value: bool) -> None:
    raw, correction, registry = inputs()
    correction[field] = value
    with pytest.raises(ValueError, match="append-only"):
        admit_receipt(raw, correction, registry)
