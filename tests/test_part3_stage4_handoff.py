from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from tools.validate_part3_stage4_handoff import (
    BASELINE_TREE,
    admit_receipt,
    main,
    validate,
    validate_baseline_tree,
    validate_blob,
    validate_freeze_identity,
    validate_member,
    validate_requirement_ids,
)

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


def test_handoff_cli_uses_the_actual_checkout() -> None:
    main(["--root", str(ROOT)])


@pytest.mark.parametrize("field", ["baseline_commit", "baseline_tree"])
def test_frozen_inventory_identity_cannot_be_substituted(field: str) -> None:
    freeze = json.loads((ROOT / "spec/part3-stage4-inherited-freeze-v1.json").read_text())
    validate_freeze_identity(freeze)
    freeze[field] = "0" * 40
    with pytest.raises(ValueError, match="source identity"):
        validate_freeze_identity(freeze)


def test_baseline_and_git_blob_bindings_reject_substitution() -> None:
    freeze = json.loads((ROOT / "spec/part3-stage4-inherited-freeze-v1.json").read_text())
    row = freeze["members"][0]
    validate_baseline_tree(BASELINE_TREE)
    validate_blob(row["git_blob"], row["git_blob"], row["path"])
    with pytest.raises(ValueError, match="baseline tree"):
        validate_baseline_tree("0" * 40)
    with pytest.raises(ValueError, match="Git binding"):
        validate_blob("0" * 40, row["git_blob"], row["path"])


@pytest.mark.parametrize(
    "change", ["duplicate", "absolute", "parent", "symlink", "bytes", "nonstring"]
)
def test_actual_inherited_members_reject_unsafe_or_altered_files(
    change: str, tmp_path: Path
) -> None:
    row = json.loads((ROOT / "spec/part3-stage4-inherited-freeze-v1.json").read_text())["members"][
        0
    ]
    path = tmp_path / row["path"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((ROOT / row["path"]).read_bytes())
    names: set[str] = set()
    assert validate_member(tmp_path, row, names) == path
    if change == "nonstring":
        row["path"] = 42
    elif change == "absolute":
        row["path"] = str(path)
    elif change == "parent":
        row["path"] = "../outside"
    elif change == "symlink":
        path.unlink()
        path.symlink_to(ROOT / row["path"])
    elif change == "bytes":
        path.write_bytes(path.read_bytes() + b"altered")
    if change != "duplicate":
        names.clear()
    with pytest.raises(ValueError):
        validate_member(tmp_path, row, names)


@pytest.mark.parametrize("change", ["missing", "duplicate"])
def test_original_requirement_ids_cannot_be_reduced_or_duplicated(change: str) -> None:
    requirements = json.loads((ROOT / "spec/part3-requirements-v1.json").read_text())
    validate_requirement_ids(requirements)
    if change == "missing":
        requirements["requirements"].pop()
    else:
        requirements["requirements"][-1] = requirements["requirements"][0]
    with pytest.raises(ValueError, match="requirement identity"):
        validate_requirement_ids(requirements)


def test_changed_freeze_bytes_reject_before_git_or_file_validation(tmp_path: Path) -> None:
    spec = tmp_path / "spec"
    spec.mkdir()
    for name in (
        "part3-stage3-external-closure-v1.json",
        "part3-stage3-external-closure-correction-v1.json",
        "part3-master-gates-v1.json",
        "part3-stage4-inherited-freeze-v1.json",
    ):
        (spec / name).write_bytes((ROOT / "spec" / name).read_bytes())
    freeze = spec / "part3-stage4-inherited-freeze-v1.json"
    freeze.write_bytes(freeze.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="inventory bytes"):
        validate(tmp_path)
