from __future__ import annotations

import json
import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from ledgerguard_correction_c1 import (
    EXPECTED_BASELINE_SUMMARY,
    EXPECTED_GATE_SUMMARY,
    EXPECTED_GENERATED_DIGESTS,
    EXPECTED_REMAINING_BY_WORKSTREAM,
    EXPECTED_RESOLUTION_SUMMARY,
    EXPECTED_SOURCE_DIGESTS,
    C1Error,
    _validate_requirement_authorities,
    reproduce_c0,
    validate_c1,
)
from ledgerguard_correction_c2 import materialize_c1_view
from ledgerguard_correction_c4 import materialize_stage5_view

ACTIVE_ROOT = Path(__file__).resolve().parents[1]
_C1_TEMPORARY = tempfile.TemporaryDirectory(prefix="ledgerguard-c1-tests-")
_STAGE5_ROOT = materialize_stage5_view(ACTIVE_ROOT, Path(_C1_TEMPORARY.name) / "stage5")
ROOT = materialize_c1_view(_STAGE5_ROOT, Path(_C1_TEMPORARY.name) / "repository")


def _load(relative: str) -> dict[str, Any]:
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def _copy_repository(tmp_path: Path) -> Path:
    destination = tmp_path / "repository"
    shutil.copytree(
        ROOT,
        destination,
        ignore=shutil.ignore_patterns(
            ".git",
            ".mypy_cache",
            ".pytest_cache",
            ".ruff_cache",
            ".venv",
            "__pycache__",
            "build",
            "*.egg-info",
        ),
    )
    return destination


def _mutate_json(root: Path, relative: str, mutation: Callable[[dict[str, Any]], None]) -> None:
    path = root / relative
    value = json.loads(path.read_text(encoding="utf-8"))
    mutation(value)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def test_c1_t001_frozen_inputs_and_generated_bytes_are_exact() -> None:
    ledger, reverse, gates = _validate_requirement_authorities(ROOT)
    assert (
        ledger["input_digests"]["requirements_catalog_sha256"]
        == (EXPECTED_SOURCE_DIGESTS["catalog"])
    )
    assert reverse["requirement_count"] == 331
    assert gates["gate_count"] == 14
    assert set(EXPECTED_GENERATED_DIGESTS) == {"ledger", "reverse", "gates"}


def test_c1_t002_all_331_requirements_have_complete_forward_ownership() -> None:
    ledger = _load("spec/part1-requirement-ledger-v1.json")
    rows = ledger["requirements"]
    assert len(rows) == len({row["requirement_id"] for row in rows}) == 331
    for row in rows:
        for field in (
            "rule_refs",
            "contract_schema_paths",
            "documentation_paths",
            "test_paths",
            "candidate_evidence_ids",
            "authority_evidence_paths",
        ):
            assert row[field], (row["requirement_id"], field)
        assert row["correction_owner"]
        assert row["correction_action"]
    assert ledger["baseline_verdict_summary"] == EXPECTED_BASELINE_SUMMARY


def test_c1_t003_reverse_mapping_partitions_all_evidence_without_orphans() -> None:
    mapping = _load("evidence/part1-phase4-bidirectional-mapping-v1.json")
    reverse = _load("spec/part1-requirement-reverse-index-v1.json")
    mapped = set(reverse["indexes"]["candidate_evidence"])
    disposed = set(reverse["explicitly_disposed_evidence"])
    registry = {item["id"] for item in mapping["evidence_registry"]}
    assert mapped.isdisjoint(disposed)
    assert mapped | disposed == registry
    for field in (
        "orphan_requirement_ids",
        "orphan_evidence_ids",
        "undisposed_evidence_ids",
        "unowned_requirement_ids",
        "uncorrected_nonpass_requirement_ids",
    ):
        assert reverse[field] == []


def test_c1_t004_exact_gate_authority_is_ordered_and_open_work_is_derived() -> None:
    registry = _load("spec/part1-gate-registry-v1.json")
    assert [row["gate_id"] for row in registry["gates"]] == [
        f"OP-GATE-R{number:03d}" for number in range(1, 15)
    ]
    assert registry["summary"] == EXPECTED_GATE_SUMMARY
    assert len(registry["remaining_gate_ids"]) == 9
    assert registry["final_c7_gate_audit_required"] is True


def test_c1_t005_remaining_work_is_mechanical_and_exactly_owned() -> None:
    ledger = _load("spec/part1-requirement-ledger-v1.json")
    derived = [
        row["requirement_id"]
        for row in ledger["requirements"]
        if row["resolution_state"] == "CORRECTION_REQUIRED"
    ]
    assert ledger["remaining_requirement_ids"] == derived
    assert len(derived) == 84
    assert {key: len(value) for key, value in ledger["remaining_by_workstream"].items()} == (
        EXPECTED_REMAINING_BY_WORKSTREAM
    )
    assert ledger["resolution_summary"] == EXPECTED_RESOLUTION_SUMMARY


def test_c1_t006_formal_amendments_have_exact_bidirectional_scope() -> None:
    reverse = _load("spec/part1-requirement-reverse-index-v1.json")
    assert reverse["indexes"]["amendments"] == {
        "P1-AWS-001": [
            "OP-DONE-R018",
            "OP-DONE-R019",
            "OP-GATE-R010",
            "OP-S0-R009",
            "OP-S3-R015",
            "OP-S3-R016",
            "OP-S3-R028",
        ],
        "P1-CONTRACT-001": ["OP-S2-R001"],
    }


def test_c1_t007_exact_c0_checkpoint_reproduces_in_isolation() -> None:
    result = reproduce_c0(ROOT)
    assert result["state"] == "PART1_CORRECTION_IN_PROGRESS"
    assert result["part2_entry"] == "BLOCKED"
    assert result["c0_sha256"] == (
        "c6d6476cfb1e1b3a62d9e3fca4d488db3f98fa96f22282d44a154fda727a6877"
    )


def test_c1_t008_validator_is_deterministic_and_does_not_claim_completion() -> None:
    first = validate_c1(ROOT, verify_evidence=False)
    second = validate_c1(ROOT, verify_evidence=False)
    assert first == second
    assert first["state"] == "PART1_CORRECTION_IN_PROGRESS"
    assert first["part2_entry"] == "BLOCKED"
    assert first["remaining_requirement_count"] == 84
    assert first["final_c7_audit_required"] is True


def test_c1_t009_ledger_mutation_fails_closed(tmp_path: Path) -> None:
    repository = _copy_repository(tmp_path)
    _mutate_json(
        repository,
        "spec/part1-requirement-ledger-v1.json",
        lambda value: value["requirements"][0].update({"correction_owner": "C2"}),
    )
    with pytest.raises(C1Error, match="generated digest differs: ledger"):
        validate_c1(repository, verify_evidence=False)


def test_c1_t010_reverse_index_mutation_fails_closed(tmp_path: Path) -> None:
    repository = _copy_repository(tmp_path)
    _mutate_json(
        repository,
        "spec/part1-requirement-reverse-index-v1.json",
        lambda value: value.update({"orphan_requirement_ids": ["OP-S0-R001"]}),
    )
    with pytest.raises(C1Error, match="generated digest differs: reverse"):
        validate_c1(repository, verify_evidence=False)


def test_c1_t011_gate_inventory_mutation_fails_closed(tmp_path: Path) -> None:
    repository = _copy_repository(tmp_path)
    _mutate_json(
        repository,
        "spec/part1-gate-registry-v1.json",
        lambda value: value["gates"].pop(),
    )
    with pytest.raises(C1Error, match="generated digest differs: gates"):
        validate_c1(repository, verify_evidence=False)


def test_c1_t012_phase8_verdict_mutation_fails_closed(tmp_path: Path) -> None:
    repository = _copy_repository(tmp_path)
    _mutate_json(
        repository,
        "evidence/part1-phase8-requirement-verdict-v1.json",
        lambda value: value["requirement_verdicts"][0].update({"final_verdict": "PASS"}),
    )
    with pytest.raises(C1Error, match="source digest differs: verdict"):
        validate_c1(repository, verify_evidence=False)
